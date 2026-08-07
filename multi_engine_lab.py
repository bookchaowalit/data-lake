#!/usr/bin/env python3
"""Multi-engine lake query lab CLI.

Proves that Bronze Parquet is the shared hub: DuckDB (production), PostgreSQL
(lab projection), and ClickHouse (lab projection) answer the same questions.

Usage:
  python3 multi_engine_lab.py status
  python3 multi_engine_lab.py equivalence --lake-root /path/to/data/lake
  python3 multi_engine_lab.py benchmark --lake-root /path/to/data/lake --json
  python3 multi_engine_lab.py seed-demo --lake-root /tmp/lake-demo
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_lake.engines.base import available_engines, get_engine  # type: ignore
from data_lake.engines.lab_runtime import optional_env_postgres  # type: ignore
from data_lake.engines.suite import (  # type: ignore
    discover_bronze_parquet,
    run_benchmark,
    run_equivalence,
)


def _print(data: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    else:
        if isinstance(data, dict):
            print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        else:
            print(data)


def seed_demo_lake(lake_root: Path) -> dict[str, Any]:
    """Write a tiny offline Bronze dataset (no CoinGecko)."""
    from data_lake.ingest import ingest_payload  # type: ignore

    sample = {
        "bitcoin": {
            "usd": 50000.0,
            "usd_24h_change": 2.5,
            "usd_24h_vol": 1e9,
            "usd_market_cap": 1e12,
            "thb": 1800000.0,
            "thb_24h_change": 1.1,
            "thb_24h_vol": 1e8,
            "thb_market_cap": 3e13,
            "last_updated_at": 1720000000,
        },
        "ethereum": {
            "usd": 3000.0,
            "usd_24h_change": -1.2,
            "usd_24h_vol": 5e8,
            "usd_market_cap": 3e11,
            "thb": 108000.0,
            "thb_24h_change": -0.5,
            "thb_24h_vol": 5e7,
            "thb_market_cap": 1e13,
            "last_updated_at": 1720000001,
        },
    }
    records = []
    for coin_id, info in sample.items():
        for curr in ("usd", "thb"):
            records.append(
                {
                    "id": f"{coin_id}:{curr}",
                    "coin_id": coin_id,
                    "currency": curr,
                    "price": info.get(curr, ""),
                    "change_24h_pct": round(info.get(f"{curr}_24h_change", 0) or 0, 2),
                    "volume_24h": info.get(f"{curr}_24h_vol", ""),
                    "market_cap": info.get(f"{curr}_market_cap", ""),
                    "event_time": "2026-08-07T00:00:00Z",
                }
            )
    # Second batch with newer event_time so latest_price is non-trivial.
    records_v2 = []
    for row in records:
        newer = dict(row)
        if row["coin_id"] == "bitcoin" and row["currency"] == "usd":
            newer["price"] = 51000.0
            newer["event_time"] = "2026-08-07T01:00:00Z"
        records_v2.append(newer)

    raw1 = json.dumps(sample, separators=(",", ":")).encode("utf-8")
    r1 = ingest_payload(
        raw1,
        records,
        source="book-crypto-data",
        domain="market",
        dataset="crypto_prices",
        data_lake_uri=str(lake_root),
        input_format="json",
        event_time_field="event_time",
        privacy_class="public",
        metadata={"lab": "multi-engine", "batch": 1},
    )
    sample2 = json.loads(raw1)
    sample2["bitcoin"]["usd"] = 51000.0
    raw2 = json.dumps(sample2, separators=(",", ":")).encode("utf-8")
    r2 = ingest_payload(
        raw2,
        records_v2,
        source="book-crypto-data",
        domain="market",
        dataset="crypto_prices",
        data_lake_uri=str(lake_root),
        input_format="json",
        event_time_field="event_time",
        privacy_class="public",
        metadata={"lab": "multi-engine", "batch": 2},
    )
    parts = discover_bronze_parquet(lake_root)
    return {
        "status": "seeded",
        "lake_root": str(lake_root),
        "ingest_runs": [r1.get("run_id"), r2.get("run_id")],
        "parquet_parts": [str(p) for p in parts],
        "note": "Offline synthetic CoinGecko-shaped payload; no network.",
    }


def cmd_status(_: argparse.Namespace) -> int:
    _print(
        {
            "source_of_truth": "bronze_parquet",
            "production_engine": "duckdb",
            "lab_engines": ["postgres", "clickhouse"],
            "engines": available_engines(),
        },
        as_json=True,
    )
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    lake_root = Path(args.lake_root)
    lake_root.mkdir(parents=True, exist_ok=True)
    result = seed_demo_lake(lake_root)
    _print(result, args.as_json)
    return 0


def cmd_equivalence(args: argparse.Namespace) -> int:
    lake_root = Path(args.lake_root)
    parts = discover_bronze_parquet(
        lake_root,
        domain=args.domain,
        dataset=args.dataset,
        schema_version=args.schema_version,
    )
    if not parts:
        print(
            f"ERROR: no Bronze Parquet under {lake_root} "
            f"(domain={args.domain} dataset={args.dataset})",
            file=sys.stderr,
        )
        return 2

    engines = []
    engine_kwargs: dict[str, dict[str, Any]] = {}
    names = [n.strip() for n in args.engines.split(",") if n.strip()]

    pg_cm = None
    if "postgres" in names:
        pg_cm = optional_env_postgres()
        dsn = pg_cm.__enter__()
        if not dsn:
            print(
                "ERROR: postgres requested but LAKE_LAB_POSTGRES_DSN unset "
                "and docker ephemeral runtime unavailable",
                file=sys.stderr,
            )
            return 2
        engine_kwargs["postgres"] = {"dsn": dsn}

    try:
        for name in names:
            engines.append(get_engine(name, **engine_kwargs.get(name, {})))
        report = run_equivalence(engines, parts, reference=args.reference)
        _print(report, args.as_json or True)
        return 0 if report.get("status") == "pass" else 1
    finally:
        if pg_cm is not None:
            pg_cm.__exit__(None, None, None)


def cmd_benchmark(args: argparse.Namespace) -> int:
    lake_root = Path(args.lake_root)
    parts = discover_bronze_parquet(
        lake_root,
        domain=args.domain,
        dataset=args.dataset,
        schema_version=args.schema_version,
    )
    if not parts:
        print(f"ERROR: no Bronze Parquet under {lake_root}", file=sys.stderr)
        return 2

    names = [n.strip() for n in args.engines.split(",") if n.strip()]
    engine_kwargs: dict[str, dict[str, Any]] = {}
    pg_cm = None
    if "postgres" in names:
        pg_cm = optional_env_postgres()
        dsn = pg_cm.__enter__()
        if not dsn:
            print("ERROR: postgres unavailable for benchmark", file=sys.stderr)
            return 2
        engine_kwargs["postgres"] = {"dsn": dsn}

    try:
        report = run_benchmark(
            names,
            parts,
            iterations=args.iterations,
            concurrency=args.concurrency,
            engine_kwargs=engine_kwargs,
        )
        _print(report, args.as_json or True)
        return 0
    finally:
        if pg_cm is not None:
            pg_cm.__exit__(None, None, None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    json_flag = argparse.ArgumentParser(add_help=False)
    json_flag.add_argument("--json", action="store_true", dest="as_json")

    p_status = sub.add_parser("status", parents=[json_flag], help="List engines and roles")
    p_status.set_defaults(func=cmd_status, as_json=True)

    p_seed = sub.add_parser(
        "seed-demo", parents=[json_flag], help="Seed offline Bronze demo dataset"
    )
    p_seed.add_argument("--lake-root", required=True)
    p_seed.set_defaults(func=cmd_seed)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--lake-root", required=True)
    common.add_argument("--domain", default="market")
    common.add_argument("--dataset", default="crypto_prices")
    common.add_argument("--schema-version", default="1")
    common.add_argument(
        "--engines",
        default="duckdb,postgres,clickhouse",
        help="Comma-separated engine names",
    )
    common.add_argument("--json", action="store_true", dest="as_json")

    p_eq = sub.add_parser("equivalence", parents=[common], help="Compare query results")
    p_eq.add_argument("--reference", default="duckdb")
    p_eq.set_defaults(func=cmd_equivalence)

    p_bench = sub.add_parser("benchmark", parents=[common], help="Latency/concurrency lab")
    p_bench.add_argument("--iterations", type=int, default=5)
    p_bench.add_argument("--concurrency", type=int, default=4)
    p_bench.set_defaults(func=cmd_benchmark)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
