"""Versioned Avro container format for the optional streaming lane.

The Avro record intentionally mirrors the stable Bronze envelope.  This keeps
the broker boundary typed and compact while allowing the same records to be
converted to Parquet without a source-specific streaming consumer.

``fastavro`` is optional at import time so the rest of the data-lake tools can
still run in a minimal environment.  A streaming sink or conversion run
fails clearly when the optional runtime has not been installed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, BinaryIO, Iterable

from .parquet import BRONZE_COLUMNS


class AvroUnavailable(RuntimeError):
    """Raised when the optional Avro runtime is not installed."""


_NULLABLE_STRING = ["null", "string"]

AVRO_SCHEMA: dict[str, Any] = {
    "type": "record",
    "name": "SoloEmpireBronzeEvent",
    "namespace": "solo_empire.data_lake",
    "doc": "Stable streaming envelope shared by Avro landing and Bronze Parquet",
    "fields": [
        {
            "name": column,
            "type": "string" if column in {"event_id", "source", "domain", "dataset", "schema_version", "received_at", "content_type", "metadata_json", "ingest_run_id", "privacy_class", "retention_class"} else _NULLABLE_STRING,
            **({"default": None} if column not in {"event_id", "source", "domain", "dataset", "schema_version", "received_at", "content_type", "metadata_json", "ingest_run_id", "privacy_class", "retention_class"} else {}),
        }
        for column in BRONZE_COLUMNS
    ],
}

AVRO_SCHEMA_VERSION = "1"


def _fastavro():
    try:
        import fastavro  # type: ignore
    except ImportError as exc:
        raise AvroUnavailable(
            "Avro streaming requires fastavro; install with "
            "python3 -m pip install -r infra/requirements-data-lake.txt"
        ) from exc
    return fastavro


def _record_for_schema(record: dict[str, Any]) -> dict[str, str | None]:
    missing = [
        column
        for column in ("event_id", "source", "domain", "dataset", "schema_version", "received_at")
        if record.get(column) in {None, ""}
    ]
    if missing:
        raise ValueError(f"Avro Bronze record is missing required fields: {', '.join(missing)}")
    return {
        column: None if record.get(column) is None else str(record.get(column))
        for column in BRONZE_COLUMNS
    }


def write_avro(records: Iterable[dict[str, Any]], destination: Path | BinaryIO) -> None:
    """Write a deterministic Avro Object Container File for one micro-batch."""
    fastavro = _fastavro()
    normalized = [_record_for_schema(record) for record in records]
    if not normalized:
        raise ValueError("Cannot write an empty Avro micro-batch")
    parsed_schema = fastavro.parse_schema(AVRO_SCHEMA)
    # fastavro otherwise generates a random sync marker for every write. A
    # content-derived marker keeps a retry byte-identical, which lets the
    # immutable ObjectStore make duplicate delivery a true no-op.
    sync_marker = hashlib.sha256(
        json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).digest()[:16]
    if isinstance(destination, Path):
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as stream:
            fastavro.writer(stream, parsed_schema, normalized, codec="deflate", sync_marker=sync_marker)
    else:
        fastavro.writer(destination, parsed_schema, normalized, codec="deflate", sync_marker=sync_marker)


def read_avro(source: Path | BinaryIO) -> list[dict[str, str | None]]:
    """Read one Avro Object Container File and return Bronze envelope rows."""
    fastavro = _fastavro()
    if isinstance(source, Path):
        with source.open("rb") as stream:
            return [dict(record) for record in fastavro.reader(stream)]
    return [dict(record) for record in fastavro.reader(source)]
