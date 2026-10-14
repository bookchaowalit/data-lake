#!/usr/bin/env python3
"""Tests for the read-only scraping/source-product coverage audit."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts"))

from data_lake.scraping_coverage import (  # noqa: E402
    CoverageConfigError,
    SCHEMA_VERSION,
    build_report,
    main as coverage_main,
    render_markdown,
    validate_config,
)
from data_lake import scraping_coverage  # noqa: E402


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


class ScrapingCoverageTests(unittest.TestCase):
    def _write_yaml(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    def _touch(self, path: Path, modified: datetime = NOW) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
        timestamp = modified.timestamp()
        os.utime(path, (timestamp, timestamp))

    def _manifest(
        self, lake_root: Path, *, received_at: object = NOW.isoformat(),
        bronze_key: str = "bronze/domain=demo/dataset=demo/part.parquet",
        batch: str = "demo",
    ) -> Path:
        path = lake_root / "control" / "manifests" / "source=demo" / f"batch_id={batch}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "manifest_version": "1", "source": "demo", "domain": "demo", "dataset": "demo",
            "received_at": received_at, "bronze": {"key": bronze_key},
        }), encoding="utf-8")
        os.utime(path, (NOW.timestamp(), NOW.timestamp()))
        return path

    def _fixtures(self, root: Path, *, source_status: str = "active") -> tuple[Path, Path, dict, dict]:
        source_registry = {
            "schema_version": "fixture.source-coverage.v1",
            "sources": [
                {
                    "job": "demo_source",
                    "business": "demo",
                    "source": "Demo API",
                    "channel": "api",
                    "schedule": "0 * * * *",
                    "status": source_status,
                    "owner_repository": "book-demo-data",
                }
            ],
        }
        config = {
            "schema_version": SCHEMA_VERSION,
            "source_registry": {"path": "source-registry.yaml"},
            "scope": {"objective": "fixture"},
            "excluded_ingress": [],
            "products": [
                {
                    "id": "demo",
                    "name": "Demo data",
                    "domain": "demo",
                    "priority": "P1",
                    "required": True,
                    "decision": "Make one evidence-backed demo decision.",
                    "owner": "book-demo-data",
                    "consumers": ["demo-consumer"],
                    "grain": "one demo record",
                    "retention": "evidence",
                    "permission": {
                        "status": "approved",
                        "classification": "public_source_with_terms",
                        "basis": "Public fixture API",
                    },
                    "cron_tags": ["book-demo-data-feeds"],
                    "sources": [
                        {
                            "job": "demo_source",
                            "quality_status": "verified",
                            "capture": {"paths": ["capture/demo.csv"], "max_age_hours": 4},
                        }
                    ],
                    "lake": {
                        "required": True,
                        "datasets": [
                            {
                                "id": "demo",
                                "paths": ["data/lake/bronze/domain=demo/dataset=demo/part.parquet"],
                                "max_age_hours": 4,
                            }
                        ],
                    },
                    "delivery": {
                        "kind": "api_and_duckdb",
                        "contract_path": "contracts/demo.yaml",
                        "schema_version": "demo.v1",
                        "api_port": 8199,
                        "api_mode": "on_demand",
                    },
                    "next_action": "Keep the fixture current.",
                }
            ],
        }
        requirements_path = root / "requirements.yaml"
        source_path = root / "source-registry.yaml"
        self._write_yaml(requirements_path, config)
        self._write_yaml(source_path, source_registry)
        self._touch(root / "capture" / "demo.csv")
        self._touch(root / "data" / "lake" / "bronze" / "domain=demo" / "dataset=demo" / "part.parquet")
        self._manifest(root / "data" / "lake")
        contract = root / "contracts" / "demo.yaml"
        contract.parent.mkdir(parents=True, exist_ok=True)
        contract.write_text("schema_version: demo.v1\n", encoding="utf-8")
        return requirements_path, source_path, config, source_registry

    def test_complete_product_is_end_to_end_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            requirements, source, _, _ = self._fixtures(root)
            report = build_report(
                root,
                requirements,
                source,
                crontab_text="0 * * * * run # book-demo-data-feeds\n",
                now=NOW,
            )
        self.assertEqual(report["validation_errors"], [])
        self.assertEqual(report["summary"]["source_job_mapping_pct"], 100.0)
        self.assertEqual(report["summary"]["permission_ready_pct"], 100.0)
        self.assertEqual(report["summary"]["schedule_ready_pct"], 100.0)
        self.assertEqual(report["summary"]["end_to_end_ready_pct"], 100.0)
        self.assertEqual(report["products"][0]["stage"], "end_to_end")
        self.assertEqual(report["products"][0]["api_status"], "not_checked")

    def test_verified_windows_schedule_is_distinct_from_cron_fixture_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            requirements, source, _, _ = self._fixtures(root)
            with patch("data_lake.scraping_coverage._read_crontab", return_value=("", "unavailable")):
                with patch("data_lake.scraping_coverage._read_windows_schedule", return_value=({"demo"}, "available")):
                    report = build_report(root, requirements, source, now=NOW)
        self.assertEqual(report["summary"]["end_to_end_ready"], 1)
        self.assertEqual(report["products"][0]["windows_task"], "SoloEmpire-Scraping-demo")
        self.assertEqual(report["safety"]["windows_scheduler"], "available")
        self.assertEqual(report["safety"]["crontab"], "unavailable")

    def test_explicit_crontab_fixture_never_probes_real_windows_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            requirements, source, _, _ = self._fixtures(root)
            with patch("data_lake.scraping_coverage._read_windows_schedule") as probe:
                report = build_report(root, requirements, source, crontab_text="", now=NOW)
        probe.assert_not_called()
        self.assertEqual(report["summary"]["schedule_ready"], 0)
        self.assertIsNone(report["products"][0]["windows_task"])

    def test_standalone_script_resolves_sibling_packages_without_pythonpath(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            requirements, source, _, _ = self._fixtures(root)
            environment = dict(os.environ)
            environment.pop("PYTHONPATH", None)
            completed = subprocess.run(
                [
                    sys.executable, "-X", "utf8",
                    str(ROOT / "infra" / "scripts" / "data_lake" / "scraping_coverage.py"),
                    "--root", str(root), "--requirements", str(requirements),
                    "--source-registry", str(source), "--check", "--now", NOW.isoformat(),
                ],
                env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Validation: OK", completed.stdout)

    def test_stale_lake_is_not_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            requirements, source, _, _ = self._fixtures(root)
            lake_file = root / "data" / "lake" / "bronze" / "domain=demo" / "dataset=demo" / "part.parquet"
            self._touch(lake_file, NOW - timedelta(hours=12))
            self._manifest(root / "data" / "lake", received_at=(NOW - timedelta(hours=12)).isoformat())
            report = build_report(
                root,
                requirements,
                source,
                crontab_text="# book-demo-data-feeds\n",
                now=NOW,
            )
        self.assertEqual(report["products"][0]["lake_status"], "stale")
        self.assertEqual(report["products"][0]["stage"], "lake_stale")
        self.assertEqual(report["summary"]["end_to_end_ready"], 0)
        self.assertIn("lake", {gap["code"] for gap in report["gaps"]})

    def test_optional_lake_dataset_does_not_hold_back_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            requirements, source, config, _ = self._fixtures(root)
            held = {
                "id": "held",
                "paths": ["data/lake/bronze/domain=demo/dataset=held/part.parquet"],
                "max_age_hours": 4,
            }
            config["products"][0]["lake"]["datasets"].append(held)
            self._write_yaml(requirements, config)
            required = build_report(root, requirements, source, crontab_text="# book-demo-data-feeds", now=NOW)
            held["required"] = False
            self._write_yaml(requirements, config)
            optional = build_report(root, requirements, source, crontab_text="# book-demo-data-feeds", now=NOW)
        self.assertEqual(required["products"][0]["lake_status"], "partial")
        self.assertEqual(optional["validation_errors"], [])
        self.assertEqual(optional["products"][0]["lake_status"], "fresh")
        self.assertEqual(
            [(item["id"], item["required"], item["status"]) for item in optional["products"][0]["lake_datasets"]],
            [("demo", True, "fresh"), ("held", False, "missing")],
        )

    def test_copied_lake_files_do_not_refresh_committed_ingest_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            requirements, source, _, _ = self._fixtures(root)
            received_at = NOW - timedelta(hours=12)
            self._manifest(root / "data" / "lake", received_at=received_at.isoformat())
            report = build_report(root, requirements, source, crontab_text="# book-demo-data-feeds", now=NOW)
        product = report["products"][0]
        self.assertEqual(product["lake_status"], "stale")
        self.assertEqual(product["lake_datasets"][0]["age_hours"], 12.0)
        self.assertEqual(product["lake_datasets"][0]["age_basis"], "manifest_received_at")
        self.assertEqual(product["lake_datasets"][0]["received_at"], received_at.isoformat())
        self.assertEqual(product["lake_datasets"][0]["modified_at"], NOW.isoformat())
        self.assertEqual(report["summary"]["end_to_end_ready"], 0)

    def test_old_file_mtime_does_not_make_recent_committed_ingest_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            requirements, source, _, _ = self._fixtures(root)
            lake_file = root / "data/lake/bronze/domain=demo/dataset=demo/part.parquet"
            self._touch(lake_file, NOW - timedelta(hours=12))
            report = build_report(root, requirements, source, crontab_text="# book-demo-data-feeds", now=NOW)
        self.assertEqual(report["products"][0]["lake_status"], "fresh")
        self.assertEqual(report["products"][0]["lake_datasets"][0]["age_hours"], 0.0)

    def test_lake_requires_valid_timezone_aware_nonfuture_manifest_timestamp(self) -> None:
        for received_at in (None, "invalid", 1, {}, NOW.replace(tzinfo=None).isoformat(),
                            (NOW + timedelta(seconds=1)).isoformat(),
                            "0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59-23:59"):
            with self.subTest(received_at=received_at), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                requirements, source, _, _ = self._fixtures(root)
                self._manifest(root / "data/lake", received_at=received_at)
                report = build_report(root, requirements, source, crontab_text="# book-demo-data-feeds", now=NOW)
                self.assertNotEqual(report["products"][0]["lake_status"], "fresh")
                self.assertIsNone(report["products"][0]["lake_datasets"][0]["age_hours"])
                self.assertEqual(report["summary"]["end_to_end_ready"], 0)

    def test_lake_timestamp_normalizes_offsets_and_includes_threshold_boundary(self) -> None:
        for received_at, status in (("2026-08-30T15:00:00+07:00", "fresh"),
                                    ("2026-08-30T07:59:59Z", "stale")):
            with self.subTest(received_at=received_at), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                requirements, source, _, _ = self._fixtures(root)
                self._manifest(root / "data/lake", received_at=received_at)
                report = build_report(root, requirements, source, crontab_text="# book-demo-data-feeds", now=NOW)
                self.assertEqual(report["products"][0]["lake_status"], status)

    def test_lake_ignores_uncommitted_parts_and_checkpoint_only_batches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            requirements, source, config, _ = self._fixtures(root)
            config["products"][0]["lake"]["datasets"][0]["paths"] = [
                "data/lake/bronze/domain=demo/dataset=demo/*.parquet"
            ]
            self._write_yaml(requirements, config)
            lake_root = root / "data/lake"
            self._manifest(lake_root, received_at=(NOW - timedelta(hours=12)).isoformat())
            uncommitted_key = "bronze/domain=demo/dataset=demo/uncommitted.parquet"
            self._touch(lake_root / uncommitted_key)
            checkpoint = lake_root / "control/checkpoints/source=demo/batch_id=uncommitted.json"
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            checkpoint.write_text(json.dumps({"received_at": NOW.isoformat(), "bronze_key": uncommitted_key}), encoding="utf-8")
            report = build_report(root, requirements, source, crontab_text="# book-demo-data-feeds", now=NOW)
        evidence = report["products"][0]["lake_datasets"][0]
        self.assertEqual(evidence["status"], "stale")
        self.assertEqual(evidence["matched_files"], 2)
        self.assertEqual(evidence["committed_files"], 1)
        self.assertTrue(evidence["path"].endswith("/part.parquet"))

    def test_lake_selects_latest_committed_timestamp_instead_of_latest_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            requirements, source, config, _ = self._fixtures(root)
            config["products"][0]["lake"]["datasets"][0]["paths"] = [
                "data/lake/bronze/domain=demo/dataset=demo/*.parquet"
            ]
            self._write_yaml(requirements, config)
            lake_root = root / "data/lake"
            self._manifest(lake_root, received_at=(NOW - timedelta(hours=12)).isoformat())
            recent_key = "bronze/domain=demo/dataset=demo/recent.parquet"
            self._touch(lake_root / recent_key, NOW - timedelta(hours=24))
            self._manifest(lake_root, received_at=NOW.isoformat(), bronze_key=recent_key, batch="recent")
            report = build_report(root, requirements, source, crontab_text="# book-demo-data-feeds", now=NOW)
        evidence = report["products"][0]["lake_datasets"][0]
        self.assertEqual(evidence["status"], "fresh")
        self.assertEqual(evidence["committed_files"], 2)
        self.assertTrue(evidence["path"].endswith("/recent.parquet"))
        self.assertEqual(evidence["received_at"], NOW.isoformat())

    def test_lake_missing_or_malformed_commit_marker_is_not_ready(self) -> None:
        for content in (None, "[", "[]", "{}", '{"bronze": []}'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                requirements, source, _, _ = self._fixtures(root)
                manifest = self._manifest(root / "data/lake")
                if content is None:
                    manifest.unlink()
                else:
                    manifest.write_text(content, encoding="utf-8")
                report = build_report(root, requirements, source, crontab_text="# book-demo-data-feeds", now=NOW)
                self.assertNotEqual(report["products"][0]["lake_status"], "fresh")
                self.assertEqual(report["summary"]["end_to_end_ready"], 0)

    def test_lake_manifest_reference_must_be_safe_and_within_its_lake_root(self) -> None:
        for key in (".", "./", "../lake/bronze/domain=demo/dataset=demo/part.parquet",
                    "/bronze/domain=demo/dataset=demo/part.parquet",
                    "bronze/../bronze/domain=demo/dataset=demo/part.parquet",
                    "bronze/.env/part.parquet", "s3://bucket/part.parquet",
                    "bronze/domain=demo/dataset=other/part.parquet", "bronze/\x00.parquet"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                requirements, source, _, _ = self._fixtures(root)
                self._manifest(root / "data/lake", bronze_key=key)
                report = build_report(root, requirements, source, crontab_text="# book-demo-data-feeds", now=NOW)
                self.assertNotEqual(report["products"][0]["lake_status"], "fresh")

    def test_lake_rejects_external_manifest_and_part_symlink_targets(self) -> None:
        for linked in ("manifest", "part"):
            with self.subTest(linked=linked), tempfile.TemporaryDirectory() as directory:
                parent = Path(directory)
                root = parent / "repository"
                requirements, source, _, _ = self._fixtures(root)
                target = parent / "external.fixture"
                if linked == "manifest":
                    link = self._manifest(root / "data/lake")
                    target.write_bytes(link.read_bytes())
                else:
                    link = root / "data/lake/bronze/domain=demo/dataset=demo/part.parquet"
                    target.write_bytes(b"fixture")
                link.unlink()
                try:
                    link.symlink_to(target)
                except OSError:
                    self.skipTest("host does not permit symlink creation")
                original_read = Path.read_text
                def safe_read(path, *args, **kwargs):
                    self.assertTrue(path.resolve().is_relative_to(root), "external symlink target read")
                    return original_read(path, *args, **kwargs)
                with patch.object(Path, "read_text", safe_read):
                    report = build_report(root, requirements, source, crontab_text="# book-demo-data-feeds", now=NOW)
                self.assertNotEqual(report["products"][0]["lake_status"], "fresh")

    def test_lake_rejects_manifest_symlink_to_another_local_lake(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            requirements, source, _, _ = self._fixtures(root)
            marker = self._manifest(root / "data/lake")
            target = root / "data/other-lake/manifest.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(marker.read_bytes())
            marker.unlink()
            try:
                marker.symlink_to(target)
            except OSError:
                self.skipTest("host does not permit symlink creation")
            report = build_report(root, requirements, source, crontab_text="# book-demo-data-feeds", now=NOW)
            self.assertNotEqual(report["products"][0]["lake_status"], "fresh")

    def test_draft_or_pending_contract_is_present_but_not_ready(self) -> None:
        for lifecycle, approval in (
            ("draft", "pending_operator_approval"),
            ("approved", "pending_operator_approval"),
            ("approved", "approved"),
            ("active-local", "approved"),
        ):
            with self.subTest(lifecycle=lifecycle, approval=approval), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                requirements, source, _, _ = self._fixtures(root)
                self._write_yaml(
                    root / "contracts" / "demo.yaml",
                    {"schema_version": "demo.v1", "status": lifecycle, "collection_approval": approval},
                )
                report = build_report(root, requirements, source, crontab_text="# book-demo-data-feeds", now=NOW)
                ready = lifecycle in {"approved", "active-local"} and approval == "approved"
                self.assertEqual(report["summary"]["contract_present"], 1)
                self.assertEqual(report["summary"]["contract_ready"], int(ready))
                self.assertEqual(report["products"][0]["end_to_end_ready"], ready)
                self.assertEqual(any(gap["code"] == "contract" for gap in report["gaps"]), not ready)

    def test_invalid_or_comment_only_contract_is_not_ready(self) -> None:
        for content in (
            "# demo.v1\nschema_version: wrong.v1\n",
            "schema_version: [demo.v1]\n",
            "schema_version: demo.v1\nstatus: [approved]\n",
            "schema_version: [\n",
        ):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                requirements, source, _, _ = self._fixtures(root)
                (root / "contracts" / "demo.yaml").write_text(content, encoding="utf-8")
                report = build_report(root, requirements, source, crontab_text="# book-demo-data-feeds", now=NOW)
                self.assertEqual(report["summary"]["contract_ready"], 0)
                self.assertFalse(report["products"][0]["end_to_end_ready"])

    def test_nested_lake_root_is_discovered_by_coverage_glob(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            requirements, source, config, _ = self._fixtures(root)
            config["products"][0]["lake"]["datasets"][0]["paths"] = [
                "data/lake*/**/bronze/domain=demo/dataset=demo/part.parquet"
            ]
            self._write_yaml(requirements, config)
            self._touch(
                root
                / "data"
                / "lake-local"
                / "scraping-captures-v2"
                / "bronze"
                / "domain=demo"
                / "dataset=demo"
                / "part.parquet"
            )
            self._manifest(root / "data/lake-local/scraping-captures-v2")
            report = build_report(
                root,
                requirements,
                source,
                crontab_text="# book-demo-data-feeds\n",
                now=NOW,
            )
        self.assertEqual(report["products"][0]["lake_status"], "fresh")
        self.assertEqual(report["products"][0]["stage"], "end_to_end")

    def test_stale_capture_is_a_separate_end_to_end_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            requirements, source, _, _ = self._fixtures(root)
            self._touch(root / "capture" / "demo.csv", NOW - timedelta(hours=12))
            report = build_report(
                root,
                requirements,
                source,
                crontab_text="# book-demo-data-feeds\n",
                now=NOW,
            )
        product = report["products"][0]
        self.assertEqual(product["source_status"], "ready")
        self.assertEqual(product["capture_status"], "stale")
        self.assertEqual(product["stage"], "capture_stale")
        self.assertEqual(report["summary"]["end_to_end_ready"], 0)
        self.assertIn("capture", {gap["code"] for gap in report["gaps"]})

    def test_blocked_source_remains_an_owned_gap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            requirements, source, _, _ = self._fixtures(root, source_status="blocked")
            report = build_report(
                root,
                requirements,
                source,
                crontab_text="# book-demo-data-feeds\n",
                now=NOW,
            )
        product = report["products"][0]
        self.assertEqual(product["source_status"], "blocked")
        self.assertEqual(product["stage"], "collection_gap")
        collection_gap = next(gap for gap in report["gaps"] if gap["code"] == "collection")
        self.assertEqual(collection_gap["owner"], "book-demo-data")
        self.assertTrue(collection_gap["next_action"])

    def test_registry_job_must_be_mapped_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _, _, config, source_registry = self._fixtures(root)
            source_registry["sources"].append(
                {
                    "job": "unmapped_source",
                    "business": "demo",
                    "status": "active",
                }
            )
            errors = validate_config(config, source_registry)
        self.assertIn("unmapped source registry jobs: unmapped_source", errors)

    def test_unknown_job_requires_an_explicit_owned_inventory_gap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            requirements, source, config, registry = self._fixtures(root)
            registry["sources"] = []
            self.assertIn("unknown source jobs in requirements: demo_source", validate_config(config, registry))
            config["products"][0]["sources"][0]["inventory_gap"] = True
            self._write_yaml(requirements, config)
            self._write_yaml(source, registry)
            report = build_report(root, requirements, source, crontab_text="# book-demo-data-feeds", now=NOW)
        self.assertEqual(report["validation_errors"], [])
        self.assertEqual(report["source_jobs"][0]["operational_status"], "missing_registry")
        self.assertFalse(report["products"][0]["end_to_end_ready"])
        gap = next(gap for gap in report["gaps"] if gap["code"] == "source_registry")
        self.assertIn("demo_source", gap["detail"])
        self.assertEqual(gap["owner"], "book-demo-data")
        self.assertTrue(gap["next_action"])

    def test_inventory_gap_flag_must_be_boolean(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, _, config, registry = self._fixtures(Path(temp_dir))
            config["products"][0]["sources"][0]["inventory_gap"] = "true"
            errors = validate_config(config, registry)
        self.assertIn("demo/demo_source: inventory_gap must be boolean", errors)

    def test_snapshot_without_runtime_never_claims_live_readiness(self) -> None:
        for status in ("active", "migrated"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                requirements, source, config, registry = self._fixtures(root, source_status=status)
                registry["kind"] = "public-source-registry-snapshot"
                registry["schema_version"] = "solo-empire.scraping-source-registry-snapshot.v1"
                config["source_registry"]["runtime_path"] = "missing-runtime.yaml"
                self._write_yaml(requirements, config)
                self._write_yaml(source, registry)
                report = build_report(root, requirements, crontab_text="# book-demo-data-feeds", now=NOW)
                self.assertEqual(report["validation_errors"], [])
                self.assertEqual(report["source_registry_mode"], "snapshot")
                self.assertEqual(report["source_jobs"][0]["registry_status"], "unknown")
                self.assertEqual(report["products"][0]["capture_status"], "fresh")
                self.assertEqual(report["products"][0]["lake_status"], "fresh")
                self.assertEqual(report["summary"]["end_to_end_ready"], 0)
                crontab = root / "crontab.txt"
                crontab.write_text("# book-demo-data-feeds", encoding="utf-8")
                with patch("builtins.print"):
                    self.assertEqual(coverage_main([
                        "--root", str(root), "--requirements", str(requirements),
                        "--crontab-file", str(crontab), "--now", NOW.isoformat(), "--strict",
                    ]), 2)

    def test_present_runtime_is_used_and_malformed_runtime_is_not_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            requirements, source, config, registry = self._fixtures(root)
            runtime = root / "runtime.yaml"
            self._write_yaml(runtime, registry)
            registry["kind"] = "public-source-registry-snapshot"
            registry["schema_version"] = "solo-empire.scraping-source-registry-snapshot.v1"
            self._write_yaml(source, registry)
            config["source_registry"]["runtime_path"] = "runtime.yaml"
            self._write_yaml(requirements, config)
            report = build_report(root, requirements, crontab_text="# book-demo-data-feeds", now=NOW)
            self.assertEqual(report["source_registry_mode"], "runtime")
            self.assertEqual(report["summary"]["end_to_end_ready"], 1)
            runtime.write_text("[fixture-private-marker", encoding="utf-8")
            with self.assertRaises(CoverageConfigError) as error:
                build_report(root, requirements, crontab_text="", now=NOW)
            self.assertNotIn("fixture-private-marker", str(error.exception))

    def test_fallback_snapshot_requires_its_kind_and_schema(self) -> None:
        for field, value in (
            ("kind", None), ("kind", "snapshot-typo"),
            ("schema_version", None), ("schema_version", "schema-typo"),
        ):
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                requirements, source, config, registry = self._fixtures(root)
                config["source_registry"]["runtime_path"] = "missing-runtime.yaml"
                registry.update(kind="public-source-registry-snapshot", schema_version="solo-empire.scraping-source-registry-snapshot.v1")
                if value is None:
                    registry.pop(field)
                else:
                    registry[field] = value
                self._write_yaml(requirements, config)
                self._write_yaml(source, registry)
                for override in (None, source):
                    with self.subTest(override=override), self.assertRaises(CoverageConfigError):
                        build_report(root, requirements, override, crontab_text="# book-demo-data-feeds", now=NOW)

    def test_runtime_path_cannot_read_sensitive_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            requirements, _, config, registry = self._fixtures(root)
            for name in (".env", ".env.local", ".ENV.production"):
                with self.subTest(name=name):
                    config["source_registry"]["runtime_path"] = "infra/" + name
                    self.assertIn("source_registry.runtime_path must be a safe repository-relative path", validate_config(config, registry))
                    self._write_yaml(requirements, config)
                    with patch("data_lake.scraping_coverage._load_yaml", wraps=scraping_coverage._load_yaml) as load:
                        with self.assertRaises(CoverageConfigError):
                            build_report(root, requirements, crontab_text="", now=NOW)
                    self.assertEqual(load.call_count, 1)

    def test_registry_paths_reject_sensitive_or_external_symlink_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            root = parent / "repository"
            requirements, _, config, _ = self._fixtures(root)
            outside = parent / "outside.yaml"
            sensitive = root / ".env.local"
            for target in (outside, sensitive):
                target.write_text("fixture-only: never read", encoding="utf-8")
                for field in ("path", "runtime_path", "override"):
                    with self.subTest(target=target.name, field=field):
                        link = root / "linked-registry.yaml"
                        if link.is_symlink():
                            link.unlink()
                        try:
                            link.symlink_to(target)
                        except OSError:
                            self.skipTest("host does not permit symlink creation")
                        fixture_config = dict(config, source_registry=dict(config["source_registry"]))
                        override = link if field == "override" else None
                        if field != "override":
                            fixture_config["source_registry"][field] = link.name
                        self._write_yaml(requirements, fixture_config)
                        with patch("data_lake.scraping_coverage._load_yaml", wraps=scraping_coverage._load_yaml) as load:
                            with self.assertRaises(CoverageConfigError):
                                build_report(root, requirements, override, crontab_text="", now=NOW)
                        self.assertEqual(load.call_count, 1)

    def test_malformed_and_duplicate_registry_rows_fail_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, _, config, registry = self._fixtures(Path(temp_dir))
            for malformed in (None, {}, "invalid"):
                self.assertIn("source registry sources must be a list", validate_config(config, {"sources": malformed}))
            self.assertIn("source registry rows must have a non-empty job", validate_config(config, {"sources": [{}]}))
            registry["sources"].append(dict(registry["sources"][0]))
            self.assertIn("duplicate source registry job: demo_source", validate_config(config, registry))
            registry["sources"][0]["status"] = None
            self.assertIn("source registry job demo_source must have a non-empty status", validate_config(config, registry))

    def test_checked_in_snapshot_is_a_pinned_public_metadata_projection(self) -> None:
        snapshot_path = ROOT / "systems" / "ai-data" / "scraping-source-registry.snapshot.yaml"
        snapshot = yaml.safe_load(snapshot_path.read_text(encoding="utf-8"))
        provenance = snapshot["provenance"]
        fields = ["job", "business", "source", "channel", "schedule", "status", "owner_repository"]
        self.assertEqual(provenance["projection_fields"], fields)
        self.assertRegex(provenance["commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(snapshot["kind"], "public-source-registry-snapshot")
        self.assertTrue(snapshot["policy"]["metadata_only"])
        for row in snapshot["sources"]:
            self.assertTrue(set(row) <= set(fields))
        owner = ROOT / provenance["local_path"]
        if owner.is_dir():
            result = subprocess.run(
                ["git", "-C", str(owner), "show", f"{provenance['commit']}:{provenance['path']}"],
                capture_output=True, text=True, encoding="utf-8", timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            canonical = yaml.safe_load(result.stdout)
            projection = [{key: row[key] for key in fields if key in row} for row in canonical["sources"]]
            self.assertEqual(snapshot["sources"], projection)

    def test_checked_in_metadata_is_portable_without_nested_checkouts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for relative in (
                "systems/ai-data/scraping-data-coverage.yaml",
                "systems/ai-data/scraping-source-registry.snapshot.yaml",
            ):
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text((ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8")
            fixture = ROOT / "infra/tests/fixtures/data_lake/scraping-host-crontab.example"
            report = build_report(root, root / "systems/ai-data/scraping-data-coverage.yaml", crontab_text=fixture.read_text(encoding="utf-8"), now=NOW)
        self.assertEqual(report["validation_errors"], [])
        self.assertEqual(report["source_registry_mode"], "snapshot")
        self.assertEqual(report["summary"]["end_to_end_ready"], 0)
        self.assertEqual(report["summary"]["collection_ready"], 0)
        self.assertEqual(report["summary"]["unregistered_source_jobs"], 7)
        missing = {row["job"] for row in report["source_jobs"] if row["registry_status"] == "missing"}
        self.assertEqual(missing, {"notebookspec_tech", "matichon_news", "thai_business_news", "thai_tech_news", "kaidee_classifieds", "wongnai_bangkok", "wongnai_upcountry"})
        self.assertTrue(any(gap["code"] == "source_registry" for gap in report["gaps"]))

    def test_sensitive_evidence_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _, _, config, source_registry = self._fixtures(root)
            config["products"][0]["sources"][0]["capture"]["paths"] = ["infra/.env"]
            errors = validate_config(config, source_registry)
        self.assertTrue(any("unsafe capture path" in error for error in errors))

    def test_report_never_includes_raw_crontab_or_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            requirements, source, _, _ = self._fixtures(root)
            report = build_report(
                root,
                requirements,
                source,
                crontab_text="SECRET_VALUE=do-not-copy\n# book-demo-data-feeds\n",
                now=NOW,
            )
            markdown = render_markdown(report)
            encoded = json.dumps(report)
        self.assertNotIn("SECRET_VALUE", markdown)
        self.assertNotIn("do-not-copy", encoded)
        self.assertIn("Requirement-to-delivery matrix", markdown)
        self.assertEqual(report["safety"]["credentials"], "not-read")

    def test_checked_in_crontab_fixture_is_consumable(self) -> None:
        fixture = ROOT / "infra" / "tests" / "fixtures" / "data_lake" / "scraping-host-crontab.example"
        self.assertTrue(fixture.is_file())
        requirements = ROOT / "systems" / "ai-data" / "scraping-data-coverage.yaml"
        report = build_report(
            ROOT,
            requirements,
            crontab_text=fixture.read_text(encoding="utf-8"),
            crontab_status="fixture",
            now=NOW,
        )
        self.assertEqual(report["safety"]["crontab"], "fixture")
        self.assertEqual(report["validation_errors"], [])
        self.assertEqual(
            coverage_main(["--check", "--crontab-file", str(fixture)]),
            0,
        )


if __name__ == "__main__":
    unittest.main()
