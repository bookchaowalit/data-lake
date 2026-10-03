"""ClickHouse lab projection engine over Bronze Parquet.

Default offline path uses embedded chDB (real ClickHouse engine, no server).
Optional native HTTP mode uses clickhouse-connect against a server DSN.
ClickHouse is never the source of truth.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional, Sequence

from .base import (
    EngineRole,
    LakeQueryEngine,
    QueryName,
    QueryResult,
    normalize_aggregate_rows,
    normalize_history_rows,
    normalize_latest_rows,
    normalize_lineage_rows,
    read_bronze_dicts,
)
from .native_runtime import probe_embedded_clickhouse


class ClickHouseLakeEngine(LakeQueryEngine):
    """Lab adapter: Bronze Parquet → ClickHouse (chDB or server)."""

    name = "clickhouse"
    role = EngineRole.LAB

    def __init__(
        self,
        *,
        dsn: Optional[str] = None,
        table: str = "bronze_crypto_prices",
        prefer_embedded: bool = True,
    ) -> None:
        self.dsn = (dsn or os.environ.get("LAKE_LAB_CLICKHOUSE_DSN") or "").strip()
        self.table = table
        self.prefer_embedded = prefer_embedded
        self._mode = "embedded_chdb"
        self._client: Any = None
        self._workdir: Optional[tempfile.TemporaryDirectory[str]] = None
        self._parquet_copy: Optional[Path] = None
        self._loaded = 0

    def open(self) -> None:
        if self._client is not None or self._workdir is not None:
            return
        if self.prefer_embedded or not self.dsn:
            available, detail = probe_embedded_clickhouse()
            if not available:
                raise RuntimeError(detail)
            try:
                import chdb  # type: ignore  # noqa: F401
            except ImportError as exc:
                if not self.dsn:
                    raise RuntimeError(
                        "ClickHouse lab engine needs chdb (embedded) or "
                        "LAKE_LAB_CLICKHOUSE_DSN; pip install chdb"
                    ) from exc
            self._mode = "embedded_chdb"
            self._workdir = tempfile.TemporaryDirectory(prefix="lake-ch-lab-")
            return

        try:
            import clickhouse_connect  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Native ClickHouse mode requires clickhouse-connect"
            ) from exc
        # dsn form: host:port or clickhouse://host:port
        host = self.dsn
        port = 8123
        if "://" in host:
            host = host.split("://", 1)[1]
        if ":" in host:
            host, port_s = host.rsplit(":", 1)
            port = int(port_s)
        self._client = clickhouse_connect.get_client(host=host, port=port)
        self._mode = "native_http"
        self._client.command(
            f"""
            CREATE TABLE IF NOT EXISTS {self.table} (
                event_id String,
                source String,
                source_record_id String,
                domain String,
                dataset String,
                schema_version String,
                received_at String,
                event_time String,
                content_type String,
                raw_object_key String,
                raw_sha256 String,
                payload_json String,
                metadata_json String,
                ingest_run_id String,
                privacy_class String,
                retention_class String
            ) ENGINE = MergeTree ORDER BY (source_record_id, event_id)
            """
        )
        self._client.command(f"TRUNCATE TABLE IF EXISTS {self.table}")

    def close(self) -> None:
        self._client = None
        if self._workdir is not None:
            self._workdir.cleanup()
            self._workdir = None
        self._parquet_copy = None
        self._loaded = 0

    def load_bronze(self, parquet_paths: Sequence[Path | str]) -> int:
        self.open()
        paths = [Path(p).resolve() for p in parquet_paths]
        if self._mode == "embedded_chdb":
            # chDB reads Parquet via file(); copy list into a stable directory.
            assert self._workdir is not None
            work = Path(self._workdir.name)
            # Single merged parquet for stable path semantics.
            rows = read_bronze_dicts(paths)
            if not rows:
                # Empty placeholder parquet
                import pyarrow as pa  # type: ignore
                import pyarrow.parquet as pq  # type: ignore

                empty = pa.table({"event_id": pa.array([], type=pa.string())})
                self._parquet_copy = work / "bronze.parquet"
                pq.write_table(empty, self._parquet_copy)
                self._loaded = 0
                return 0
            import pyarrow as pa  # type: ignore
            import pyarrow.parquet as pq  # type: ignore

            table = pa.Table.from_pylist(rows)
            self._parquet_copy = work / "bronze.parquet"
            pq.write_table(table, self._parquet_copy)
            self._loaded = len(rows)
            return self._loaded

        # Native: insert rows from Parquet via pyarrow
        rows = read_bronze_dicts(paths)
        assert self._client is not None
        self._client.command(f"TRUNCATE TABLE IF EXISTS {self.table}")
        if rows:
            columns = [
                "event_id",
                "source",
                "source_record_id",
                "domain",
                "dataset",
                "schema_version",
                "received_at",
                "event_time",
                "content_type",
                "raw_object_key",
                "raw_sha256",
                "payload_json",
                "metadata_json",
                "ingest_run_id",
                "privacy_class",
                "retention_class",
            ]
            data = []
            for col in columns:
                col_vals = []
                for row in rows:
                    value = row.get(col)
                    if col in {"payload_json", "metadata_json"} and value is not None and not isinstance(value, str):
                        value = json.dumps(value, ensure_ascii=False)
                    col_vals.append("" if value is None else str(value))
                data.append(col_vals)
            self._client.insert(self.table, data, column_names=columns)
        self._loaded = len(rows)
        return self._loaded

    def _source_sql(self) -> str:
        if self._mode == "embedded_chdb":
            assert self._parquet_copy is not None
            path = str(self._parquet_copy).replace("'", "\\'")
            return f"file('{path}', Parquet)"
        return self.table

    def _query(self, sql: str) -> list[dict[str, Any]]:
        if self._mode == "embedded_chdb":
            import chdb  # type: ignore

            result = chdb.query(sql, "JSONEachRow")
            text = result.data() if hasattr(result, "data") else str(result)
            if isinstance(text, bytes):
                text = text.decode("utf-8")
            rows: list[dict[str, Any]] = []
            for line in str(text).splitlines():
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
            return rows

        assert self._client is not None
        result = self._client.query(sql)
        columns = list(result.column_names)
        return [dict(zip(columns, row)) for row in result.result_rows]

    def _timed(self, query: QueryName, sql: str, normalizer) -> QueryResult:
        started = time.perf_counter()
        raw = self._query(sql)
        elapsed = (time.perf_counter() - started) * 1000.0
        return QueryResult(
            engine=self.name,
            query=query.value,
            rows=normalizer(raw),
            elapsed_ms=elapsed,
            notes={
                "role": self.role.value,
                "mode": self._mode,
                "loaded_rows": self._loaded,
                "source_of_truth": False,
                "projection": "bronze_parquet_to_clickhouse",
            },
        )

    def latest_price(self) -> QueryResult:
        src = self._source_sql()
        sql = f"""
        SELECT
            source_record_id,
            payload_json,
            event_time,
            ingest_run_id,
            raw_object_key
        FROM (
            SELECT
                *,
                row_number() OVER (
                    PARTITION BY source_record_id
                    ORDER BY event_time DESC, received_at DESC, event_id DESC
                ) AS rn
            FROM {src}
        )
        WHERE rn = 1
        ORDER BY source_record_id
        """
        return self._timed(QueryName.LATEST_PRICE, sql, normalize_latest_rows)

    def full_history(self) -> QueryResult:
        src = self._source_sql()
        sql = f"""
        SELECT
            event_id,
            source_record_id,
            payload_json,
            event_time,
            received_at,
            ingest_run_id,
            raw_object_key
        FROM {src}
        ORDER BY event_time, event_id, source_record_id, ingest_run_id, raw_object_key
        """
        return self._timed(QueryName.FULL_HISTORY, sql, normalize_history_rows)

    def aggregate_by_coin(self) -> QueryResult:
        src = self._source_sql()
        # JSONExtractString works in ClickHouse / chDB.
        sql = f"""
        SELECT
            JSONExtractString(payload_json, 'coin_id') AS coin_id,
            count() AS event_count,
            avg(toFloat64OrNull(JSONExtractString(payload_json, 'price'))) AS avg_price,
            min(toFloat64OrNull(JSONExtractString(payload_json, 'price'))) AS min_price,
            max(toFloat64OrNull(JSONExtractString(payload_json, 'price'))) AS max_price
        FROM {src}
        GROUP BY coin_id
        ORDER BY coin_id
        """
        return self._timed(QueryName.AGGREGATE_BY_COIN, sql, normalize_aggregate_rows)

    def lineage(self) -> QueryResult:
        src = self._source_sql()
        sql = f"""
        SELECT
            event_id,
            source_record_id,
            raw_object_key,
            ingest_run_id,
            event_time
        FROM {src}
        ORDER BY event_id, source_record_id, ingest_run_id, raw_object_key, event_time
        """
        return self._timed(QueryName.LINEAGE, sql, normalize_lineage_rows)
