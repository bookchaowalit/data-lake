#!/usr/bin/env python3
"""Offline tests for the bounded TG Condo RSS property capture runner."""

from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts"))

from data_lake import run_property_capture as runner  # noqa: E402

RUNNER = ROOT / "infra/scripts/data_lake/run_property_capture.py"
WORKFLOW = ROOT / ".github/workflows/scheduled-lake-capture.yml"

HEADER = [*runner.LISTING_FIELDS, *runner.LEAD_FIELDS]


def _capture_csv(rows: list[dict[str, str]], header: list[str] = HEADER) -> bytes:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=header, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in header})
    return out.getvalue().encode("utf-8")


def _listing(index: int, **extra: str) -> dict[str, str]:
    return {
        "scraped_at": "2026-10-14T00:00:00Z",
        "title": f"Fixture Condo {index} for Rent - 20,000 ฿/month",
        "type": "condo",
        "listing_type": "rent",
        "url": f"https://www.tgcondo.com/Property/fixture-condo-{index}",
        "price_raw": "20,000 ฿/month",
        "price": "20000.0",
        "bedrooms": "1",
        "source_channel": "tgcondo",
        "source_platform": "condo_rent_bkk",
        # The collector writes placeholder lead defaults even when held.
        "contact_role": "unknown",
        "co_agent_status": "unknown",
        "contact_source_url": f"https://www.tgcondo.com/Property/fixture-condo-{index}",
        "contact_public": "True",
        "lead_review_status": "unqualified",
        **extra,
    }


class ProjectionTests(unittest.TestCase):
    def test_projection_keeps_listing_fields_and_drops_lead_columns(self) -> None:
        projected, count = runner.project_listing_csv(_capture_csv([_listing(1), _listing(2)]))
        self.assertEqual(count, 2)
        rows = list(csv.DictReader(io.StringIO(projected.decode("utf-8"))))
        self.assertEqual(list(rows[0]), list(runner.LISTING_FIELDS))
        self.assertFalse(any(field.startswith("contact_") for field in rows[0]))
        self.assertEqual(rows[1]["url"], "https://www.tgcondo.com/Property/fixture-condo-2")

    def test_personal_contact_value_fails_closed(self) -> None:
        raw = _capture_csv([_listing(1, contact_phone="081 234 5678")])
        with self.assertRaises(runner.PropertyCycleError) as ctx:
            runner.project_listing_csv(raw)
        self.assertEqual(ctx.exception.code, "contact_fields_present")

    def test_unknown_column_fails_closed(self) -> None:
        raw = _capture_csv([_listing(1)], [*HEADER, "agent_mobile"])
        with self.assertRaises(runner.PropertyCycleError) as ctx:
            runner.project_listing_csv(raw)
        self.assertEqual(ctx.exception.code, "capture_headers_mismatch")

    def test_empty_capture_is_rejected(self) -> None:
        with self.assertRaises(runner.PropertyCycleError) as ctx:
            runner.project_listing_csv(_capture_csv([]))
        self.assertEqual(ctx.exception.code, "capture_empty")


class CycleTests(unittest.TestCase):
    def test_relative_lake_path_is_blocked(self) -> None:
        with self.assertRaises(runner.PropertyCycleError) as ctx:
            runner.validate_lake_uri("data/lake-local/scraping-captures-v2")
        self.assertEqual(ctx.exception.code, "lake_uri_not_absolute")

    def test_dry_run_is_read_only(self) -> None:
        with patch.object(runner.subprocess, "run") as run:
            report = runner.run_property_cycle(lake_uri="", dry_run=True)
        run.assert_not_called()
        self.assertEqual(report["status"], "dry-run")
        self.assertEqual(report["plan"]["contact_enrichment"], "disabled")
        self.assertEqual(report["plan"]["dataset"], "property_listings")

    def test_safe_env_drops_contact_approval(self) -> None:
        with patch.dict(runner.os.environ, {name: "1" for name in runner.CONTACT_ENV}):
            env = runner._safe_env()
        self.assertFalse(set(runner.CONTACT_ENV) & set(env))
        self.assertEqual(env["ALLOW_EXTERNAL_WRITES"], "false")

    def test_cycle_lands_bronze_property_listings(self) -> None:
        (ROOT / "data").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "data") as directory:
            base = Path(directory)
            workspace = base / "career-job-scraper"
            (workspace / "scripts").mkdir(parents=True)
            fixture = base / "fixture.csv"
            fixture.write_bytes(_capture_csv([_listing(1), _listing(2), _listing(3)]))
            # A stand-in collector that copies the fixture like the real one.
            (workspace / "scripts/scrape_tgcondo_rss.py").write_text(
                textwrap.dedent(
                    f"""
                    import argparse, pathlib, shutil
                    p = argparse.ArgumentParser()
                    p.add_argument("--feed-url"); p.add_argument("--limit"); p.add_argument("--output-dir")
                    a = p.parse_args()
                    out = pathlib.Path(a.output_dir); out.mkdir(parents=True, exist_ok=True)
                    shutil.copy({str(fixture)!r}, out / "tgcondo_condo_rent.csv")
                    print("Saved 3 listings to", out / "tgcondo_condo_rent.csv")
                    """
                ),
                encoding="utf-8",
            )
            lake = base / "lake"
            lake.mkdir()
            with patch.object(runner, "PROPERTY_SCRAPING", workspace):
                report = runner.run_property_cycle(
                    lake_uri=str(lake),
                    lock_path=base / "property.lock",
                    log_dir=base / "logs",
                    attempts=1,
                )
            self.assertEqual(report["status"], "ok", report)
            self.assertEqual(report["result"]["counts"], {"listings": 3, "ingested_records": 3})
            parts = list(
                lake.glob(
                    "bronze/domain=property/dataset=property_listings/schema_version=*/"
                    "ingest_date=*/source=book-property-scraping/*.parquet"
                )
            )
            self.assertEqual(len(parts), 1)
            import pyarrow.parquet as pq

            payloads = [json.loads(value) for value in pq.read_table(parts[0]).column("payload_json").to_pylist()]
            self.assertEqual(len(payloads), 3)
            self.assertFalse(any(key.startswith("contact_") for row in payloads for key in row))

    def test_unchanged_capture_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            workspace = base / "career-job-scraper"
            (workspace / "scripts").mkdir(parents=True)
            (workspace / "scripts/scrape_tgcondo_rss.py").write_text("print('noop')\n", encoding="utf-8")
            exported = workspace / "data/exported"
            exported.mkdir(parents=True)
            (exported / "tgcondo_condo_rent.csv").write_bytes(_capture_csv([_listing(1)]))
            with patch.object(runner, "PROPERTY_SCRAPING", workspace):
                result = runner.run_capture(lake_uri=str(base), log_dir=base / "logs")
        self.assertEqual(result["error"], "capture_unchanged")


class SchedulerContractTests(unittest.TestCase):
    def test_runner_help_is_local(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(RUNNER), "--help"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("--lake-uri", completed.stdout)
        self.assertIn("--attempts", completed.stdout)

    def test_hosted_workflow_schedules_property(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(f'"{runner.PROPERTY_CAPTURE.schedule}"', workflow)
        self.assertIn("run_property_capture.py", workflow)
        self.assertIn("feedparser", workflow)


if __name__ == "__main__":
    unittest.main()
