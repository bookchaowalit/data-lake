#!/usr/bin/env python3
"""Local, read-only Telegram channel collection through a user session."""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import getpass
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sys
import tempfile
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra/scripts"))
sys.path.insert(0, str(ROOT / "infra/scripts/utils"))
STATE_DIR = Path.home() / ".local/state/solo-empire/telegram"
LAKE_DIR = ROOT / "data/lake/telegram"


class SetupError(Exception):
    """Safe, user-facing configuration error."""


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        try:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    temp.replace(path)


def load_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


@contextmanager
def single_writer(directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    with (directory / "collector.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SetupError("มีตัวติดตามทำงานอยู่แล้ว ให้หยุดตัวเดิมก่อน") from None
        yield


def validate_config(config):
    channels = config.get("channels")
    if not isinstance(channels, list) or not channels or len(channels) > 100:
        raise SetupError("เลือก channel 1–100 ช่องด้วยคำสั่ง setup")
    if any(type(value) is not int or value >= 0 for value in channels):
        raise SetupError("รายการ channel ไม่ถูกต้อง ให้รัน setup ใหม่")
    if len(set(channels)) != len(channels):
        raise SetupError("รายการ channel ซ้ำกัน ให้รัน setup ใหม่")
    for key, low, high in (("initial_limit", 1, 1000), ("batch_size", 1, 1000),
                           ("interval_seconds", 30, 3600)):
        value = config.get(key)
        if type(value) is not int or not low <= value <= high:
            raise SetupError(f"ค่า {key} ไม่ถูกต้อง")
    return config


def require_terminal():
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise SetupError("รัน setup ใน terminal ของคุณโดยตรง เพื่อกรอกข้อมูลเข้าบัญชีอย่างปลอดภัย")


def credentials(interactive):
    from _env import get_secret
    values = {}
    provider_error = None
    for name in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH"):
        try:
            values[name] = get_secret(name)
        except Exception as exc:
            # Provider diagnostics can include endpoint or account details. Keep
            # only the error class and never print the provider's raw message.
            provider_error = type(exc).__name__
            values[name] = None
    api_id = values["TELEGRAM_API_ID"]
    api_hash = values["TELEGRAM_API_HASH"]
    if provider_error and not interactive:
        raise SetupError(
            f"อ่าน Telegram API credentials จาก secret provider ไม่สำเร็จ "
            f"(error_class={provider_error}); ตั้งค่าใน secret provider หรือ infra/.env"
        )
    if not api_id or not api_hash:
        if not interactive:
            raise SetupError("ยังไม่มี TELEGRAM_API_ID / TELEGRAM_API_HASH: รัน watch ใน terminal หรือกำหนดผ่าน secret provider")
        require_terminal()
        if provider_error:
            print(f"secret provider ใช้งานไม่ได้ชั่วคราว (error_class={provider_error}); ใช้ค่าที่กรอกในรอบนี้แทน")
        print("ใช้ API ID และ API hash จาก https://my.telegram.org/apps")
        print("ค่าที่กรอกจะอยู่ในหน่วยความจำของรอบนี้เท่านั้น")
        api_id = api_id or getpass.getpass("API ID (ซ่อน): ").strip()
        api_hash = api_hash or getpass.getpass("API hash (ซ่อน): ").strip()
    if not str(api_id).isdigit() or int(api_id) <= 0 or not re.fullmatch(r"[a-fA-F0-9]{32}", str(api_hash)):
        raise SetupError("รูปแบบ API ID / API hash ไม่ถูกต้อง")
    return int(api_id), api_hash


async def login(client):
    from telethon.errors import SessionPasswordNeededError
    require_terminal()
    # Avoid client.start(): its success message includes the user's identity.
    phone = getpass.getpass("หมายเลขโทรศัพท์พร้อมรหัสประเทศ (ซ่อน): ").strip()
    await client.send_code_request(phone)
    code = getpass.getpass("รหัสยืนยันจาก Telegram (ซ่อน): ").strip()
    try:
        await client.sign_in(phone=phone, code=code)
    except SessionPasswordNeededError:
        await client.sign_in(password=getpass.getpass("รหัสผ่าน 2FA (ซ่อน): "))
    print("เชื่อมบัญชีแล้ว")


async def choose_channels(client, state_dir):
    from telethon import utils
    require_terminal()
    available = []
    async for dialog in client.iter_dialogs():
        if getattr(dialog.entity, "broadcast", False):
            available.append(dialog)
    if not available:
        raise SetupError("บัญชีนี้ยังไม่มี channel ให้เลือก เปิด Telegram แล้วเข้าร่วมช่องที่ต้องการก่อน")
    for index, dialog in enumerate(available, 1):
        # JSON escaping prevents channel titles from injecting terminal controls.
        print(f"{index}. {json.dumps(dialog.name, ensure_ascii=False)}")
    raw = input("เลือกหมายเลข channel คั่นด้วย comma เช่น 1,3,5: ").strip()
    try:
        selected = list(dict.fromkeys(int(item.strip()) for item in raw.split(",")))
        if any(number < 1 or number > len(available) for number in selected):
            raise ValueError
    except ValueError:
        raise SetupError("หมายเลขที่เลือกไม่ถูกต้อง") from None
    config = validate_config({
        "channels": [utils.get_peer_id(available[number - 1].entity) for number in selected],
        "initial_limit": 100, "batch_size": 500, "interval_seconds": 60,
    })
    save_json(state_dir / "channels.json", config)
    print(f"บันทึกรายการ {len(selected)} channel แล้ว")
    return config


def bind_state(state_dir, account_id, lake_dir):
    state = load_json(state_dir / "checkpoint.json", {})
    account = hashlib.sha256(str(account_id).encode()).hexdigest()
    identity = {"account": account, "lake": str(lake_dir.resolve())}
    if state and any(state.get(key) != value for key, value in identity.items()):
        raise SetupError("บัญชีหรือตำแหน่ง lake ต่างจาก checkpoint เดิม ให้ใช้ session เดิม")
    if not state:
        state = {**identity, "cursors": {}}
        save_json(state_dir / "checkpoint.json", state)
    return state


def commit_pending(state_dir, lake_dir, state):
    """Replay a durable batch before advancing its cursor; safe after a crash."""
    from data_lake.ingest import ingest_payload
    pending_path = state_dir / "pending.json"
    if not pending_path.exists():
        return 0
    batch = load_json(pending_path, {})
    result = ingest_payload(
        batch["raw"].encode("utf-8"), batch["records"],
        source="telegram-channels", domain="communication", dataset="channel-posts",
        data_lake_uri=str(lake_dir), input_format="jsonl",
        event_time_field="date", privacy_class="private", retention_class="operational",
        metadata={"adapter": "telethon", "contract": "telegram.channel-post.v1",
                  "capture": "sdk-message-json", "media_downloaded": False},
    )
    if result["status"] != "success":
        raise RuntimeError("lake_ingest_failed")
    key = str(batch["channel_id"])
    state["cursors"][key] = max(state["cursors"].get(key, 0), batch["cursor"])
    save_json(state_dir / "checkpoint.json", state)
    pending_path.unlink()
    return len(batch["records"])


async def collect_channel(client, entity, channel_id, config, state_dir, lake_dir, state):
    key = str(channel_id)
    cursor = state["cursors"].get(key)
    options = {"limit": config["initial_limit"]} if cursor is None else {
        "min_id": cursor, "reverse": True, "limit": config["batch_size"],
    }
    messages = [message async for message in client.iter_messages(entity, **options)]
    if not messages:
        if cursor is None:
            state["cursors"][key] = 0
            save_json(state_dir / "checkpoint.json", state)
        return 0
    messages.sort(key=lambda message: message.id)
    records = [{
        "id": f"{channel_id}:{message.id}", "channel_id": channel_id,
        "message_id": message.id, "date": message.date.isoformat(),
        "text": message.message or "", "has_media": bool(message.media),
        "edit_date": message.edit_date.isoformat() if message.edit_date else None,
    } for message in messages]
    # This preserves the SDK serialization, not the encrypted MTProto wire body.
    raw = "".join(message.to_json() + "\n" for message in messages)
    save_json(state_dir / "pending.json", {
        "channel_id": channel_id, "cursor": messages[-1].id,
        "raw": raw, "records": records,
    })
    return commit_pending(state_dir, lake_dir, state)


async def run(args, state_dir=STATE_DIR, lake_dir=LAKE_DIR):
    from telethon import TelegramClient, utils
    from telethon.errors import FloodWaitError
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if args.command == "setup":
        require_terminal()
    api_id, api_hash = credentials(interactive)
    client = TelegramClient(str(state_dir / "reader.session"), api_id, api_hash,
                            receive_updates=False, flood_sleep_threshold=0,
                            request_retries=2, connection_retries=3, timeout=20)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            if args.command == "sync" or not interactive:
                raise SetupError("ยังไม่ได้เชื่อมบัญชี ให้รัน task telegram -- setup ใน terminal")
            await login(client)
        me = await client.get_me()
        if me.bot:
            raise SetupError("ต้องใช้บัญชีผู้ใช้ Telegram ไม่ใช่ bot")
        state = bind_state(state_dir, me.id, lake_dir)
        config = load_json(state_dir / "channels.json", {})
        if args.command == "setup" or (args.command == "watch" and not config and interactive):
            config = await choose_channels(client, state_dir)
        validate_config(config)
        if args.command == "setup":
            print("พร้อมใช้งาน: task telegram -- watch")
            return 0
        # Preflight before reading any channel payload.
        import pyarrow  # noqa: F401
        lake_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        lake_dir.chmod(0o700)
        # Populate the access-hash cache using this user's current memberships.
        entities = {}
        async for dialog in client.iter_dialogs():
            if getattr(dialog.entity, "broadcast", False):
                entities[utils.get_peer_id(dialog.entity)] = dialog.entity
        pending = load_json(state_dir / "pending.json", None)
        if pending and pending["channel_id"] not in config["channels"]:
            raise SetupError("มี batch ค้างจาก channel ที่เลิกเลือก ให้เลือกช่องเดิมเพื่อกู้คืนก่อน")
        commit_pending(state_dir, lake_dir, state)
        while True:
            count, failed, wait = 0, 0, config["interval_seconds"]
            for index, channel_id in enumerate(config["channels"], 1):
                entity = entities.get(channel_id)
                if entity is None:
                    print(f"channel #{index}: ไม่อยู่ในรายการที่บัญชีเข้าถึงได้ ให้รัน setup ใหม่", file=sys.stderr)
                    failed += 1
                    continue
                try:
                    count += await collect_channel(client, entity, channel_id, config,
                                                   state_dir, lake_dir, state)
                except FloodWaitError as exc:
                    wait = max(wait, exc.seconds + 1)
                    print(f"Telegram ขอให้รอ {wait} วินาที", file=sys.stderr)
                    failed += 1
                    break
                except Exception as exc:
                    print(f"channel #{index}: {type(exc).__name__}", file=sys.stderr)
                    failed += 1
                    # Never overwrite a failed durable batch with another channel.
                    if (state_dir / "pending.json").exists():
                        raise SetupError("เก็บข้อมูลยังไม่สำเร็จ หยุดเพื่อรักษา batch ค้าง; รันใหม่หลังแก้ปัญหา storage") from None
            print(f"เก็บ {count} โพสต์ใหม่ | {len(config['channels'])} channel | ผิดพลาด {failed}", flush=True)
            if args.command == "sync":
                return 2 if failed else 0
            await asyncio.sleep(wait)
    finally:
        await client.disconnect()


def read_posts(args, lake_dir=LAKE_DIR):
    """Read bounded private posts from Bronze; never call Telegram."""
    import pyarrow.parquet as pq
    latest = {}
    for path in lake_dir.glob("bronze/domain=communication/dataset=channel-posts/**/*.parquet"):
        for batch in pq.ParquetFile(path).iter_batches(columns=["payload_json"]):
            for row in batch.column(0).to_pylist():
                record = json.loads(row)
                if args.keyword and args.keyword.casefold() not in record["text"].casefold():
                    continue
                latest[record["id"]] = record
            latest = dict(sorted(latest.items(), key=lambda pair: (pair[1]["date"], pair[0]), reverse=True)[:args.limit])
    for record in sorted(latest.values(), key=lambda item: (item["date"], item["id"]), reverse=True):
        # JSONL remains reusable and escapes terminal control characters.
        print(json.dumps(record, ensure_ascii=False))
    return 0


def main():
    os.umask(0o077)
    logging.disable(logging.CRITICAL)  # Library errors can contain private RPC context.
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("setup", "watch", "sync", "status"):
        sub.add_parser(name)
    reader = sub.add_parser("read")
    reader.add_argument("--limit", type=int, default=20)
    reader.add_argument("--keyword", default="")
    args = parser.parse_args()
    try:
        if args.command == "status":
            config = load_json(STATE_DIR / "channels.json", {})
            state = load_json(STATE_DIR / "checkpoint.json", {})
            print(json.dumps({"session_file_exists": (STATE_DIR / "reader.session").exists(),
                              "configured_channels": len(config.get("channels", [])),
                              "checkpoint_channels": len(state.get("cursors", {})),
                              "pending_batch": (STATE_DIR / "pending.json").exists(),
                              "authorization_verified": False}))
            return 0
        if args.command == "read":
            if not 1 <= args.limit <= 1000:
                raise SetupError("--limit ต้องอยู่ระหว่าง 1–1000")
            return read_posts(args)
        with single_writer(STATE_DIR):
            return asyncio.run(run(args))
    except SetupError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("หยุดแล้ว เริ่มใหม่เพื่ออ่านต่อจาก checkpoint ได้")
        return 0
    except Exception as exc:
        print(f"ทำงานไม่สำเร็จ: {type(exc).__name__} (ไม่แสดงข้อมูลส่วนตัว)", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
