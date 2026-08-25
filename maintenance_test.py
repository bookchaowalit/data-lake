#!/usr/bin/env python3
"""Tests for the read-only lake maintenance and restore drill."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts"))

from data_lake.ingest import ingest_payload  # noqa: E402
from data_lake.maintenance import build_maintenance_report, restore_manifest  # noqa: E402
from data_lake.storage import ObjectStore  # noqa: E402


class MaintenanceTests(unittest.TestCase):
    def _ingest(self, root: str) -> dict[str, str]:
        try:
            import pyarrow  # noqa: F401
            import duckdb  # noqa: F401
        except ImportError:
            self.skipTest("pyarrow/duckdb not installed")
        return ingest_payload(
            b'{"id":"a","value":1}',
            [{"id": "a", "value": 1, "event_time": "2026-08-07T00:00:00Z"}],
            source="maintenance-test",
            domain="portfolio",
            dataset="demo",
            data_lake_uri=root,
            input_format="json",
            event_time_field="event_time",
            privacy_class="public",
            retention_class="operational",
        )

    def test_report_uses_manifest_lineage_and_finds_orphan(self):
        with tempfile.TemporaryDirectory() as root:
            result = self._ingest(root)
            ObjectStore(root).put_bytes("bronze/orphan/part-000.parquet", b"orphan")
            report = build_maintenance_report(root, small_file_bytes=10 * 1024 * 1024)
            self.assertEqual(report["mode"], "read_only_dry_run")
            self.assertEqual(report["integrity"]["missing_references"], [])
            self.assertIn(
                "bronze/orphan/part-000.parquet",
                [item["key"] for item in report["integrity"]["orphan_candidates"]],
            )
            self.assertEqual(report["safety"]["deletes"], False)
            self.assertIn(
                result["bronze_key"],
                [item["key"] for item in report["compaction"]["small_file_candidates"]],
            )

    def test_report_marks_old_manifest_without_deleting(self):
        with tempfile.TemporaryDirectory() as root:
            result = self._ingest(root)
            store = ObjectStore(root)
            original = json.loads(store.get_bytes(result["manifest_key"]))
            original["received_at"] = "2020-01-01T00:00:00Z"
            old_key = "control/manifests/source=maintenance-test/old.json"
            store.put_bytes(old_key, (json.dumps(original) + "\n").encode())
            report = build_maintenance_report(
                root,
                older_than_days=30,
                now=datetime(2026, 8, 8, tzinfo=timezone.utc),
            )
            self.assertTrue(any(item["manifest_key"] == old_key for item in report["retention"]["candidates"]))

    def test_report_surfaces_permission_errors_without_false_orphans(self):
        with tempfile.TemporaryDirectory() as root:
            result = self._ingest(root)
            with patch.object(ObjectStore, "get_bytes", side_effect=PermissionError("denied")):
                report = build_maintenance_report(root)
            self.assertEqual(report["status"], "attention")
            self.assertFalse(report["integrity"]["orphan_check_complete"])
            self.assertEqual(len(report["integrity"]["permission_errors"]), 1)
            self.assertEqual(report["integrity"]["orphan_candidates"], [])
            self.assertEqual(
                report["integrity"]["permission_errors"][0]["manifest_key"],
                result["manifest_key"],
            )

    def test_restore_verifies_raw_bytes_and_bronze_rows(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as evidence:
            result = self._ingest(root)
            restored = restore_manifest(root, result["manifest_key"], output_dir=evidence)
            self.assertEqual(restored["status"], "verified")
            self.assertTrue(restored["raw_bytes_exact"])
            self.assertEqual(restored["record_count"], 1)
            self.assertTrue((Path(evidence) / "bronze.parquet").exists())


if __name__ == "__main__":
    unittest.main()
