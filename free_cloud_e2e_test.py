#!/usr/bin/env python3
"""Offline tests for the FREE-CLOUD-E2E-001 evidence runner."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts"))

from data_lake.free_cloud_e2e import DEFAULT_FIXTURE, run_offline_e2e  # noqa: E402


class FreeCloudE2ETests(unittest.TestCase):
    def test_fixture_lake_to_duckdb_e2e(self):
        try:
            import duckdb  # noqa: F401
            import pyarrow  # noqa: F401
        except ImportError:
            self.skipTest("duckdb/pyarrow not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            report = run_offline_e2e(fixture=DEFAULT_FIXTURE, output_dir=Path(temp_dir) / "evidence")
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["query_engine"], "duckdb")
            self.assertEqual(report["query_path"], "bronze_parquet")
            self.assertEqual(report["csv_projection"], "not-written")
            self.assertEqual(report["record_count"], 2)
            self.assertTrue((Path(temp_dir) / "evidence" / "result.json").exists())


if __name__ == "__main__":
    unittest.main()
