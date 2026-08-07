#!/usr/bin/env python3
"""Run the operator-gated hosted fixture replay and verify its lake contract.

This command is the live counterpart to ``free_cloud_e2e.py``. It expects the
runtime environment to be injected by a secret provider (Infisical in the
current R2 lane), requires an explicit cloud-write gate, writes only the
bounded fixture batch, and verifies landing bytes, Bronze Parquet, manifest,
DuckDB rows, and lineage. It does not register an Iceberg table; that remains
an explicit follow-up operation because the R2 Data Catalog is a separate
metadata mutation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = ROOT / "infra" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from data_lake.cloud_preflight import validate_config  # noqa: E402
from data_lake.ingest import ingest_payload  # noqa: E402
from data_lake.query import query_parquet  # noqa: E402
from data_lake.storage import ObjectStore  # noqa: E402


LAB_ID = "free-cloud-e2e-001"
DEFAULT_FIXTURE = ROOT / "infra" / "tests" / "fixtures" / "cloud_lake_demo.json"
DEFAULT_R2_URI = "s3://solo-empire-portfolio/portfolio-demo/free-cloud-e2e-001"
REQUIRED_RUNTIME_KEYS = (
    "DATA_LAKE_S3_ENDPOINT",
    "AWS_REGION",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "ICEBERG_CATALOG_URI",
    "ICEBERG_CATALOG_TOKEN",
)


def _load_fixture(path: Path) -> tuple[bytes, list[dict[str, Any]]]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, list) or not value or not all(
        isinstance(item, dict) for item in value
    ):
        raise ValueError("fixture must be a non-empty JSON array of objects")
    return raw, value


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def validate_runtime(data_lake_uri: str) -> dict[str, Any]:
    """Validate hosted settings without making a network call or reading values."""
    parsed = urlparse(data_lake_uri)
    if parsed.scheme.lower() != "s3" or not parsed.netloc or not parsed.path.strip("/"):
        raise ValueError("hosted replay requires a bounded s3:// bucket/prefix URI")

    missing = [name for name in REQUIRED_RUNTIME_KEYS if not os.environ.get(name)]
    if missing:
        raise ValueError(f"missing hosted runtime settings: {', '.join(missing)}")

    report = validate_config(
        data_lake_uri=data_lake_uri,
        catalog_uri=os.environ.get("ICEBERG_CATALOG_URI"),
        require_cloud_write=True,
    )
    if report["status"] != "ok":
        errors = "; ".join(str(item) for item in report["errors"])
        raise ValueError(f"cloud preflight failed: {errors}")
    return report


def run_hosted_e2e(
    *, fixture: Path = DEFAULT_FIXTURE, data_lake_uri: str = DEFAULT_R2_URI
) -> dict[str, Any]:
    """Replay the bounded fixture to Object Storage and verify the contract."""
    config = validate_runtime(data_lake_uri)
    raw, source_records = _load_fixture(fixture)
    raw_sha256 = hashlib.sha256(raw).hexdigest()

    result = ingest_payload(
        raw,
        source_records,
        source="free-cloud-e2e",
        domain="portfolio",
        dataset="cloud_lake_demo",
        data_lake_uri=data_lake_uri,
        input_format="json",
        schema_version="1",
        source_record_id_field="id",
        event_time_field="event_time",
        metadata={"lab_id": LAB_ID, "provider": "fixture"},
        privacy_class="public",
        retention_class="portfolio-demo",
    )

    store = ObjectStore(data_lake_uri)
    manifest = json.loads(store.get_bytes(result["manifest_key"]).decode("utf-8"))
    raw_key = result["raw_key"]
    bronze_key = result["bronze_key"]
    raw_remote = store.get_bytes(raw_key)
    bronze_remote = store.get_bytes(bronze_key)

    with tempfile.NamedTemporaryFile(suffix=".parquet") as handle:
        handle.write(bronze_remote)
        handle.flush()
        rows = query_parquet(
            handle.name,
            "SELECT source_record_id, raw_object_key, raw_sha256, ingest_run_id "
            "FROM lake_table ORDER BY source_record_id",
        )

    keys = store.list_keys()
    _assert(raw_remote == raw, "remote landing bytes differ from fixture bytes")
    _assert(manifest["raw"]["sha256"] == raw_sha256, "manifest raw checksum mismatch")
    _assert(manifest["raw"]["key"] == raw_key, "manifest raw key mismatch")
    _assert(manifest["bronze"]["key"] == bronze_key, "manifest Bronze key mismatch")
    _assert(manifest["record_count"] == len(source_records), "manifest record count mismatch")
    _assert(len(rows) == len(source_records), "DuckDB record count mismatch")
    _assert(all(row["raw_object_key"] == raw_key for row in rows), "Bronze raw lineage missing")
    _assert(all(row["raw_sha256"] == raw_sha256 for row in rows), "Bronze checksum lineage missing")
    _assert(all(row["ingest_run_id"] == result["run_id"] for row in rows), "Bronze run lineage missing")
    _assert(not any(key.endswith(".csv") for key in keys), "CSV projection was written")

    return {
        "lab_id": LAB_ID,
        "status": "verified",
        "mode": "hosted-fixture",
        "network": "enabled-by-operator",
        "cloud_write": "enabled-for-this-command",
        "data_lake": store.describe(),
        "catalog": "validated-only",
        "config": {
            "catalog_uri": config["catalog_uri"],
            "max_object_bytes": config["max_object_bytes"],
        },
        "fixture": str(fixture),
        "raw_sha256": raw_sha256,
        "run_id": result["run_id"],
        "record_count": len(rows),
        "raw_key": raw_key,
        "bronze_key": bronze_key,
        "manifest_key": result["manifest_key"],
        "raw_bytes_exact": True,
        "query_engine": "duckdb",
        "query_path": "bronze_parquet",
        "csv_projection": "not-written",
        "lineage_fields_verified": ["raw_object_key", "raw_sha256", "ingest_run_id"],
        "idempotent_retry": bool(
            result["raw_existed"] and result["bronze_existed"] and result["manifest_existed"]
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument(
        "--data-lake-uri",
        default=os.environ.get("SOLO_EMPIRE_DATA_LAKE_URI", DEFAULT_R2_URI),
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = run_hosted_e2e(
            fixture=args.fixture.resolve(),
            data_lake_uri=args.data_lake_uri,
        )
    except Exception as exc:  # noqa: BLE001 - CLI returns concise contract failures
        error = {"lab_id": LAB_ID, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        if args.as_json:
            print(json.dumps(error, ensure_ascii=False, sort_keys=True))
        else:
            print(f"{LAB_ID}: FAILED — {error['error']}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(f"{LAB_ID}: VERIFIED")
        print(f"  records: {report['record_count']}")
        print(f"  query: {report['query_engine']} -> {report['query_path']}")
        print(f"  idempotent retry: {report['idempotent_retry']}")
        print(f"  CSV projection: {report['csv_projection']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
