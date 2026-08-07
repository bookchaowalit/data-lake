#!/usr/bin/env python3
"""Run the FREE-CLOUD-E2E-001 lake-to-query contract without network access.

This lab proves the same object layout used by an R2 target while writing to a
temporary/local ``file://`` store:

    fixture bytes -> landing -> Bronze Parquet -> manifest -> DuckDB query

It deliberately does not read credentials, call a provider, or write an
``s3://`` target. A later, operator-approved cloud run can replay the exact
fixture with ``ingest.py`` after the cloud preflight and write guard pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = ROOT / "infra" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from data_lake.ingest import ingest_payload  # noqa: E402
from data_lake.query import query_parquet  # noqa: E402
from data_lake.storage import ObjectStore  # noqa: E402


LAB_ID = "free-cloud-e2e-001"
DEFAULT_FIXTURE = ROOT / "infra" / "tests" / "fixtures" / "cloud_lake_demo.json"
DEFAULT_R2_URI = "s3://solo-empire-portfolio/portfolio-demo/free-cloud-e2e-001"


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


def _validate_r2_contract(uri: str) -> None:
    parsed = urlparse(uri)
    _assert(parsed.scheme.lower() == "s3", "R2 contract must use an s3:// URI")
    _assert(bool(parsed.netloc), "R2 contract must include a bucket")
    _assert(bool(parsed.path.strip("/")), "R2 contract must include a bounded prefix")


def _execute(lake_root: Path, fixture_path: Path, r2_uri: str) -> dict[str, Any]:
    _validate_r2_contract(r2_uri)
    raw, source_records = _load_fixture(fixture_path)
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    result = ingest_payload(
        raw,
        source_records,
        source="free-cloud-e2e",
        domain="portfolio",
        dataset="cloud_lake_demo",
        data_lake_uri=str(lake_root),
        input_format="json",
        schema_version="1",
        source_record_id_field="id",
        event_time_field="event_time",
        metadata={
            "lab_id": LAB_ID,
            "execution": "offline-fixture",
            "provider": "fixture",
            "cloud_target_contract": r2_uri,
        },
        privacy_class="public",
        retention_class="portfolio-demo",
    )

    store = ObjectStore(str(lake_root))
    manifest = json.loads(store.get_bytes(result["manifest_key"]).decode("utf-8"))
    bronze_path = lake_root / result["bronze_key"]
    rows = query_parquet(
        str(bronze_path),
        "SELECT source_record_id, raw_object_key, raw_sha256, ingest_run_id "
        "FROM lake_table ORDER BY source_record_id",
    )
    keys = store.list_keys()

    _assert(store.get_bytes(result["raw_key"]) == raw, "landing bytes changed")
    _assert(manifest["raw"]["sha256"] == raw_sha256, "manifest raw checksum mismatch")
    _assert(manifest["raw"]["key"] == result["raw_key"], "manifest raw key mismatch")
    _assert(manifest["bronze"]["key"] == result["bronze_key"], "manifest Bronze key mismatch")
    _assert(manifest["record_count"] == len(source_records), "manifest record count mismatch")
    _assert(len(rows) == len(source_records), "DuckDB record count mismatch")
    _assert(all(row["raw_object_key"] == result["raw_key"] for row in rows), "Bronze lineage raw key missing")
    _assert(all(row["raw_sha256"] == raw_sha256 for row in rows), "Bronze lineage checksum missing")
    _assert(all(row["ingest_run_id"] == result["run_id"] for row in rows), "Bronze ingest run lineage missing")
    _assert(not any(key.endswith(".csv") for key in keys), "CSV projection was written")

    return {
        "lab_id": LAB_ID,
        "status": "passed",
        "mode": "offline-fixture",
        "network": "disabled-by-design",
        "cloud_write": "disabled-by-design",
        "r2_target_contract": r2_uri,
        "lake_uri": f"file://{lake_root}",
        "fixture": str(fixture_path),
        "raw_sha256": raw_sha256,
        "run_id": result["run_id"],
        "record_count": len(rows),
        "manifest_key": result["manifest_key"],
        "bronze_key": result["bronze_key"],
        "raw_key": result["raw_key"],
        "query_engine": "duckdb",
        "query_path": "bronze_parquet",
        "csv_projection": "not-written",
        "lineage_fields_verified": [
            "raw_object_key",
            "raw_sha256",
            "ingest_run_id",
        ],
        "object_keys": keys,
    }


def run_offline_e2e(
    *, fixture: Path = DEFAULT_FIXTURE, output_dir: Path | None = None, r2_uri: str = DEFAULT_R2_URI
) -> dict[str, Any]:
    """Run the bounded local proof and optionally retain its evidence bundle."""
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        return _run_and_write(output_dir, fixture, r2_uri)

    with tempfile.TemporaryDirectory(prefix=f"{LAB_ID}-") as temp_dir:
        return _execute(Path(temp_dir), fixture, r2_uri)


def _run_and_write(output_dir: Path, fixture: Path, r2_uri: str) -> dict[str, Any]:
    lake_root = output_dir / "lake"
    report = _execute(lake_root, fixture, r2_uri)
    report_path = output_dir / "result.json"
    report["evidence_report"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="retain lake objects and result.json for CI evidence; otherwise use a temporary directory",
    )
    parser.add_argument("--r2-uri", default=DEFAULT_R2_URI, help="R2/S3 key layout contract only; never written by this command")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = run_offline_e2e(fixture=args.fixture.resolve(), output_dir=args.output_dir, r2_uri=args.r2_uri)
    except Exception as exc:  # noqa: BLE001 - CLI must return a concise contract failure
        error = {"lab_id": LAB_ID, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        if args.as_json:
            print(json.dumps(error, ensure_ascii=False, sort_keys=True))
        else:
            print(f"{LAB_ID}: FAILED — {error['error']}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(f"{LAB_ID}: PASSED")
        print(f"  records: {report['record_count']}")
        print(f"  query: {report['query_engine']} -> {report['query_path']}")
        print(f"  CSV projection: {report['csv_projection']}")
        if report.get("evidence_report"):
            print(f"  evidence: {report['evidence_report']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
