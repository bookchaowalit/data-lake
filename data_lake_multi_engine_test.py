#!/usr/bin/env python3
"""Offline multi-engine lake query lab tests (no CoinGecko)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts"))

from data_lake.engines.base import (  # noqa: E402
    EngineRole,
    canonicalize_row,
    get_engine,
)
from data_lake.engines.lab_runtime import optional_env_postgres  # noqa: E402
from data_lake.engines.suite import (  # noqa: E402
    discover_bronze_parquet,
    run_benchmark,
    run_equivalence,
)
from data_lake.ingest import ingest_payload  # noqa: E402
from data_lake.multi_engine_lab import seed_demo_lake  # noqa: E402


def _deps_ok() -> bool:
    try:
        import duckdb  # noqa: F401
        import pyarrow  # noqa: F401
    except ImportError:
        return False
    return True


@unittest.skipUnless(_deps_ok(), "duckdb/pyarrow required")
class MultiEngineLabTests(unittest.TestCase):
    def test_roles_and_source_of_truth_flags(self):
        duck = get_engine("duckdb")
        self.assertEqual(duck.role, EngineRole.PRODUCTION)
        ch = get_engine("clickhouse")
        self.assertEqual(ch.role, EngineRole.LAB)
        # Production API path remains DuckDB; labs are projections.
        self.assertNotEqual(ch.role, EngineRole.PRODUCTION)

    def test_seed_demo_writes_parquet_not_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            lake = Path(tmp) / "lake"
            result = seed_demo_lake(lake)
            self.assertEqual(result["status"], "seeded")
            parts = discover_bronze_parquet(lake)
            self.assertGreaterEqual(len(parts), 1)
            for part in parts:
                self.assertTrue(part.name.endswith(".parquet"))
            # No CSV as lake input.
            self.assertEqual(list(lake.rglob("*.csv")), [])

    def test_duckdb_and_clickhouse_equivalence(self):
        with tempfile.TemporaryDirectory() as tmp:
            lake = Path(tmp) / "lake"
            seed_demo_lake(lake)
            parts = discover_bronze_parquet(lake)
            engines = [get_engine("duckdb"), get_engine("clickhouse")]
            report = run_equivalence(engines, parts, reference="duckdb")
            self.assertEqual(report["status"], "pass", msg=json.dumps(report, indent=2))
            self.assertEqual(report["source_of_truth"], "bronze_parquet")
            for query in report["queries"]:
                self.assertTrue(query["equivalent"], msg=query)
                self.assertIn("duckdb", query["engines"])
                self.assertIn("clickhouse", query["engines"])

    def test_three_engines_equivalence_when_postgres_available(self):
        with optional_env_postgres() as dsn:
            if not dsn:
                self.skipTest("PostgreSQL lab DSN/docker unavailable")
            with tempfile.TemporaryDirectory() as tmp:
                lake = Path(tmp) / "lake"
                seed_demo_lake(lake)
                parts = discover_bronze_parquet(lake)
                engines = [
                    get_engine("duckdb"),
                    get_engine("postgres", dsn=dsn),
                    get_engine("clickhouse"),
                ]
                report = run_equivalence(engines, parts, reference="duckdb")
                self.assertEqual(
                    report["status"],
                    "pass",
                    msg=json.dumps(report, indent=2, default=str),
                )
                for query in report["queries"]:
                    self.assertTrue(query["equivalent"], msg=query)
                    self.assertEqual(set(query["engines"]), {"clickhouse", "duckdb", "postgres"})

    def test_benchmark_reproducible_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            lake = Path(tmp) / "lake"
            seed_demo_lake(lake)
            parts = discover_bronze_parquet(lake)
            report = run_benchmark(
                ["duckdb", "clickhouse"],
                parts,
                iterations=2,
                concurrency=2,
            )
            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["source_of_truth"], "bronze_parquet")
            # 2 engines * 4 queries
            self.assertEqual(len(report["results"]), 8)
            sample = report["results"][0]
            self.assertIn("latency_ms", sample)
            self.assertIn("mean", sample["latency_ms"])
            self.assertIn("concurrent_latency_ms", sample)

    def test_latest_price_picks_newer_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            lake = Path(tmp) / "lake"
            seed_demo_lake(lake)
            parts = discover_bronze_parquet(lake)
            engine = get_engine("duckdb")
            engine.open()
            try:
                engine.load_bronze(parts)
                latest = engine.latest_price()
            finally:
                engine.close()
            btc_usd = [
                row
                for row in latest.rows
                if row["source_record_id"] == "bitcoin:usd"
            ]
            self.assertEqual(len(btc_usd), 1)
            self.assertEqual(btc_usd[0]["price"], 51000.0)

    def test_lineage_includes_raw_object_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            lake = Path(tmp) / "lake"
            seed_demo_lake(lake)
            parts = discover_bronze_parquet(lake)
            for name in ("duckdb", "clickhouse"):
                engine = get_engine(name)
                engine.open()
                try:
                    engine.load_bronze(parts)
                    lin = engine.lineage()
                finally:
                    engine.close()
                self.assertGreater(len(lin.rows), 0)
                for row in lin.rows:
                    self.assertTrue(str(row["raw_object_key"]).startswith("landing/"))
                    self.assertTrue(row["ingest_run_id"])
                    self.assertTrue(row["event_id"])

    def test_canonicalize_stable(self):
        a = canonicalize_row({"price": 1.0000004, "coin_id": "bitcoin", "event_count": 2})
        b = canonicalize_row({"event_count": 2, "coin_id": "bitcoin", "price": 1.0000001})
        self.assertEqual(a["price"], b["price"])
        self.assertEqual(a["event_count"], 2)

    def test_ingest_payload_is_shared_input(self):
        """Ensure engines never require CSV — only Parquet from ingest_payload."""
        with tempfile.TemporaryDirectory() as tmp:
            lake = Path(tmp) / "lake"
            raw = b'{"bitcoin":{"usd":1}}'
            records = [
                {
                    "id": "bitcoin:usd",
                    "coin_id": "bitcoin",
                    "currency": "usd",
                    "price": 1,
                    "event_time": "2026-08-07T00:00:00Z",
                }
            ]
            result = ingest_payload(
                raw,
                records,
                source="book-crypto-data",
                domain="market",
                dataset="crypto_prices",
                data_lake_uri=str(lake),
                input_format="json",
                event_time_field="event_time",
                privacy_class="public",
            )
            self.assertTrue(result["bronze_key"].endswith(".parquet"))
            self.assertTrue(result["raw_key"].startswith("landing/"))
            parts = discover_bronze_parquet(lake)
            engine = get_engine("duckdb")
            engine.open()
            try:
                count = engine.load_bronze(parts)
            finally:
                engine.close()
            self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
