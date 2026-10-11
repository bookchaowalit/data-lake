#!/usr/bin/env python3
"""Tests for the deterministic Bronze → Silver job pilot."""

from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts"))
from data_lake.workspace import OWNER_ROOT  # noqa: E402

PRODUCT_SOURCE_ROOTS = (
    OWNER_ROOT / "public/book-products/book-crypto-data/src/book_crypto",
    OWNER_ROOT / "public/book-products/book-stock-data/src/book_stock",
    OWNER_ROOT / "public/book-products/book-fx-data/src/book_fx",
)

from data_lake.ingest import ingest_payload  # noqa: E402
from data_lake.query import query_parquet  # noqa: E402
from data_lake.silver import (  # noqa: E402
    SilverProductContract,
    SilverQualityError,
    normalize_fx_row,
    transform_bronze_to_silver,
)
from data_lake.silver_parity_evidence import run_evidence  # noqa: E402
from data_lake.storage import ObjectStore  # noqa: E402


class SilverTests(unittest.TestCase):
    def setUp(self):
        try:
            import duckdb  # noqa: F401
            import pyarrow  # noqa: F401
        except ImportError:
            self.skipTest("duckdb/pyarrow not installed")

    def test_job_bronze_to_silver_is_deduplicated_lineaged_and_replayable(self):
        with tempfile.TemporaryDirectory() as root:
            raw = b"fixture-job-capture"
            ingest_payload(
                raw,
                [
                    {
                        "id": "job-1",
                        "title": "Old title",
                        "company": "Old Co",
                        "url": "https://example.com/jobs/1?utm_source=test",
                        "event_time": "2026-08-08T00:00:00Z",
                        "provider": "fixture",
                    },
                    {
                        "id": "job-1",
                        "title": "New title",
                        "company": "New Co",
                        "url": "https://example.com/jobs/1?utm_source=test",
                        "event_time": "2026-08-08T01:00:00Z",
                        "provider": "fixture",
                    },
                    {
                        "id": "job-2",
                        "title": "Second title",
                        "company": "Demo Co",
                        "url": "https://example.com/jobs/2",
                        "event_time": "2026-08-08T01:00:00Z",
                        "provider": "fixture",
                    },
                ],
                source="book-job-data",
                domain="jobs",
                dataset="job_postings",
                data_lake_uri=root,
                input_format="text",
                event_time_field="event_time",
                privacy_class="internal",
            )
            contract = SilverProductContract()
            first = transform_bronze_to_silver(contract, data_lake_uri=root)
            second = transform_bronze_to_silver(contract, data_lake_uri=root)
            self.assertEqual(first["record_count"], 2)
            self.assertEqual(first["duplicate_count"], 1)
            self.assertEqual(first["silver_run_id"], second["silver_run_id"])
            self.assertTrue(second["silver_existed"])
            self.assertTrue(second["manifest_existed"])
            self.assertEqual(first["lineage"]["record_count"], 3)
            rows = query_parquet(
                str(Path(root) / first["silver_key"]),
                "SELECT record_id, title, company, canonical_url, quality_status FROM lake_table ORDER BY record_id",
            )
            self.assertEqual(rows[0]["title"], "New title")
            self.assertEqual(rows[0]["company"], "New Co")
            self.assertEqual(rows[0]["canonical_url"], "https://example.com/jobs/1")
            self.assertTrue(all(row["quality_status"] == "valid" for row in rows))
            lineage_row = query_parquet(
                str(Path(root) / first["silver_key"]),
                "SELECT privacy_class, retention_class, raw_sha256 FROM lake_table LIMIT 1",
            )[0]
            self.assertEqual(lineage_row["privacy_class"], "internal")
            self.assertEqual(lineage_row["retention_class"], "operational")
            self.assertTrue(lineage_row["raw_sha256"])
            manifest = __import__("json").loads(
                ObjectStore(root).get_bytes(first["manifest_key"])
            )
            self.assertEqual(manifest["quality"]["status"], "passed")
            self.assertEqual(manifest["silver"]["key"], first["silver_key"])

    def test_quality_failure_is_fail_closed_before_silver_write(self):
        with tempfile.TemporaryDirectory() as root:
            ingest_payload(
                b"invalid-job",
                [{"id": "bad-1", "company": "No title or URL", "event_time": "2026-08-08T00:00:00Z"}],
                source="book-job-data",
                domain="jobs",
                dataset="job_postings",
                data_lake_uri=root,
                input_format="text",
                event_time_field="event_time",
                privacy_class="internal",
            )
            with self.assertRaises(SilverQualityError):
                transform_bronze_to_silver(data_lake_uri=root)
            self.assertEqual(ObjectStore(root).list_keys("silver/"), [])
            self.assertEqual(ObjectStore(root).list_keys("control/manifests/silver/"), [])

    def test_fx_quality_rejects_non_finite_rates(self):
        for value in ("NaN", "Infinity", "-Infinity"):
            _row, errors = normalize_fx_row(
                {
                    "source_record_id": "fx-1",
                    "payload_json": json.dumps(
                        {"base": "USD", "quote": "THB", "rate": value}
                    ),
                },
                silver_run_id="fixture",
            )
            self.assertIn("rate must be finite", errors)

    def test_crypto_contract_reuses_shared_writer_with_domain_schema(self):
        with tempfile.TemporaryDirectory() as root:
            ingest_payload(
                b'{"bitcoin":{"usd":65000},"ethereum":{"usd":3200}}',
                [
                    {
                        "id": "bitcoin:usd",
                        "coin_id": "bitcoin",
                        "currency": "usd",
                        "price": 65000,
                        "change_24h_pct": 1.2,
                        "volume_24h": 1000,
                        "market_cap": "1e12",
                        "event_time": "2026-08-08T00:00:00Z",
                        "last_updated_at": 1786147200,
                    },
                    {
                        "id": "ethereum:usd",
                        "coin_id": "ethereum",
                        "currency": "usd",
                        "price": 3200,
                        "change_24h_pct": -0.5,
                        "volume_24h": 500,
                        "market_cap": "4e11",
                        "event_time": "2026-08-08T00:00:00Z",
                        "last_updated_at": 1786147200,
                    },
                ],
                source="book-crypto-data",
                domain="market",
                dataset="crypto_prices",
                data_lake_uri=root,
                input_format="json",
                event_time_field="event_time",
                privacy_class="public",
            )
            contract = SilverProductContract(
                source="book-crypto-data",
                domain="market",
                bronze_dataset="crypto_prices",
                silver_dataset="crypto_prices",
                product_schema_version="crypto.silver.v1",
                bronze_product_schema_version="crypto.v1",
                transform_version="crypto-prices-silver.v1",
                normalizer="crypto_prices",
                privacy_class="public",
                required_fields=("source_record_id", "coin_id", "currency", "price"),
            )
            result = transform_bronze_to_silver(contract, data_lake_uri=root)
            rows = query_parquet(
                str(Path(root) / result["silver_key"]),
                "SELECT coin_id, currency, price, quality_status FROM lake_table ORDER BY coin_id",
            )
            self.assertEqual(result["record_count"], 2)
            self.assertEqual(rows[0]["coin_id"], "bitcoin")
            self.assertEqual(rows[0]["price"], "65000")
            self.assertEqual(rows[1]["coin_id"], "ethereum")
            self.assertTrue(all(row["quality_status"] == "valid" for row in rows))
            self.assertEqual(result["quality"]["required_fields"], ["source_record_id", "coin_id", "currency", "price"])

    def _ohlcv_record(self, open_ms, *, high="101", low="99"):
        return {
            "id": f"binance_futures:BTCUSDT:1h:{open_ms}",
            "venue": "binance_futures",
            "symbol": "BTCUSDT",
            "interval": "1h",
            "open_time_ms": open_ms,
            "close_time_ms": open_ms + 3_599_999,
            "open": "100",
            "high": high,
            "low": low,
            "close": "100.5",
            "volume": "12.5",
            "quote_volume": "1250",
            "trades": 0,
            "event_time": "2026-08-08T00:00:00Z",
        }

    def _ohlcv_contract(self):
        return SilverProductContract(
            source="book-crypto-data",
            domain="market",
            bronze_dataset="crypto_ohlcv",
            silver_dataset="crypto_ohlcv",
            product_schema_version="crypto-ohlcv.silver.v1",
            bronze_product_schema_version="crypto.v1",
            transform_version="crypto-ohlcv-silver.v1",
            normalizer="crypto_ohlcv",
            privacy_class="public",
            required_fields=("source_record_id", "symbol", "interval", "open_time_ms"),
        )

    def test_crypto_ohlcv_bars_are_deduplicated_and_typed(self):
        with tempfile.TemporaryDirectory() as root:
            for _ in range(2):  # the same closed bars captured twice
                ingest_payload(
                    b"[[1786147200000]]",
                    [self._ohlcv_record(1786147200000), self._ohlcv_record(1786150800000)],
                    source="book-crypto-data",
                    domain="market",
                    dataset="crypto_ohlcv",
                    data_lake_uri=root,
                    input_format="json",
                    event_time_field="event_time",
                    privacy_class="public",
                )
            result = transform_bronze_to_silver(self._ohlcv_contract(), data_lake_uri=root)
            rows = query_parquet(
                str(Path(root) / result["silver_key"]),
                "SELECT symbol, open_time_ms, high, trades, quality_status FROM lake_table ORDER BY open_time_ms",
            )
            self.assertEqual(result["record_count"], 2)
            self.assertEqual(rows[0]["open_time_ms"], "1786147200000")
            self.assertEqual(rows[0]["trades"], "0")
            self.assertTrue(all(row["quality_status"] == "valid" for row in rows))

    def test_crypto_ohlcv_rejects_inconsistent_high_low(self):
        with tempfile.TemporaryDirectory() as root:
            ingest_payload(
                b"[[1786147200000]]",
                [self._ohlcv_record(1786147200000, high="99.9")],
                source="book-crypto-data",
                domain="market",
                dataset="crypto_ohlcv",
                data_lake_uri=root,
                input_format="json",
                event_time_field="event_time",
                privacy_class="public",
            )
            with self.assertRaises(SilverQualityError):
                transform_bronze_to_silver(self._ohlcv_contract(), data_lake_uri=root)
            self.assertFalse((Path(root) / "silver").exists())

    def test_stock_contract_reuses_shared_writer_with_market_quality_rules(self):
        with tempfile.TemporaryDirectory() as root:
            ingest_payload(
                b'{"symbol":"AAPL","price":225.5}',
                [
                    {
                        "id": "AAPL",
                        "symbol": "aapl",
                        "price": 225.5,
                        "prev_close": 224.0,
                        "change": 1.5,
                        "change_pct": 0.67,
                        "currency": "usd",
                        "exchange": "NASDAQ",
                        "timestamp": "2026-08-08T00:00:00Z",
                        "event_time": "2026-08-08T00:00:00Z",
                    }
                ],
                source="book-stock-data",
                domain="market",
                dataset="stock_prices",
                data_lake_uri=root,
                input_format="json",
                event_time_field="event_time",
                privacy_class="public",
            )
            contract = SilverProductContract(
                source="book-stock-data",
                domain="market",
                bronze_dataset="stock_prices",
                silver_dataset="stock_prices",
                product_schema_version="stock.silver.v1",
                bronze_product_schema_version="stock.v1",
                transform_version="stock-prices-silver.v1",
                normalizer="stock_prices",
                privacy_class="public",
                required_fields=("source_record_id", "symbol", "price", "currency"),
            )
            result = transform_bronze_to_silver(contract, data_lake_uri=root)
            rows = query_parquet(
                str(Path(root) / result["silver_key"]),
                "SELECT symbol, price, currency, exchange, quality_status FROM lake_table",
            )
            self.assertEqual(result["record_count"], 1)
            self.assertEqual(rows[0]["symbol"], "AAPL")
            self.assertEqual(rows[0]["price"], "225.5")
            self.assertEqual(rows[0]["currency"], "USD")
            self.assertEqual(rows[0]["exchange"], "NASDAQ")
            self.assertEqual(rows[0]["quality_status"], "valid")

    def test_fx_contract_reuses_shared_writer_with_positive_rate_rules(self):
        with tempfile.TemporaryDirectory() as root:
            ingest_payload(
                b'{"base":"THB","date":"2026-08-08","rates":{"USD":0.028,"EUR":0.026}}',
                [
                    {
                        "id": "THB:USD",
                        "base": "thb",
                        "currency": "usd",
                        "rate": 0.028,
                        "inverse": 35.714286,
                        "date": "2026-08-08",
                        "event_time": "2026-08-08T00:00:00Z",
                    },
                    {
                        "id": "THB:EUR",
                        "base": "THB",
                        "currency": "EUR",
                        "rate": 0.026,
                        "inverse": 38.461538,
                        "date": "2026-08-08",
                        "event_time": "2026-08-08T00:00:00Z",
                    },
                ],
                source="book-fx-data",
                domain="market",
                dataset="exchange_rates",
                data_lake_uri=root,
                input_format="json",
                event_time_field="event_time",
                privacy_class="public",
            )
            contract = SilverProductContract(
                source="book-fx-data",
                domain="market",
                bronze_dataset="exchange_rates",
                silver_dataset="exchange_rates",
                product_schema_version="fx.silver.v1",
                bronze_product_schema_version="fx.v1",
                transform_version="fx-rates-silver.v1",
                normalizer="fx_rates",
                privacy_class="public",
                required_fields=("source_record_id", "base_currency", "quote_currency", "rate"),
            )
            result = transform_bronze_to_silver(contract, data_lake_uri=root)
            replay = transform_bronze_to_silver(contract, data_lake_uri=root)
            rows = query_parquet(
                str(Path(root) / result["silver_key"]),
                "SELECT base_currency, quote_currency, rate, inverse_rate, quality_status FROM lake_table ORDER BY quote_currency",
            )
            self.assertEqual(result["record_count"], 2)
            self.assertEqual(result["silver_run_id"], replay["silver_run_id"])
            self.assertEqual(rows[0]["base_currency"], "THB")
            self.assertEqual(rows[0]["quote_currency"], "EUR")
            self.assertEqual(rows[0]["rate"], "0.026")
            self.assertEqual(rows[1]["quote_currency"], "USD")
            self.assertTrue(all(row["quality_status"] == "valid" for row in rows))

    def test_offline_api_parity_evidence_covers_crypto_stock_and_fx(self):
        if not all(path.is_dir() for path in PRODUCT_SOURCE_ROOTS):
            self.skipTest(
                "nested product source repos are not present in this root checkout"
            )
        report = run_evidence()
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["network"], "not-used")
        self.assertEqual(report["csv"], "not-used-as-source")
        self.assertEqual(
            [item["product"] for item in report["products"]],
            ["crypto", "stock", "fx"],
        )
        self.assertTrue(all(item["status"] == "passed" for item in report["products"]))


if __name__ == "__main__":
    unittest.main()
