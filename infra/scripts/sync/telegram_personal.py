#!/usr/bin/env python3
"""Private Telegram user-account manager with an explicit send gate.

This integration uses a Telegram *user* session through Telethon.  It is a
local assistant boundary: sync/read/search/draft are separate from outbound
actions, and sending requires an unexpired approval record whose target and
exact text match the command.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import getpass
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile
from typing import Any, AsyncIterator, Iterable

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra/scripts"))
sys.path.insert(0, str(ROOT / "infra/scripts/utils"))

STATE_DIR = Path.home() / ".local/state/solo-empire/telegram-personal"
LAKE_DIR = ROOT / "data/lake/telegram-personal"
CONFIG_FILE = "config.json"
CHECKPOINT_FILE = "checkpoint.json"
PENDING_FILE = "pending.json"
APPROVALS_FILE = "approvals.json"
DRAFTS_FILE = "drafts.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "max_dialogs": 100,
    "initial_limit": 50,
    "batch_size": 100,
    "interval_seconds": 60,
    "dialog_ids": [],
}


class SetupError(Exception):
    """Safe, user-facing configuration or local-state error."""


class ApprovalError(SetupError):
    """An outbound action is missing or fails the explicit approval gate."""


class TelegramDeliveryError(SetupError):
    """Telegram rejected or could not complete an approved send."""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError) as exc:
        raise SetupError("invalid_timestamp") from exc


def _text_fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def save_json(path: Path, value: Any) -> None:
    """Atomically write local state with private permissions."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        temporary = Path(handle.name)
        try:
            os.chmod(temporary, 0o600)
            json.dump(value, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    temporary.replace(path)
    path.chmod(0o600)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SetupError(f"local_state_unreadable:{path.name}") from exc


@contextmanager
def single_writer(directory: Path) -> Iterable[None]:
    """Prevent concurrent sync/send processes from mutating private state."""
    import fcntl

    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    with (directory / "manager.lock").open("a", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SetupError("manager_already_running") from None
        yield


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    """Merge and validate bounded personal-manager settings."""
    if not isinstance(config, dict):
        raise SetupError("config_must_be_object")
    merged = {**DEFAULT_CONFIG, **config}
    for key, low, high in (
        ("max_dialogs", 1, 500),
        ("initial_limit", 1, 1000),
        ("batch_size", 1, 1000),
        ("interval_seconds", 30, 3600),
    ):
        value = merged.get(key)
        if type(value) is not int or not low <= value <= high:
            raise SetupError(f"invalid_{key}")
    dialog_ids = merged.get("dialog_ids")
    if not isinstance(dialog_ids, list) or len(dialog_ids) > merged["max_dialogs"]:
        raise SetupError("invalid_dialog_ids")
    if any(type(value) is not int or value == 0 for value in dialog_ids):
        raise SetupError("invalid_dialog_ids")
    if len(set(dialog_ids)) != len(dialog_ids):
        raise SetupError("duplicate_dialog_ids")
    merged["dialog_ids"] = list(dialog_ids)
    return merged


def classify_message(text: str, *, is_outgoing: bool = False, mentions_me: bool = False) -> str:
    """Assign a deterministic triage priority without calling an AI provider."""
    normalized = str(text or "").casefold()
    urgent_terms = ("urgent", "asap", "ด่วน", "ภายในวันนี้", "deadline วันนี้", "หมดเขตวันนี้")
    if any(term in normalized for term in urgent_terms):
        return "urgent"
    if is_outgoing:
        return "low"
    question_mark = "?" in normalized or "ไหม" in normalized or "ช่วย" in normalized
    if mentions_me or question_mark:
        return "important"
    return "normal"


def build_brief(messages: list[dict[str, Any]], *, limit: int = 20) -> dict[str, Any]:
    """Build a local triage brief without sending private text to a provider."""
    if not 1 <= limit <= 1000:
        raise SetupError("invalid_brief_limit")
    counts = {"urgent": 0, "important": 0, "normal": 0, "low": 0}
    action_required: list[dict[str, Any]] = []
    for message in messages:
        priority = str(message.get("priority") or "normal")
        if priority not in counts:
            priority = "normal"
        counts[priority] += 1
        if priority in {"urgent", "important"} and len(action_required) < limit:
            action_required.append(dict(message))
    return {
        "contract": "telegram.personal-brief.v1",
        "counts": counts,
        "total": len(messages),
        "action_required": action_required,
        "generator": "local-triage",
    }


def build_draft(message: dict[str, Any], *, tone: str = "concise") -> dict[str, Any]:
    """Build a conservative draft; it never sends or calls a model provider."""
    if tone not in {"concise", "formal"}:
        raise SetupError("invalid_draft_tone")
    text = str(message.get("text") or "").strip()
    source_id = str(message.get("id") or message.get("message_id") or "")
    if not text:
        return {"status": "no_draft", "source_message_id": source_id, "text": ""}
    if tone == "formal":
        draft_text = "ขอบคุณสำหรับข้อความครับ ผมจะตรวจสอบรายละเอียดและอัปเดตให้ทราบครับ"
    elif "?" in text or "ไหม" in text or "ช่วย" in text:
        draft_text = "ขอบคุณสำหรับข้อความครับ ผมขอตรวจสอบรายละเอียดแล้วจะตอบกลับครับ"
    else:
        draft_text = "รับทราบครับ ขอบคุณสำหรับข้อมูล เดี๋ยวผมตรวจสอบและอัปเดตให้ครับ"
    return {
        "status": "draft",
        "source_message_id": source_id,
        "text": draft_text,
        "tone": tone,
        "generator": "deterministic-safe-template",
    }


def _approvals_path(state_dir: Path) -> Path:
    return state_dir / APPROVALS_FILE


def _drafts_path(state_dir: Path) -> Path:
    return state_dir / DRAFTS_FILE


def _read_records(path: Path, default: list[dict[str, Any]]) -> list[dict[str, Any]]:
    value = load_json(path, default)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise SetupError(f"local_state_invalid:{path.name}")
    return value


def create_draft_record(state_dir: Path, *, message: dict[str, Any], tone: str = "concise") -> dict[str, Any]:
    draft = build_draft(message, tone=tone)
    if draft["status"] != "draft":
        raise SetupError("message_has_no_text")
    record = {
        **draft,
        "draft_id": secrets.token_urlsafe(12),
        "chat_id": int(message["chat_id"]),
        "message_id": int(message["message_id"]),
        "created_at": _iso(_now()),
        "status": "draft",
    }
    drafts = _read_records(_drafts_path(state_dir), [])
    drafts.append(record)
    save_json(_drafts_path(state_dir), drafts)
    return record


def create_approval(
    state_dir: Path,
    *,
    chat_id: int,
    message_id: int,
    text: str,
    ttl_seconds: int = 900,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create a pending approval for one exact outbound message."""
    if not isinstance(chat_id, int) or chat_id == 0:
        raise ApprovalError("approval_invalid_chat")
    if not isinstance(message_id, int) or message_id <= 0:
        raise ApprovalError("approval_invalid_message")
    if not isinstance(text, str) or not text.strip():
        raise ApprovalError("approval_text_empty")
    if type(ttl_seconds) is not int or not 60 <= ttl_seconds <= 3600:
        raise ApprovalError("approval_invalid_ttl")
    created = now or _now()
    record = {
        "approval_id": secrets.token_urlsafe(12),
        "status": "pending",
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "text_sha256": _text_fingerprint(text),
        "created_at": _iso(created),
        "expires_at": _iso(created + timedelta(seconds=ttl_seconds)),
    }
    approvals = _read_records(_approvals_path(state_dir), [])
    approvals.append(record)
    save_json(_approvals_path(state_dir), approvals)
    return record


def _find_approval(state_dir: Path, approval_id: str) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
    approvals = _read_records(_approvals_path(state_dir), [])
    for index, record in enumerate(approvals):
        if record.get("approval_id") == approval_id:
            return approvals, record, index
    raise ApprovalError("approval_not_found")


def verify_approval(
    state_dir: Path,
    approval_id: str,
    *,
    chat_id: int,
    text: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Verify status, expiry, exact target, and exact text before any send."""
    _approvals, record, _index = _find_approval(state_dir, approval_id)
    status = record.get("status")
    if status == "used":
        raise ApprovalError("approval_already_used")
    if status == "sending":
        raise ApprovalError("approval_in_flight")
    if status != "pending":
        raise ApprovalError("approval_not_pending")
    current = now or _now()
    if current >= _parse_time(str(record.get("expires_at"))):
        raise ApprovalError("approval_expired")
    if int(record.get("chat_id", 0)) != int(chat_id):
        raise ApprovalError("approval_target_mismatch")
    if _text_fingerprint(text) != record.get("text_sha256"):
        raise ApprovalError("approval_text_mismatch")
    return record


def _set_approval_status(state_dir: Path, approval_id: str, **updates: Any) -> dict[str, Any]:
    approvals, record, index = _find_approval(state_dir, approval_id)
    record = {**record, **updates}
    approvals[index] = record
    save_json(_approvals_path(state_dir), approvals)
    return record


async def send_approved(
    client: Any,
    state_dir: Path,
    approval_id: str,
    *,
    chat_id: int,
    text: str,
) -> dict[str, Any]:
    """Send once through an injected client after claiming the approval."""
    record = verify_approval(state_dir, approval_id, chat_id=chat_id, text=text)
    _set_approval_status(state_dir, approval_id, status="sending", sending_at=_iso(_now()))
    try:
        sent = await client.send_message(chat_id, text)
    except Exception:
        _set_approval_status(
            state_dir,
            approval_id,
            status="pending",
            last_error="telegram_send_failed",
            last_attempt_at=_iso(_now()),
        )
        raise TelegramDeliveryError("telegram_send_failed") from None
    sent_id = getattr(sent, "id", None)
    if sent_id is None and isinstance(sent, dict):
        sent_id = sent.get("id")
    _set_approval_status(
        state_dir,
        approval_id,
        status="used",
        sent_at=_iso(_now()),
        sent_message_id=sent_id,
    )
    return {"status": "sent", "approval_id": record["approval_id"], "sent_message_id": sent_id}


def _payload_from_json(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict) and isinstance(value.get("payload_json"), str):
        try:
            value = json.loads(value["payload_json"])
        except json.JSONDecodeError:
            return None
    if not isinstance(value, dict):
        return None
    if "text" not in value and "message" in value:
        value = {**value, "text": value.get("message", "")}
    if "id" not in value and "chat_id" in value and "message_id" in value:
        value = {**value, "id": f"{value['chat_id']}:{value['message_id']}"}
    if "text" not in value or "id" not in value:
        return None
    return value


def _iter_local_payloads(lake_dir: Path) -> Iterable[dict[str, Any]]:
    """Read Bronze payloads; landing JSONL is a safe test/fallback reader."""
    bronze_root = lake_dir / "bronze" / "domain=communication" / "dataset=personal-messages"
    try:
        import pyarrow.parquet as pq  # type: ignore
    except ImportError:
        pq = None
    if pq is not None:
        for path in bronze_root.rglob("*.parquet"):
            try:
                for batch in pq.ParquetFile(path).iter_batches(columns=["payload_json"]):
                    for payload in batch.column(0).to_pylist():
                        record = _payload_from_json(payload)
                        if record:
                            yield record
            except (OSError, ValueError):
                continue
    for path in (lake_dir / "landing").rglob("*.jsonl"):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                record = _payload_from_json(json.loads(line))
            except json.JSONDecodeError:
                continue
            if record:
                yield record


def search_messages(
    lake_dir: Path,
    *,
    keyword: str = "",
    limit: int = 20,
    priority: str = "",
    chat_id: int | None = None,
    message_id: int | None = None,
) -> list[dict[str, Any]]:
    """Search captured messages locally; this function never calls Telegram."""
    if not 1 <= limit <= 1000:
        raise SetupError("invalid_read_limit")
    if priority and priority not in {"urgent", "important", "normal", "low"}:
        raise SetupError("invalid_priority")
    needle = keyword.casefold().strip()
    deduped: dict[str, dict[str, Any]] = {}
    for raw in _iter_local_payloads(lake_dir):
        record = dict(raw)
        if "priority" not in record:
            record["priority"] = classify_message(
                str(record.get("text", "")),
                is_outgoing=bool(record.get("is_outgoing", False)),
                mentions_me=bool(record.get("mentions_me", False)),
            )
        if needle and needle not in str(record.get("text", "")).casefold():
            continue
        if priority and record["priority"] != priority:
            continue
        if chat_id is not None and int(record.get("chat_id", 0)) != int(chat_id):
            continue
        if message_id is not None and int(record.get("message_id", 0)) != int(message_id):
            continue
        record_id = str(record.get("id"))
        deduped[record_id] = record
    return sorted(
        deduped.values(),
        key=lambda item: (str(item.get("date", "")), str(item.get("id", ""))),
        reverse=True,
    )[:limit]


def _find_message(lake_dir: Path, *, chat_id: int, message_id: int) -> dict[str, Any]:
    rows = search_messages(lake_dir, chat_id=chat_id, message_id=message_id, limit=2)
    if not rows:
        raise SetupError("message_not_found")
    return rows[0]


def _save_config(state_dir: Path, config: dict[str, Any]) -> dict[str, Any]:
    config = validate_config(config)
    save_json(state_dir / CONFIG_FILE, config)
    return config


def _bind_state(state_dir: Path, account_id: int, lake_dir: Path) -> dict[str, Any]:
    state = load_json(state_dir / CHECKPOINT_FILE, {})
    account_hash = hashlib.sha256(str(account_id).encode("utf-8")).hexdigest()
    identity = {"account_hash": account_hash, "lake": str(lake_dir.resolve())}
    if state and any(state.get(key) != value for key, value in identity.items()):
        raise SetupError("account_or_lake_mismatch")
    if not state:
        state = {**identity, "cursors": {}}
        save_json(state_dir / CHECKPOINT_FILE, state)
    state.setdefault("cursors", {})
    return state


def _commit_pending(state_dir: Path, lake_dir: Path, state: dict[str, Any]) -> int:
    pending_path = state_dir / PENDING_FILE
    if not pending_path.exists():
        return 0
    pending = load_json(pending_path, {})
    if not isinstance(pending, dict) or not pending.get("records"):
        raise SetupError("pending_batch_invalid")
    try:
        from data_lake.ingest import ingest_payload

        result = ingest_payload(
            str(pending["raw"]).encode("utf-8"),
            pending["records"],
            source="telegram-personal",
            domain="communication",
            dataset="personal-messages",
            data_lake_uri=str(lake_dir),
            input_format="jsonl",
            source_record_id_field="id",
            event_time_field="date",
            privacy_class="private",
            retention_class="operational",
            metadata={"adapter": "telethon", "contract": "telegram.personal-message.v1"},
        )
    except Exception as exc:
        raise SetupError(f"lake_ingest_failed:{type(exc).__name__}") from None
    if result.get("status") != "success":
        raise SetupError("lake_ingest_failed")
    chat_key = str(pending["chat_id"])
    state["cursors"][chat_key] = max(int(state["cursors"].get(chat_key, 0)), int(pending["cursor"]))
    save_json(state_dir / CHECKPOINT_FILE, state)
    pending_path.unlink(missing_ok=True)
    return len(pending["records"])


def _normalize_message(message: Any, *, chat_id: int, dialog: Any, mentions_me: bool | None = None) -> dict[str, Any]:
    text = str(getattr(message, "message", "") or "")
    is_outgoing = bool(getattr(message, "out", False))
    if mentions_me is None:
        mentions_me = bool(getattr(message, "mentioned", False))
    message_id = int(getattr(message, "id"))
    date = getattr(message, "date", None)
    date_value = _iso(date) if isinstance(date, datetime) else str(date or "")
    edit_date = getattr(message, "edit_date", None)
    return {
        "id": f"{chat_id}:{message_id}",
        "chat_id": chat_id,
        "chat_title": str(getattr(dialog, "name", "") or ""),
        "chat_type": str(getattr(dialog, "kind", "") or ""),
        "message_id": message_id,
        "date": date_value,
        "text": text,
        "has_media": bool(getattr(message, "media", None)),
        "edit_date": _iso(edit_date) if isinstance(edit_date, datetime) else None,
        "is_outgoing": is_outgoing,
        "mentions_me": bool(mentions_me),
        "priority": classify_message(text, is_outgoing=is_outgoing, mentions_me=mentions_me),
    }


async def _iter_dialogs(client: Any) -> AsyncIterator[Any]:
    async for dialog in client.iter_dialogs():
        yield dialog


async def sync_once(
    client: Any,
    *,
    config: dict[str, Any],
    state_dir: Path = STATE_DIR,
    lake_dir: Path = LAKE_DIR,
    account_id: int | None = None,
) -> dict[str, Any]:
    """Capture one bounded pass across the configured dialogs."""
    config = validate_config(config)
    me = await client.get_me()
    if account_id is None:
        account_id = int(getattr(me, "id"))
    if bool(getattr(me, "bot", False)):
        raise SetupError("telegram_user_account_required")
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_dir.chmod(0o700)
    lake_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    state = _bind_state(state_dir, account_id, lake_dir)
    recovered = _commit_pending(state_dir, lake_dir, state)
    selected = set(config["dialog_ids"])
    dialogs: list[Any] = []
    async for dialog in _iter_dialogs(client):
        chat_id = int(getattr(dialog, "id", 0))
        if not chat_id or (selected and chat_id not in selected):
            continue
        dialogs.append(dialog)
        if len(dialogs) >= config["max_dialogs"]:
            break
    collected = 0
    failures = 0
    for dialog in dialogs:
        chat_id = int(getattr(dialog, "id"))
        cursor = int(state["cursors"].get(str(chat_id), 0))
        options = (
            {"limit": config["initial_limit"]}
            if cursor == 0
            else {"min_id": cursor, "reverse": True, "limit": config["batch_size"]}
        )
        messages = [message async for message in client.iter_messages(dialog.entity, **options)]
        messages.sort(key=lambda item: int(getattr(item, "id")))
        if not messages:
            continue
        records = [_normalize_message(message, chat_id=chat_id, dialog=dialog) for message in messages]
        raw = "".join(message.to_json() + "\n" for message in messages)
        save_json(
            state_dir / PENDING_FILE,
            {"chat_id": chat_id, "cursor": records[-1]["message_id"], "raw": raw, "records": records},
        )
        try:
            collected += _commit_pending(state_dir, lake_dir, state)
        except SetupError:
            failures += 1
            raise
    return {"status": "success" if failures == 0 else "partial", "dialogs": len(dialogs), "collected": collected, "recovered": recovered, "failures": failures}


def require_terminal() -> None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise SetupError("run_setup_in_owner_terminal")


def _credentials(interactive: bool) -> tuple[int, str]:
    from _env import get_secret

    values: dict[str, str | None] = {}
    provider_error: str | None = None
    for name in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH"):
        try:
            values[name] = get_secret(name)
        except Exception as exc:
            provider_error = type(exc).__name__
            values[name] = None
    api_id = values["TELEGRAM_API_ID"]
    api_hash = values["TELEGRAM_API_HASH"]
    if not api_id or not api_hash:
        if not interactive:
            raise SetupError("telegram_api_credentials_missing")
        require_terminal()
        if provider_error:
            print(f"secret provider unavailable (error_class={provider_error}); using this session only")
        api_id = api_id or getpass.getpass("API ID (hidden): ").strip()
        api_hash = api_hash or getpass.getpass("API hash (hidden): ").strip()
    if not str(api_id).isdigit() or int(api_id) <= 0 or not re.fullmatch(r"[a-fA-F0-9]{32}", str(api_hash)):
        raise SetupError("telegram_api_credentials_invalid")
    return int(api_id), str(api_hash)


async def _login(client: Any) -> None:
    from telethon.errors import SessionPasswordNeededError

    require_terminal()
    phone = getpass.getpass("Telegram phone with country code (hidden): ").strip()
    await client.send_code_request(phone)
    code = getpass.getpass("Telegram login code (hidden): ").strip()
    try:
        await client.sign_in(phone=phone, code=code)
    except SessionPasswordNeededError:
        await client.sign_in(password=getpass.getpass("Telegram 2FA password (hidden): "))
    print("Telegram account connected")


async def _run_live(args: argparse.Namespace) -> int:
    try:
        from telethon import TelegramClient
    except ImportError:
        raise SetupError("telethon_not_installed") from None
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    api_id, api_hash = _credentials(interactive)
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE_DIR.chmod(0o700)
    client = TelegramClient(
        str(STATE_DIR / "personal.session"), api_id, api_hash,
        receive_updates=False, flood_sleep_threshold=0, request_retries=2,
        connection_retries=3, timeout=20,
    )
    try:
        await client.connect()
        if not await client.is_user_authorized():
            if args.command != "setup" or not interactive:
                raise SetupError("telegram_session_not_authorized")
            await _login(client)
        me = await client.get_me()
        if bool(getattr(me, "bot", False)):
            raise SetupError("telegram_user_account_required")
        if args.command == "setup":
            _save_config(STATE_DIR, validate_config(load_json(STATE_DIR / CONFIG_FILE, DEFAULT_CONFIG)))
            _bind_state(STATE_DIR, int(me.id), LAKE_DIR)
            print(json.dumps({"status": "ready", "config": load_json(STATE_DIR / CONFIG_FILE, DEFAULT_CONFIG)}, ensure_ascii=False))
            return 0
        config = validate_config(load_json(STATE_DIR / CONFIG_FILE, DEFAULT_CONFIG))
        if args.command in {"sync", "watch"}:
            while True:
                result = await sync_once(client, config=config, account_id=int(me.id))
                print(json.dumps(result, ensure_ascii=False), flush=True)
                if args.command == "sync":
                    return 0
                await asyncio.sleep(config["interval_seconds"])
        if args.command == "send":
            result = await send_approved(
                client, STATE_DIR, args.approval_id, chat_id=args.chat_id, text=args.text
            )
            print(json.dumps(result, ensure_ascii=False))
            return 0
        raise SetupError("unsupported_live_command")
    finally:
        await client.disconnect()


def _offline_command(args: argparse.Namespace) -> int:
    state_dir = STATE_DIR
    if args.command == "status":
        config = validate_config(load_json(state_dir / CONFIG_FILE, DEFAULT_CONFIG))
        checkpoint = load_json(state_dir / CHECKPOINT_FILE, {})
        print(json.dumps({
            "session_file_exists": (state_dir / "personal.session").exists(),
            "configured_dialogs": len(config.get("dialog_ids", [])),
            "checkpoint_dialogs": len(checkpoint.get("cursors", {})),
            "pending_batch": (state_dir / PENDING_FILE).exists(),
            "authorization_verified": False,
        }, ensure_ascii=False))
        return 0
    if args.command == "read":
        rows = search_messages(
            LAKE_DIR, keyword=args.keyword, limit=args.limit,
            priority=args.priority, chat_id=args.chat_id,
        )
        for row in rows:
            print(json.dumps(row, ensure_ascii=False))
        return 0
    if args.command == "brief":
        rows = search_messages(LAKE_DIR, limit=args.limit)
        print(json.dumps(build_brief(rows, limit=args.limit), ensure_ascii=False))
        return 0
    if args.command == "draft":
        message = _find_message(LAKE_DIR, chat_id=args.chat_id, message_id=args.message_id)
        draft = create_draft_record(state_dir, message=message, tone=args.tone)
        print(json.dumps(draft, ensure_ascii=False))
        return 0
    if args.command == "approve":
        if args.draft_id:
            drafts = _read_records(_drafts_path(state_dir), [])
            matches = [row for row in drafts if row.get("draft_id") == args.draft_id]
            if not matches:
                raise ApprovalError("draft_not_found")
            draft = matches[0]
            approval = create_approval(
                state_dir, chat_id=int(draft["chat_id"]), message_id=int(draft["message_id"]), text=str(draft["text"])
            )
        else:
            if args.chat_id is None or args.message_id is None or args.text is None:
                raise ApprovalError("approval_input_required")
            approval = create_approval(
                state_dir, chat_id=args.chat_id, message_id=args.message_id, text=args.text
            )
        print(json.dumps(approval, ensure_ascii=False))
        return 0
    raise SetupError("command_requires_live_session")


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("setup", "sync", "watch", "status"):
        sub.add_parser(name)
    reader = sub.add_parser("read")
    reader.add_argument("--limit", type=int, default=20)
    reader.add_argument("--keyword", default="")
    reader.add_argument("--priority", default="")
    reader.add_argument("--chat-id", type=int)
    brief = sub.add_parser("brief")
    brief.add_argument("--limit", type=int, default=20)
    draft = sub.add_parser("draft")
    draft.add_argument("--chat-id", type=int, required=True)
    draft.add_argument("--message-id", type=int, required=True)
    draft.add_argument("--tone", choices=("concise", "formal"), default="concise")
    approve = sub.add_parser("approve")
    approve.add_argument("--draft-id")
    approve.add_argument("--chat-id", type=int)
    approve.add_argument("--message-id", type=int)
    approve.add_argument("--text")
    send = sub.add_parser("send")
    send.add_argument("--approval-id", required=True)
    send.add_argument("--chat-id", type=int, required=True)
    send.add_argument("--text", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in {"status", "read", "brief", "draft", "approve"}:
            with single_writer(STATE_DIR) if args.command in {"draft", "approve"} else _null_context():
                return _offline_command(args)
        with single_writer(STATE_DIR):
            return asyncio.run(_run_live(args))
    except (SetupError, ApprovalError, TelegramDeliveryError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("stopped; restart to resume from the durable checkpoint", file=sys.stderr)
        return 130


@contextmanager
def _null_context() -> Iterable[None]:
    yield


if __name__ == "__main__":
    raise SystemExit(main())
