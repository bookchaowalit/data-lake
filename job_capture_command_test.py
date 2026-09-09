#!/usr/bin/env python3
"""Tests for the root operator adapter around the owned jobs ingest."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts"))

from data_lake import ingest_job_captures  # noqa: E402


class JobCaptureCommandTests(unittest.TestCase):
    def test_default_inputs_are_forwarded_as_stable_repo_relative_paths(self) -> None:
        capture = ROOT / "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-job-scraping/data/job_postings.csv"
        with tempfile.TemporaryDirectory() as directory, patch.object(
            ingest_job_captures.job_ingest, "default_inputs", return_value=[capture]
        ), patch.object(ingest_job_captures.job_ingest, "main", return_value=0) as owned_main:
            self.assertEqual(
                ingest_job_captures.main(["--data-lake-uri", directory, "--dry-run"]),
                0,
            )
        args = owned_main.call_args.args[0]
        self.assertIn(
            "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-job-scraping/data/job_postings.csv",
            args,
        )
        self.assertIn(
            "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-job-scraping/data/career_postings.csv",
            args,
        )
        self.assertNotIn(str(capture), args)


if __name__ == "__main__":
    unittest.main()
