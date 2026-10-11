#!/usr/bin/env python3
"""Offline monitoring, regeneration, approval and delivery regressions."""

from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts"))

from data_lake import run_collection_monitor as monitor


def audit() -> dict:
    return {
        "contract": "solo-empire.scraping-data-coverage.v1",
        "generated_at": "2026-09-30T03:00:00+00:00",
        "validation_errors": [],
        "summary": {
            "required_products": 1, "end_to_end_ready": 0,
            "end_to_end_ready_pct": 0.0, "p0_gaps": 0, "p1_gaps": 0, "p2_gaps": 0,
        },
        "gaps": [],
    }


class CollectionMonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name)
        self.coverage = patch.object(monitor, "build_report", return_value=audit()).start()
        self.markdown = patch.object(monitor, "render_markdown", return_value="# Fixture\n").start()
        self.delivery = patch.object(monitor, "_deliver").start()
        self.addCleanup(patch.stopall)

    def test_regenerates_stale_audit_and_writes_daily_and_latest_reports(self) -> None:
        path = self.output / "scraping-data-coverage.json"
        path.write_text("invalid old audit", encoding="utf-8")
        result = monitor.run_monitor(self.output)
        self.coverage.assert_called_once_with(probe_api=False)
        self.assertEqual(result["status"], "attention")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), audit())
        self.assertEqual(json.loads(
            (self.output / "scraping-data-coverage-2026-09-30.json").read_text(encoding="utf-8")
        ), audit())
        self.assertTrue((self.output / "scraping-data-coverage-2026-09-30.md").is_file())
        health = json.loads((self.output / "scraping-collection-health.json").read_text(encoding="utf-8"))
        self.assertEqual(health["status"], "attention")
        self.delivery.assert_not_called()

    def test_delivery_gate_precedes_any_inspection_or_writes(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires_operator_approval"):
            monitor.run_monitor(self.output, telegram=True)
        self.coverage.assert_not_called()
        self.assertEqual(list(self.output.iterdir()), [])
        self.delivery.assert_not_called()

    def test_local_cycle_never_loads_the_credential_backed_alert_adapter(self) -> None:
        with patch.dict(sys.modules, {"alerts": None}):
            self.assertEqual(monitor.run_monitor(self.output)["delivery"], "not-requested")

    def test_alert_contains_only_aggregate_audit_data(self) -> None:
        fixture = copy.deepcopy(audit())
        fixture["gaps"] = [{
            "priority": "P0", "product_id": "fixture", "code": "capture_stale",
            "detail": "PRIVATE DETAIL", "owner": "PRIVATE OWNER", "next_action": "PRIVATE ACTION",
        }]
        fixture["summary"]["p0_gaps"] = 1
        self.coverage.return_value = fixture
        result = monitor.run_monitor(self.output, telegram=True, delivery_approved=True)
        self.assertEqual(result["delivery"], "delivered")
        message = self.delivery.call_args.args[0]
        self.assertNotIn("PRIVATE", message)
        self.assertIn("P0=1", message)

    def test_healthy_audit_does_not_send_an_alert(self) -> None:
        fixture = audit()
        fixture["summary"].update(end_to_end_ready=1, end_to_end_ready_pct=100.0)
        self.coverage.return_value = fixture
        result = monitor.run_monitor(self.output, telegram=True, delivery_approved=True)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["delivery"], "not-needed")
        self.delivery.assert_not_called()

    def test_delivery_failure_returns_failure_after_persisting_evidence(self) -> None:
        self.delivery.side_effect = monitor.MonitorDeliveryError("telegram_delivery_failed")
        with redirect_stdout(io.StringIO()) as output:
            code = monitor.main([
                "--output-dir", str(self.output), "--telegram", "--delivery-approved",
            ])
        self.assertEqual(code, 1)
        self.assertIn("telegram_delivery_failed", output.getvalue())
        self.assertTrue((self.output / "scraping-collection-health.json").is_file())

    def test_strict_attention_and_validation_errors_have_distinct_exit_codes(self) -> None:
        with redirect_stdout(io.StringIO()):
            self.assertEqual(monitor.main(["--output-dir", str(self.output), "--strict"]), 2)
            self.coverage.return_value["validation_errors"] = ["fixture error"]
            self.assertEqual(monitor.main(["--output-dir", str(self.output)]), 1)

    def test_malformed_audit_never_replaces_previous_evidence(self) -> None:
        path = self.output / "scraping-data-coverage.json"
        path.write_text("previous evidence", encoding="utf-8")
        self.coverage.return_value = {}
        with redirect_stdout(io.StringIO()):
            self.assertEqual(monitor.main(["--output-dir", str(self.output)]), 1)
        self.assertEqual(path.read_text(encoding="utf-8"), "previous evidence")
        self.delivery.assert_not_called()

    def test_concurrent_run_fails_without_overwriting_or_delivery(self) -> None:
        with monitor.acquire_lock(self.output / "scraping-collection-monitor.lock"):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(monitor.main(["--output-dir", str(self.output)]), 1)
        self.coverage.assert_not_called()
        self.delivery.assert_not_called()

    def test_plan_never_reads_audit_or_creates_scheduler_evidence(self) -> None:
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(monitor.main(["--schedule-plan"]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "plan-not-installed")
        self.assertEqual(result["external_delivery"], "disabled")
        self.assertEqual(result["host"], "unselected")
        self.assertEqual(result["interval_hours"], 1)
        self.coverage.assert_not_called()
        self.delivery.assert_not_called()

    def test_report_replace_failure_preserves_previous_complete_document(self) -> None:
        path = self.output / "fixture.json"
        path.write_text("previous evidence", encoding="utf-8")
        with patch.object(Path, "replace", side_effect=OSError("fixture write failure")):
            with self.assertRaises(OSError):
                monitor.write_report(path, "new evidence")
        self.assertEqual(path.read_text(encoding="utf-8"), "previous evidence")
        self.assertEqual(list(self.output.iterdir()), [path])


if __name__ == "__main__":
    unittest.main()
