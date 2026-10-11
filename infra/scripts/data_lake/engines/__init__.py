"""Multi-engine lake query adapters.

Parquet in Object Storage remains the durable source of truth. Engines are
query/projection layers only — never a competing system of record.
"""

from __future__ import annotations

from .base import (
    EngineRole,
    LakeQueryEngine,
    QueryName,
    QueryResult,
    available_engines,
    get_engine,
)
from .duckdb_engine import DuckDBLakeEngine

__all__ = [
    "DuckDBLakeEngine",
    "EngineRole",
    "LakeQueryEngine",
    "QueryName",
    "QueryResult",
    "available_engines",
    "get_engine",
]
