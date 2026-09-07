#!/usr/bin/env python3
"""Tests for the read-only scraping/source-product coverage audit."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts"))

from data_lake.scraping_coverage import (  # noqa: E402
    SCHEMA_VERSION,
    build_report,
    render_markdown,
    validate_config,
)


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


class ScrapingCoverageTests(unittest.TestCase):
    def _write_yaml(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    def _touch(self, path: Path, modified: datetime = NOW) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
        timestamp = modified.timestamp()
        os.utime(path, (timestamp, timestamp))

    def _fixtures(self, root: Path, *, source_status: str = "active") -> tuple[Path, Path, dict, dict]:
        source_registry = {
            "schema_version": "fixture.source-coverage.v1",
            "sources": [
                {
                    "job": "demo_source",
                    "business": "demo",
                    "source": "Demo API",
                    "channel": "api",
                    "schedule": "0 * * * *",
                    "status": source_status,
                    "owner_repository": "book-demo-data",
                }
            ],
        }
        config = {
            "schema_version": SCHEMA_VERSION,
            "source_registry": {"path": "source-registry.yaml"},
            "scope": {"objective": "fixture"},
            "excluded_ingress": [],
            "products": [
                {
                    "id": "demo",
                    "name": "Demo data",
                    "domain": "demo",
                    "priority": "P1",
                    "required": True,
                    "decision": "Make one evidence-backed demo decision.",
                    "owner": "book-demo-data",
                    "consumers": ["demo-consumer"],
                    "grain": "one demo record",
                    "retention": "evidence",
                    "permission": {
                        "status": "approved",
                        "classification": "public_source_with_terms",
                        "basis": "Public fixture API",
                    },
                    "cron_tags": ["book-demo-data-feeds"],
                    "sources": [
                        {
                            "job": "demo_source",
                            "quality_status": "verified",
                            "capture": {"paths": ["capture/demo.csv"], "max_age_hours": 4},
                        }
                    ],
                    "lake": {
                        "required": True,
                        "datasets": [
                            {
                                "id": "demo",
                                "paths": ["data/lake/bronze/domain=demo/dataset=demo/part.parquet"],
                                "max_age_hours": 4,
                            }
                        ],
                    },
                    "delivery": {
                        "kind": "api_and_duckdb",
                        "contract_path": "contracts/demo.yaml",
                        "schema_version": "demo.v1",
                        "api_port": 8199,
                        "api_mode": "on_demand",
                    },
                    "next_action": "Keep the fixture current.",
                }
            ],
        }
        requirements_path = root / "requirements.yaml"
        source_path = root / "source-registry.yaml"
        self._write_yaml(requirements_path, config)
        self._write_yaml(source_path, source_registry)
        self._touch(root / "capture" / "demo.csv")
        self._touch(root / "data" / "lake" / "bronze" / "domain=demo" / "dataset=demo" / "part.parquet")
        contract = root / "contracts" / "demo.yaml"
        contract.parent.mkdir(parents=True, exist_ok=True)
        contract.write_text("schema_version: demo.v1\n", encoding="utf-8")
        return requirements_path, source_path, config, source_registry

    def test_complete_product_is_end_to_end_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            requirements, source, _, _ = self._fixtures(root)
            report = build_report(
                root,
                requirements,
                source,
                crontab_text="0 * * * * run # book-demo-data-feeds\n",
                now=NOW,
            )
        self.assertEqual(report["validation_errors"], [])
        self.assertEqual(report["summary"]["source_job_mapping_pct"], 100.0)
        self.assertEqual(report["summary"]["permission_ready_pct"], 100.0)
        self.assertEqual(report["summary"]["schedule_ready_pct"], 100.0)
        self.assertEqual(report["summary"]["end_to_end_ready_pct"], 100.0)
        self.assertEqual(report["products"][0]["stage"], "end_to_end")
        self.assertEqual(report["products"][0]["api_status"], "not_checked")

    def test_stale_lake_is_not_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            requirements, source, _, _ = self._fixtures(root)
            lake_file = root / "data" / "lake" / "bronze" / "domain=demo" / "dataset=demo" / "part.parquet"
            self._touch(lake_file, NOW - timedelta(hours=12))
            report = build_report(
                root,
                requirements,
                source,
                crontab_text="# book-demo-data-feeds\n",
                now=NOW,
            )
        self.assertEqual(report["products"][0]["lake_status"], "stale")
        self.assertEqual(report["products"][0]["stage"], "lake_stale")
        self.assertEqual(report["summary"]["end_to_end_ready"], 0)
        self.assertIn("lake", {gap["code"] for gap in report["gaps"]})

    def test_stale_capture_is_a_separate_end_to_end_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            requirements, source, _, _ = self._fixtures(root)
            self._touch(root / "capture" / "demo.csv", NOW - timedelta(hours=12))
            report = build_report(
                root,
                requirements,
                source,
                crontab_text="# book-demo-data-feeds\n",
                now=NOW,
            )
        product = report["products"][0]
        self.assertEqual(product["source_status"], "ready")
        self.assertEqual(product["capture_status"], "stale")
        self.assertEqual(product["stage"], "capture_stale")
        self.assertEqual(report["summary"]["end_to_end_ready"], 0)
        self.assertIn("capture", {gap["code"] for gap in report["gaps"]})

    def test_blocked_source_remains_an_owned_gap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            requirements, source, _, _ = self._fixtures(root, source_status="blocked")
            report = build_report(
                root,
                requirements,
                source,
                crontab_text="# book-demo-data-feeds\n",
                now=NOW,
            )
        product = report["products"][0]
        self.assertEqual(product["source_status"], "blocked")
        self.assertEqual(product["stage"], "collection_gap")
        collection_gap = next(gap for gap in report["gaps"] if gap["code"] == "collection")
        self.assertEqual(collection_gap["owner"], "book-demo-data")
        self.assertTrue(collection_gap["next_action"])

    def test_registry_job_must_be_mapped_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _, _, config, source_registry = self._fixtures(root)
            source_registry["sources"].append(
                {
                    "job": "unmapped_source",
                    "business": "demo",
                    "status": "active",
                }
            )
            errors = validate_config(config, source_registry)
        self.assertIn("unmapped source registry jobs: unmapped_source", errors)

    def test_sensitive_evidence_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _, _, config, source_registry = self._fixtures(root)
            config["products"][0]["sources"][0]["capture"]["paths"] = ["infra/.env"]
            errors = validate_config(config, source_registry)
        self.assertTrue(any("unsafe capture path" in error for error in errors))

    def test_report_never_includes_raw_crontab_or_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            requirements, source, _, _ = self._fixtures(root)
            report = build_report(
                root,
                requirements,
                source,
                crontab_text="SECRET_VALUE=do-not-copy\n# book-demo-data-feeds\n",
                now=NOW,
            )
            markdown = render_markdown(report)
            encoded = json.dumps(report)
        self.assertNotIn("SECRET_VALUE", markdown)
        self.assertNotIn("do-not-copy", encoded)
        self.assertIn("Requirement-to-delivery matrix", markdown)
        self.assertEqual(report["safety"]["credentials"], "not-read")


if __name__ == "__main__":
    unittest.main()
