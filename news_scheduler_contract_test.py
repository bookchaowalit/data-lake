#!/usr/bin/env python3
"""Offline contract checks for the domain-owned News scheduler plan."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SETUP_CRON = (
    ROOT
    / "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-news-scraping/setup_cron.sh"
)


class NewsSchedulerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = SETUP_CRON.read_text(encoding="utf-8")

    def test_cron_targets_control_plane_runner_and_shared_lock(self) -> None:
        self.assertIn("15 */2", self.script)
        self.assertIn("run_news_capture.py", self.script)
        self.assertIn("--lake-uri", self.script)
        self.assertIn("--lock-path", self.script)
        self.assertIn("--limit 50", self.script)
        self.assertIn("--attempts 2", self.script)
        self.assertIn("--collector-timeout-seconds 120", self.script)
        self.assertIn("book-news-scraping-feeds", self.script)
        self.assertNotIn("scripts/run_feeds.py --limit 50", self.script)

    def test_install_requires_explicit_writable_lake(self) -> None:
        self.assertIn("SOLO_EMPIRE_DATA_LAKE_URI", self.script)
        self.assertIn("Refusing cron install", self.script)
        self.assertIn("missing or not writable", self.script)
        self.assertIn("duckdb, feedparser, pyarrow", self.script)

    def test_plan_is_read_only_and_prints_the_resolved_entry(self) -> None:
        with tempfile.TemporaryDirectory(prefix="news-scheduler-plan-") as lake:
            env = os.environ.copy()
            env["SOLO_EMPIRE_DATA_LAKE_URI"] = lake
            completed = subprocess.run(
                ["bash", str(SETUP_CRON), "plan"],
                cwd=ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
        self.assertIn("Scheduler plan (not installed)", completed.stdout)
        self.assertIn("15 */2", completed.stdout)
        self.assertIn("run_news_capture.py", completed.stdout)
        self.assertIn("--lake-uri", completed.stdout)
        self.assertIn("book-news-scraping-feeds", completed.stdout)

    def test_install_fails_before_touching_crontab_without_lake(self) -> None:
        env = os.environ.copy()
        env.pop("SOLO_EMPIRE_DATA_LAKE_URI", None)
        completed = subprocess.run(
            ["bash", str(SETUP_CRON), "install"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("set SOLO_EMPIRE_DATA_LAKE_URI", completed.stderr)


if __name__ == "__main__":
    unittest.main()
