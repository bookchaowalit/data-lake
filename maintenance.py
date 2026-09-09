#!/usr/bin/env python3
"""Audit and restore a bounded Parquet lake prefix without deleting data.

The command is intentionally a read-only operations tool. It uses manifests
as the source of truth for lineage, reports retention/orphan/small-file
candidates, and can restore one manifest's source and Bronze objects into a
local evidence directory. Snapshot expiry, orphan deletion, and compaction are
deliberately not implemented here until the report and restore evidence have
been reviewed by an operator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = ROOT / "infra" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from data_lake.query import query_parquet  # noqa: E402
from data_lake.storage import ObjectStore, StorageError  # noqa: E402


MANIFEST_PREFIX = "control/manifests"
# Include control checkpoints in lineage/orphan inventory. They are immutable
# control-plane objects, but a checkpoint left by a crashed run still needs a
# bounded cleanup candidate once its final manifest is absent.
DATA_PREFIXES = ("landing/", "bronze/", "silver/", "gold/", "control/checkpoints/")
DEFAULT_SMALL_FILE_BYTES = 8 * 1024 * 1024
DEFAULT_RETENTION_DAYS = 30
PROTECTED_RETENTION_CLASSES = {"evidence", "legal-hold"}


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _manifest_object_keys(value: Any) -> set[str]:
    """Collect relative lake object keys from nested manifest references."""
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"key", "checkpoint_key"} and isinstance(item, str):
                candidate = item.strip("/")
                if "://" not in candidate and candidate.startswith(DATA_PREFIXES):
                    found.add(candidate)
            found.update(_manifest_object_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_manifest_object_keys(item))
    return found


def _safe_object_size(store: ObjectStore, key: str) -> int | None:
    try:
        return store.object_size(key)
    except StorageError:
        return None


def _manifest_retention_candidate(
    manifest_key: str,
    manifest: dict[str, Any],
    *,
    cutoff: datetime,
) -> dict[str, Any] | None:
    received_at = _parse_timestamp(manifest.get("received_at"))
    if received_at is None or received_at >= cutoff:
        return None
    retention_class = str(manifest.get("retention_class") or "unspecified")
    return {
        "manifest_key": manifest_key,
        "run_id": manifest.get("run_id"),
        "received_at": received_at.isoformat().replace("+00:00", "Z"),
        "retention_class": retention_class,
        "protected": retention_class in PROTECTED_RETENTION_CLASSES,
    }


def build_maintenance_report(
    data_lake_uri: str,
    *,
    prefix: str = "",
    older_than_days: int = DEFAULT_RETENTION_DAYS,
    small_file_bytes: int = DEFAULT_SMALL_FILE_BYTES,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Inventory a bounded lake and return a redacted, read-only report."""
    if older_than_days < 0:
        raise ValueError("older-than-days must be non-negative")
    if small_file_bytes < 0:
        raise ValueError("small-file-bytes must be non-negative")

    store = ObjectStore(data_lake_uri)
    keys = store.list_keys(prefix)
    key_set = set(keys)
    manifest_keys = [
        key for key in keys
        if key.startswith(MANIFEST_PREFIX + "/") and key.endswith(".json")
    ]
    referenced_keys: set[str] = set()
    missing_references: set[str] = set()
    malformed_manifests: list[dict[str, str]] = []
    permission_errors: list[dict[str, str]] = []
    retention_candidates: list[dict[str, Any]] = []
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = now_utc - timedelta(days=older_than_days)

    for manifest_key in manifest_keys:
        try:
            manifest = json.loads(store.get_bytes(manifest_key).decode("utf-8"))
        except PermissionError as exc:
            permission_errors.append({
                "manifest_key": manifest_key,
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue
        except (UnicodeDecodeError, json.JSONDecodeError, StorageError) as exc:
            malformed_manifests.append({
                "manifest_key": manifest_key,
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue
        if not isinstance(manifest, dict):
            malformed_manifests.append({
                "manifest_key": manifest_key,
                "error": "manifest root must be an object",
            })
            continue
        manifest_refs = _manifest_object_keys(manifest)
        referenced_keys.update(manifest_refs)
        missing_references.update(manifest_refs - key_set)
        candidate = _manifest_retention_candidate(
            manifest_key, manifest, cutoff=cutoff
        )
        if candidate is not None:
            retention_candidates.append(candidate)

    data_keys = [key for key in keys if key.startswith(DATA_PREFIXES)]
    manifest_read_errors = bool(permission_errors or malformed_manifests)
    # A bounded data prefix normally does not contain the control manifests.
    # Never call its objects orphaned without the lineage index; report the
    # incomplete scope and fail closed instead.
    lineage_scope_complete = not data_keys or not prefix or bool(manifest_keys)
    lineage_scope_warning = None
    if not lineage_scope_complete:
        lineage_scope_warning = (
            "scan prefix does not include control/manifests; orphan check skipped"
        )
    orphan_candidates = [] if manifest_read_errors or not lineage_scope_complete else [
        {"key": key, "bytes": _safe_object_size(store, key)}
        for key in data_keys
        if key not in referenced_keys
    ]
    small_file_candidates = []
    for key in data_keys:
        if not key.endswith(".parquet"):
            continue
        size = _safe_object_size(store, key)
        if size is not None and size <= small_file_bytes:
            small_file_candidates.append({"key": key, "bytes": size})

    by_layer: dict[str, int] = {}
    for key in keys:
        layer = key.split("/", 1)[0] if "/" in key else key
        by_layer[layer] = by_layer.get(layer, 0) + 1

    findings = len(orphan_candidates) + len(missing_references) + len(
        malformed_manifests
    ) + len(permission_errors) + len(retention_candidates) + len(
        small_file_candidates
    ) + (1 if not lineage_scope_complete else 0)
    return {
        "status": "attention" if findings else "ok",
        "mode": "read_only_dry_run",
        "data_lake": store.describe(),
        "scan_prefix": prefix or "/",
        "inventory": {
            "object_count": len(keys),
            "manifest_count": len(manifest_keys),
            "by_layer": dict(sorted(by_layer.items())),
        },
        "integrity": {
            "referenced_object_count": len(referenced_keys),
            "missing_references": sorted(missing_references),
            "malformed_manifests": malformed_manifests,
            "permission_errors": permission_errors,
            "lineage_scope_complete": lineage_scope_complete,
            "lineage_scope_warning": lineage_scope_warning,
            "orphan_check_complete": (
                not manifest_read_errors and lineage_scope_complete
            ),
            "orphan_candidates": orphan_candidates,
        },
        "retention": {
            "older_than_days": older_than_days,
            "cutoff": cutoff.isoformat().replace("+00:00", "Z"),
            "candidates": retention_candidates,
            "protected_classes": sorted(PROTECTED_RETENTION_CLASSES),
        },
        "compaction": {
            "small_file_bytes": small_file_bytes,
            "small_file_candidates": small_file_candidates,
        },
        "safety": {
            "object_storage_writes": False,
            "deletes": False,
            "apply_supported": False,
            "review_required": bool(findings),
        },
    }


def _manifest_ref(manifest: dict[str, Any], *names: str) -> tuple[str, dict[str, Any]]:
    for name in names:
        value = manifest.get(name)
        if isinstance(value, dict) and isinstance(value.get("key"), str):
            return name, value
    raise ValueError(f"manifest must contain one of: {', '.join(names)}")


def restore_manifest(
    data_lake_uri: str,
    manifest_key: str,
    *,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Restore one source object and Bronze Parquet part and verify both."""
    normalized_manifest_key = manifest_key.strip("/")
    if not (
        normalized_manifest_key.startswith(MANIFEST_PREFIX + "/")
        and normalized_manifest_key.endswith(".json")
    ):
        raise ValueError("restore manifest key must be under control/manifests/*.json")
    store = ObjectStore(data_lake_uri)
    manifest_bytes = store.get_bytes(normalized_manifest_key)
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("manifest root must be an object")
    source_name, source_ref = _manifest_ref(manifest, "raw", "source_avro", "avro")
    _, bronze_ref = _manifest_ref(manifest, "bronze")
    source_key = str(source_ref["key"])
    bronze_key = str(bronze_ref["key"])
    source_key = source_key.strip("/")
    bronze_key = bronze_key.strip("/")
    if not source_key.startswith("landing/"):
        raise ValueError("restore source reference must be under landing/")
    if not bronze_key.startswith("bronze/"):
        raise ValueError("restore Bronze reference must be under bronze/")
    source_bytes = store.get_bytes(source_key)
    bronze_bytes = store.get_bytes(bronze_key)

    def verify_bytes(label: str, payload: bytes, reference: dict[str, Any]) -> str:
        digest = hashlib.sha256(payload).hexdigest()
        expected = reference.get("sha256")
        if not isinstance(expected, str) or not re.fullmatch(
            r"[0-9a-fA-F]{64}", expected
        ):
            raise ValueError(f"{label} reference is missing a valid sha256")
        if digest != expected.lower():
            raise ValueError(f"{label} checksum mismatch")
        expected_bytes = reference.get("bytes")
        if expected_bytes is not None:
            if (
                isinstance(expected_bytes, bool)
                or not isinstance(expected_bytes, int)
                or expected_bytes < 0
            ):
                raise ValueError(f"{label} reference has an invalid byte count")
            if len(payload) != expected_bytes:
                raise ValueError(f"{label} byte count mismatch")
        return digest

    source_sha256 = verify_bytes(source_name, source_bytes, source_ref)
    bronze_sha256 = verify_bytes("bronze", bronze_bytes, bronze_ref)
    restore_dir = Path(output_dir) if output_dir else Path(
        tempfile.mkdtemp(prefix="solo-empire-lake-restore-")
    )
    restore_dir.mkdir(parents=True, exist_ok=True)
    (restore_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    source_suffix = Path(source_key).suffix or ".bin"
    (restore_dir / f"source{source_suffix}").write_bytes(source_bytes)
    bronze_path = restore_dir / "bronze.parquet"
    bronze_path.write_bytes(bronze_bytes)
    rows = query_parquet(
        str(bronze_path), "SELECT COUNT(*) AS row_count FROM lake_table"
    )
    row_count = int(rows[0]["row_count"]) if rows else 0
    expected_count = manifest.get("record_count")
    if expected_count is not None:
        if (
            isinstance(expected_count, bool)
            or not isinstance(expected_count, int)
            or expected_count < 0
        ):
            raise ValueError("manifest record_count must be a non-negative integer")
        if row_count != expected_count:
            raise ValueError(
                f"restored Bronze row count mismatch ({row_count} != {expected_count})"
            )
    evidence = {
        "evidence_version": "1",
        "status": "verified",
        "mode": "read_only_restore_drill",
        "manifest_key": normalized_manifest_key,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "source": {
            "kind": source_name,
            "key": source_key,
            "sha256": source_sha256,
            "bytes": len(source_bytes),
        },
        "bronze": {
            "key": bronze_key,
            "sha256": bronze_sha256,
            "bytes": len(bronze_bytes),
            "record_count": row_count,
        },
        "checks": {
            "source_checksum": True,
            "bronze_checksum": True,
            "bronze_query": True,
            "manifest_replayed": True,
        },
        "object_storage_writes": False,
    }
    evidence_path = restore_dir / "restore-evidence.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "verified",
        "mode": "read_only_restore_drill",
        "manifest_key": normalized_manifest_key,
        "source_kind": source_name,
        "source_key": source_key,
        "bronze_key": bronze_key,
        "source_sha256": source_sha256,
        "bronze_sha256": bronze_sha256,
        "record_count": row_count,
        "restore_dir": str(restore_dir),
        "evidence_path": str(evidence_path),
        "raw_bytes_exact": True,
        "manifest_replayed": True,
        "checks": evidence["checks"],
        "object_storage_writes": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-lake-uri",
        default=os.environ.get("SOLO_EMPIRE_DATA_LAKE_URI")
        or os.environ.get("DATA_LAKE_URI")
        or "file://./data/lake",
    )
    parser.add_argument("--prefix", default="", help="bounded object prefix to scan")
    parser.add_argument("--older-than-days", type=int, default=DEFAULT_RETENTION_DAYS)
    parser.add_argument("--small-file-bytes", type=int, default=DEFAULT_SMALL_FILE_BYTES)
    parser.add_argument("--restore-manifest-key")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="reserved for a future reviewed delete/compaction workflow; always rejected",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.apply:
            raise ValueError(
                "apply is not supported by the safe maintenance command; review the dry-run first"
            )
        report = build_maintenance_report(
            args.data_lake_uri,
            prefix=args.prefix,
            older_than_days=args.older_than_days,
            small_file_bytes=args.small_file_bytes,
        )
        if args.restore_manifest_key:
            report["restore"] = restore_manifest(
                args.data_lake_uri,
                args.restore_manifest_key,
                output_dir=args.output_dir,
            )
    except Exception as exc:  # noqa: BLE001 - concise operator-facing CLI error
        payload = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        if args.as_json:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            print(f"Lake maintenance: FAILED — {payload['error']}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Lake maintenance: {report['status']} (read-only dry-run)")
        print(f"  objects: {report['inventory']['object_count']}")
        print(f"  manifests: {report['inventory']['manifest_count']}")
        print(f"  orphan candidates: {len(report['integrity']['orphan_candidates'])}")
        print(f"  retention candidates: {len(report['retention']['candidates'])}")
        print(f"  small Parquet files: {len(report['compaction']['small_file_candidates'])}")
        if "restore" in report:
            print(f"  restore: {report['restore']['status']}")
            print(f"  evidence: {report['restore']['restore_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
