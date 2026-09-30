#!/usr/bin/env python3
"""Offline contract checks for approved market scheduler wiring."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scheduler_contract_utils import require_bash


ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "infra/scripts/data_lake/run_market_capture.py"
SETUP = ROOT / "infra/scripts/data_lake/setup_market_cron.sh"


class MarketSchedulerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = RUNNER.read_text(encoding="utf-8")
        cls.setup = SETUP.read_text(encoding="utf-8")

    def test_runner_declares_only_bounded_approved_products(self) -> None:
        for product, module, tag in (
            ("crypto", "book_crypto.ingest", "book-crypto-data-feeds"),
            ("stocks", "book_stock.ingest", "book-stock-data-feeds"),
            ("fx", "book_fx.ingest", "book-fx-data-feeds"),
            ("defi", "book_defi.ingest", "book-defi-data-feeds"),
        ):
            with self.subTest(product=product):
                self.assertIn(f'"{product}"', self.runner)
                self.assertIn(f'"{module}"', self.runner)
                self.assertIn(tag, self.setup)
        self.assertIn("FREE_ONLY", self.runner)
        self.assertIn("ALLOW_PAID_PROVIDERS", self.runner)
        self.assertIn("ALLOW_EXTERNAL_WRITES", self.runner)
        self.assertIn("market-feeds.lock", self.runner)
        self.assertIn("dependencies_missing", self.runner)

    def test_plan_is_read_only_and_contains_all_entries(self) -> None:
        env = os.environ.copy()
        env["SOLO_EMPIRE_DATA_LAKE_URI"] = "/tmp/market-lake-plan"
        completed = subprocess.run(
            [require_bash(), SETUP.as_posix(), "plan"],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("Market scheduler plan (not installed)", completed.stdout)
        for tag in (
            "book-crypto-data-feeds",
            "book-stock-data-feeds",
            "book-fx-data-feeds",
            "book-defi-data-feeds",
        ):
            self.assertIn(tag, completed.stdout)
        self.assertIn("run_market_capture.py", completed.stdout)

    def test_install_fails_before_crontab_without_explicit_lake(self) -> None:
        env = os.environ.copy()
        env.pop("SOLO_EMPIRE_DATA_LAKE_URI", None)
        with tempfile.TemporaryDirectory(prefix="market-cron-test-") as home:
            env["HOME"] = home
            completed = subprocess.run(
                [require_bash(), SETUP.as_posix(), "install"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("set SOLO_EMPIRE_DATA_LAKE_URI", completed.stderr)

    def test_runner_help_is_local_and_does_not_contact_providers(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(RUNNER), "--help"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("--product", completed.stdout)
        self.assertIn("--lake-uri", completed.stdout)

    def test_runner_rejects_unknown_product_without_traceback(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(RUNNER), "--product", "missing", "--json"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn('"status": "blocked"', completed.stdout)
        self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()
