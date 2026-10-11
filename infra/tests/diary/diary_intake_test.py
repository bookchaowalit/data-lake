#!/usr/bin/env python3
"""Regression tests for the private Diary Markdown lake-first adapter."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "infra" / "database" / "schema.sql"
CLI = ROOT / "infra" / "scripts" / "cli" / "diary-intake-cli.py"


def run_cli(
    db_path: Path,
    diary_root: Path,
    lake_path: Path,
    args: list[str],
    *,
    expect_ok: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["SOLO_EMPIRE_DB_PATH"] = str(db_path)
    # sitecustomize puts the SQLite cell double behind every (nested) Python process
    env["PYTHONPATH"] = str(ROOT / "infra" / "tests" / "support")
    env["EMPIRE_CLIENT_CONFIG"] = "/nonexistent"
    env["SOLO_EMPIRE_DIARY_ROOT"] = str(diary_root)
    env["SOLO_EMPIRE_DATA_LAKE_URI"] = str(lake_path)
    result = subprocess.run(
        [sys.executable, str(CLI), *args],
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
    with tempfile.TemporaryDirectory(prefix="solo-empire-diary-") as temp_dir:
        temp = Path(temp_dir)
        db_path = temp / "diary-test.db"
        diary_root = temp / "entries"
        lake_path = temp / "lake"
        day_root = diary_root / "2026" / "08" / "08"
        day_root.mkdir(parents=True)
        private_text = "A private fixture thought that must never appear in CLI output."
        (day_root / "daily.md").write_text(
            "---\nentry_date: 2026-08-08\n---\n\n" + private_text + "\n",
            encoding="utf-8",
        )

        conn = sqlite3.connect(db_path)
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        conn.close()

        registered = run_cli(db_path, diary_root, lake_path, ["register", "--json"])
        assert json.loads(registered.stdout)["status"] == "planned"
        activated = run_cli(db_path, diary_root, lake_path, ["activate", "--json"])
        assert json.loads(activated.stdout)["status"] == "active"

        ingested = run_cli(db_path, diary_root, lake_path, [
            "ingest", "--date", "2026-08-08", "--entry", "daily.md", "--json",
        ])
        result = json.loads(ingested.stdout)
        assert result["status"] == "verified"
        assert result["idempotent"] is False
        assert private_text not in ingested.stdout
        assert "daily.md" not in ingested.stdout

        repeated = run_cli(db_path, diary_root, lake_path, [
            "ingest", "--date", "2026-08-08", "--entry", "daily.md", "--json",
        ])
        repeated_result = json.loads(repeated.stdout)
        assert repeated_result["status"] == "already_verified"
        assert repeated_result["idempotent"] is True

        escaped = run_cli(db_path, diary_root, lake_path, [
            "ingest", "--date", "2026-08-08", "--entry", "../daily.md",
        ], expect_ok=False)
        assert "one filename" in escaped.stderr

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("source_registry", "intake_queue", "intake_events")
        }
        row = conn.execute(
            "SELECT status, input_ref, record_count, raw_sha256, lake_manifest_key FROM intake_queue"
        ).fetchone()
        assert counts == {"source_registry": 1, "intake_queue": 1, "intake_events": 4}
        assert row["status"] == "verified"
        assert row["input_ref"] == "diary:2026-08-08:daily"
        assert row["record_count"] == 1
        assert row["lake_manifest_key"].startswith("control/manifests/")
        assert private_text not in row["input_ref"]

        manifest_path = lake_path / row["lake_manifest_key"]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["privacy_class"] == "restricted"
        assert manifest["retention_class"] == "personal"
        assert private_text not in manifest_path.read_text(encoding="utf-8")
        conn.close()

    print("✅ diary-intake: canonical date boundary, lake-first archive, privacy-safe projection, and idempotency passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
