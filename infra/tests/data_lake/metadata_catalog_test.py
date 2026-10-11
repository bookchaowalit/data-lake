#!/usr/bin/env python3
"""Offline tests for the provider-neutral metadata catalog contract."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts" / "utils"))

from metadata_catalog_guard import validate  # noqa: E402


class MetadataCatalogTests(unittest.TestCase):
    def test_repository_metadata_catalog_is_valid(self):
        self.assertEqual(validate(), [])


if __name__ == "__main__":
    unittest.main()
