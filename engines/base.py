"""LakeQueryEngine contract for multi-engine Bronze Parquet labs.

Production default is DuckDB. PostgreSQL and ClickHouse adapters are lab /
optional projection engines. No engine owns the data; Bronze Parquet does.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Sequence


class EngineRole(str, Enum):
    PRODUCTION = "production"
    LAB = "lab"


class QueryName(str, Enum):
    LATEST_PRICE = "latest_price"
    FULL_HISTORY = "full_history"
    AGGREGATE_BY_COIN = "aggregate_by_coin"
    LINEAGE = "lineage"


@dataclass(frozen=True)
class QueryResult:
    """Normalized rows for cross-engine comparison."""

    engine: str
    query: str
    rows: list[dict[str, Any]]
    elapsed_ms: float
    notes: dict[str, Any] = field(default_factory=dict)

    def canonical_rows(self) -> list[dict[str, Any]]:
        return [canonicalize_row(row) for row in self.rows]

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["row_count"] = len(self.rows)
        return body


class LakeQueryEngine(ABC):
    """Query/projection engine over the same Bronze Parquet dataset."""

    name: str
    role: EngineRole

    @abstractmethod
    def open(self) -> None:
        """Acquire connections / runtime resources."""

    @abstractmethod
    def close(self) -> None:
        """Release resources. Safe to call more than once."""

    @abstractmethod
    def load_bronze(self, parquet_paths: Sequence[Path | str]) -> int:
        """Register or project Bronze Parquet parts. Returns row count loaded."""

    @abstractmethod
    def latest_price(self) -> QueryResult:
        """Latest row per source_record_id (snapshot)."""

    @abstractmethod
    def full_history(self) -> QueryResult:
        """All Bronze rows ordered by event time."""

    @abstractmethod
    def aggregate_by_coin(self) -> QueryResult:
        """Counts and price stats grouped by coin_id."""

    @abstractmethod
    def lineage(self) -> QueryResult:
        """Lineage fields: source_record_id, raw_object_key, ingest_run_id, event_id."""

    def run_all(self) -> dict[str, QueryResult]:
        return {
            QueryName.LATEST_PRICE.value: self.latest_price(),
            QueryName.FULL_HISTORY.value: self.full_history(),
            QueryName.AGGREGATE_BY_COIN.value: self.aggregate_by_coin(),
            QueryName.LINEAGE.value: self.lineage(),
        }

    def __enter__(self) -> "LakeQueryEngine":
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def parse_payload(payload_json: Any) -> dict[str, Any]:
    if payload_json is None or payload_json == "":
        return {}
    if isinstance(payload_json, dict):
        return payload_json
    try:
        value = json.loads(str(payload_json))
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


def canonicalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Stable JSON-friendly form for equivalence checks."""
    numeric_keys = {
        "price",
        "avg_price",
        "min_price",
        "max_price",
        "sum_price",
    }
    int_keys = {"event_count", "row_count"}
    out: dict[str, Any] = {}
    for key in sorted(row.keys()):
        value = row[key]
        if key in int_keys:
            out[key] = as_int(value)
        elif key in numeric_keys:
            num = as_float(value)
            out[key] = None if num is None else round(num, 6)
        elif value is None:
            out[key] = None
        elif isinstance(value, bool):
            out[key] = value
        elif isinstance(value, int):
            out[key] = value
        elif isinstance(value, float):
            out[key] = round(value, 6)
        else:
            out[key] = str(value)
    return out


