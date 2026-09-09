#!/usr/bin/env python3
"""Contract tests for the read-only book-job-data readiness gate."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
import sys

sys.path.insert(0, str(ROOT / "infra" / "scripts"))

from data_lake.ingest import ingest_payload
from data_lake.job_data_readiness import build_job_readiness_report
from data_lake.storage import ObjectStore


class JobDataReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            import duckdb  # noqa: F401
            import pyarrow  # noqa: F401
        except ImportError:
            self.skipTest("pyarrow/duckdb not installed")

    def _ingest(self, root: str, dataset: str, records: list[dict[str, str]]) -> dict:
        return ingest_payload(
            json.dumps(records, ensure_ascii=False).encode("utf-8"),
            records,
            source="book-job-data",
            domain="jobs",
            dataset=dataset,
            data_lake_uri=root,
            input_format="json",
            event_time_field=None,
            metadata={"provider": "fixture"},
            privacy_class="public",
            retention_class="operational",
        )

    def _received_at(self, root: str, manifest_key: str) -> datetime:
        value = json.loads(ObjectStore(root).get_bytes(manifest_key))["received_at"]
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def test_reconciles_committed_batches_and_quality_identity(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            postings = self._ingest(
                root, "job_postings", [{"id": "job-1"}, {"id": "job-2"}]
            )
            matches = self._ingest(root, "job_matches", [{"id": "match-1"}])
            now = max(
                self._received_at(root, postings["manifest_key"]),
                self._received_at(root, matches["manifest_key"]),
            ) + timedelta(hours=1)

            report = build_job_readiness_report(
                root,
                datasets=("job_postings", "job_matches"),
                max_age_hours=24,
                now=now,
            )

            self.assertEqual(report["status"], "ok", report)
            self.assertEqual(report["reconciliation"]["passed_batches"], 2)
            self.assertEqual(report["reconciliation"]["failed_batches"], 0)
            self.assertEqual(
                report["datasets"]["job_postings"]["verified_record_count"], 2
            )
            self.assertEqual(
                report["datasets"]["job_matches"]["verified_record_count"], 1
            )
            self.assertTrue(
                all(
                    batch["checks"]["checkpoint_present"] for batch in report["batches"]
                )
            )
            self.assertTrue(
                all(
                    batch["raw_record_count"] == batch["manifest_record_count"]
                    for batch in report["batches"]
                )
            )
            self.assertFalse(report["safety"]["object_storage_writes"])
            self.assertFalse(report["safety"]["payloads_included"])
            self.assertNotIn("job-1", json.dumps(report, ensure_ascii=False))

    def test_reconciles_deduplicated_capture_against_declared_source_count(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            result = ingest_payload(
                b"id\nsource-1\nsource-1\n",
                [{"id": "logical-1"}],
                source="book-job-data",
                domain="jobs",
                dataset="job_postings",
                data_lake_uri=root,
                input_format="csv",
                metadata={"record_count_before_dedupe": 2},
                privacy_class="internal",
                retention_class="operational",
            )
            received_at = self._received_at(root, result["manifest_key"])
            report = build_job_readiness_report(
                root,
                datasets=("job_postings",),
                max_age_hours=24,
                now=received_at + timedelta(hours=1),
            )
            self.assertEqual(report["status"], "ok", report)
            batch = report["batches"][0]
            self.assertEqual(batch["raw_record_count"], 2)
            self.assertEqual(batch["raw_record_count_expected"], 2)
            self.assertEqual(batch["manifest_record_count"], 1)

    def test_freshness_gate_reports_stale_and_missing_datasets(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            result = self._ingest(root, "job_postings", [{"id": "job-1"}])
            received_at = self._received_at(root, result["manifest_key"])
            report = build_job_readiness_report(
                root,
                datasets=("job_postings", "job_matches"),
                now=received_at + timedelta(hours=9),
            )

            self.assertEqual(report["status"], "attention")
            self.assertEqual(
                report["freshness"]["datasets"]["job_postings"]["status"], "stale"
            )
            self.assertEqual(
                report["freshness"]["datasets"]["job_matches"]["status"], "missing"
            )
            codes = {alert["code"] for alert in report["alerts"]}
            self.assertIn("JOB_DATA_FRESHNESS_STALE", codes)
            self.assertIn("JOB_DATA_DATASET_MISSING", codes)

    def test_raw_checksum_and_manifest_row_count_mismatch_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            result = self._ingest(
                root, "job_postings", [{"id": "job-1"}, {"id": "job-2"}]
            )
            Path(root, result["raw_key"]).write_bytes(b'{"id":"tampered"}')
            received_at = self._received_at(root, result["manifest_key"])
            report = build_job_readiness_report(
                root,
                datasets=("job_postings",),
                max_age_hours=24,
                now=received_at + timedelta(hours=1),
            )
            errors = set(report["batches"][0]["errors"])
            self.assertEqual(report["status"], "attention")
            self.assertIn("raw_checksum_mismatch", errors)
            self.assertIn("raw_record_count_mismatch", errors)

            # A manifest claiming a different total must not make a valid
            # Parquet part appear healthy.
            manifest_path = Path(root, result["manifest_key"])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["record_count"] = 99
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            report = build_job_readiness_report(
                root,
                datasets=("job_postings",),
                max_age_hours=24,
                now=received_at + timedelta(hours=1),
            )
            self.assertIn(
                "record_count_row_count_mismatch", report["batches"][0]["errors"]
            )

    def test_restore_latest_produces_local_evidence_without_storage_writes(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as root,
            tempfile.TemporaryDirectory() as evidence,
        ):
            result = self._ingest(root, "job_postings", [{"id": "job-1"}])
            received_at = self._received_at(root, result["manifest_key"])
            report = build_job_readiness_report(
                root,
                datasets=("job_postings",),
                max_age_hours=24,
                now=received_at + timedelta(hours=1),
                restore_latest=True,
                output_dir=evidence,
            )
            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["recovery"]["status"], "verified")
            self.assertTrue(Path(report["recovery"]["evidence_path"]).is_file())
            self.assertFalse(report["recovery"]["object_storage_writes"])
            self.assertTrue((Path(evidence) / "bronze.parquet").is_file())
            self.assertFalse(
                (Path(evidence) / "source.json").read_bytes().find(b"job-1") == -1
            )


if __name__ == "__main__":
    unittest.main()
