#!/usr/bin/env python3
"""Offline contract tests for the Redpanda/Kafka-compatible lake lane."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts"))

from data_lake.avro import read_avro  # noqa: E402
from data_lake.storage import ObjectStore  # noqa: E402
from data_lake.stream_sink import (  # noqa: E402
    StreamMessage,
    convert_avro_file,
    convert_pending,
    run_once,
)


HAS_STREAM_RUNTIME = all(
    importlib.util.find_spec(name) is not None
    for name in ("fastavro", "pyarrow")
)


class FakeConsumer:
    def __init__(self, messages: list[StreamMessage]):
        self.messages = messages
        self.commits: list[object] = []

    def poll(self, *, timeout_ms: int, max_records: int):
        del timeout_ms
        messages, self.messages = self.messages[:max_records], self.messages[max_records:]
        return messages

    def commit(self, offsets=None):
        self.commits.append(offsets)


@unittest.skipUnless(HAS_STREAM_RUNTIME, "install requirements-data-lake.txt for Avro/Parquet runtime")
class StreamLakeContractTests(unittest.TestCase):
    def test_sink_is_durable_before_commit_and_retry_is_idempotent(self):
        messages = [
            StreamMessage("events", 0, 10, {"id": "evt-10", "payload": {"value": 1}}),
            StreamMessage("events", 0, 11, {"id": "evt-11", "payload": {"value": 2}}),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            first_consumer = FakeConsumer(messages.copy())
            first = run_once(
                first_consumer,
                data_lake_uri=temp_dir,
                source="sensor",
                domain="operations",
                dataset="events",
                poll_ms=1,
                max_records=10,
            )
            self.assertEqual(first["status"], "success")
            self.assertTrue(first["committed"])
            self.assertEqual(len(first_consumer.commits), 1)

            store = ObjectStore(temp_dir)
            avro_rows = read_avro(__import__("io").BytesIO(store.get_bytes(first["avro_key"])))
            self.assertEqual(len(avro_rows), 2)
            self.assertEqual(avro_rows[0]["dataset"], "events")

            retry_consumer = FakeConsumer(messages.copy())
            retry = run_once(
                retry_consumer,
                data_lake_uri=temp_dir,
                source="sensor",
                domain="operations",
                dataset="events",
                poll_ms=1,
                max_records=10,
            )
            self.assertEqual(retry["batch_id"], first["batch_id"])
            self.assertTrue(retry["avro_existed"])
            self.assertTrue(retry["manifest_existed"])
            self.assertTrue(retry["checkpoint_existed"])
            self.assertEqual(len(retry_consumer.commits), 1)

            converted = convert_avro_file(data_lake_uri=temp_dir, avro_key=first["avro_key"])
            self.assertEqual(converted["status"], "success")
            self.assertEqual(converted["record_count"], 2)
            self.assertTrue(Path(temp_dir, converted["bronze_key"]).exists())
            converted_retry = convert_avro_file(data_lake_uri=temp_dir, avro_key=first["avro_key"])
            self.assertEqual(converted_retry["status"], "already_converted")
            pending = convert_pending(data_lake_uri=temp_dir)
            self.assertEqual(pending["status"], "healthy")
            self.assertEqual(pending["already_converted"], 1)


if __name__ == "__main__":
    unittest.main()
