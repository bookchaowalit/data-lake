#!/usr/bin/env python3
"""Offline contract tests for the hosted cloud-lake target."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts"))

from data_lake.cloud_preflight import validate_config  # noqa: E402
from data_lake.iceberg import _catalog_properties  # noqa: E402
from data_lake.storage import ObjectStore, StorageError  # noqa: E402


class CloudLakeContractTests(unittest.TestCase):
    def test_local_preflight_is_network_free(self):
        report = validate_config(data_lake_uri="file:///tmp/solo-empire-lake")
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["mode"], "local")

    def test_cloud_preflight_requires_explicit_endpoint_and_write_opt_in(self):
        with patch.dict(
            os.environ,
            {
                "DATA_LAKE_S3_ENDPOINT": "https://account.r2.cloudflarestorage.com",
                "DATA_LAKE_CLOUD_WRITE_ENABLED": "false",
            },
            clear=False,
        ):
            report = validate_config(
                data_lake_uri="s3://solo-empire-portfolio/lake",
                require_cloud_write=True,
            )
        self.assertEqual(report["status"], "error")
        self.assertIn("DATA_LAKE_CLOUD_WRITE_ENABLED", " ".join(report["errors"]))

    def test_cloud_rest_catalog_properties_use_scoped_token(self):
        with patch.dict(
            os.environ,
            {"ICEBERG_CATALOG_TOKEN": "test-token"},
            clear=False,
        ):
            properties = _catalog_properties(
                "https://catalog.example.com/v1",
                "portfolio-warehouse",
            )
        self.assertEqual(properties["type"], "rest")
        self.assertEqual(properties["warehouse"], "portfolio-warehouse")
        self.assertEqual(properties["token"], "test-token")

    def test_rest_catalog_requires_token(self):
        with patch.dict(
            os.environ,
            {"ICEBERG_CATALOG_TOKEN": "", "R2_DATA_CATALOG_TOKEN": ""},
            clear=False,
        ):
            with self.assertRaises(StorageError):
                _catalog_properties("https://catalog.example.com/v1", "warehouse")

    def test_cloud_write_requires_explicit_opt_in_without_network_call(self):
        with patch.dict(
            os.environ,
            {
                "DATA_LAKE_S3_ENDPOINT": "https://account.r2.cloudflarestorage.com",
                "DATA_LAKE_CLOUD_WRITE_ENABLED": "false",
            },
            clear=False,
        ):
            with self.assertRaises(StorageError):
                ObjectStore("s3://solo-empire-portfolio/lake").put_bytes(
                    "landing/demo.json", b"{}"
                )

    def test_cloud_object_budget_rejects_large_object_without_network_call(self):
        with patch.dict(
            os.environ,
            {
                "DATA_LAKE_S3_ENDPOINT": "https://account.r2.cloudflarestorage.com",
                "DATA_LAKE_CLOUD_WRITE_ENABLED": "true",
                "DATA_LAKE_CLOUD_MAX_OBJECT_BYTES": "3",
            },
            clear=False,
        ):
            with self.assertRaises(StorageError):
                ObjectStore("s3://solo-empire-portfolio/lake").put_bytes(
                    "landing/demo.json", b"toolarge"
                )


if __name__ == "__main__":
    unittest.main()
