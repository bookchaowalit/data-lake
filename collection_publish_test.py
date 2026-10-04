#!/usr/bin/env python3
"""Offline publication gates plus optional installed Production Hub integration."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
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

from data_lake.collection_health import build_health_report  # noqa: E402
from data_lake import publish_collection_outputs as publisher  # noqa: E402


class CollectionPublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.report_dir = Path(self.temporary.name) / "reports"
        self.hub_home = Path(self.temporary.name) / "owned-hub"
        self.report_dir.mkdir()
        self.coverage = {
            "contract": "solo-empire.scraping-data-coverage.v1",
            "generated_at": "2026-10-04T12:00:00+00:00",
            "validation_errors": [],
            "summary": {
                "required_products": 2, "end_to_end_ready": 1,
                "end_to_end_ready_pct": 50.0, "p0_gaps": 0,
                "p1_gaps": 1, "p2_gaps": 0,
                "schedule_ready": 1, "schedule_ready_pct": 50.0,
                "fresh_capture": 2, "fresh_capture_pct": 100.0,
            },
            "gaps": [{
                "priority": "P1", "product_id": "private-fixture-marker",
                "code": "schedule", "detail": "private-fixture-marker",
                "owner": "private-fixture-marker", "next_action": "private-fixture-marker",
            }],
            "records": [{"private_payload": "private-fixture-marker"}],
            "source_jobs": [{"token": "private-fixture-marker"}],
        }
        self._write_coverage()

    def _write_coverage(self) -> None:
        (self.report_dir / publisher.COVERAGE_NAME).write_text(json.dumps(self.coverage), encoding="utf-8")

    def _write_health(self, payload: dict) -> None:
        (self.report_dir / publisher.HEALTH_NAME).write_text(json.dumps(payload), encoding="utf-8")

    def _fake_cli(self, command: list[str], timeout_seconds: int) -> bytes:
        self.assertEqual(command[:4], [sys.executable, "-m", "production_hub", "--home"])
        self.assertEqual(Path(command[4]), self.hub_home)
        if command[5] == "show":
            artifact_id = command[6]
            digest = artifact_id.split(":")[1]
            content = (self.hub_home / "store" / "sha256" / digest[:2] / digest).read_bytes()
            return json.dumps({
                "schema_version": "artifact.v1", "artifact_id": artifact_id,
                "kind": "dataset.table" if content.startswith(b"{") else "workflow.plan",
                "byte_size": len(content), "privacy_class": "internal",
                "qa": {"status": "accepted"},
                "producer": {"tool_id": "external", "tool_version": publisher.TOOL_VERSION},
            }).encode()
        self.assertEqual(command[command.index("--privacy") + 1], "internal")
        self.assertEqual(command[command.index("--qa") + 1], "accepted")
        self.assertEqual(command[command.index("--tool") + 1], "external")
        self.assertEqual(command[command.index("--tool-version") + 1], publisher.TOOL_VERSION)
        self.assertEqual(timeout_seconds, 30)
        path = Path(command[command.index("import-file") + 1])
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        self.assertEqual(command[command.index("--job") + 1], f"scraping-collection-{digest}")
        destination = self.hub_home / "store" / "sha256" / digest[:2] / digest
        created = not destination.exists()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return json.dumps({
            "artifact_id": f"sha256:{digest}",
            "kind": command[command.index("--kind") + 1], "created": created,
        }).encode()

    def _publish(self) -> dict:
        return publisher.publish_outputs(self.report_dir, hub_home=self.hub_home)

    def test_publishes_verified_hashes_and_download_links_without_private_fields(self) -> None:
        health = build_health_report(self.coverage, source_report="private-fixture-marker")
        self._write_health(health)
        (self.report_dir / "scraping-data-coverage.md").write_text("private-fixture-marker", encoding="utf-8")
        with patch.object(publisher, "_run_cli", side_effect=self._fake_cli) as cli:
            receipt = self._publish()
        self.assertEqual(cli.call_count, 4)
        self.assertEqual(receipt["status"], "published")
        self.assertEqual(receipt["runtime_status"], "attention")
        self.assertEqual(receipt["health_input"], "verified")
        self.assertEqual(receipt["hub_home"], str(self.hub_home))
        self.assertEqual(receipt["cloud_readiness"], "not-asserted")
        self.assertEqual(receipt["coverage_sha256"], hashlib.sha256(
            (self.report_dir / publisher.COVERAGE_NAME).read_bytes()
        ).hexdigest())
        self.assertEqual(json.loads((self.report_dir / publisher.RECEIPT_NAME).read_bytes()), receipt)
        self.assertEqual({artifact["kind"] for artifact in receipt["artifacts"]}, {"dataset.table", "workflow.plan"})
        for artifact in receipt["artifacts"]:
            stored = Path(artifact["local_destination"]).read_bytes()
            digest = hashlib.sha256(stored).hexdigest()
            self.assertEqual(artifact["artifact_id"], f"sha256:{digest}")
            self.assertEqual(artifact["sha256"], digest)
            self.assertEqual(artifact["byte_size"], len(stored))
            self.assertTrue(artifact["metadata_verified"])
            self.assertEqual(artifact["content_path"], f"/api/production/v1/artifacts/sha256:{digest}/content")
            self.assertNotIn("private-fixture-marker", stored.decode())
        self.assertNotIn("private-fixture-marker", json.dumps(receipt))
        output = json.loads((self.report_dir / "scraping-collection-output.json").read_bytes())
        self.assertEqual(output["health"]["status"], "attention")
        self.assertEqual(output["gap_counts"]["schedule"], 1)
        self.assertNotIn("gaps", output["health"])
        self.assertNotIn("products", output)

    def test_schema_and_count_inconsistency_fail_before_any_hub_call(self) -> None:
        invalid = [
            {"contract": "unsupported"}, {"generated_at": "2026-10-04T12:00:00"},
            {"validation_errors": ["private-fixture-marker"]},
            {"gaps": "private-fixture-marker"},
        ]
        for mutation in invalid:
            with self.subTest(mutation=mutation):
                candidate = {**self.coverage, **mutation}
                (self.report_dir / publisher.COVERAGE_NAME).write_text(json.dumps(candidate), encoding="utf-8")
                with patch.object(publisher, "_run_cli") as cli, self.assertRaises(publisher.PublicationError):
                    self._publish()
                cli.assert_not_called()
        for field, value in [("p1_gaps", 2), ("end_to_end_ready_pct", 100.0), ("schedule_ready", 3), ("fresh_capture_pct", float("nan"))]:
            with self.subTest(field=field):
                candidate = copy.deepcopy(self.coverage)
                candidate["summary"][field] = value
                (self.report_dir / publisher.COVERAGE_NAME).write_text(json.dumps(candidate), encoding="utf-8")
                with patch.object(publisher, "_run_cli") as cli, self.assertRaises(publisher.PublicationError):
                    self._publish()
                cli.assert_not_called()
        self.assertFalse((self.report_dir / publisher.RECEIPT_NAME).exists())

    def test_unknown_gap_code_cannot_forward_private_text(self) -> None:
        self.coverage["gaps"][0]["code"] = "private-fixture-marker"
        self._write_coverage()
        with patch.object(publisher, "_run_cli") as cli, self.assertRaisesRegex(publisher.PublicationError, "coverage_gap_code_unsupported"):
            self._publish()
        cli.assert_not_called()

    def test_inconsistent_supplied_health_is_regenerated_from_current_coverage(self) -> None:
        health = build_health_report(self.coverage, source_report=publisher.COVERAGE_NAME)
        candidates = [
            {**health, "contract": "unsupported"}, {**health, "status": "ok"},
            {**health, "generated_at": "2026-09-30T00:00:00+00:00"},
            {**health, "summary": {**health["summary"], "end_to_end_ready": True}},
            {**health, "summary": {**health["summary"], "end_to_end_ready_pct": float("nan")}},
        ]
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                self._write_health(candidate)
                with patch.object(publisher, "_run_cli", side_effect=self._fake_cli):
                    receipt = self._publish()
                self.assertEqual(receipt["health_input"], "regenerated")
                self.assertEqual(receipt["runtime_status"], "attention")

    def test_missing_or_malformed_health_is_regenerated(self) -> None:
        for content in (None, b"not-json", b"[]", b"x" * (publisher.MAX_REPORT_BYTES + 1)):
            with self.subTest(content_length=None if content is None else len(content)):
                path = self.report_dir / publisher.HEALTH_NAME
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(content)
                with patch.object(publisher, "_run_cli", side_effect=self._fake_cli):
                    receipt = self._publish()
                self.assertEqual(receipt["health_input"], "regenerated")

    def test_partial_failure_writes_no_success_receipt_and_retry_reuses_content(self) -> None:
        attempts = []

        def fail_second(command: list[str], timeout_seconds: int) -> bytes:
            if command[5] == "import-file":
                attempts.append(command)
                if len(attempts) == 2:
                    raise publisher.PublicationError("hub_import_failed")
            return self._fake_cli(command, timeout_seconds)

        with patch.object(publisher, "_run_cli", side_effect=fail_second), self.assertRaisesRegex(publisher.PublicationError, "hub_import_failed"):
            self._publish()
        self.assertFalse((self.report_dir / publisher.RECEIPT_NAME).exists())
        self.assertEqual(len(list((self.hub_home / "store" / "sha256").glob("*/*"))), 1)
        with patch.object(publisher, "_run_cli", side_effect=self._fake_cli):
            receipt = self._publish()
            retry = self._publish()
        self.assertFalse(receipt["artifacts"][0]["created"])
        self.assertTrue(receipt["artifacts"][1]["created"])
        self.assertEqual([item["artifact_id"] for item in receipt["artifacts"]], [item["artifact_id"] for item in retry["artifacts"]])
        self.assertTrue(all(not item["created"] for item in retry["artifacts"]))

    def test_failure_preserves_previous_success_receipt_with_its_source_timestamp(self) -> None:
        with patch.object(publisher, "_run_cli", side_effect=self._fake_cli):
            self._publish()
        before = (self.report_dir / publisher.RECEIPT_NAME).read_bytes()
        self.coverage["generated_at"] = "2026-10-05T12:00:00+00:00"
        self._write_coverage()
        with patch.object(publisher, "_run_cli", side_effect=publisher.PublicationError("hub_import_failed")), self.assertRaises(publisher.PublicationError):
            self._publish()
        self.assertEqual((self.report_dir / publisher.RECEIPT_NAME).read_bytes(), before)
        self.assertEqual(json.loads(before)["generated_at"], "2026-10-04T12:00:00+00:00")

    def test_receipt_mismatch_and_malformed_output_are_rejected(self) -> None:
        for raw in (b"private-fixture-marker", b"[]", b'{"artifact_id":"sha256:wrong","kind":"dataset.table","created":true}'):
            with self.subTest(raw=raw), patch.object(publisher, "_run_cli", return_value=raw), self.assertRaises(publisher.PublicationError):
                self._publish()
        self.assertFalse((self.report_dir / publisher.RECEIPT_NAME).exists())

    def test_receipt_does_not_claim_content_that_is_missing_or_corrupted(self) -> None:
        for corrupt in (False, True):
            def bad_store(command: list[str], timeout_seconds: int) -> bytes:
                raw = self._fake_cli(command, timeout_seconds)
                digest = json.loads(raw)["artifact_id"].split(":")[1]
                target = self.hub_home / "store" / "sha256" / digest[:2] / digest
                if corrupt:
                    target.write_bytes(b"private-fixture-marker")
                else:
                    target.unlink()
                return raw

            with self.subTest(corrupt=corrupt), patch.object(publisher, "_run_cli", side_effect=bad_store), self.assertRaises(publisher.PublicationError):
                self._publish()
        self.assertFalse((self.report_dir / publisher.RECEIPT_NAME).exists())

    def test_deduplicated_metadata_must_match_before_receipt_claims_privacy_or_qa(self) -> None:
        for changes in (
            {"privacy_class": "public"}, {"kind": "workflow.plan"},
            {"qa": {"status": "needs_review"}}, {"schema_version": "unsupported"},
            {"producer": {"tool_id": "unknown", "tool_version": "unknown"}},
        ):
            def mismatch(command: list[str], timeout_seconds: int) -> bytes:
                raw = self._fake_cli(command, timeout_seconds)
                return json.dumps({**json.loads(raw), **changes}).encode() if command[5] == "show" else raw

            with self.subTest(changes=changes), patch.object(publisher, "_run_cli", side_effect=mismatch), self.assertRaisesRegex(publisher.PublicationError, "hub_record_metadata_mismatch"):
                self._publish()
        self.assertFalse((self.report_dir / publisher.RECEIPT_NAME).exists())

    def test_bounded_input_and_symlinks_are_rejected_before_cli(self) -> None:
        path = self.report_dir / publisher.COVERAGE_NAME
        path.write_bytes(b"x" * (publisher.MAX_REPORT_BYTES + 1))
        with patch.object(publisher, "_run_cli") as cli, self.assertRaisesRegex(publisher.PublicationError, "report_too_large"):
            self._publish()
        cli.assert_not_called()
        path.unlink()
        private_file = self.report_dir / ".env-fixture"
        private_file.write_text("private-fixture-marker", encoding="utf-8")
        path.symlink_to(private_file)
        with patch.object(publisher, "_run_cli") as cli, self.assertRaisesRegex(publisher.PublicationError, "report_missing_or_unsafe"):
            self._publish()
        cli.assert_not_called()

    def test_timeout_option_is_bounded_before_cli(self) -> None:
        for timeout in (0, 61, True):
            with self.subTest(timeout=timeout), patch.object(publisher, "_run_cli") as cli, self.assertRaisesRegex(publisher.PublicationError, "timeout_out_of_bounds"):
                publisher.publish_outputs(self.report_dir, hub_home=self.hub_home, timeout_seconds=timeout)
            cli.assert_not_called()

    def test_cli_errors_never_echo_private_child_payload(self) -> None:
        with patch.object(publisher, "_run_cli", return_value=b"private-fixture-marker"), redirect_stdout(io.StringIO()) as captured:
            code = publisher.main(["--report-dir", str(self.report_dir), "--hub-home", str(self.hub_home)])
        self.assertEqual(code, 1)
        response = json.loads(captured.getvalue())
        self.assertEqual(response, {"status": "error", "error": "hub_receipt_invalid", "receipt_updated": False})
        self.assertNotIn("private-fixture-marker", captured.getvalue())

    def test_required_explicit_hub_home(self) -> None:
        with redirect_stdout(io.StringIO()), patch("sys.stderr", new=io.StringIO()), self.assertRaises(SystemExit) as raised:
            publisher.main([])
        self.assertEqual(raised.exception.code, 2)

    def test_real_child_output_cap_timeout_and_failures_are_safe(self) -> None:
        commands = [
            ([sys.executable, "-c", "import sys; sys.stdout.write('x' * 20000); sys.stdout.flush()"], "hub_receipt_too_large"),
            ([sys.executable, "-c", "import time; time.sleep(5)"], "hub_import_timeout"),
            ([sys.executable, "-c", "import sys; sys.stderr.write('private-fixture-marker'); sys.exit(2)"], "hub_import_failed"),
        ]
        for command, error in commands:
            with self.subTest(error=error), self.assertRaisesRegex(publisher.PublicationError, error):
                publisher._run_cli(command, 1)
        self.assertEqual(publisher._run_cli([sys.executable, "-c", "print('{}')"], 1), b"{}\n")

    @unittest.skipUnless(importlib.util.find_spec("production_hub") is not None, "installed production_hub package unavailable")
    def test_installed_hub_cli_import_retry_and_readback(self) -> None:
        receipt = self._publish()
        retry = self._publish()
        self.assertEqual([item["artifact_id"] for item in receipt["artifacts"]], [item["artifact_id"] for item in retry["artifacts"]])
        self.assertTrue(all(not item["created"] for item in retry["artifacts"]))
        listed = json.loads(publisher._run_cli([
            sys.executable, "-m", "production_hub", "--home", str(self.hub_home), "list", "--json",
        ], 30))
        self.assertEqual(len(listed), 2)
        for row in listed:
            record = json.loads(publisher._run_cli([
                sys.executable, "-m", "production_hub", "--home", str(self.hub_home), "show", row["artifact_id"],
            ], 30))
            self.assertEqual(record["privacy_class"], "internal")
            self.assertEqual(record["qa"]["status"], "accepted")
            self.assertEqual(record["producer"]["tool_id"], "external")
            self.assertIn(record["artifact_id"], {item["artifact_id"] for item in receipt["artifacts"]})

    @unittest.skipUnless(importlib.util.find_spec("production_hub") is not None, "installed production_hub package unavailable")
    def test_installed_hub_dedup_cannot_override_existing_public_metadata(self) -> None:
        output, _ = publisher.build_output(self.coverage, None)
        path = self.report_dir / "previous-public.json"
        path.write_bytes(publisher._json_bytes(output))
        publisher._run_cli([
            sys.executable, "-m", "production_hub", "--home", str(self.hub_home),
            "import-file", str(path), "--kind", "dataset.table", "--tool", "external",
            "--tool-version", publisher.TOOL_VERSION, "--job", "previous-public-fixture",
            "--privacy", "public", "--qa", "accepted",
        ], 30)
        with self.assertRaisesRegex(publisher.PublicationError, "hub_record_metadata_mismatch"):
            self._publish()
        self.assertFalse((self.report_dir / publisher.RECEIPT_NAME).exists())


if __name__ == "__main__":
    unittest.main()
