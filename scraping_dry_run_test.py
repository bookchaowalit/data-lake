#!/usr/bin/env python3
"""Offline tests for scraping runner and ingest dry-run contracts."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts"))

from data_lake import (  # noqa: E402
    capture_lock,
    ingest_discovery_captures,
    ingest_scraping_captures,
    run_data_product_stack,
    run_jobs_capture,
    run_market_capture,
    run_news_capture,
    run_seo_capture,
)


class ScrapingDryRunTests(unittest.TestCase):
    def test_capture_runners_return_plans_without_side_effects(self) -> None:
        with (
            patch("subprocess.run", side_effect=AssertionError("dry-run spawned a process")),
            patch.object(Path, "mkdir", side_effect=AssertionError("dry-run created a directory")),
            patch.object(Path, "open", side_effect=AssertionError("dry-run opened a file")),
        ):
            news = run_news_capture.run_news_cycle(lake_uri="fixture", dry_run=True)
            market = run_market_capture.run_market_cycle(
                lake_uri="fixture",
                products=run_market_capture.select_products(["crypto"]),
                dry_run=True,
            )
            seo = run_seo_capture.run_seo_cycle(lake_uri="fixture", dry_run=True)
            jobs = run_jobs_capture.run_jobs_cycle(lake_uri="fixture", dry_run=True)

        self.assertEqual(news["status"], "dry-run")
        self.assertEqual(market["status"], "dry-run")
        self.assertEqual(seo["status"], "dry-run")
        self.assertEqual(jobs["status"], "dry-run")
        self.assertEqual(jobs["plan"]["network"], "not-used")
        self.assertNotIn("health", news)
        self.assertEqual(market["results"], [])

    def test_ingest_parsers_expose_non_writing_dry_run(self) -> None:
        self.assertTrue(ingest_scraping_captures.build_parser().parse_args(["--dry-run"]).dry_run)
        self.assertTrue(ingest_discovery_captures.build_parser().parse_args(["--dry-run"]).dry_run)
        self.assertTrue(run_data_product_stack.build_parser().parse_args(["--dry-run"]).dry_run)

    def test_ingest_dry_run_reports_missing_captures_but_rejects_invalid_ones(self) -> None:
        for module in (ingest_scraping_captures, ingest_discovery_captures):
            for exists in (False, True):
                with self.subTest(module=module.__name__, exists=exists), ExitStack() as mocks:
                    mocks.enter_context(patch.object(Path, "is_file", return_value=exists))
                    ingest = mocks.enter_context(
                        patch.object(module, "ingest_capture", side_effect=ValueError("invalid capture"))
                    )
                    if module is ingest_discovery_captures:
                        mocks.enter_context(patch.object(module, "_capture_lookup", return_value={}))
                    output = mocks.enter_context(redirect_stdout(io.StringIO()))
                    self.assertEqual(module.main(["--dry-run", "--json"]), 1 if exists else 0)
                    payload = json.loads(output.getvalue())
                    self.assertEqual(bool(payload["errors"]), exists)
                    self.assertEqual(bool(payload["skipped"]), not exists)
                    for call in ingest.call_args_list:
                        self.assertTrue(call.kwargs["validate_only"])

    def test_capture_lock_excludes_another_process_and_releases_after_failure(self) -> None:
        probe = (
            "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
            "from data_lake.capture_lock import acquire_lock, LockBusyError\n"
            "try:\n"
            "    with acquire_lock(Path(sys.argv[2])): print('acquired')\n"
            "except LockBusyError:\n"
            "    print('busy')\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.lock"
            command = [sys.executable, "-c", probe, str(ROOT / "infra" / "scripts"), str(path)]
            with self.assertRaisesRegex(RuntimeError, "fixture failure"):
                with capture_lock.acquire_lock(path):
                    result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=10)
                    self.assertEqual(result.stdout.strip(), "busy")
                    raise RuntimeError("fixture failure")
            result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=10)
            self.assertEqual(result.stdout.strip(), "acquired")


if __name__ == "__main__":
    unittest.main()
