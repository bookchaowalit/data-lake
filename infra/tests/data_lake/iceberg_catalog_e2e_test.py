#!/usr/bin/env python3
"""Offline guards for the operator-gated Iceberg catalog E2E command."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts"))

from data_lake.iceberg_catalog_e2e import validate_catalog_runtime  # noqa: E402


class IcebergCatalogE2ETests(unittest.TestCase):
    def _env(self, *, write_enabled: str) -> dict[str, str]:
        return {
            "DATA_LAKE_S3_ENDPOINT": "https://account.r2.cloudflarestorage.com",
            "AWS_REGION": "auto",
            "AWS_ACCESS_KEY_ID": "test-access-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret-key",
            "ICEBERG_CATALOG_URI": "https://catalog.example.test/catalog",
            "ICEBERG_WAREHOUSE_URI": "test-warehouse",
            "ICEBERG_CATALOG_TOKEN": "test-catalog-token",
            "DATA_LAKE_CLOUD_WRITE_ENABLED": write_enabled,
            "DATA_LAKE_CLOUD_MAX_OBJECT_BYTES": "67108864",
        }

    def test_requires_explicit_catalog_write_gate(self):
        with patch.dict(os.environ, self._env(write_enabled="false"), clear=True):
            with self.assertRaisesRegex(ValueError, "cloud writes"):
                validate_catalog_runtime("s3://bucket/prefix")

    def test_validates_all_catalog_runtime_fields_without_network(self):
        with patch.dict(os.environ, self._env(write_enabled="true"), clear=True):
            report = validate_catalog_runtime("s3://bucket/prefix")
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["mode"], "cloud")
        self.assertEqual(report["catalog_uri"], "https://catalog.example.test/catalog")


if __name__ == "__main__":
    unittest.main()
