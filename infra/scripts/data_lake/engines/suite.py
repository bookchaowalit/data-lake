"""Equivalence + benchmark suite for multi-engine lake queries."""

from __future__ import annotations

import concurrent.futures
import json
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from .base import (
    LakeQueryEngine,
    QueryName,
    QueryResult,
    available_engines,
    canonicalize_row,
    get_engine,
)


@dataclass
class EquivalenceReport:
    query: str
    engines: list[str]
    equivalent: bool
    reference_engine: str
    row_counts: dict[str, int]
    mismatches: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkReport:
    engine: str
    role: str
    query: str
    iterations: int
    latency_ms: list[float]
    concurrency: int
    concurrent_latency_ms: list[float] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        def stats(values: list[float]) -> dict[str, float]:
            if not values:
                return {"min": 0.0, "max": 0.0, "mean": 0.0, "p50": 0.0}
            ordered = sorted(values)
            p50 = statistics.median(ordered)
            return {
                "min": round(min(ordered), 3),
                "max": round(max(ordered), 3),
                "mean": round(statistics.mean(ordered), 3),
                "p50": round(float(p50), 3),
            }

        return {
            "engine": self.engine,
            "role": self.role,
            "query": self.query,
            "iterations": self.iterations,
            "concurrency": self.concurrency,
            "latency_ms": stats(self.latency_ms),
            "concurrent_latency_ms": stats(self.concurrent_latency_ms),
        }


def discover_bronze_parquet(
    lake_root: Path | str,
    *,
    domain: str = "market",
    dataset: str = "crypto_prices",
    schema_version: str = "1",
) -> list[Path]:
    root = Path(lake_root)
    base = (
        root
        / "bronze"
        / f"domain={domain}"
        / f"dataset={dataset}"
        / f"schema_version={schema_version}"
    )
    if not base.exists():
        return []
    return sorted(path for path in base.rglob("*.parquet") if path.is_file())


def compare_results(
    results: dict[str, QueryResult],
    *,
    reference: str = "duckdb",
) -> list[EquivalenceReport]:
    if reference not in results:
        reference = next(iter(results))
    reports: list[EquivalenceReport] = []
    ref = results[reference]
    queries = sorted({item.query for item in results.values()})
    for query_name in queries:
        by_engine = {
            engine: result
            for engine, result in results.items()
            if result.query == query_name
        }
        # When run_all is used, each engine maps to one result per call site.
        # Caller should pass flat map engine->result for one query, or we group.
    # Prefer caller passes engine -> QueryResult for a single query; also support
    # engine -> dict[query -> QueryResult]
    return reports


def compare_query_map(
    engine_results: dict[str, QueryResult],
    *,
    reference: str = "duckdb",
) -> EquivalenceReport:
    """Compare one query across engines."""
    if not engine_results:
        raise ValueError("No engine results to compare")
    if reference not in engine_results:
        reference = next(iter(engine_results))
    ref_rows = engine_results[reference].canonical_rows()
    mismatches: list[dict[str, Any]] = []
    row_counts = {name: len(result.rows) for name, result in engine_results.items()}
    equivalent = True
    for name, result in engine_results.items():
        if name == reference:
            continue
        other = result.canonical_rows()
        if other != ref_rows:
            equivalent = False
            mismatches.append(
                {
                    "engine": name,
                    "reference": reference,
                    "reference_row_count": len(ref_rows),
                    "engine_row_count": len(other),
                    "first_diff_index": _first_diff(ref_rows, other),
                    "reference_sample": ref_rows[:3],
                    "engine_sample": other[:3],
                }
            )
    return EquivalenceReport(
        query=engine_results[reference].query,
        engines=sorted(engine_results.keys()),
        equivalent=equivalent,
        reference_engine=reference,
        row_counts=row_counts,
        mismatches=mismatches,
    )


