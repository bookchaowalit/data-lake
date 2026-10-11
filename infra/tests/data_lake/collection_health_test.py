#!/usr/bin/env python3
"""Offline tests for coverage-audit-backed collection health."""

from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts"))

from data_lake.collection_health import CollectionHealthError, build_health_report, main  # noqa: E402


class CollectionHealthTests(unittest.TestCase):
    def _report(self) -> dict:
        return {
            "contract": "solo-empire.scraping-data-coverage.v1",
            "generated_at": "2026-09-30T00:00:00+00:00",
            "validation_errors": [],
            "summary": {
                "required_products": 1,
                "end_to_end_ready": 1,
                "end_to_end_ready_pct": 100.0,
                "p0_gaps": 0,
                "p1_gaps": 0,
                "p2_gaps": 0,
            },
            "gaps": [],
        }

    def test_health_uses_coverage_summary_and_never_scheduler_state(self) -> None:
        report = build_health_report(
            {
                "contract": "solo-empire.scraping-data-coverage.v1",
                "generated_at": "2026-09-30T00:00:00+00:00",
                "validation_errors": [],
                "summary": {
                    "required_products": 2,
                    "end_to_end_ready": 1,
                    "end_to_end_ready_pct": 50.0,
                    "p0_gaps": 0,
                    "p1_gaps": 1,
                    "p2_gaps": 0,
                },
                "gaps": [
                    {
                        "priority": "P1",
                        "product_id": "demo",
                        "code": "capture_missing",
                        "detail": "fixture only",
                        "owner": "demo-owner",
                        "next_action": "keep fixture current",
                    }
                ],
            },
            source_report="fixture.json",
        )
        self.assertEqual(report["source"], "scraping_coverage_audit")
        self.assertEqual(report["status"], "attention")
        self.assertEqual(report["safety"]["scheduler_state"], "not-used")
        self.assertEqual(report["summary"]["gap_count"], 1)

    def test_strict_gate_fails_only_from_audit_gaps(self) -> None:
        report = self._report()
        report["summary"]["end_to_end_ready"] = 0
        report["summary"]["end_to_end_ready_pct"] = 0.0
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "coverage.json"
            path.write_text(
                json.dumps(report),
                encoding="utf-8",
            )
            self.assertEqual(main(["--coverage-report", str(path), "--strict"]), 2)

    def test_malformed_audits_never_pass_the_strict_gate(self) -> None:
        mutations = [
            ("contract", "unsupported"),
            ("generated_at", "invalid"),
            ("generated_at", "2026-09-30T00:00:00"),
            ("validation_errors", "not-a-list"),
            ("validation_errors", [None]),
            ("summary", {}),
            ("gaps", "not-a-list"),
            ("gaps", [None]),
            ("gaps", [{"priority": "P1"}]),
        ]
        for key, value in mutations:
            report = self._report()
            report[key] = value
            self._assert_invalid_audit(report)
        for key, value in [
            ("required_products", 0),
            ("required_products", -1),
            ("required_products", "1"),
            ("required_products", True),
            ("required_products", 1.9),
            ("end_to_end_ready", 2),
            ("end_to_end_ready", 1.1),
            ("end_to_end_ready_pct", float("nan")),
            ("end_to_end_ready_pct", 50.0),
            ("p1_gaps", 1),
        ]:
            report = self._report()
            report["summary"][key] = value
            self._assert_invalid_audit(report)

    def _assert_invalid_audit(self, report: dict) -> None:
        with self.subTest(report=report):
            with self.assertRaises(CollectionHealthError):
                build_health_report(copy.deepcopy(report), source_report="fixture.json")
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "coverage.json"
                path.write_text(json.dumps(report), encoding="utf-8")
                with redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(main(["--coverage-report", str(path), "--strict"]), 1)
                self.assertIn("ERROR:", output.getvalue())

    def test_complete_audit_passes_and_validation_errors_fail(self) -> None:
        report = self._report()
        self.assertEqual(build_health_report(report, source_report="fixture.json")["status"], "ok")
        report["validation_errors"] = ["fixture invalid"]
        self.assertEqual(build_health_report(report, source_report="fixture.json")["status"], "error")


if __name__ == "__main__":
    unittest.main()
