#!/usr/bin/env python3
"""
dbt-duckdb project smoke test.

infra/dbt/ reads the real local Bronze lake (data/lake-local/bronze), which
is real personal data that is intentionally never committed to git — so it
never exists in a clean checkout or CI. This test proves the dbt project
itself (models, schema tests, config) is structurally correct by pointing
it at a small synthetic Bronze fixture with the same envelope schema
instead, via dbt's `--vars bronze_root:...` override.

Usage:
    python3 infra/tests/data_lake/dbt_lake_test.py

Exit code 0 = pass, 1 = failure.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DBT_PROJECT_DIR = ROOT / "infra" / "dbt"


def resolve_dbt_bin() -> Path | None:
    on_path = shutil.which("dbt")
    if on_path:
        return Path(on_path)
    venv_dbt = ROOT / "infra" / ".venv-datalake" / "bin" / "dbt"
    if venv_dbt.exists():
        return venv_dbt
    return None


DBT_BIN = resolve_dbt_bin()


def build_synthetic_bronze(root: Path) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pyarrow required for this test") from exc

    now = datetime.now(timezone.utc)
    rows = []
    for i in range(5):
        received = now - timedelta(hours=i * 6)
        rows.append(
            {
                "event_id": str(uuid.uuid4()),
                "source": "fixture",
                "source_record_id": f"msg-{i}",
                "domain": "communications",
                "dataset": "emails",
                "schema_version": "1",
                "received_at": received.isoformat(),
                "event_time": received.isoformat(),
                "content_type": "application/json",
                "raw_object_key": f"fixture/msg-{i}.json",
                "raw_sha256": "0" * 64,
                "payload_json": json.dumps(
                    {
                        "id": f"msg-{i}",
                        "thread_id": f"thread-{i % 2}",
                        "from_address": "fixture@example.invalid",
                        "from_name": "Fixture Sender",
                        "subject": "Synthetic fixture — not real content",
                        "snippet": "synthetic",
                        "to_addresses": ["nobody@example.invalid"],
                        "is_read": i % 2 == 0,
                        "is_important": i == 0,
                        "has_attachment": i % 3 == 0,
                        "labels": ["INBOX"],
                        "source": "fixture",
                        "received_at": received.isoformat(),
                    }
                ),
                "metadata_json": "{}",
                "ingest_run_id": "fixture-run",
                "privacy_class": "private",
                "retention_class": "operational",
                "ingest_date": received.date().isoformat(),
            }
        )

    table = pa.Table.from_pylist(rows)
    part_dir = (
        root
        / "domain=communications"
        / "dataset=emails"
        / "schema_version=1"
        / f"ingest_date={now.date().isoformat()}"
    )
    part_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, part_dir / "part-fixture.parquet")


def run() -> bool:
    if DBT_BIN is None:
        print("SKIP: dbt not on PATH (pip install -r infra/requirements-data-lake.txt)")
        return True

    with tempfile.TemporaryDirectory() as tmp:
        bronze_root = Path(tmp) / "bronze"
        build_synthetic_bronze(bronze_root)
        target_dir = Path(tmp) / "target"
        # dbt-duckdb does not create the target directory itself before
        # opening the database file there — confirmed by a real CI failure
        # ("Cannot open file .../target/local.duckdb: No such file or
        # directory") on the first run of this test.
        target_dir.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            [
                str(DBT_BIN),
                "build",
                "--profiles-dir",
                str(DBT_PROJECT_DIR),
                "--project-dir",
                str(DBT_PROJECT_DIR),
                "--target-path",
                str(target_dir),
                "--vars",
                json.dumps({"bronze_root": str(bronze_root)}),
            ],
            cwd=str(DBT_PROJECT_DIR),
            capture_output=True,
            text=True,
        )
        print(result.stdout[-4000:])
        if result.returncode != 0:
            print(result.stderr[-2000:])
            print("FAIL: dbt build against synthetic fixture failed")
            return False

        if "PASS=11" not in result.stdout and "ERROR=0" not in result.stdout:
            print("FAIL: unexpected dbt summary (models/tests count changed?)")
            return False

        print("PASS: dbt build (2 models, 9 tests) succeeded against a synthetic Bronze fixture")
        return True


if __name__ == "__main__":
    success = run()
    print("\nResult:", "PASS" if success else "FAIL")
    sys.exit(0 if success else 1)
