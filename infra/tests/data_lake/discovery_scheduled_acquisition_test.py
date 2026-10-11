"""Offline contract checks for the local Discovery acquisition runner."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "infra/scripts/discovery/run_scheduled_acquisition.py"
SPEC = importlib.util.spec_from_file_location("run_scheduled_acquisition", RUNNER)
assert SPEC and SPEC.loader
scheduled = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = scheduled
SPEC.loader.exec_module(scheduled)


class DiscoveryScheduledAcquisitionTests(unittest.TestCase):
    def test_summary_keeps_counts_and_failed_source_ids_without_payloads(self) -> None:
        payload = {
            "contract": "discovery.portfolio.v1",
            "command": "acquire",
            "partial": True,
            "sources": [
                {"source_id": "first-source", "status": "captured", "count": 4},
                {"source_id": "second-source", "status": "captured", "count": 2},
                {
                    "source_id": "third-source",
                    "status": "unavailable",
                    "error": "PRIVATE_RESPONSE_BODY_SHOULD_NOT_BE_LOGGED",
                },
            ],
        }

        summary = scheduled.summarize_result(payload)

        self.assertIn("sources=3", summary)
        self.assertIn("captured=2", summary)
        self.assertIn("unavailable=1", summary)
        self.assertIn("third-source", summary)
        self.assertNotIn("PRIVATE_RESPONSE_BODY_SHOULD_NOT_BE_LOGGED", summary)

    def test_summary_handles_empty_source_set(self) -> None:
        self.assertIn("sources=0", scheduled.summarize_result({"sources": []}))


if __name__ == "__main__":
    unittest.main()
