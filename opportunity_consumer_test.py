#!/usr/bin/env python3
"""Contract tests for Track A opportunity consumers (opportunity.v1 / :8108)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "utils"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from _env import PROJECT_ROOT  # noqa: E402
import opportunity_client as oc  # noqa: E402
import data_product_contract_guard as guard  # noqa: E402


SAMPLE_ENVELOPE = {
    "schema_version": "opportunity.v1",
    "source": "book-opportunity-intelligence",
    "retrieved_at": "2026-08-07T12:00:00Z",
    "data_status": "ok",
    "items": [
        {
            "title": "AI tool: Example AI Chat",
            "category": "ai-content",
            "source": "domain:ai_tools",
            "price": "free",
            "url": "https://example.com/ai-chat",
            "trend_score": 85,
            "competition_level": "low",
            "notes": "domain=ai_tools",
            "scraped_at": "2026-08-07 12:00:00",
            "synthesis_run_id": "run-test-1",
            "record_id": "hash:abc",
        },
        {
            "title": "Low score skip",
            "category": "trending-products",
            "source": "domain:crypto",
            "price": "",
            "url": "local://crypto/x",
            "trend_score": 10,
            "competition_level": "high",
            "notes": "",
            "scraped_at": "2026-08-07 12:00:00",
            "synthesis_run_id": "run-test-1",
        },
    ],
    "next_cursor": None,
}


class OpportunityClientTests(unittest.TestCase):
    def test_envelope_validation(self):
        self.assertTrue(oc.is_opportunity_envelope(SAMPLE_ENVELOPE))
        bad = {**SAMPLE_ENVELOPE, "schema_version": "crypto.v1"}
        self.assertFalse(oc.is_opportunity_envelope(bad))

    def test_fetch_via_hook_filters_min_score(self):
        result = oc.fetch_opportunities(
            min_score=50,
            fetch_impl=lambda _url: SAMPLE_ENVELOPE,
            use_gold_fallback=False,
        )
        self.assertEqual(result.source, "api")
        self.assertEqual(result.data_status, "ok")
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0]["title"], "AI tool: Example AI Chat")
        self.assertEqual(result.items[0]["trend_score"], 85)
        self.assertEqual(result.synthesis_run_id, "run-test-1")

    def test_stale_status_preserved(self):
        body = {**SAMPLE_ENVELOPE, "data_status": "stale"}
        result = oc.fetch_opportunities(
            fetch_impl=lambda _url: body,
            use_gold_fallback=False,
        )
        self.assertEqual(result.data_status, "stale")
        self.assertTrue(result.ok)

    def test_empty_status(self):
        body = {**SAMPLE_ENVELOPE, "data_status": "empty", "items": []}
        result = oc.fetch_opportunities(
            fetch_impl=lambda _url: body,
            use_gold_fallback=False,
        )
        self.assertEqual(result.data_status, "empty")
        self.assertEqual(result.items, [])
        self.assertFalse(result.ok)

    def test_unavailable_without_gold_fallback(self):
        def boom(_url):
            raise ConnectionError("refused")

        result = oc.fetch_opportunities(
            fetch_impl=boom,
            use_gold_fallback=False,
        )
        self.assertEqual(result.data_status, "unavailable")
        self.assertEqual(result.source, "none")
        self.assertIn("unavailable", result.error_message.lower())

    def test_invalid_envelope(self):
        result = oc.fetch_opportunities(
            fetch_impl=lambda _url: {"not": "envelope"},
            use_gold_fallback=False,
        )
        self.assertEqual(result.data_status, "malformed")

    def test_client_never_opens_csv(self):
        src = (PROJECT_ROOT / "infra/scripts/utils/opportunity_client.py").read_text(
            encoding="utf-8"
        )
        # Ban list may name the fragments; open()/Path assignment must not.
        self.assertNotIn('open("money_opportunities', src)
        self.assertNotIn("open('money_opportunities", src)
        self.assertNotIn("DictReader", src)
        self.assertIn("/v1/records", src)
        self.assertIn("opportunity.v1", src)


class TrackABoundaryTests(unittest.TestCase):
    def test_track_a_files_exist_and_clean(self):
        errors: list[str] = []
        guard.check_opportunity_consumer_boundaries(errors)
        self.assertEqual(errors, [], msg="\n".join(errors))

    def test_cross_match_uses_client_not_csv(self):
        path = PROJECT_ROOT / "catalog/automation/cross_match_opportunities.py"
        text = path.read_text(encoding="utf-8")
        self.assertIn("opportunity_client", text)
        self.assertIn("opportunity.v1", text)
        self.assertNotIn("money_opportunities.csv", text)
        self.assertNotIn("book-opportunity-scraping", text)

    def test_job_track_b_uses_job_contract_not_opportunity(self):
        """Track B consumes job.v1 and remains separate from opportunity.v1."""
        path = PROJECT_ROOT / "infra/scripts/opportunities/import_job_scraper.py"
        text = path.read_text(encoding="utf-8")
        self.assertIn("job_client", text)
        self.assertIn(":8109", text)
        self.assertNotIn("matched_jobs.csv", text)
        self.assertNotIn("job_postings.csv", text)
        self.assertNotIn("money_opportunities.csv", text)
        self.assertNotIn("8108", text)

    def test_guard_flags_synthetic_csv_consumer(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Simulate a new consumer under catalog/ that opens the forbidden CSV.
            # We call the fragment checker directly.
            violations = oc.assert_no_forbidden_csv_paths(
                'path = ROOT / "data" / "money_opportunities.csv"\n',
                label="catalog/automation/evil.py",
            )
            self.assertTrue(violations)


class CrossMatchUnitTests(unittest.TestCase):
    def test_match_with_injected_items(self):
        # Import without executing network by patching fetch.
        sys.path.insert(0, str(PROJECT_ROOT / "catalog" / "automation"))
        import cross_match_opportunities as cmo  # type: ignore

        sample = [
            {
                "title": "SVG design bundle for cricut",
                "category": "trending-products",
                "source": "domain:ai_tools",
                "price": "",
                "url": "https://example.com/svg",
                "trend_score": 80,
                "competition_level": "medium",
                "notes": "svg vinyl",
                "scraped_at": "2026-08-07 12:00:00",
            }
        ]
        fake = oc.OpportunityLoadResult(
            items=sample,
            data_status="ok",
            source="api",
            schema_version="opportunity.v1",
            retrieved_at="2026-08-07T12:00:00Z",
            synthesis_run_id="run-x",
        )
        with mock.patch.object(oc, "fetch_opportunities", return_value=fake):
            with mock.patch(
                "cross_match_opportunities.fetch_opportunities", return_value=fake
            ):
                opps, meta = cmo.load_opportunities(min_score=50)
        self.assertEqual(len(opps), 1)
        self.assertEqual(meta["data_status"], "ok")
        match = cmo.match_opportunity_to_product(opps[0], cmo.PRODUCT_CATALOG["svg-bundles"])
        self.assertIsNotNone(match)
        self.assertGreaterEqual(match["relevance_score"], 20)


if __name__ == "__main__":
    unittest.main()
