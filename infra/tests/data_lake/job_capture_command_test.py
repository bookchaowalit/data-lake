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

from data_lake.workspace import OWNER_REL, product_repo_available  # noqa: E402

JOB_DATA_REL = OWNER_REL + "/public/book-apps/tools/book-job-data"
if product_repo_available(JOB_DATA_REL):
    from data_lake import ingest_job_captures  # noqa: E402


@unittest.skipUnless(
    product_repo_available(JOB_DATA_REL),
    "book-job-data repository not found under SOLO_EMPIRE_ROOT",
)
class JobCaptureCommandTests(unittest.TestCase):
    def test_default_inputs_are_forwarded_as_stable_repo_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "data") as directory:
            fixture_root = Path(directory)
            capture_dir = fixture_root / (
                "projects/product/engineering/book-dev/github/bookchaowalit/"
                "public/book-apps/tools/book-job-scraping/data"
            )
            capture_dir.mkdir(parents=True)
            capture = capture_dir / "job_postings.csv"
            career_capture = capture_dir / "career_postings.csv"
            capture.write_text("id,title\nfixture,Engineer\n", encoding="utf-8")
            career_capture.write_text("id,title\ncareer,Engineer\n", encoding="utf-8")

            with patch.object(ingest_job_captures, "ROOT", fixture_root), patch.object(
                ingest_job_captures, "WORKSPACE", fixture_root
            ), patch.object(
                ingest_job_captures, "OWNER_ROOT", fixture_root / OWNER_REL
            ), patch.object(
                ingest_job_captures.job_ingest, "default_inputs", return_value=[capture]
            ), patch.object(ingest_job_captures.job_ingest, "main", return_value=0) as owned_main:
                self.assertEqual(
                    ingest_job_captures.main(
                        ["--data-lake-uri", str(fixture_root / "lake"), "--dry-run"]
                    ),
                    0,
                )
        args = owned_main.call_args.args[0]
        self.assertIn(
            "projects/product/engineering/book-dev/github/bookchaowalit/public/book-apps/tools/book-job-scraping/data/job_postings.csv",
            args,
        )
        self.assertIn(
            "projects/product/engineering/book-dev/github/bookchaowalit/public/book-apps/tools/book-job-scraping/data/career_postings.csv",
            args,
        )
        self.assertNotIn(str(capture), args)


if __name__ == "__main__":
    unittest.main()
