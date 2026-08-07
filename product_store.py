"""Shared Bronze→API store helpers for lake-first data products."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Sequence
from urllib.parse import unquote

from .product_adapter import (
    LakeIngestError,
    LakeProductContract,
    LakeUnavailable,
    bronze_dataset_dir,
    parse_payload_json,
    read_bronze_rows,
    select_latest_bronze_rows,
    default_data_lake_uri,
)


TIMESTAMP_KEYS = (
    "updated_at",
    "event_time",
    "scraped_at",
    "date",
    "timestamp",
    "retrieved_at",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_ts(value: str) -> Optional[datetime]:
    if not value:
        return None
    value = value.strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def make_record_id(row: dict[str, Any], *, id_fields: Sequence[str], id_sep: str = ":") -> str:
    parts = []
    for field in id_fields:
        raw = str(row.get(field, "")).strip()
        if not raw and field == "url":
            raw = str(row.get("name", "") or row.get("title", "")).strip()
        parts.append(raw)
    joined = id_sep.join(parts)
    if not joined or joined == id_sep * (len(parts) - 1):
        blob = json.dumps(row, sort_keys=True, default=str)
        return "hash:" + hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]
    if any(ch in joined for ch in ("://", "?", "#", " ")) or joined.count("/") > 0:
        return "hash:" + hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]
    return joined.replace("/", "_")


def freshness(
    rows: list[dict[str, Any]],
    *,
    stale_after_hours: float,
) -> tuple[str, Optional[str]]:
    if not rows:
        return "empty", None
    latest: Optional[datetime] = None
    latest_raw = None
    for row in rows:
        for key in TIMESTAMP_KEYS:
            if key in row and row[key]:
                parsed = parse_ts(str(row[key]))
                if parsed and (latest is None or parsed > latest):
                    latest = parsed
                    latest_raw = str(row[key])
                break
    if latest is None:
        return "ok", latest_raw
    age_hours = (datetime.now(timezone.utc) - latest).total_seconds() / 3600.0
    if age_hours > stale_after_hours:
        return "stale", latest_raw
    return "ok", latest_raw


def stringify(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def default_item_from_bronze(
    row: dict[str, Any],
    *,
    id_fields: Sequence[str],
    id_sep: str = ":",
    history: bool = False,
    history_idx: int = 0,
    extra_payload_fields: Sequence[str] = (),
) -> dict[str, Any]:
    """Project Bronze envelope → product API item using payload_json fields."""
    payload = parse_payload_json(row)
    event_time = stringify(row.get("event_time") or payload.get("event_time") or "")
    item: dict[str, Any] = {
        "updated_at": event_time,
        "event_time": event_time,
        "ingest_run_id": stringify(row.get("ingest_run_id", "")),
        "source_record_id": stringify(row.get("source_record_id", "")),
        "raw_object_key": stringify(row.get("raw_object_key", "")),
    }
    # Copy common payload keys; callers can pass extras.
    for key, value in payload.items():
        if key in {"id"}:
            continue
        item[key] = stringify(value) if not isinstance(value, (dict, list)) else value
    for key in extra_payload_fields:
        if key not in item:
            item[key] = stringify(payload.get(key, ""))
    if history:
        item.setdefault("date", event_time)
        item["record_id"] = make_record_id(item, id_fields=id_fields, id_sep=id_sep) + f"#h{history_idx}"
    else:
        item["record_id"] = make_record_id(item, id_fields=id_fields, id_sep=id_sep)
    return item


def load_bronze_dataset(
    contract: LakeProductContract,
    dataset: str,
    *,
    data_lake_uri: Optional[str] = None,
    latest_only: bool = False,
    id_fields: Sequence[str],
    id_sep: str = ":",
    stale_after_hours: float = 24.0,
    item_builder: Optional[Callable[..., dict[str, Any]]] = None,
) -> dict[str, Any]:
    uri = data_lake_uri or default_data_lake_uri(
        data_lake_uri=contract.data_lake_uri,
        project_root=contract.project_root,
        solo_empire_root=contract.solo_empire_root,
    )
    bronze_path = str(bronze_dataset_dir(contract, dataset, data_lake_uri=uri))
    builder = item_builder or (
        lambda row, history=False, history_idx=0: default_item_from_bronze(
            row,
            id_fields=id_fields,
            id_sep=id_sep,
            history=history,
            history_idx=history_idx,
        )
    )
    try:
        rows = read_bronze_rows(contract, dataset, data_lake_uri=uri)
        if latest_only:
            rows = select_latest_bronze_rows(rows)
            items = [builder(row, history=False, history_idx=0) for row in rows]
        else:
            items = [
                builder(row, history=True, history_idx=idx)
                for idx, row in enumerate(rows)
            ]
        status, _ = freshness(items, stale_after_hours=stale_after_hours)
        return {
            "items": items,
            "data_status": status if items else "empty",
            "error": None,
            "path": bronze_path,
            "source_kind": "bronze_parquet",
            "retrieved_at": utc_now_iso(),
        }
    except LakeUnavailable as exc:
        return {
            "items": [],
            "data_status": "error",
            "error": str(exc),
            "path": bronze_path,
            "source_kind": "bronze_parquet",
            "retrieved_at": utc_now_iso(),
        }
    except LakeIngestError as exc:
        return {
            "items": [],
            "data_status": "malformed",
            "error": str(exc),
            "path": bronze_path,
            "source_kind": "bronze_parquet",
            "retrieved_at": utc_now_iso(),
        }


def load_csv_projection(
    *,
    path: Path,
    id_fields: Sequence[str],
    id_sep: str = ":",
    history: bool = False,
    stale_after_hours: float = 24.0,
) -> dict[str, Any]:
    """CLI-only CSV helper; never used by lake-first HTTP APIs."""
    path = Path(path)
    if not path.exists():
        return {
            "items": [],
            "data_status": "empty",
            "error": None,
            "path": str(path),
            "source_kind": "csv_projection",
            "retrieved_at": utc_now_iso(),
        }
    try:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            rows: list[dict[str, str]] = []
        else:
            rows = [dict(row) for row in csv.DictReader(text.splitlines())]
    except Exception as exc:  # noqa: BLE001
        return {
            "items": [],
            "data_status": "malformed",
            "error": f"malformed: {exc}",
            "path": str(path),
            "source_kind": "csv_projection",
            "retrieved_at": utc_now_iso(),
        }
    status, _ = freshness(rows, stale_after_hours=stale_after_hours)
    items = []
    for idx, row in enumerate(rows):
        item = dict(row)
        rid = make_record_id(row, id_fields=id_fields, id_sep=id_sep)
        item["record_id"] = rid + f"#h{idx}" if history else rid
        items.append(item)
    return {
        "items": items,
        "data_status": status if rows else "empty",
        "error": None,
        "path": str(path),
        "source_kind": "csv_projection",
        "retrieved_at": utc_now_iso(),
    }


def paginate(
    items: list[dict[str, Any]],
    *,
    limit: int = 50,
    cursor: Optional[str] = None,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    limit = max(1, min(int(limit), 500))
    start = 0
    if cursor:
        try:
            start = max(0, int(cursor))
        except ValueError:
            start = 0
    end = start + limit
    page = items[start:end]
    next_cursor = str(end) if end < len(items) else None
    return page, next_cursor


def envelope(
    *,
    schema_version: str,
    source: str,
    items: list[dict[str, Any]],
    data_status: str,
    next_cursor: Optional[str] = None,
    retrieved_at: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    body = {
        "schema_version": schema_version,
        "source": source,
        "retrieved_at": retrieved_at or utc_now_iso(),
        "data_status": data_status,
        "items": items,
        "next_cursor": next_cursor,
    }
    if extra:
        body.update(extra)
    return body


def get_record_from_payload(
    record_id: str,
    payload: dict[str, Any],
) -> Optional[dict[str, Any]]:
    record_id = unquote(record_id)
    for item in payload.get("items") or []:
        if item.get("record_id") == record_id:
            return item
    return None
