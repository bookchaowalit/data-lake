#!/usr/bin/env python3
"""Tests for the local nested product-source readiness boundary."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts"))

from data_lake.product_source_preflight import PRODUCTS, build_report  # noqa: E402


class ProductSourcePreflightTests(unittest.TestCase):
    def _make_package(self, root: Path, index: int) -> None:
        product = PRODUCTS[index]
        (root / product["relative_path"] / "src" / product["package"]).mkdir(parents=True)

    def test_empty_root_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report = build_report(Path(temp_dir))
        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["available_count"], 0)
        self.assertEqual(report["network"], "not-used")
        self.assertEqual(report["credentials"], "not-read")

    def test_partial_root_is_not_full_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._make_package(root, 0)
            report = build_report(root)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["available_count"], 1)

    def test_all_packages_are_available(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index in range(len(PRODUCTS)):
                self._make_package(root, index)
            report = build_report(root)
        self.assertEqual(report["status"], "available")
        self.assertEqual(report["available_count"], len(PRODUCTS))
        self.assertTrue(all(item["source_available"] for item in report["products"]))


if __name__ == "__main__":
    unittest.main()
