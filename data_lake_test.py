#!/usr/bin/env python3
"""Offline contract tests for the Solo Empire data-lake foundation."""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts"))

from data_lake.ingest import canonical_json, ingest_payload, slug  # noqa: E402
from data_lake.query import _s3_settings, _sql_string_literal, query_parquet  # noqa: E402
from data_lake.storage import ObjectStore, StorageConflict, StorageError  # noqa: E402


class DataLakeContractTests(unittest.TestCase):
    def test_slug_rejects_path_traversal(self):
        self.assertEqual(slug("Gmail / Inbox"), "gmail-inbox")
        with self.assertRaises(ValueError):
            slug("...")

    def test_canonical_json_is_stable(self):
        self.assertEqual(canonical_json({"b": 2, "a": 1}), '{"a":1,"b":2}')

    def test_duckdb_path_literal_escapes_single_quotes(self):
        self.assertEqual(_sql_string_literal("file:///tmp/owner's-lake"), "'file:///tmp/owner''s-lake'")

    def test_duckdb_s3_settings_support_r2_path_style(self):
        with patch.dict(
            "os.environ",
            {
                "DATA_LAKE_S3_ENDPOINT": "https://account.r2.cloudflarestorage.com",
                "AWS_REGION": "auto",
                "AWS_ACCESS_KEY_ID": "test-access",
                "AWS_SECRET_ACCESS_KEY": "test-secret",
            },
            clear=False,
        ):
            settings = _s3_settings()
        self.assertEqual(settings["s3_endpoint"], "account.r2.cloudflarestorage.com")
        self.assertEqual(settings["s3_url_style"], "path")
        self.assertTrue(settings["s3_use_ssl"])
        self.assertEqual(settings["s3_region"], "auto")

    def test_windows_drive_path_is_accepted_as_local_object_store(self):
        if os.name != "nt":
            self.skipTest("Windows drive path behavior requires Windows")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ObjectStore(temp_dir)
            self.assertEqual(store.scheme, "file")
            self.assertEqual(store.root, Path(temp_dir).resolve())
            file_uri = ObjectStore(Path(temp_dir).as_uri())
            self.assertEqual(file_uri.scheme, "file")
            self.assertEqual(file_uri.root, Path(temp_dir).resolve())

    def test_local_object_store_is_immutable_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ObjectStore(temp_dir)
            first = store.put_bytes("landing/source=test/payload.json", b'{"ok":true}')
            retry = store.put_bytes("landing/source=test/payload.json", b'{"ok":true}')
            self.assertFalse(first.existed)
            self.assertTrue(retry.existed)
            self.assertEqual(retry.sha256, hashlib.sha256(b'{"ok":true}').hexdigest())
            self.assertEqual(store.get_bytes(first.key), b'{"ok":true}')
            self.assertEqual(store.list_keys("landing/source=test"), [first.key])
            with self.assertRaises(StorageConflict):
                store.put_bytes(first.key, b'{"ok":false}')

    def test_local_listing_rejects_path_traversal_prefix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ObjectStore(temp_dir)
            with self.assertRaises(StorageError):
                store.list_keys("../outside")

    def test_ingest_payload_preserves_exact_raw_bytes(self):
        try:
            import pyarrow  # noqa: F401
        except ImportError:
            self.skipTest("pyarrow not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            raw = b'{"provider":"demo","items":[{"id":"a","v":1}]}'
            result = ingest_payload(
                raw,
                [{"id": "a", "v": 1, "event_time": "2026-08-07T00:00:00Z"}],
                source="unit-test",
                domain="market",
                dataset="demo",
                data_lake_uri=temp_dir,
                input_format="json",
                event_time_field="event_time",
                privacy_class="public",
            )
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["record_count"], 1)
            stored = ObjectStore(temp_dir).get_bytes(result["raw_key"])
            self.assertEqual(stored, raw)
            self.assertTrue(result["bronze_key"].endswith(".parquet"))

    def test_ingest_resumes_after_manifest_write_failure(self):
        try:
            import pyarrow  # noqa: F401
        except ImportError:
            self.skipTest("pyarrow not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            raw = b'{"id":"resume-1"}'
            records = [{"id": "resume-1", "event_time": "2026-08-07T00:00:00Z"}]
            original_put = ObjectStore.put_bytes

            def fail_final_manifest(store, key, data, **kwargs):
                if key.startswith("control/manifests/source=resume-test/"):
                    raise StorageError("synthetic manifest outage")
                return original_put(store, key, data, **kwargs)

            with patch.object(ObjectStore, "put_bytes", fail_final_manifest), patch(
                "data_lake.ingest.utc_now", return_value="2026-08-07T00:00:00Z"
            ):
                with self.assertRaises(StorageError):
                    ingest_payload(
                        raw,
                        records,
                        source="resume-test",
                        domain="testing",
                        dataset="resume",
                        data_lake_uri=temp_dir,
                        input_format="json",
                        event_time_field="event_time",
                        privacy_class="internal",
                    )

            with patch("data_lake.ingest.utc_now", return_value="2026-08-08T00:00:00Z"):
                resumed = ingest_payload(
                    raw,
                    records,
                    source="resume-test",
                    domain="testing",
                    dataset="resume",
                    data_lake_uri=temp_dir,
                    input_format="json",
                    event_time_field="event_time",
                    privacy_class="internal",
                )

            self.assertEqual(resumed["status"], "success")
            self.assertEqual(resumed["checkpoint_existed"], True)
            self.assertTrue(resumed["raw_existed"])
            self.assertTrue(resumed["bronze_existed"])

    def test_html_landing_keeps_structured_bronze_payload(self):
        try:
            import pyarrow  # noqa: F401
        except ImportError:
            self.skipTest("pyarrow not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            raw = b"<html><body>price 100</body></html>"
            result = ingest_payload(
                raw,
                [
                    {
                        "id": "html-1",
                        "price": 100,
                        "event_time": "2026-08-07T00:00:00Z",
                    }
                ],
                source="unit-test-html",
                domain="travel",
                dataset="demo-html",
                data_lake_uri=temp_dir,
                input_format="html",
                content_type="text/html",
                event_time_field="event_time",
                privacy_class="public",
                metadata={"provider": "public_html_experimental"},
            )
            self.assertTrue(result["raw_key"].endswith(".html"))
            self.assertIn("provider=public_html_experimental", result["raw_key"])
            self.assertEqual(ObjectStore(temp_dir).get_bytes(result["raw_key"]), raw)
            rows = query_parquet(
                str(Path(temp_dir) / result["bronze_key"]),
                "SELECT payload_json, content_type FROM lake_table",
            )
            self.assertEqual(len(rows), 1)
            self.assertIn("html-1", rows[0]["payload_json"])
            self.assertEqual(rows[0]["content_type"], "text/html")

    def test_identical_provider_payloads_get_distinct_idempotent_batches(self):
        try:
            import pyarrow  # noqa: F401
        except ImportError:
            self.skipTest("pyarrow not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            raw = b"<html><body>shared public page</body></html>"
            common = dict(
                raw=raw,
                records=[{"id": "shared", "event_time": "2026-09-12T00:00:00Z"}],
                source="unit-test-provider-collision",
                domain="competition",
                dataset="source-captures",
                data_lake_uri=temp_dir,
                input_format="html",
                content_type="text/html",
                event_time_field="event_time",
                privacy_class="public",
            )
            first = ingest_payload(**common, metadata={"provider": "provider-a"})
            second = ingest_payload(**common, metadata={"provider": "provider-b"})
            retry = ingest_payload(**common, metadata={"provider": "provider-a"})

            self.assertNotEqual(first["manifest_key"], second["manifest_key"])
            self.assertNotEqual(first["bronze_key"], second["bronze_key"])
            self.assertEqual(first["run_id"], retry["run_id"])
            self.assertTrue(retry["manifest_existed"])
            self.assertEqual(
                ObjectStore(temp_dir).get_bytes(first["raw_key"]),
                ObjectStore(temp_dir).get_bytes(second["raw_key"]),
            )

    def test_same_provider_payload_retry_reuses_committed_bronze(self):
        try:
            import pyarrow  # noqa: F401
        except ImportError:
            self.skipTest("pyarrow not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            raw = b'{"provider":"time-dependent","items":[{"id":"a"}]}'
            common = dict(
                raw=raw,
                source="unit-test-time-dependent",
                domain="market",
                dataset="demo",
                data_lake_uri=temp_dir,
                input_format="json",
                event_time_field="event_time",
                privacy_class="public",
                metadata={"provider": "provider-a"},
            )
            first = ingest_payload(
                records=[{"id": "a", "event_time": "2026-09-12T00:00:00Z"}],
                **common,
            )
            retry = ingest_payload(
                records=[{"id": "a", "event_time": "2026-09-13T00:00:00Z"}],
                **common,
            )

            self.assertEqual(first["run_id"], retry["run_id"])
            self.assertTrue(retry["manifest_existed"])
            self.assertTrue(retry["bronze_existed"])
            self.assertEqual(first["bronze_key"], retry["bronze_key"])

    def test_query_parquet_reads_bronze_payload(self):
        try:
            import duckdb  # noqa: F401
            import pyarrow  # noqa: F401
        except ImportError:
            self.skipTest("duckdb/pyarrow not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            raw = b'{"id":"btc-usd","price":1}'
            result = ingest_payload(
                raw,
                [{"id": "btc-usd", "price": 1, "event_time": "2026-08-07T00:00:00Z"}],
                source="unit-test",
                domain="market",
                dataset="demo-query",
                data_lake_uri=temp_dir,
                input_format="json",
                event_time_field="event_time",
                privacy_class="public",
            )
            rows = query_parquet(
                str(Path(temp_dir) / result["bronze_key"]),
                "SELECT source_record_id, payload_json FROM lake_table",
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["source_record_id"], "btc-usd")
            self.assertIn("btc-usd", rows[0]["payload_json"])


if __name__ == "__main__":
    unittest.main()