def normalize_latest_rows(raw_rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in raw_rows:
        payload = parse_payload(row.get("payload_json"))
        items.append(
            {
                "source_record_id": str(row.get("source_record_id") or payload.get("id") or ""),
                "coin_id": str(payload.get("coin_id") or ""),
                "currency": str(payload.get("currency") or ""),
                "price": as_float(payload.get("price")),
                "event_time": str(row.get("event_time") or payload.get("event_time") or ""),
                "ingest_run_id": str(row.get("ingest_run_id") or ""),
                "raw_object_key": str(row.get("raw_object_key") or ""),
            }
        )
    items.sort(key=lambda r: (r["source_record_id"], r["event_time"]))
    return items


def normalize_history_rows(raw_rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in raw_rows:
        payload = parse_payload(row.get("payload_json"))
        items.append(
            {
                "event_id": str(row.get("event_id") or ""),
                "source_record_id": str(row.get("source_record_id") or payload.get("id") or ""),
                "coin_id": str(payload.get("coin_id") or ""),
                "currency": str(payload.get("currency") or ""),
                "price": as_float(payload.get("price")),
                "event_time": str(row.get("event_time") or payload.get("event_time") or ""),
                "received_at": str(row.get("received_at") or ""),
                "ingest_run_id": str(row.get("ingest_run_id") or ""),
                "raw_object_key": str(row.get("raw_object_key") or ""),
            }
        )
    # Include ingest_run_id / raw_object_key so multi-batch rows with the same
    # event_id (identical source_record_id identity) still sort deterministically.
    items.sort(
        key=lambda r: (
            r["event_time"],
            r["event_id"],
            r["source_record_id"],
            r["ingest_run_id"],
            r["raw_object_key"],
        )
    )
    return items


def normalize_aggregate_rows(raw_rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in raw_rows:
        items.append(
            {
                "coin_id": str(row.get("coin_id") or ""),
                "event_count": as_int(row.get("event_count") if row.get("event_count") is not None else row.get("row_count")),
                "avg_price": as_float(row.get("avg_price")),
                "min_price": as_float(row.get("min_price")),
                "max_price": as_float(row.get("max_price")),
            }
        )
    items.sort(key=lambda r: r["coin_id"])
    return items


def normalize_lineage_rows(raw_rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in raw_rows:
        items.append(
            {
                "event_id": str(row.get("event_id") or ""),
                "source_record_id": str(row.get("source_record_id") or ""),
                "raw_object_key": str(row.get("raw_object_key") or ""),
                "ingest_run_id": str(row.get("ingest_run_id") or ""),
                "event_time": str(row.get("event_time") or ""),
            }
        )
    items.sort(
        key=lambda r: (
            r["event_id"],
            r["source_record_id"],
            r["ingest_run_id"],
            r["raw_object_key"],
            r["event_time"],
        )
    )
    return items


def read_bronze_dicts(parquet_paths: Sequence[Path | str]) -> list[dict[str, Any]]:
    """Load Bronze Parquet parts via PyArrow (no CSV)."""
    try:
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Reading Bronze Parquet requires PyArrow; install infra/requirements-data-lake.txt"
        ) from exc

    paths = [Path(p) for p in parquet_paths]
    if not paths:
        return []
    # Bronze paths can live below Hive-style directories such as
    # ``domain=...``.  PyArrow's default dataset partition inference then
    # collides with an explicit ``domain`` column in the file (and can also
    # surface dictionary-vs-string schema differences).  The Bronze envelope
    # already carries these fields, so disable path partition inference and
    # let the file schema remain authoritative.
    tables = [pq.read_table(path, partitioning=None) for path in paths]
    table = tables[0]
    for extra in tables[1:]:
        table = pa.concat_tables([table, extra], promote_options="default")
    return table.to_pylist()


def get_engine(name: str, **kwargs: Any) -> LakeQueryEngine:
    key = name.strip().lower()
    if key in {"duckdb", "duck", "production"}:
        from .duckdb_engine import DuckDBLakeEngine

        return DuckDBLakeEngine(**kwargs)
    if key in {"postgres", "postgresql", "pg"}:
        from .postgres_engine import PostgresLakeEngine

        return PostgresLakeEngine(**kwargs)
    if key in {"clickhouse", "ch"}:
        from .clickhouse_engine import ClickHouseLakeEngine

        return ClickHouseLakeEngine(**kwargs)
    raise ValueError(f"Unknown lake query engine: {name!r}")


def available_engines() -> list[dict[str, Any]]:
    """Report which engines can be constructed in this environment."""
    rows: list[dict[str, Any]] = []
    for name, role in (
        ("duckdb", EngineRole.PRODUCTION),
        ("postgres", EngineRole.LAB),
        ("clickhouse", EngineRole.LAB),
    ):
        status = "ready"
        detail = ""
        try:
            engine = get_engine(name)
            engine.open()
            engine.close()
        except Exception as exc:  # noqa: BLE001
            status = "unavailable"
            detail = str(exc)
        rows.append(
            {
                "engine": name,
                "role": role.value,
                "status": status,
                "detail": detail,
                "source_of_truth": False,
            }
        )
    return rows
