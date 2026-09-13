#!/usr/bin/env python3
"""Offline contract checks for the approved owned-page SEO scheduler."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "infra/scripts/data_lake/run_seo_capture.py"
SETUP = ROOT / "infra/scripts/data_lake/setup_seo_cron.sh"


class SeoSchedulerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = RUNNER.read_text(encoding="utf-8")
        cls.setup = SETUP.read_text(encoding="utf-8")

    def test_runner_is_bounded_and_free_only(self) -> None:
        for value in (
            "book_seo.ingest",
            "python developer thailand",
            "bookchaowalit.com,chaowalit.com",
            "owned-page",
            "FREE_ONLY",
            "ALLOW_PAID_PROVIDERS",
            "ALLOW_EXTERNAL_WRITES",
            "seo-feeds.lock",
            "dependencies_missing",
        ):
            self.assertIn(value, self.runner)
        self.assertIn("book-seo-data-feeds", self.setup)

    def test_plan_is_read_only_and_explicit(self) -> None:
        env = os.environ.copy()
        env["SOLO_EMPIRE_DATA_LAKE_URI"] = "/tmp/seo-lake-plan"
        completed = subprocess.run(
            ["bash", str(SETUP), "plan"],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("SEO scheduler plan (not installed)", completed.stdout)
        self.assertIn("daily 08:30", completed.stdout)
        self.assertIn("run_seo_capture.py", completed.stdout)
        self.assertIn("book-seo-data-feeds", completed.stdout)

    def test_install_fails_without_explicit_lake(self) -> None:
        env = os.environ.copy()
        env.pop("SOLO_EMPIRE_DATA_LAKE_URI", None)
        with tempfile.TemporaryDirectory(prefix="seo-cron-test-") as home:
            env["HOME"] = home
            completed = subprocess.run(
                ["bash", str(SETUP), "install"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("set SOLO_EMPIRE_DATA_LAKE_URI", completed.stderr)

    def test_runner_help_is_local(self) -> None:
        completed = subprocess.run(
            [str(ROOT / ".venv/bin/python"), str(RUNNER), "--help"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("--lake-uri", completed.stdout)
        self.assertIn("--attempts", completed.stdout)


if __name__ == "__main__":
    unittest.main()
