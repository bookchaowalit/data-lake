#!/usr/bin/env python3
"""Validate a cloud data-lake target without making a network call.

This command is deliberately safe to run in CI. It checks URI shape, required
R2/S3 endpoint settings, explicit remote-write opt-in, catalog token presence,
and the per-object upload budget. It never contacts Object Storage or a
catalog service and never prints secret values.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.parse import urlparse


TRUE_VALUES = {"1", "true", "yes", "on"}
DEFAULT_MAX_OBJECT_BYTES = 64 * 1024 * 1024


def _is_true(value: str | None) -> bool:
    return str(value or "").strip().lower() in TRUE_VALUES


def _is_local_endpoint(endpoint: str | None) -> bool:
    if not endpoint:
        return False
    return urlparse(endpoint).hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
        "minio",
        "se-minio",
    }


def _max_object_bytes() -> int:
    raw = os.environ.get(
        "DATA_LAKE_CLOUD_MAX_OBJECT_BYTES",
        str(DEFAULT_MAX_OBJECT_BYTES),
    )
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            "DATA_LAKE_CLOUD_MAX_OBJECT_BYTES must be a non-negative integer"
        ) from exc
    if value < 0:
        raise ValueError("DATA_LAKE_CLOUD_MAX_OBJECT_BYTES must be non-negative")
    return value


def validate_config(
    *,
    data_lake_uri: str,
    catalog_uri: str | None = None,
    require_cloud_write: bool = False,
) -> dict[str, object]:
    """Return a redacted validation report for local or hosted lake settings."""
    parsed = urlparse(data_lake_uri)
    scheme = parsed.scheme.lower() or "file"
    errors: list[str] = []
    warnings: list[str] = []
    endpoint = os.environ.get("DATA_LAKE_S3_ENDPOINT") or os.environ.get(
        "AWS_ENDPOINT_URL"
    )
    local_s3 = _is_local_endpoint(endpoint)

    if scheme == "file":
        mode = "local"
    elif scheme == "s3":
        mode = "s3-local" if local_s3 else "cloud"
        if not parsed.netloc:
            errors.append("s3:// URI must include a bucket")
        if not endpoint:
            errors.append(
                "DATA_LAKE_S3_ENDPOINT or AWS_ENDPOINT_URL is required for "
                "an explicit S3-compatible target"
            )
        if not local_s3 and require_cloud_write and not _is_true(
            os.environ.get("DATA_LAKE_CLOUD_WRITE_ENABLED")
        ):
            errors.append(
                "DATA_LAKE_CLOUD_WRITE_ENABLED=true is required for cloud writes"
            )
        if not local_s3 and not require_cloud_write:
            warnings.append("cloud writes are not requested by this preflight")
    else:
        errors.append("data lake URI must use file:// or s3://")
        mode = "invalid"

    if catalog_uri:
        catalog_scheme = urlparse(catalog_uri).scheme.lower()
        if catalog_scheme in {"http", "https"}:
            if not os.environ.get("ICEBERG_CATALOG_TOKEN") and not os.environ.get(
                "R2_DATA_CATALOG_TOKEN"
            ):
                errors.append(
                    "REST catalog requires ICEBERG_CATALOG_TOKEN or "
                    "R2_DATA_CATALOG_TOKEN"
                )
        elif not (
            catalog_uri.startswith("sqlite://")
            or catalog_uri.startswith("postgresql")
        ):
            errors.append("catalog URI must be SQLite, PostgreSQL, or HTTP(S) REST")
    elif mode == "cloud":
        warnings.append("cloud data is configured without an Iceberg catalog")

    try:
        max_bytes = _max_object_bytes()
    except ValueError as exc:
        errors.append(str(exc))
        max_bytes = 0

    return {
        "status": "error" if errors else "ok",
        "mode": mode,
        "data_lake_uri": data_lake_uri,
        "catalog_uri": catalog_uri,
        "endpoint_configured": bool(endpoint),
        "cloud_write_enabled": _is_true(
            os.environ.get("DATA_LAKE_CLOUD_WRITE_ENABLED")
        ),
        "max_object_bytes": max_bytes,
        "errors": errors,
        "warnings": warnings,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-lake-uri",
        default=os.environ.get("SOLO_EMPIRE_DATA_LAKE_URI")
        or os.environ.get("DATA_LAKE_URI")
        or "file://./data/lake",
    )
    parser.add_argument(
        "--catalog-uri",
        default=os.environ.get("ICEBERG_CATALOG_URI"),
    )
    parser.add_argument(
        "--require-cloud-write",
        action="store_true",
        help="Fail unless explicit cloud-write opt-in is present",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = validate_config(
        data_lake_uri=args.data_lake_uri,
        catalog_uri=args.catalog_uri,
        require_cloud_write=args.require_cloud_write,
    )
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Cloud lake preflight: {report['status']}")
        print(f"  mode: {report['mode']}")
        print(f"  max object bytes: {report['max_object_bytes']}")
        for warning in report["warnings"]:
            print(f"  warning: {warning}")
        for error in report["errors"]:
            print(f"  error: {error}", file=sys.stderr)
    return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
