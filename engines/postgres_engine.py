"""PostgreSQL lab projection engine over Bronze Parquet.

Lab-only: materializes Bronze rows into a temporary schema. PostgreSQL is never
the source of truth — reload from Parquet for each lab session.
"""

from __future__ import annotations

import json
import os
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


class PostgresLakeEngine(LakeQueryEngine):
    """Lab adapter: project Bronze Parquet → PostgreSQL, then query."""

    name = "postgres"
    role = EngineRole.LAB

    def __init__(
        self,
        *,
        dsn: Optional[str] = None,
        schema: str = "lake_lab",
        table: str = "bronze_crypto_prices",
    ) -> None:
        self.dsn = (
            dsn
            or os.environ.get("LAKE_LAB_POSTGRES_DSN")
            or os.environ.get("DATABASE_URL")
            or ""
        ).strip()
        self.schema = schema
        self.table = table
        self._conn: Any = None
        self._owns_connection = False
        self._loaded = 0
        self._mode = "native"

    def open(self) -> None:
        try:
            import psycopg  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL lab engine requires psycopg; "
                "pip install 'psycopg[binary]>=3.1'"
            ) from exc

        if self._conn is not None:
            return

        if not self.dsn:
            # Offline lab: ephemeral local postgres via docker helper is
            # orchestrated by the suite; here we only accept an explicit DSN.
            raise RuntimeError(
                "PostgreSQL lab engine needs LAKE_LAB_POSTGRES_DSN "
                "(or pass dsn=...). It is a projection, not a source of truth."
            )

        self._conn = psycopg.connect(self.dsn)
        self._owns_connection = True
        self._mode = "native"
        with self._conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
            cur.execute(
                f'''
                CREATE TABLE IF NOT EXISTS "{self.schema}"."{self.table}" (
                    event_id TEXT,
                    source TEXT,
                    source_record_id TEXT,
                    domain TEXT,
                    dataset TEXT,
                    schema_version TEXT,
                    received_at TEXT,
                    event_time TEXT,
                    content_type TEXT,
                    raw_object_key TEXT,
                    raw_sha256 TEXT,
                    payload_json JSONB,
                    metadata_json JSONB,
                    ingest_run_id TEXT,
                    privacy_class TEXT,
                    retention_class TEXT
                )
                '''
            )
            cur.execute(f'TRUNCATE TABLE "{self.schema}"."{self.table}"')
        self._conn.commit()

    def close(self) -> None:
        if self._conn is not None and self._owns_connection:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
        self._conn = None
        self._loaded = 0

    def load_bronze(self, parquet_paths: Sequence[Path | str]) -> int:
        self.open()
        rows = read_bronze_dicts(parquet_paths)
        assert self._conn is not None
        with self._conn.cursor() as cur:
            cur.execute(f'TRUNCATE TABLE "{self.schema}"."{self.table}"')
            if rows:
                from psycopg.types.json import Jsonb  # type: ignore

                insert_sql = f'''
                    INSERT INTO "{self.schema}"."{self.table}" (
                        event_id, source, source_record_id, domain, dataset,
                        schema_version, received_at, event_time, content_type,
                        raw_object_key, raw_sha256, payload_json, metadata_json,
                        ingest_run_id, privacy_class, retention_class
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                '''
                batch = []
                for row in rows:
                    payload = row.get("payload_json")
                    if isinstance(payload, str):
                        try:
                            payload_obj = json.loads(payload)
                        except json.JSONDecodeError:
                            payload_obj = {"raw": payload}
                    else:
                        payload_obj = payload
                    meta = row.get("metadata_json")
                    if isinstance(meta, str):
                        try:
                            meta_obj = json.loads(meta)
                        except json.JSONDecodeError:
                            meta_obj = {"raw": meta}
                    else:
                        meta_obj = meta
                    batch.append(
                        (
                            row.get("event_id"),
                            row.get("source"),
                            row.get("source_record_id"),
                            row.get("domain"),
                            row.get("dataset"),
                            row.get("schema_version"),
                            row.get("received_at"),
                            row.get("event_time"),
                            row.get("content_type"),
                            row.get("raw_object_key"),
                            row.get("raw_sha256"),
                            Jsonb(payload_obj) if payload_obj is not None else None,
                            Jsonb(meta_obj) if meta_obj is not None else None,
                            row.get("ingest_run_id"),
                            row.get("privacy_class"),
                            row.get("retention_class"),
                        )
                    )
                cur.executemany(insert_sql, batch)
        self._conn.commit()
        self._loaded = len(rows)
        return self._loaded

    def _rel(self) -> str:
        return f'"{self.schema}"."{self.table}"'

    def _timed(self, query: QueryName, sql: str, normalizer) -> QueryResult:
        assert self._conn is not None
        started = time.perf_counter()
        with self._conn.cursor() as cur:
            cur.execute(sql)
            columns = [desc[0] for desc in cur.description or []]
            raw = [dict(zip(columns, row)) for row in cur.fetchall()]
        elapsed = (time.perf_counter() - started) * 1000.0
        # payload_json may already be dict from jsonb
        for row in raw:
            if "payload_json" in row and not isinstance(row["payload_json"], (str, type(None))):
                row["payload_json"] = json.dumps(row["payload_json"], ensure_ascii=False)
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
                "projection": "bronze_parquet_to_postgres",
            },
        )

    def latest_price(self) -> QueryResult:
        sql = f"""
        SELECT source_record_id, payload_json::text AS payload_json, event_time,
               ingest_run_id, raw_object_key
        FROM (
          SELECT *,
                 row_number() OVER (
                   PARTITION BY source_record_id
                   ORDER BY event_time DESC NULLS LAST, received_at DESC NULLS LAST, event_id DESC
                 ) AS rn
          FROM {self._rel()}
        ) ranked
        WHERE rn = 1
        ORDER BY source_record_id
        """
        return self._timed(QueryName.LATEST_PRICE, sql, normalize_latest_rows)

    def full_history(self) -> QueryResult:
        sql = f"""
        SELECT event_id, source_record_id, payload_json::text AS payload_json,
               event_time, received_at, ingest_run_id, raw_object_key
        FROM {self._rel()}
        ORDER BY event_time NULLS LAST, event_id, source_record_id, ingest_run_id, raw_object_key
        """
        return self._timed(QueryName.FULL_HISTORY, sql, normalize_history_rows)

    def aggregate_by_coin(self) -> QueryResult:
        sql = f"""
        SELECT
          payload_json->>'coin_id' AS coin_id,
          count(*)::int AS event_count,
          avg((payload_json->>'price')::double precision) AS avg_price,
          min((payload_json->>'price')::double precision) AS min_price,
          max((payload_json->>'price')::double precision) AS max_price
        FROM {self._rel()}
        GROUP BY 1
        ORDER BY 1
        """
        return self._timed(QueryName.AGGREGATE_BY_COIN, sql, normalize_aggregate_rows)

    def lineage(self) -> QueryResult:
        sql = f"""
        SELECT event_id, source_record_id, raw_object_key, ingest_run_id, event_time
        FROM {self._rel()}
        ORDER BY event_id, source_record_id, ingest_run_id, raw_object_key, event_time
        """
        return self._timed(QueryName.LINEAGE, sql, normalize_lineage_rows)