def _first_diff(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> int | None:
    limit = max(len(left), len(right))
    for idx in range(limit):
        if idx >= len(left) or idx >= len(right) or left[idx] != right[idx]:
            return idx
    return None


def run_equivalence(
    engines: Sequence[LakeQueryEngine],
    parquet_paths: Sequence[Path | str],
    *,
    reference: str = "duckdb",
) -> dict[str, Any]:
    """Load the same Bronze parts into each engine and compare all queries."""
    loaded: dict[str, int] = {}
    all_results: dict[str, dict[str, QueryResult]] = {}
    for engine in engines:
        engine.open()
        try:
            loaded[engine.name] = engine.load_bronze(parquet_paths)
            all_results[engine.name] = engine.run_all()
        finally:
            engine.close()

    reports: list[dict[str, Any]] = []
    all_ok = True
    for query in (
        QueryName.LATEST_PRICE.value,
        QueryName.FULL_HISTORY.value,
        QueryName.AGGREGATE_BY_COIN.value,
        QueryName.LINEAGE.value,
    ):
        engine_map = {
            name: results[query]
            for name, results in all_results.items()
            if query in results
        }
        report = compare_query_map(engine_map, reference=reference)
        reports.append(report.to_dict())
        all_ok = all_ok and report.equivalent

    return {
        "status": "pass" if all_ok else "fail",
        "reference_engine": reference,
        "source_of_truth": "bronze_parquet",
        "parquet_parts": [str(p) for p in parquet_paths],
        "loaded_rows": loaded,
        "queries": reports,
        "engines_available": available_engines(),
    }


def _run_one_query(engine_name: str, engine_factory, parquet_paths, query: str) -> float:
    engine = engine_factory()
    engine.open()
    try:
        engine.load_bronze(parquet_paths)
        started = time.perf_counter()
        fn = {
            QueryName.LATEST_PRICE.value: engine.latest_price,
            QueryName.FULL_HISTORY.value: engine.full_history,
            QueryName.AGGREGATE_BY_COIN.value: engine.aggregate_by_coin,
            QueryName.LINEAGE.value: engine.lineage,
        }[query]
        fn()
        return (time.perf_counter() - started) * 1000.0
    finally:
        engine.close()


def run_benchmark(
    engine_names: Sequence[str],
    parquet_paths: Sequence[Path | str],
    *,
    iterations: int = 5,
    concurrency: int = 4,
    engine_kwargs: Optional[dict[str, dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Reproducible latency/concurrency micro-benchmark (offline Bronze only)."""
    engine_kwargs = engine_kwargs or {}
    reports: list[dict[str, Any]] = []
    for name in engine_names:
        kwargs = engine_kwargs.get(name, {})

        def factory(n=name, kw=kwargs):
            return get_engine(n, **kw)

        probe = factory()
        role = probe.role.value
        for query in (
            QueryName.LATEST_PRICE.value,
            QueryName.FULL_HISTORY.value,
            QueryName.AGGREGATE_BY_COIN.value,
            QueryName.LINEAGE.value,
        ):
            sequential: list[float] = []
            for _ in range(iterations):
                sequential.append(_run_one_query(name, factory, parquet_paths, query))

            concurrent_latencies: list[float] = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = [
                    pool.submit(_run_one_query, name, factory, parquet_paths, query)
                    for _ in range(concurrency)
                ]
                for fut in concurrent.futures.as_completed(futures):
                    concurrent_latencies.append(fut.result())

            report = BenchmarkReport(
                engine=name,
                role=role,
                query=query,
                iterations=iterations,
                latency_ms=sequential,
                concurrency=concurrency,
                concurrent_latency_ms=concurrent_latencies,
            )
            reports.append(report.summary())

    return {
        "status": "ok",
        "source_of_truth": "bronze_parquet",
        "iterations": iterations,
        "concurrency": concurrency,
        "parquet_parts": [str(p) for p in parquet_paths],
        "results": reports,
    }


def results_equal(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> bool:
    return [canonicalize_row(r) for r in left] == [canonicalize_row(r) for r in right]
