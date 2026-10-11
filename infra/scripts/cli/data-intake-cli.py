#!/usr/bin/env python3
"""Privacy-safe Source Registry and lake-first Intake Queue CLI.

Usage:
    python3 infra/scripts/cli/data-intake-cli.py source register ...
    python3 infra/scripts/cli/data-intake-cli.py source list [--json]
    python3 infra/scripts/cli/data-intake-cli.py source set-status <key> <status>
    python3 infra/scripts/cli/data-intake-cli.py enqueue ...
    python3 infra/scripts/cli/data-intake-cli.py queue [--status STATUS]
    python3 infra/scripts/cli/data-intake-cli.py show <intake>
    python3 infra/scripts/cli/data-intake-cli.py status [--json]
    python3 infra/scripts/cli/data-intake-cli.py claim <intake> --worker <name>
    python3 infra/scripts/cli/data-intake-cli.py renew <intake> --worker <name>
    python3 infra/scripts/cli/data-intake-cli.py land <intake> ... --worker <name>
    python3 infra/scripts/cli/data-intake-cli.py verify <intake> [--data-lake-uri URI]
    python3 infra/scripts/cli/data-intake-cli.py fail <intake> ... --worker <name>
    python3 infra/scripts/cli/data-intake-cli.py retry <intake>
    python3 infra/scripts/cli/data-intake-cli.py reject <intake> --reason "..."

The intake records (the Intake cell API) contain control metadata and lineage only. This CLI never
accepts or stores source payloads. A producer must write landing/Bronze lake
artifacts first, then call ``land`` and ``verify`` with the resulting lineage.
"""

from __future__ import annotations

import time
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
UTILS_DIR = SCRIPTS_DIR / "utils"
if str(UTILS_DIR) not in sys.path:
    sys.path.insert(0, str(UTILS_DIR))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _env import PROJECT_ROOT  # noqa: E402
from cell_store import CellStoreError, open_cell_store  # noqa: E402
from data_lake.storage import ObjectStore, StorageError  # noqa: E402
from task_store import ClientConfigError  # noqa: E402

AUTOMATION_ID = "owner-cli"
Row = dict[str, Any]


DEFAULT_LAKE_URI = os.environ.get(
    "SOLO_EMPIRE_DATA_LAKE_URI",
    os.environ.get("DATA_LAKE_URI", str(PROJECT_ROOT / "data" / "lake")),
)
SOURCE_KINDS = (
    "manual", "file", "api", "webhook", "email", "calendar", "database",
    "application", "other",
)
OWNER_SCOPES = ("personal", "solo_empire", "venture", "client", "shared")
PRIVACY_CLASSES = ("public", "internal", "private", "restricted")
RETENTION_DEFAULT = "operational"
INGEST_MODES = ("manual", "batch", "stream", "webhook")
SOURCE_STATUSES = ("planned", "active", "paused", "retired")
QUEUE_STATUSES = (
    "queued", "processing", "landed", "verified", "rejected", "failed", "cancelled",
)
PAYLOAD_KINDS = ("json", "jsonl", "csv", "binary", "markdown", "parquet", "other")
PRIVACY_RANK = {name: index for index, name in enumerate(PRIVACY_CLASSES)}
SAFE_TOKEN_RE = re.compile(
    r"(?ix)"
    r"-----BEGIN\s+[^-]*PRIVATE\s+KEY-----|"
    r"\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}|"
    r"\b(?:token|password|passwd|secret|api[_-]?key|refresh[_-]?token)\s*[:=]|"
    r"(?:https?|s3)://[^\s/@:]+:[^\s/@]+@"
)
SAFE_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def lease_expiry(row: Row) -> datetime | None:
    """Parse a queue lease, failing closed when a stored value is malformed."""
    raw_value = row["lease_expires_at"]
    if raw_value is None or not str(raw_value).strip():
        return None
    parsed = parse_utc(raw_value)
    if parsed is None:
        raise ValueError(f"intake {row['intake_key']!r} has an invalid lease expiry")
    return parsed


