#!/usr/bin/env python3
"""Offline Telegram collector contracts; synthetic messages only."""
import argparse
import asyncio
from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra/scripts"))
from sync import telegram_channels as tracker


class FakeMessage:
    def __init__(self, number, text="ตัวอย่างข่าว"):
        self.id = number
        self.message = text
        self.date = datetime(2026, 9, 7, tzinfo=timezone.utc)
        self.edit_date = None
        self.media = None
        self.channel_id = -1001

    def to_json(self):
        return json.dumps({"id": self.id, "message": self.message,
                           "peer_id": self.channel_id}, ensure_ascii=False)


class FakeClient:
    def __init__(self, messages):
        self.messages = messages

    async def iter_messages(self, entity, **options):
        items = [m for m in self.messages if m.id > options.get("min_id", 0)]
        items.sort(key=lambda m: m.id, reverse=not options.get("reverse", False))
        for message in items[:options["limit"]]:
            message.channel_id = entity
            yield message


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.state_dir = self.directory / "state"
        self.lake_dir = self.directory / "lake"
        self.state = tracker.bind_state(self.state_dir, 123, self.lake_dir)
        self.config = {"channels": [-1001, -1002], "initial_limit": 2,
                       "batch_size": 2, "interval_seconds": 60}

    def collect(self, messages, channel=-1001):
        return asyncio.run(tracker.collect_channel(
            FakeClient(messages), channel, channel, self.config,
            self.state_dir, self.lake_dir, self.state))

    def test_initial_tail_then_catch_up_oldest_first_without_gaps(self):
        self.assertEqual(self.collect([FakeMessage(n) for n in range(1, 6)]), 2)
        self.assertEqual(self.state["cursors"]["-1001"], 5)
        messages = [FakeMessage(n) for n in range(1, 11)]
        self.assertEqual(self.collect(messages), 2)
        self.assertEqual(self.state["cursors"]["-1001"], 7)
        self.assertEqual(self.collect(messages), 2)
        self.assertEqual(self.collect(messages), 1)
        self.assertEqual(self.collect(messages), 0)
        self.assertEqual(self.state["cursors"]["-1001"], 10)

    def test_lake_failure_keeps_pending_and_cursor_then_recovers(self):
        with patch("data_lake.ingest.ingest_payload", side_effect=OSError("synthetic")):
            with self.assertRaises(OSError):
                self.collect([FakeMessage(1)])
        self.assertEqual(self.state["cursors"], {})
        self.assertTrue((self.state_dir / "pending.json").exists())
        tracker.commit_pending(self.state_dir, self.lake_dir, self.state)
        self.assertEqual(self.state["cursors"]["-1001"], 1)
        self.assertFalse((self.state_dir / "pending.json").exists())

    def test_crash_after_lake_write_replays_same_batch_without_duplicate(self):
        real_save = tracker.save_json

        def crash_checkpoint(path, value):
            if path.name == "checkpoint.json":
                raise OSError("simulated crash")
            real_save(path, value)

        with patch.object(tracker, "save_json", side_effect=crash_checkpoint):
            with self.assertRaises(OSError):
                self.collect([FakeMessage(1)])
        restored = tracker.bind_state(self.state_dir, 123, self.lake_dir)
        self.assertEqual(restored["cursors"], {})
        tracker.commit_pending(self.state_dir, self.lake_dir, restored)
        self.assertEqual(restored["cursors"]["-1001"], 1)
        self.assertEqual(len(list(self.lake_dir.rglob("*.parquet"))), 1)

    def test_channels_with_same_message_id_stay_separate(self):
        self.collect([FakeMessage(1)], -1001)
        self.collect([FakeMessage(1)], -1002)
        import pyarrow.parquet as pq
        rows = [row for path in self.lake_dir.rglob("*.parquet")
                for row in pq.ParquetFile(path).read().to_pylist()]
        self.assertEqual(len({row["event_id"] for row in rows}), 2)
        self.assertTrue(all(row["privacy_class"] == "private" for row in rows))

    def test_raw_sdk_json_and_checksum_preserved(self):
        message = FakeMessage(1)
        self.collect([message])
        raw = next(self.lake_dir.glob("landing/**/*.jsonl")).read_bytes()
        self.assertEqual(raw, (message.to_json() + "\n").encode())
        import hashlib
        manifest = json.loads(next(self.lake_dir.glob("control/manifests/**/*.json")).read_text())
        self.assertEqual(manifest["raw"]["sha256"], hashlib.sha256(raw).hexdigest())

    def test_empty_channel_can_receive_future_messages(self):
        self.assertEqual(self.collect([]), 0)
        self.assertEqual(self.collect([FakeMessage(2)]), 1)

    def test_changed_account_or_lake_rejected(self):
        with self.assertRaises(tracker.SetupError):
            tracker.bind_state(self.state_dir, 456, self.lake_dir)
        with self.assertRaises(tracker.SetupError):
            tracker.bind_state(self.state_dir, 123, self.directory / "other")

    def test_config_rejects_empty_duplicates_and_unbounded_limits(self):
        for update in ({"channels": []}, {"channels": [-1001, -1001]},
                       {"channels": ["@example"]}, {"batch_size": 0},
                       {"interval_seconds": 1}, {"initial_limit": True}):
            with self.subTest(update=update), self.assertRaises(tracker.SetupError):
                tracker.validate_config({**self.config, **update})

    def test_second_writer_is_rejected(self):
        with tracker.single_writer(self.state_dir):
            with self.assertRaises(tracker.SetupError):
                with tracker.single_writer(self.state_dir):
                    pass

    def test_checkpoint_private_permissions(self):
        self.assertEqual((self.state_dir / "checkpoint.json").stat().st_mode & 0o777, 0o600)

    def test_read_filters_thai_text_and_bounds_output(self):
        self.collect([FakeMessage(1, "ข่าวอื่น"), FakeMessage(2, "ข่าว AI")])
        output = io.StringIO()
        with redirect_stdout(output):
            tracker.read_posts(argparse.Namespace(keyword="ai", limit=1), self.lake_dir)
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["message_id"], 2)

    def test_setup_cannot_prompt_in_noninteractive_process(self):
        with patch("sys.stdin.isatty", return_value=False):
            with self.assertRaises(tracker.SetupError):
                tracker.require_terminal()

    def test_secret_provider_error_is_sanitized_for_noninteractive_run(self):
        with patch("_env.get_secret", side_effect=RuntimeError("private endpoint details")):
            with self.assertRaisesRegex(tracker.SetupError, "error_class=RuntimeError"):
                tracker.credentials(interactive=False)


if __name__ == "__main__":
    unittest.main()
