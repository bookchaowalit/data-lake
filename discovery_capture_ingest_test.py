"""Offline tests for the technology-discovery capture replay contract."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "infra/scripts/data_lake/ingest_discovery_captures.py"
sys.path.insert(0, str(ROOT / "infra/scripts"))

from data_lake.ingest_discovery_captures import (  # noqa: E402
    CAPTURES,
    SOURCE_ROOT,
    _capture_lookup,
    map_records,
    normalize_timestamp,
)


class DiscoveryCaptureTests(unittest.TestCase):
    def _write_capture_fixtures(self, root: Path) -> None:
        for spec in CAPTURES:
            key = f"{spec.source_id}-1"
            url = f"https://example.test/{spec.source_id}/one"
            if spec.id_field == "url":
                key = url
            headers = [spec.id_field, spec.observed_field]
            if spec.captured_field and spec.captured_field not in headers:
                headers.append(spec.captured_field)
            for field in ("title", "url", "description"):
                if field not in headers:
                    headers.append(field)
            row = {
                spec.id_field: key,
                spec.observed_field: "2026-09-08T01:00:00Z",
                "title": f"{spec.source_id} fixture",
                "url": url,
                "description": "offline discovery fixture",
            }
            if spec.captured_field:
                row[spec.captured_field] = "2026-09-08T02:15:00Z"
            path = root / spec.filename
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=headers)
                writer.writeheader()
                writer.writerow(row)

    def test_timestamp_variants_are_normalized_to_utc(self) -> None:
        self.assertEqual(normalize_timestamp("2026-09-08 02:15:05"), "2026-09-08T02:15:05Z")
        self.assertEqual(normalize_timestamp("2026-09-08T02:15:05"), "2026-09-08T02:15:05Z")
        self.assertEqual(normalize_timestamp("2026-09-08T02:15:05+07:00"), "2026-09-07T19:15:05Z")
        self.assertEqual(normalize_timestamp("not-a-date"), "")

    def test_snapshot_capture_time_comes_from_history_when_source_omits_it(self) -> None:
        spec = next(item for item in CAPTURES if item.filename == "hackernews_top.csv")
        mapped = map_records(
            spec,
            [{"id": "123", "title": "Story", "url": "https://example.test/story", "time": "2026-09-08T01:00:00"}],
            capture_lookup={("hackernews", "123"): "2026-09-08T02:15:00Z"},
        )
        self.assertEqual(mapped[0]["captured_at"], "2026-09-08T02:15:00Z")
        self.assertEqual(mapped[0]["id"], "hackernews|123")
        self.assertTrue(mapped[0]["attribution_required"])

    def test_all_approved_captures_validate_without_network(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "data") as temp_dir:
            capture_root = Path(temp_dir)
            self._write_capture_fixtures(capture_root)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source-root",
                    str(capture_root),
                    "--validate-only",
                    "--json",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema_version"], "discovery.v1")
        self.assertEqual(payload["source"], "book-discovery-data")
        self.assertEqual(payload["errors"], [])
        self.assertEqual(payload["skipped"], [])
        self.assertEqual(len(payload["results"]), 8)
        self.assertTrue(all(row["record_count"] > 0 for row in payload["results"]))
        self.assertTrue(SOURCE_ROOT.is_dir())

    def test_missing_capture_root_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "data") as temp_dir:
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source-root",
                    temp_dir,
                    "--validate-only",
                    "--json",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["results"], [])
        self.assertEqual(len(payload["skipped"]), len(CAPTURES))


if __name__ == "__main__":
    unittest.main()
