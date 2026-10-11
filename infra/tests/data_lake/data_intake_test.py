#!/usr/bin/env python3
"""Regression tests for Source Registry and lake-first Intake Queue."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "infra" / "database" / "schema.sql"
CLI = ROOT / "infra" / "scripts" / "cli" / "data-intake-cli.py"
RUNNER = ROOT / "infra" / "tests" / "support" / "run_with_sqlite_store.py"


def run_cli(db_path: Path, args: list[str], *, expect_ok: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["SOLO_EMPIRE_DB_PATH"] = str(db_path)
    env["EMPIRE_CLIENT_CONFIG"] = "/nonexistent"
    result = subprocess.run(
        [sys.executable, str(RUNNER), str(CLI), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if expect_ok and result.returncode != 0:
        raise AssertionError(result.stderr.strip() or result.stdout.strip())
    if not expect_ok and result.returncode == 0:
        raise AssertionError("command unexpectedly succeeded")
    return result


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="solo-empire-intake-") as temp_dir:
        temp = Path(temp_dir)
        db_path = temp / "intake-test.db"
        lake_path = temp / "lake"
        conn = sqlite3.connect(db_path)
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        conn.close()

        register = run_cli(db_path, [
            "source", "register",
            "--key", "diary-manual",
            "--name", "Diary Manual Fixture",
            "--kind", "manual",
            "--domain", "life",
            "--dataset", "diary",
            "--privacy-class", "private",
            "--status", "active",
            "--json",
        ])
        source = json.loads(register.stdout)
        assert source["source_key"] == "diary-manual"
        assert source["status"] == "active"

        secret_attempt = run_cli(db_path, [
            "source", "register",
            "--key", "unsafe-source",
            "--name", "Unsafe",
            "--kind", "manual",
            "--domain", "life",
            "--dataset", "unsafe",
            "--description", "token=do-not-store",
        ], expect_ok=False)
        assert "credential-shaped" in secret_attempt.stderr

        lower_privacy = run_cli(db_path, [
            "enqueue",
            "--source", "diary-manual",
            "--input-ref", "manual:fixture-privacy",
            "--idempotency-key", "fixture-privacy-001",
            "--payload-kind", "json",
            "--privacy-class", "internal",
        ], expect_ok=False)
        assert "less restrictive" in lower_privacy.stderr

        queued = run_cli(db_path, [
            "enqueue",
            "--source", "diary-manual",
            "--input-ref", "manual:fixture-001",
            "--idempotency-key", "fixture-001",
            "--source-batch-ref", "batch-fixture-001",
            "--payload-kind", "json",
            "--requested-by", "agent",
            "--json",
        ])
        intake = json.loads(queued.stdout)
        assert intake["status"] == "queued"
        assert intake["privacy_class"] == "private"
        assert "manual:fixture-001" not in queued.stdout

        duplicate = run_cli(db_path, [
            "enqueue",
            "--source", "diary-manual",
            "--input-ref", "manual:fixture-001-retry",
            "--idempotency-key", "fixture-001",
            "--payload-kind", "json",
        ], expect_ok=False)
        assert "constraint conflict" in duplicate.stderr

        run_cli(db_path, ["claim", intake["intake_key"], "--worker", "test-worker", "--json"])
        wrong_renew = run_cli(
            db_path,
            ["renew", intake["intake_key"], "--worker", "other-worker"],
            expect_ok=False,
        )
        assert "another worker" in wrong_renew.stderr
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE intake_queue SET lease_expires_at = '2099-01-01T00:00:00.900000Z' WHERE intake_key = ?",
            (intake["intake_key"],),
        )
        conn.commit()
        conn.close()
        renewed = run_cli(
            db_path,
            [
                "renew", intake["intake_key"], "--worker", "test-worker",
                "--lease-minutes", "1", "--json",
            ],
        )
        renewed_payload = json.loads(renewed.stdout)
        assert renewed_payload["lease_owner"] == "test-worker"
        assert renewed_payload["lease_expires_at"] == "2099-01-01T00:00:01Z"

        raw_key = "landing/source=diary-manual/batch_id=fixture-001/payload.json"
        bronze_key = "bronze/domain=life/dataset=diary/schema_version=1/ingest_date=2026-08-08/source=diary-manual/part-fixture-001.parquet"
        manifest_key = "control/manifests/source=diary-manual/batch_id=fixture-001.json"
        raw_bytes = b'{"fixture":true}\n'
        raw_digest = hashlib.sha256(raw_bytes).hexdigest()
        for key, content in ((raw_key, raw_bytes), (bronze_key, b"bronze-fixture")):
            target = lake_path / key
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        manifest = {
            "manifest_version": "1",
            "source": "diary-manual",
            "domain": "life",
            "dataset": "diary",
            "schema_version": "1",
            "run_id": "2026-08-08-fixture-001",
            "record_count": 1,
            "raw": {"key": raw_key, "sha256": raw_digest, "bytes": len(raw_bytes)},
            "bronze": {
                "key": bronze_key,
                "sha256": hashlib.sha256(b"bronze-fixture").hexdigest(),
                "bytes": len(b"bronze-fixture"),
            },
            "privacy_class": "private",
            "retention_class": "operational",
        }
        manifest_path = lake_path / manifest_key
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

        run_cli(db_path, [
            "land", intake["intake_key"],
            "--lake-run-id", "2026-08-08-fixture-001",
            "--manifest-key", manifest_key,
            "--raw-key", raw_key,
            "--bronze-key", bronze_key,
            "--raw-sha256", raw_digest,
            "--record-count", "1",
            "--worker", "test-worker",
            "--json",
        ])
        verified = run_cli(db_path, [
            "verify", intake["intake_key"],
            "--data-lake-uri", str(lake_path),
            "--json",
        ])
        assert json.loads(verified.stdout)["status"] == "verified"

        status = json.loads(run_cli(db_path, ["status", "--json"]).stdout)
        assert status["intakes"]["verified"] == 1
        assert status["verified_records"] == 1

        queued_recovery = run_cli(db_path, [
            "enqueue",
            "--source", "diary-manual",
            "--input-ref", "manual:fixture-recovery",
            "--idempotency-key", "fixture-recovery",
            "--payload-kind", "json",
            "--json",
        ])
        recovery_key = json.loads(queued_recovery.stdout)["intake_key"]
        run_cli(db_path, ["claim", recovery_key, "--worker", "stale-worker", "--json"])
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE intake_queue SET status = 'processing', lease_owner = 'stale-worker', "
            "lease_expires_at = '2000-01-01T00:00:00Z' WHERE intake_key = ?",
            (recovery_key,),
        )
        conn.commit()
        conn.close()
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE intake_queue SET lease_expires_at = 'not-a-timestamp' WHERE intake_key = ?",
            (recovery_key,),
        )
        conn.commit()
        conn.close()
        malformed_renew = run_cli(
            db_path,
            ["renew", recovery_key, "--worker", "stale-worker"],
            expect_ok=False,
        )
        assert "invalid lease expiry" in malformed_renew.stderr
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE intake_queue SET lease_expires_at = '2000-01-01T00:00:00Z' WHERE intake_key = ?",
            (recovery_key,),
        )
        conn.commit()
        conn.close()
        expired_renew = run_cli(
            db_path,
            ["renew", recovery_key, "--worker", "stale-worker"],
            expect_ok=False,
        )
        assert "lease has expired" in expired_renew.stderr
        recovered = run_cli(db_path, ["claim", recovery_key, "--worker", "recovery-worker", "--json"])
        assert json.loads(recovered.stdout)["lease_owner"] == "recovery-worker"
        stale_renew = run_cli(
            db_path,
            ["renew", recovery_key, "--worker", "stale-worker"],
            expect_ok=False,
        )
        assert "another worker" in stale_renew.stderr
        stale_fail = run_cli(db_path, [
            "fail", recovery_key,
            "--error-code", "stale_worker",
            "--error-message", "stale worker must be fenced",
            "--worker", "stale-worker",
        ], expect_ok=False)
        assert "another worker" in stale_fail.stderr
        run_cli(db_path, [
            "fail", recovery_key,
            "--error-code", "fixture_failure",
            "--error-message", "bounded fixture failure",
            "--worker", "recovery-worker",
        ])

        conn = sqlite3.connect(db_path)
        events = conn.execute(
            "SELECT event_type FROM intake_events ORDER BY id"
        ).fetchall()
        assert [row[0] for row in events] == [
            "queued", "claimed", "lease_renewed", "landed", "verified",
            "queued", "claimed", "retried", "claimed", "failed",
        ]
        conn.close()

    print("✅ data-intake: source registry, privacy boundary, idempotent queue, lake lineage, and verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