def safe_text(value: str, field: str, *, max_length: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must not be empty")
    if len(text) > max_length:
        raise ValueError(f"{field} is too long (max {max_length} characters)")
    if SAFE_TOKEN_RE.search(text):
        raise ValueError(
            f"{field} looks like credential-shaped data; use the secret resolver instead"
        )
    return text


def component(value: str, field: str, *, max_length: int = 64) -> str:
    text = safe_text(value, field, max_length=max_length).lower()
    if not SAFE_SLUG_RE.fullmatch(text):
        raise ValueError(
            f"{field} must use lowercase letters, numbers, dots, underscores, or hyphens"
        )
    return text


def opaque_ref(value: str, field: str = "input_ref") -> str:
    text = safe_text(value, field, max_length=240)
    if text.startswith(("/", "~", "\\")) or ".." in text:
        raise ValueError(f"{field} must be an opaque reference, not a filesystem path")
    if "://" in text:
        raise ValueError(f"{field} must not contain a URL or object-store URI")
    return text


def object_key(value: str, field: str, required_prefix: str) -> str:
    text = safe_text(value, field, max_length=512)
    parts = text.strip("/").split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{field} must be a relative immutable object key")
    if "\\" in text or not text.startswith(required_prefix):
        raise ValueError(f"{field} must start with {required_prefix}")
    return text.strip("/")


def sha256(value: str) -> str:
    text = safe_text(value, "raw_sha256", max_length=64).lower()
    if not SHA256_RE.fullmatch(text):
        raise ValueError("raw_sha256 must be a 64-character SHA-256 hex digest")
    return text


def json_print(payload: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    if isinstance(payload, dict):
        for key, value in payload.items():
            print(f"{key}: {value}")
    else:
        print(payload)


def get_store() -> Any:
    """The intake cell store (sources, intakes and intake events live in the Intake cell, not local SQLite)."""
    return open_cell_store("intake", AUTOMATION_ID, channel="cli")


def parse_sort(value: Any) -> datetime:
    return parse_utc(value) or datetime.min.replace(tzinfo=timezone.utc)


def public_source(row: Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "source_key": row["source_key"],
        "display_name": row["display_name"],
        "source_kind": row["source_kind"],
        "provider": row["provider"],
        "domain": row["domain"],
        "dataset": row["dataset"],
        "owner_scope": row["owner_scope"],
        "privacy_class": row["privacy_class"],
        "retention_class": row["retention_class"],
        "ingest_mode": row["ingest_mode"],
        "status": row["status"],
        "last_ingested_at": row["last_ingested_at"],
    }


def public_intake(row: Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "intake_key": row["intake_key"],
        "source_key": row["source_key"],
        "domain": row["domain"],
        "dataset": row["dataset"],
        "schema_version": row["schema_version"],
        "payload_kind": row["payload_kind"],
        "privacy_class": row["privacy_class"],
        "retention_class": row["retention_class"],
        "requested_by": row["requested_by"],
        "status": row["status"],
        "requested_at": row["requested_at"],
        "claimed_at": row["claimed_at"],
        "lease_owner": row["lease_owner"],
        "lease_expires_at": row["lease_expires_at"],
        "attempt_count": row["attempt_count"],
        "record_count": row["record_count"],
        "lake_run_id": row["lake_run_id"],
        "verified_at": row["verified_at"],
    }


def source_by_key(conn: Any, source_key: str) -> Row:
    key = component(source_key, "source_key")
    rows = conn.list("sources", source_key=key)
    if not rows:
        raise ValueError(f"source {key!r} not found")
    return rows[0]


def intake_by_identifier(conn: Any, identifier: str) -> Row:
    """The intake joined with the source fields the CLI needs (source_key, source_status, ...)."""
    value = safe_text(identifier, "intake", max_length=96)
    if value.isdigit():
        row = conn.get("intakes", int(value))
    else:
        found = conn.list("intakes", intake_key=value)
        row = found[0] if found else None
    source = conn.get("sources", row["source_id"]) if row else None
    if not row or not source:
        raise ValueError(f"intake {value!r} not found")
    return {
        **row,
        "source_key": source["source_key"],
        "source_status": source["status"],
        "source_privacy_class": source["privacy_class"],
    }


def event(
    conn: Any,
    intake_id: int,
    event_type: str,
    from_status: str | None,
    to_status: str,
    actor: str,
    reason: str | None = None,
    version: int | None = None,
) -> None:
    """Record one transition; safe to repeat: the key names the transition and the intake version it produced.

    ``version`` is the version the transition's own update returned (never re-read: two quick renewals must
    produce two events).
    """
    fields: dict[str, Any] = {
        "intake_id": intake_id, "event_type": event_type, "actor": actor,
        "from_status": from_status, "to_status": to_status, "reason": reason,
    }
    if version is None:
        version = int((conn.get("intakes", intake_id) or {}).get("version", 0))
    key = f"intake-event:{intake_id}:{event_type}:{from_status}:{to_status}:{version}"
    for attempt in range(3):  # the status already changed: the event must land too
        try:
            conn.create("intake-events", {k: v for k, v in fields.items() if v is not None}, idempotency_key=key)
            return
        except CellStoreError as exc:
            if exc.status < 500 or attempt == 2:
                raise
            time.sleep(1 + attempt)


REPAIR_EVENT = {"queued": "retried", "processing": "claimed", "landed": "landed", "verified": "verified",
                "failed": "failed", "rejected": "rejected", "cancelled": "cancelled"}


def repair_events(conn: Any, row: Row) -> None:
    """Record a transition whose event was lost (the status changed, the event write failed).

    The intake and its events live in one cell but are separate writes; before acting on an intake,
    its last event must name its current status. A missing first "queued" event is restored too.
    """
    events = conn.list("intake-events", intake_id=row["id"], order="desc", limit=1)
    last = events[0] if events else None
    if last is not None and last.get("to_status") == row["status"]:
        return
    event_type = "queued" if last is None and row["status"] == "queued" else REPAIR_EVENT.get(row["status"])
    if event_type is None:
        return
    event(conn, row["id"], event_type, last.get("to_status") if last else None, row["status"], "repair",
          "event lost before; recorded on repair", version=int(row.get("version") or 0))


def guarded_update(conn: Any, row: Row, fields: dict[str, Any], conflict_message: str) -> Row:
    """Update an intake only if nobody changed it since ``row`` was read (replaces the SQL WHERE guards)."""
    try:
        return conn.update("intakes", row["id"], fields, expected_version=row.get("version"))
    except CellStoreError as exc:
        if exc.status == 409:
            raise ValueError(conflict_message) from None
        raise


def cmd_source_register(args: argparse.Namespace, conn: Any) -> None:
    source_key = component(args.source_key, "source_key")
    display_name = safe_text(args.display_name, "display_name", max_length=160)
    provider = safe_text(args.provider, "provider", max_length=80) if args.provider else None
    domain = component(args.domain, "domain", max_length=80)
    dataset = component(args.dataset, "dataset", max_length=120)
    retention_class = component(args.retention_class, "retention_class", max_length=64)
    description = safe_text(args.description, "description", max_length=500) if args.description else None
    fields: dict[str, Any] = {
        "source_key": source_key, "display_name": display_name, "source_kind": args.source_kind,
        "provider": provider, "domain": domain, "dataset": dataset, "owner_scope": args.owner_scope,
        "privacy_class": args.privacy_class, "retention_class": retention_class,
        "ingest_mode": args.ingest_mode, "status": args.status, "description": description,
    }
    conn.create("sources", {k: v for k, v in fields.items() if v is not None})
    row = source_by_key(conn, source_key)
    json_print(public_source(row), args.as_json)


def cmd_source_list(args: argparse.Namespace, conn: Any) -> None:
    rows = sorted(
        conn.list("sources", status=args.status) if args.status else conn.list("sources"),
        key=lambda row: row["source_key"],
    )
    payload = [public_source(row) for row in rows]
    if args.as_json:
        json_print(payload, True)
        return
    if not payload:
        print("No registered sources.")
        return
    for source in payload:
        print(
            f"{source['source_key']} | {source['status']} | "
            f"{source['domain']}/{source['dataset']} | {source['privacy_class']}"
        )


def cmd_source_set_status(args: argparse.Namespace, conn: Any) -> None:
    source = source_by_key(conn, args.source_key)
    if source["status"] == "retired":
        raise ValueError("retired sources cannot be changed")
    if args.status == "planned" and source["status"] == "active":
        raise ValueError("active sources cannot move back to planned")
    conn.update("sources", source["id"], {"status": args.status})
    json_print({"source_key": source["source_key"], "status": args.status}, args.as_json)


def cmd_enqueue(args: argparse.Namespace, conn: Any) -> None:
    source = source_by_key(conn, args.source_key)
    if source["status"] != "active":
        raise ValueError(f"source {source['source_key']!r} is {source['status']}; activate it before enqueue")

    domain = component(args.domain or source["domain"], "domain", max_length=80)
    dataset = component(args.dataset or source["dataset"], "dataset", max_length=120)
    privacy_class = args.privacy_class or source["privacy_class"]
    if PRIVACY_RANK[privacy_class] < PRIVACY_RANK[source["privacy_class"]]:
        raise ValueError("intake privacy_class cannot be less restrictive than its source")
    input_ref = opaque_ref(args.input_ref)
    idempotency_key = safe_text(args.idempotency_key, "idempotency_key", max_length=160)
    source_batch_ref = (
        opaque_ref(args.source_batch_ref, "source_batch_ref") if args.source_batch_ref else None
    )
    retention_class = (
        component(args.retention_class, "retention_class", max_length=64)
        if args.retention_class else source["retention_class"]
    )
    intake_key = (
        component(args.intake_key, "intake_key", max_length=96)
        if args.intake_key
        else "intake-" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:20]
    )
    now = utc_now()
    fields: dict[str, Any] = {
        "intake_key": intake_key, "source_id": source["id"], "domain": domain, "dataset": dataset,
        "schema_version": component(args.schema_version, "schema_version", max_length=32),
        "payload_kind": args.payload_kind, "input_ref": input_ref, "source_batch_ref": source_batch_ref,
        "idempotency_key": idempotency_key, "privacy_class": privacy_class,
        "retention_class": retention_class, "requested_by": args.requested_by,
        "status": "queued", "requested_at": now,
    }
    created = conn.create("intakes", {k: v for k, v in fields.items() if v is not None})
    event(conn, int(created["id"]), "queued", None, "queued", args.requested_by, version=created["version"])
    row = intake_by_identifier(conn, intake_key)
    json_print(public_intake(row), args.as_json)


def cmd_queue(args: argparse.Namespace, conn: Any) -> None:
    sources = {source["id"]: source for source in conn.list("sources")}
    intakes = conn.list("intakes", status=args.status) if args.status else conn.list("intakes")
    intakes = [row for row in intakes if row["source_id"] in sources]
    intakes.sort(key=lambda row: (parse_sort(row.get("requested_at")), row["id"]), reverse=True)
    rows = [{**row, "source_key": sources[row["source_id"]]["source_key"]} for row in intakes[: args.limit]]
    payload = [public_intake(row) for row in rows]
    if args.as_json:
        json_print(payload, True)
        return
    if not payload:
        print("Intake queue is empty.")
        return
    for intake in payload:
        print(
            f"{intake['intake_key']} | {intake['status']} | "
            f"{intake['source_key']} | {intake['domain']}/{intake['dataset']}"
        )


def cmd_repair(args: argparse.Namespace, conn: Any) -> None:
    """Record lost events of one intake (and a verified intake's source freshness); changes no status."""
    row = intake_by_identifier(conn, args.intake)
    repair_events(conn, row)
    if row["status"] == "verified" and row.get("verified_at"):
        conn.update("sources", row["source_id"], {"last_ingested_at": row["verified_at"]})
    json_print({"intake_key": row["intake_key"], "status": row["status"], "repaired": True}, args.as_json)


def cmd_show(args: argparse.Namespace, conn: Any) -> None:
    row = intake_by_identifier(conn, args.intake)
    json_print(public_intake(row), args.as_json)


def cmd_status(args: argparse.Namespace, conn: Any) -> None:
    source_counts = conn.stats("sources", "status")
    intake_counts = conn.stats("intakes", "status")
    payload = {
        "sources": {status: source_counts.get(status, 0) for status in SOURCE_STATUSES},
        "intakes": {status: intake_counts.get(status, 0) for status in QUEUE_STATUSES},
        "verified_records": sum(
            int(row.get("record_count") or 0) for row in conn.list("intakes", status="verified")
        ),
    }
    json_print(payload, args.as_json)


def cmd_claim(args: argparse.Namespace, conn: Any) -> None:
    row = intake_by_identifier(conn, args.intake)
    repair_events(conn, row)
    if row["source_status"] != "active":
        raise ValueError(f"source {row['source_key']!r} is {row['source_status']}; cannot claim intake")
    worker = safe_text(args.worker, "worker", max_length=80)
    lease_minutes = max(1, min(args.lease_minutes, 1440))
    now = datetime.now(timezone.utc)
    if row["status"] == "processing":
        expires = lease_expiry(row)
        if expires is not None and expires > now:
            raise ValueError(f"intake {row['intake_key']!r} is already leased")
        # A crashed worker must not leave work permanently stuck in
        # processing. Requeue only the exact expired lease before claiming it.
        updated = guarded_update(conn, row, {
            "status": "queued", "claimed_at": None, "lease_owner": None, "lease_expires_at": None,
        }, "intake lease changed before reclaim")
        event(conn, row["id"], "retried", "processing", "queued", worker, "lease_expired", version=updated["version"])
        row = intake_by_identifier(conn, args.intake)
        now = datetime.now(timezone.utc)
    if row["status"] != "queued":
        raise ValueError(f"intake {row['intake_key']!r} is {row['status']}; only queued items can be claimed")
    claimed_at = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    expires_at = (now + timedelta(minutes=lease_minutes)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    updated = guarded_update(conn, row, {
        "status": "processing", "claimed_at": claimed_at, "lease_owner": worker,
        "lease_expires_at": expires_at, "attempt_count": int(row.get("attempt_count") or 0) + 1,
    }, "intake was claimed by another worker")
    event(conn, row["id"], "claimed", "queued", "processing", worker, version=updated["version"])
    json_print({"intake_key": row["intake_key"], "status": "processing", "lease_owner": worker, "lease_expires_at": expires_at}, args.as_json)


def cmd_renew(args: argparse.Namespace, conn: Any) -> None:
    """Extend an active lease without changing ownership or intake status."""
    row = intake_by_identifier(conn, args.intake)
    repair_events(conn, row)
    if row["status"] != "processing":
        raise ValueError(
            f"intake {row['intake_key']!r} is {row['status']}; only processing items can renew"
        )
    worker = safe_text(args.worker, "worker", max_length=80)
    if row["lease_owner"] != worker:
        raise ValueError("intake is leased by another worker")
    now = datetime.now(timezone.utc)
    expires = lease_expiry(row)
    if expires is None:
        raise ValueError(
            f"intake {row['intake_key']!r} has no active lease; reclaim before renewing"
        )
    if expires <= now:
        raise ValueError(
            f"intake {row['intake_key']!r} lease has expired; reclaim before renewing"
        )
    lease_minutes = max(1, min(args.lease_minutes, 1440))
    candidate = now + timedelta(minutes=lease_minutes)
    # A heartbeat may extend a lease, but never shorten a still-valid lease if
    # a caller supplies a smaller TTL than the current one.
    new_expires = max(expires, candidate)
    if new_expires.microsecond:
        # Lease values are emitted at second precision. Round up rather than
        # truncating a legacy fractional value and accidentally shortening it.
        new_expires += timedelta(seconds=1)
    new_expires = new_expires.replace(microsecond=0)
    new_expires_at = new_expires.isoformat().replace("+00:00", "Z")
    updated = guarded_update(conn, row, {"lease_expires_at": new_expires_at}, "intake lease changed or expired before renewal")
    event(conn, row["id"], "lease_renewed", "processing", "processing", worker, version=updated["version"])
    json_print(
        {
            "intake_key": row["intake_key"],
            "status": "processing",
            "lease_owner": worker,
            "lease_expires_at": new_expires_at,
        },
        args.as_json,
    )


def cmd_land(args: argparse.Namespace, conn: Any) -> None:
    row = intake_by_identifier(conn, args.intake)
    repair_events(conn, row)
    if row["status"] != "processing":
        raise ValueError(f"intake {row['intake_key']!r} is {row['status']}; only processing items can be landed")
    run_id = opaque_ref(args.lake_run_id, "lake_run_id")
    manifest_key = object_key(args.manifest_key, "manifest_key", "control/manifests/")
    raw_key = object_key(args.raw_key, "raw_key", "landing/")
    bronze_key = object_key(args.bronze_key, "bronze_key", "bronze/")
    digest = sha256(args.raw_sha256)
    if args.record_count < 1:
        raise ValueError("record_count must be at least 1")
    now = datetime.now(timezone.utc)
    expires = lease_expiry(row)
    if expires is None:
        raise ValueError(f"intake {row['intake_key']!r} has no active lease; reclaim before landing")
    if expires <= now:
        raise ValueError(f"intake {row['intake_key']!r} lease has expired; reclaim before landing")
    worker = safe_text(args.worker, "worker", max_length=80)
    if row["lease_owner"] != worker:
        raise ValueError("intake is leased by another worker")
    actor = safe_text(args.actor, "actor", max_length=80)
    updated = guarded_update(conn, row, {
        "status": "landed", "record_count": args.record_count, "raw_sha256": digest,
        "lake_run_id": run_id, "lake_manifest_key": manifest_key, "lake_raw_object_key": raw_key,
        "lake_bronze_object_key": bronze_key, "lease_owner": None, "lease_expires_at": None,
    }, "intake changed state before landing")
    event(conn, row["id"], "landed", "processing", "landed", actor, version=updated["version"])
    json_print({"intake_key": row["intake_key"], "status": "landed", "lake_run_id": run_id, "record_count": args.record_count}, args.as_json)


def verify_manifest(row: Row, data_lake_uri: str) -> None:
    if not row["lake_manifest_key"] or not row["lake_raw_object_key"] or not row["lake_bronze_object_key"]:
        raise ValueError("landed intake is missing lake lineage")
    try:
        store = ObjectStore(data_lake_uri)
        manifest_bytes = store.get_bytes(row["lake_manifest_key"])
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (StorageError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("lake manifest could not be read or parsed") from exc
    if not isinstance(manifest, dict):
        raise ValueError("lake manifest has an invalid shape")
    raw_meta = manifest.get("raw")
    bronze_meta = manifest.get("bronze")
    if not isinstance(raw_meta, dict) or not isinstance(bronze_meta, dict):
        raise ValueError("lake manifest is missing raw or Bronze lineage")
    try:
        raw_bytes = store.get_bytes(row["lake_raw_object_key"])
        bronze_bytes = store.get_bytes(row["lake_bronze_object_key"])
    except StorageError as exc:
        raise ValueError("lake manifest references a missing raw or Bronze object") from exc
    actual_raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    actual_bronze_sha256 = hashlib.sha256(bronze_bytes).hexdigest()

    def manifest_int(value: Any, field: str) -> int:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"lake manifest has invalid {field}") from exc

    checks = (
        manifest.get("source") == row["source_key"],
        manifest.get("domain") == row["domain"],
        manifest.get("dataset") == row["dataset"],
        manifest.get("schema_version") == row["schema_version"],
        manifest.get("run_id") == row["lake_run_id"],
        manifest_int(manifest.get("record_count", -1), "record_count")
        == int(row["record_count"] or -2),
        raw_meta.get("sha256") == row["raw_sha256"],
        raw_meta.get("sha256") == actual_raw_sha256,
        manifest_int(raw_meta.get("bytes", -1), "raw.bytes") == len(raw_bytes),
        raw_meta.get("key") == row["lake_raw_object_key"],
        bronze_meta.get("key") == row["lake_bronze_object_key"],
        bronze_meta.get("sha256") == actual_bronze_sha256,
        manifest_int(bronze_meta.get("bytes", -1), "bronze.bytes") == len(bronze_bytes),
        manifest.get("privacy_class") == row["privacy_class"],
        manifest.get("retention_class") == row["retention_class"],
    )
    if not all(checks):
        raise ValueError("lake manifest lineage does not match the intake record")


def cmd_verify(args: argparse.Namespace, conn: Any) -> None:
    row = intake_by_identifier(conn, args.intake)
    repair_events(conn, row)
    if row["status"] == "verified":  # a rerun after a lost source update or event: finish them, change nothing else
        actor = safe_text(args.actor, "actor", max_length=80)
        conn.update("sources", row["source_id"], {"last_ingested_at": row["verified_at"]})
        event(conn, row["id"], "verified", "landed", "verified", actor)
        json_print({"intake_key": row["intake_key"], "status": "verified", "verified_at": row["verified_at"]},
                   args.as_json)
        return
    if row["status"] != "landed":
        raise ValueError(f"intake {row['intake_key']!r} is {row['status']}; only landed items can be verified")
    verify_manifest(row, args.data_lake_uri)
    actor = safe_text(args.actor, "actor", max_length=80)
    verified_at = utc_now()
    updated = guarded_update(conn, row, {"status": "verified", "verified_at": verified_at},
                   "intake changed state before verification")
    conn.update("sources", row["source_id"], {"last_ingested_at": verified_at})
    event(conn, row["id"], "verified", "landed", "verified", actor, version=updated["version"])
    json_print({"intake_key": row["intake_key"], "status": "verified", "verified_at": verified_at}, args.as_json)


def cmd_fail(args: argparse.Namespace, conn: Any) -> None:
    row = intake_by_identifier(conn, args.intake)
    repair_events(conn, row)
    if row["status"] != "processing":
        raise ValueError(f"intake {row['intake_key']!r} is {row['status']}; only processing items can fail")
    code = component(args.error_code, "error_code", max_length=80)
    message = safe_text(args.error_message, "error_message", max_length=500)
    now = datetime.now(timezone.utc)
    expires = lease_expiry(row)
    if expires is None:
        raise ValueError(f"intake {row['intake_key']!r} has no active lease; reclaim before failing")
    if expires <= now:
        raise ValueError(f"intake {row['intake_key']!r} lease has expired; reclaim before failing")
    worker = safe_text(args.worker, "worker", max_length=80)
    if row["lease_owner"] != worker:
        raise ValueError("intake is leased by another worker")
    actor = safe_text(args.actor, "actor", max_length=80)
    updated = guarded_update(conn, row, {
        "status": "failed", "error_code": code, "error_message": message,
        "lease_owner": None, "lease_expires_at": None,
    }, "intake lease changed before failing")
    event(conn, row["id"], "failed", "processing", "failed", actor, code, version=updated["version"])
    json_print({"intake_key": row["intake_key"], "status": "failed", "error_code": code}, args.as_json)


def cmd_retry(args: argparse.Namespace, conn: Any) -> None:
    row = intake_by_identifier(conn, args.intake)
    repair_events(conn, row)
    if row["status"] not in {"failed", "rejected"}:
        raise ValueError(f"intake {row['intake_key']!r} is {row['status']}; only failed/rejected items can retry")
    actor = safe_text(args.actor, "actor", max_length=80)
    updated = guarded_update(conn, row, {
        "status": "queued", "error_code": None, "error_message": None,
        "claimed_at": None, "lease_owner": None, "lease_expires_at": None,
    }, "intake changed state before retry")
    event(conn, row["id"], "retried", row["status"], "queued", actor, version=updated["version"])
    json_print({"intake_key": row["intake_key"], "status": "queued"}, args.as_json)


def cmd_reject(args: argparse.Namespace, conn: Any) -> None:
    row = intake_by_identifier(conn, args.intake)
    repair_events(conn, row)
    if row["status"] not in {"queued", "processing", "landed"}:
        raise ValueError(f"intake {row['intake_key']!r} is {row['status']}; cannot reject it")
    reason = safe_text(args.reason, "reason", max_length=500)
    actor = safe_text(args.actor, "actor", max_length=80)
    updated = guarded_update(conn, row, {
        "status": "rejected", "error_code": "rejected_by_policy", "error_message": reason,
        "lease_owner": None, "lease_expires_at": None,
    }, "intake changed state before rejection")
    event(conn, row["id"], "rejected", row["status"], "rejected", actor, reason, version=updated["version"])
    json_print({"intake_key": row["intake_key"], "status": "rejected"}, args.as_json)


def add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", dest="as_json", help="Print privacy-safe JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    source = sub.add_parser("source", help="Manage source registry metadata")
    source_sub = source.add_subparsers(dest="source_command", required=True)

    register = source_sub.add_parser("register")
    register.add_argument("--key", dest="source_key", required=True)
    register.add_argument("--name", dest="display_name", required=True)
    register.add_argument("--kind", dest="source_kind", choices=SOURCE_KINDS, required=True)
    register.add_argument("--provider")
    register.add_argument("--domain", required=True)
    register.add_argument("--dataset", required=True)
    register.add_argument("--owner-scope", choices=OWNER_SCOPES, default="solo_empire")
    register.add_argument("--privacy-class", choices=PRIVACY_CLASSES, default="private")
    register.add_argument("--retention-class", default=RETENTION_DEFAULT)
    register.add_argument("--ingest-mode", choices=INGEST_MODES, default="manual")
    register.add_argument("--status", choices=SOURCE_STATUSES, default="planned")
    register.add_argument("--description")
    add_json_flag(register)

    source_list = source_sub.add_parser("list")
    source_list.add_argument("--status", choices=SOURCE_STATUSES)
    add_json_flag(source_list)

    source_status = source_sub.add_parser("set-status")
    source_status.add_argument("source_key")
    source_status.add_argument("status", choices=SOURCE_STATUSES)
    add_json_flag(source_status)

    enqueue = sub.add_parser("enqueue", help="Create a metadata-only intake request")
    enqueue.add_argument("--source", dest="source_key", required=True)
    enqueue.add_argument("--input-ref", required=True, help="Opaque reference only; never raw content or a filesystem path")
    enqueue.add_argument("--idempotency-key", required=True)
    enqueue.add_argument("--intake-key")
    enqueue.add_argument("--source-batch-ref")
    enqueue.add_argument("--domain")
    enqueue.add_argument("--dataset")
    enqueue.add_argument("--schema-version", default="1")
    enqueue.add_argument("--payload-kind", choices=PAYLOAD_KINDS, required=True)
    enqueue.add_argument("--privacy-class", choices=PRIVACY_CLASSES)
    enqueue.add_argument("--retention-class")
    enqueue.add_argument("--requested-by", choices=("human", "agent", "automation"), default="human")
    add_json_flag(enqueue)

    queue = sub.add_parser("queue", help="List queued intake metadata")
    queue.add_argument("--status", choices=QUEUE_STATUSES)
    queue.add_argument("--limit", type=int, default=50)
    add_json_flag(queue)

    show = sub.add_parser("show", help="Show one privacy-safe intake record")
    show.add_argument("intake")
    repair = sub.add_parser("repair", help="Record lost transition events of one intake")
    repair.add_argument("intake")
    add_json_flag(repair)
    add_json_flag(show)

    status = sub.add_parser("status", help="Show aggregate source/intake counts")
    add_json_flag(status)

    claim = sub.add_parser("claim", help="Lease one queued intake")
    claim.add_argument("intake")
    claim.add_argument("--worker", required=True)
    claim.add_argument("--lease-minutes", type=int, default=30)
    add_json_flag(claim)

    renew = sub.add_parser("renew", help="Extend an active intake lease")
    renew.add_argument("intake")
    renew.add_argument("--worker", required=True)
    renew.add_argument("--lease-minutes", type=int, default=30)
    add_json_flag(renew)

    land = sub.add_parser("land", help="Attach completed lake lineage to a processing intake")
    land.add_argument("intake")
    land.add_argument("--lake-run-id", required=True)
    land.add_argument("--manifest-key", required=True)
    land.add_argument("--raw-key", required=True)
    land.add_argument("--bronze-key", required=True)
    land.add_argument("--raw-sha256", required=True)
    land.add_argument("--record-count", type=int, required=True)
    land.add_argument("--worker", required=True, help="Expected lease owner; fences stale workers")
    land.add_argument("--actor", default="lake-worker")
    add_json_flag(land)

    verify = sub.add_parser("verify", help="Verify the immutable lake manifest and close the intake")
    verify.add_argument("intake")
    verify.add_argument("--data-lake-uri", default=DEFAULT_LAKE_URI)
    verify.add_argument("--actor", default="lake-verifier")
    add_json_flag(verify)

    fail = sub.add_parser("fail", help="Record a bounded, redacted processing failure")
    fail.add_argument("intake")
    fail.add_argument("--error-code", required=True)
    fail.add_argument("--error-message", required=True)
    fail.add_argument("--worker", required=True, help="Expected lease owner; fences stale workers")
    fail.add_argument("--actor", default="lake-worker")
    add_json_flag(fail)

    retry = sub.add_parser("retry", help="Return a failed/rejected intake to queued")
    retry.add_argument("intake")
    retry.add_argument("--actor", default="human")
    add_json_flag(retry)

    reject = sub.add_parser("reject", help="Reject an intake by policy")
    reject.add_argument("intake")
    reject.add_argument("--reason", required=True)
    reject.add_argument("--actor", default="human")
    add_json_flag(reject)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        conn = get_store()
        if args.command == "source" and args.source_command == "register":
            cmd_source_register(args, conn)
        elif args.command == "source" and args.source_command == "list":
            cmd_source_list(args, conn)
        elif args.command == "source" and args.source_command == "set-status":
            cmd_source_set_status(args, conn)
        elif args.command == "enqueue":
            cmd_enqueue(args, conn)
        elif args.command == "queue":
            if args.limit < 1 or args.limit > 500:
                raise ValueError("limit must be between 1 and 500")
            cmd_queue(args, conn)
        elif args.command == "show":
            cmd_show(args, conn)
        elif args.command == "repair":
            cmd_repair(args, conn)
        elif args.command == "status":
            cmd_status(args, conn)
        elif args.command == "claim":
            cmd_claim(args, conn)
        elif args.command == "renew":
            cmd_renew(args, conn)
        elif args.command == "land":
            cmd_land(args, conn)
        elif args.command == "verify":
            cmd_verify(args, conn)
        elif args.command == "fail":
            cmd_fail(args, conn)
        elif args.command == "retry":
            cmd_retry(args, conn)
        elif args.command == "reject":
            cmd_reject(args, conn)
        else:
            parser.error("unknown command")
    except (ValueError, RuntimeError, ClientConfigError, StorageError) as exc:
        message = str(exc)
        if isinstance(exc, CellStoreError) and exc.status == 409:
            message = "database constraint conflict; check unique keys and source status"
        print(f"ERROR: {message}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
