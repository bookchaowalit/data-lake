#!/usr/bin/env python3
"""Offline contracts for the Telegram personal manager."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra/scripts"))

from sync import telegram_personal as manager  # noqa: E402


class FakeSender:
    def __init__(self):
        self.calls = []

    async def send_message(self, chat_id, text):
        self.calls.append((chat_id, text))
        return {"id": 999}


class FailingSender:
    async def send_message(self, chat_id, text):
        raise RuntimeError("private telegram response body")


class FakeMessage:
    def __init__(self, number, text):
        self.id = number
        self.message = text
        self.date = datetime(2026, 9, 13, 10, number, tzinfo=timezone.utc)
        self.edit_date = None
        self.media = None
        self.out = False

    def to_json(self):
        return json.dumps({"id": self.id, "message": self.message}, ensure_ascii=False)


class FakeDialog:
    def __init__(self, chat_id, messages):
        self.id = chat_id
        self.entity = chat_id
        self.name = "Synthetic chat"
        self.kind = "private"
        self.messages = messages


class FakeClient:
    def __init__(self, dialogs, *, bot=False):
        self.dialogs = dialogs
        self.me = type("Me", (), {"id": 7001, "bot": bot})()

    async def get_me(self):
        return self.me

    async def iter_dialogs(self):
        for dialog in self.dialogs:
            yield dialog

    async def iter_messages(self, entity, **options):
        dialog = next(dialog for dialog in self.dialogs if dialog.id == entity)
        cursor = options.get("min_id", 0)
        rows = [message for message in dialog.messages if message.id > cursor]
        rows = rows[: options["limit"]]
        for message in rows:
            yield message


class PersonalManagerTests(unittest.TestCase):
    def test_config_defaults_and_bounds(self):
        config = manager.validate_config({})
        self.assertEqual(config["max_dialogs"], 100)
        self.assertEqual(config["initial_limit"], 50)
        with self.assertRaises(manager.SetupError):
            manager.validate_config({"max_dialogs": 0})
        with self.assertRaises(manager.SetupError):
            manager.validate_config({"batch_size": 1001})

    def test_single_writer_creates_private_lock_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir) / "state"
            with manager.single_writer(directory):
                self.assertEqual((directory / "manager.lock").stat().st_mode & 0o777, 0o600)

    def test_classification_prioritizes_explicit_urgent_and_mentions(self):
        self.assertEqual(manager.classify_message("ด่วน ต้องส่งวันนี้"), "urgent")
        self.assertEqual(manager.classify_message("ช่วยดูให้หน่อย", mentions_me=True), "important")
        self.assertEqual(manager.classify_message("อัปเดตทั่วไป", is_outgoing=True), "low")
        self.assertEqual(manager.classify_message("สวัสดีครับ"), "normal")

    def test_draft_is_deterministic_and_does_not_send(self):
        result = manager.build_draft({"id": "42", "text": "ขออัปเดตงานวันนี้"})
        self.assertEqual(result["source_message_id"], "42")
        self.assertEqual(result["status"], "draft")
        self.assertIn("ตรวจสอบ", result["text"])

    def test_brief_groups_priority_counts_and_action_rows(self):
        result = manager.build_brief([
            {"id": "1", "priority": "urgent", "text": "ด่วน"},
            {"id": "2", "priority": "important", "text": "ช่วยดู"},
            {"id": "3", "priority": "normal", "text": "ข่าว"},
        ])
        self.assertEqual(result["counts"]["urgent"], 1)
        self.assertEqual(result["counts"]["important"], 1)
        self.assertEqual([row["id"] for row in result["action_required"]], ["1", "2"])

    def test_approval_requires_exact_target_and_text_then_can_be_consumed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            now = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
            approval = manager.create_approval(
                state_dir,
                chat_id=-1001,
                message_id=42,
                text="ตอบกลับครับ",
                ttl_seconds=900,
                now=now,
            )
            verified = manager.verify_approval(
                state_dir,
                approval["approval_id"],
                chat_id=-1001,
                text="ตอบกลับครับ",
                now=now + timedelta(seconds=10),
            )
            self.assertEqual(verified["status"], "pending")
            with self.assertRaisesRegex(manager.ApprovalError, "approval_target_mismatch"):
                manager.verify_approval(
                    state_dir,
                    approval["approval_id"],
                    chat_id=-1002,
                    text="ตอบกลับครับ",
                    now=now + timedelta(seconds=10),
                )
            with self.assertRaisesRegex(manager.ApprovalError, "approval_text_mismatch"):
                manager.verify_approval(
                    state_dir,
                    approval["approval_id"],
                    chat_id=-1001,
                    text="ข้อความอื่น",
                    now=now + timedelta(seconds=10),
                )
            with self.assertRaisesRegex(manager.ApprovalError, "approval_expired"):
                manager.verify_approval(
                    state_dir,
                    approval["approval_id"],
                    chat_id=-1001,
                    text="ตอบกลับครับ",
                    now=now + timedelta(seconds=901),
                )

    def test_send_requires_approval_and_marks_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            approval = manager.create_approval(
                state_dir,
                chat_id=17,
                message_id=3,
                text="อนุมัติแล้ว",
                now=datetime.now(timezone.utc),
            )
            sender = FakeSender()
            result = asyncio.run(manager.send_approved(
                sender,
                state_dir,
                approval["approval_id"],
                chat_id=17,
                text="อนุมัติแล้ว",
            ))
            self.assertEqual(result["status"], "sent")
            self.assertEqual(sender.calls, [(17, "อนุมัติแล้ว")])
            with self.assertRaisesRegex(manager.ApprovalError, "approval_already_used"):
                asyncio.run(manager.send_approved(
                    sender, state_dir, approval["approval_id"], chat_id=17, text="อนุมัติแล้ว"
                ))

    def test_send_failure_keeps_retryable_approval_with_safe_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            approval = manager.create_approval(
                state_dir, chat_id=17, message_id=3, text="ส่งไม่สำเร็จ",
            )
            with self.assertRaisesRegex(manager.TelegramDeliveryError, "telegram_send_failed"):
                asyncio.run(manager.send_approved(
                    FailingSender(), state_dir, approval["approval_id"], chat_id=17, text="ส่งไม่สำเร็จ"
                ))
            stored = json.loads((state_dir / manager.APPROVALS_FILE).read_text())[0]
            self.assertEqual(stored["status"], "pending")
            self.assertEqual(stored["last_error"], "telegram_send_failed")

    def test_credentials_provider_failure_is_sanitized(self):
        with patch("_env.get_secret", side_effect=RuntimeError("private endpoint details")):
            with self.assertRaisesRegex(manager.SetupError, "telegram_api_credentials_missing"):
                manager._credentials(interactive=False)

    def test_search_filters_priority_and_keyword_from_local_jsonl(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            lake_dir = Path(temp_dir)
            path = lake_dir / "landing" / "messages.jsonl"
            path.parent.mkdir(parents=True)
            rows = [
                {"id": "1", "chat_id": 10, "message_id": 1, "date": "2026-09-13T10:00:00Z", "text": "ด่วน: ใบเสนอราคา", "priority": "urgent"},
                {"id": "2", "chat_id": 10, "message_id": 2, "date": "2026-09-13T11:00:00Z", "text": "ทั่วไป", "priority": "normal"},
            ]
            path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
            found = manager.search_messages(lake_dir, keyword="ใบเสนอ", priority="urgent", limit=5)
            self.assertEqual([row["id"] for row in found], ["1"])

    def test_search_ignores_unstructured_landing_rows_when_chat_filter_is_used(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "landing" / "raw.jsonl"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"id": 9, "message": "raw payload"}) + "\n")
            self.assertEqual(manager.search_messages(Path(temp_dir), chat_id=17, limit=5), [])

    def test_sync_once_ingests_bounded_dialogs_and_advances_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dialog = FakeDialog(77, [FakeMessage(1, "ด่วน"), FakeMessage(2, "อัปเดต")])
            result = asyncio.run(manager.sync_once(
                FakeClient([dialog]),
                config={"max_dialogs": 1, "initial_limit": 1, "batch_size": 1, "interval_seconds": 60, "dialog_ids": []},
                state_dir=root / "state",
                lake_dir=root / "lake",
            ))
            self.assertEqual(result["collected"], 1)
            checkpoint = json.loads((root / "state" / manager.CHECKPOINT_FILE).read_text())
            self.assertEqual(checkpoint["cursors"]["77"], 1)
            found = manager.search_messages(root / "lake", limit=10)
            self.assertEqual(len(found), 1)

    def test_sync_once_rejects_bot_accounts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(manager.SetupError, "telegram_user_account_required"):
                asyncio.run(manager.sync_once(
                    FakeClient([], bot=True),
                    config=manager.DEFAULT_CONFIG,
                    state_dir=Path(temp_dir) / "state",
                    lake_dir=Path(temp_dir) / "lake",
                ))


if __name__ == "__main__":
    unittest.main()
