from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "opportunities" / "import_job_scraper.py"
SPEC = importlib.util.spec_from_file_location("import_job_scraper", MODULE_PATH)
assert SPEC and SPEC.loader
import_job_scraper = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = import_job_scraper
SPEC.loader.exec_module(import_job_scraper)


def qualified_row(status: str = "PASS") -> dict[str, str]:
    return {
        "title": "Contract Python Engineer",
        "url": "https://example.test/jobs/1",
        "location": "Worldwide",
        "qualification_status": status,
        "policy_version": "contract-first-thailand-v1",
        "employment_type": "Contract",
        "work_arrangement": "Remote",
        "thailand_eligibility": "LIKELY",
        "concurrent_employment": "VERIFY",
        "engagement_boundary": "VERIFY",
        "application_readiness": "REVIEW_REQUIRED",
        "qualification_reasons": "flexible_engagement_and_thailand_eligible",
    }


class JobScraperImportTests(unittest.TestCase):
    def test_career_lane_and_canonical_backlog_path(self):
        lane, category = import_job_scraper.classify({**qualified_row(), 'search_lane': 'relocation'}, 'job_matches')
        self.assertEqual(lane, 'relocation')
        self.assertEqual(category, 'International career')
        self.assertTrue(import_job_scraper.BACKLOG_MD.is_file())

    def test_central_backlog_defaults_to_pass_only(self):
        self.assertEqual(import_job_scraper.DEFAULT_IMPORT_STATUSES, "PASS")

    def test_reads_job_matches_not_raw_postings(self):
        result = SimpleNamespace(
            data_status="ok",
            items=[qualified_row()],
            source="api",
            error_message="",
        )
        with mock.patch.object(import_job_scraper, "fetch_jobs", return_value=result) as fetch:
            rows, source = import_job_scraper.read_rows(20)
        fetch.assert_called_once_with(dataset="job_matches", limit=20)
        self.assertEqual(source, "api")
        self.assertEqual(rows[0]["qualification_status"], "PASS")

    def test_empty_or_legacy_dataset_fails_closed(self):
        empty = SimpleNamespace(data_status="empty", items=[], source="api", error_message="")
        with mock.patch.object(import_job_scraper, "fetch_jobs", return_value=empty):
            with self.assertRaises(RuntimeError):
                import_job_scraper.read_rows(20)

        legacy = SimpleNamespace(
            data_status="ok",
            items=[{"title": "Legacy", "url": "https://example.test/legacy"}],
            source="api",
            error_message="",
        )
        with mock.patch.object(import_job_scraper, "fetch_jobs", return_value=legacy):
            with self.assertRaises(RuntimeError):
                import_job_scraper.read_rows(20)

        partial = SimpleNamespace(
            data_status="ok",
            items=[{**qualified_row(), "thailand_eligibility": ""}],
            source="api",
            error_message="",
        )
        with mock.patch.object(import_job_scraper, "fetch_jobs", return_value=partial):
            with self.assertRaises(RuntimeError):
                import_job_scraper.read_rows(20)

    def test_reject_never_enters_selected_rows(self):
        rows = [qualified_row("PASS"), qualified_row("VERIFY"), qualified_row("REJECT")]
        selected = import_job_scraper.select_qualified_rows(rows, {"PASS", "VERIFY"})
        self.assertEqual([row["qualification_status"] for row in selected], ["PASS", "VERIFY"])

    def test_normalized_engagement_preserves_review_state(self):
        row = import_job_scraper.normalize_row(
            qualified_row("VERIFY"),
            "job_matches",
            "SCRAPER-1",
            "2026-08-30",
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["engagement"], "Contract opportunity (VERIFY)")


if __name__ == "__main__":
    unittest.main()
