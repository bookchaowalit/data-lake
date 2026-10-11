"""DuckDB production lake query engine — reads Bronze Parquet in place."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Sequence

from .base import (
    EngineRole,
    LakeQueryEngine,
    QueryName,
    QueryResult,
    normalize_aggregate_rows,
    normalize_history_rows,
    normalize_latest_rows,
    normalize_lineage_rows,
)


class DuckDBLakeEngine(LakeQueryEngine):
    """Default production path: DuckDB over immutable Bronze Parquet parts."""

    name = "duckdb"
    role = EngineRole.PRODUCTION

    def __init__(self) -> None:
        self._conn: Any = None
        self._loaded = 0

    def open(self) -> None:
        try:
            import duckdb  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "DuckDB is required for the production lake query path; "
                "install infra/requirements-data-lake.txt"
            ) from exc
        if self._conn is None:
            self._conn = duckdb.connect(":memory:")

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        self._loaded = 0

    def load_bronze(self, parquet_paths: Sequence[Path | str]) -> int:
        self.open()
        paths = [str(Path(p).resolve()) for p in parquet_paths]
        if not paths:
            self._conn.execute("CREATE OR REPLACE TABLE bronze AS SELECT * FROM (SELECT 1 AS _x) WHERE 0")
            self._loaded = 0
            return 0
        # DuckDB reads Parquet files directly — no intermediate CSV.
        self._conn.execute(
            "CREATE OR REPLACE TABLE bronze AS SELECT * FROM read_parquet(?, union_by_name=true)",
            [paths if len(paths) > 1 else paths[0]],
        )
        self._loaded = int(self._conn.execute("SELECT count(*) FROM bronze").fetchone()[0])
        return self._loaded

    def _timed(self, query: QueryName, sql: str, normalizer) -> QueryResult:
        assert self._conn is not None
        started = time.perf_counter()
        cursor = self._conn.execute(sql)
        columns = [str(col[0]) for col in cursor.description or []]
        raw = [dict(zip(columns, row)) for row in cursor.fetchall()]
        elapsed = (time.perf_counter() - started) * 1000.0
        return QueryResult(
            engine=self.name,
            query=query.value,
            rows=normalizer(raw),
            elapsed_ms=elapsed,
            notes={"role": self.role.value, "loaded_rows": self._loaded, "reads_parquet_in_place": True},
        )

    def latest_price(self) -> QueryResult:
        sql = """
        SELECT source_record_id, payload_json, event_time, ingest_run_id, raw_object_key
        FROM (
          SELECT *,
                 row_number() OVER (
                   PARTITION BY source_record_id
                   ORDER BY event_time DESC NULLS LAST, received_at DESC NULLS LAST, event_id DESC
                 ) AS rn
          FROM bronze
        ) ranked
        WHERE rn = 1
        ORDER BY source_record_id
        """
        return self._timed(QueryName.LATEST_PRICE, sql, normalize_latest_rows)

    def full_history(self) -> QueryResult:
        sql = """
        SELECT event_id, source_record_id, payload_json, event_time, received_at,
               ingest_run_id, raw_object_key
        FROM bronze
        ORDER BY event_time NULLS LAST, event_id, source_record_id, ingest_run_id, raw_object_key
        """
        return self._timed(QueryName.FULL_HISTORY, sql, normalize_history_rows)

    def aggregate_by_coin(self) -> QueryResult:
        sql = """
        SELECT
          json_extract_string(payload_json, '$.coin_id') AS coin_id,
          count(*) AS event_count,
          avg(try_cast(json_extract_string(payload_json, '$.price') AS DOUBLE)) AS avg_price,
          min(try_cast(json_extract_string(payload_json, '$.price') AS DOUBLE)) AS min_price,
          max(try_cast(json_extract_string(payload_json, '$.price') AS DOUBLE)) AS max_price
        FROM bronze
        GROUP BY 1
        ORDER BY 1
        """
        return self._timed(QueryName.AGGREGATE_BY_COIN, sql, normalize_aggregate_rows)

    def lineage(self) -> QueryResult:
        sql = """
        SELECT event_id, source_record_id, raw_object_key, ingest_run_id, event_time
        FROM bronze
        ORDER BY event_id, source_record_id, ingest_run_id, raw_object_key, event_time
        """
        return self._timed(QueryName.LINEAGE, sql, normalize_lineage_rows)
