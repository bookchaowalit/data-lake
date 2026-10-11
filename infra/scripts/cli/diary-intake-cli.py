#!/usr/bin/env python3
"""Lake-first adapter for private daily Diary Markdown entries.

Usage:
    python3 infra/scripts/cli/diary-intake-cli.py register [--json]
    python3 infra/scripts/cli/diary-intake-cli.py activate [--json]
    python3 infra/scripts/cli/diary-intake-cli.py ingest --date YYYY-MM-DD --entry daily.md [--json]

The adapter accepts only a single Markdown file from the canonical
``diary/entries/YYYY/MM/DD/`` boundary. It archives the exact bytes to the
data lake and stores only control-plane metadata and lineage in the Intake cell.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
UTILS_DIR = SCRIPTS_DIR / "utils"
if str(UTILS_DIR) not in sys.path:
    sys.path.insert(0, str(UTILS_DIR))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _env import PROJECT_ROOT  # noqa: E402
from cell_store import open_cell_store  # noqa: E402
from data_lake.ingest import ingest_payload  # noqa: E402
from task_store import ClientConfigError  # noqa: E402

AUTOMATION_ID = "owner-cli"


SOURCE_KEY = "diary-markdown"
DIARY_ENTRIES_ROOT = Path(
    os.environ.get(
        "SOLO_EMPIRE_DIARY_ROOT",
        str(PROJECT_ROOT / "diary" / "entries"),
    )
).expanduser().resolve()
DEFAULT_LAKE_URI = os.environ.get(
    "SOLO_EMPIRE_DATA_LAKE_URI",
    os.environ.get("DATA_LAKE_URI", str(PROJECT_ROOT / "data" / "lake")),
)
CONTROL_CLI = PROJECT_ROOT / "infra" / "scripts" / "cli" / "data-intake-cli.py"
MAX_ENTRY_BYTES = 2 * 1024 * 1024
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def json_print(payload: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    elif isinstance(payload, dict):
        for key, value in payload.items():
            print(f"{key}: {value}")
    else:
        print(payload)


def slug(value: str, *, max_length: int = 36) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "-", str(value).strip().lower()).strip("-")
    text = text[:max_length].strip("-")
    if not text:
        raise ValueError("entry filename must contain at least one usable character")
    return text


def parse_entry_date(value: str) -> date:
    if not DATE_RE.fullmatch(value):
        raise ValueError("date must use YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("date is not a valid calendar date") from exc


def resolve_entry_path(entry_date: date, entry_name: str) -> Path:
    candidate = Path(entry_name)
    if candidate.is_absolute() or len(candidate.parts) != 1:
        raise ValueError("entry must be one filename, not a path")
    if candidate.name in {".", ".."} or candidate.suffix.lower() not in {".md", ".markdown"}:
        raise ValueError("entry must be a Markdown filename ending in .md or .markdown")
    day_root = (DIARY_ENTRIES_ROOT / f"{entry_date.year:04d}" / f"{entry_date.month:02d}" / f"{entry_date.day:02d}").resolve()
    raw_path = day_root / candidate.name
    if raw_path.is_symlink():
        raise ValueError("symlinked diary entries are not accepted")
    path = raw_path.resolve()
    if path.parent != day_root:
        raise ValueError("entry resolved outside the canonical diary date boundary")
    if not path.is_file():
        raise ValueError(f"diary entry not found for {entry_date.isoformat()}")
    return path


def get_store() -> Any:
    """The intake cell store (sources and intakes live in the Intake cell, not local SQLite)."""
    return open_cell_store("intake", AUTOMATION_ID, channel="cli")


def source_policy(store: Any) -> dict[str, Any] | None:
    rows = store.list("sources", source_key=SOURCE_KEY)
    return rows[0] if rows else None


def intake_row(store: Any, intake_key: str) -> dict[str, Any] | None:
    rows = store.list("intakes", intake_key=intake_key)
    if not rows:
        return None
    source = store.get("sources", rows[0]["source_id"])
    if not source:
        return None
    return {**rows[0], "source_key": source["source_key"], "source_status": source["status"]}


def run_control(command: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(CONTROL_CLI), *command, "--json"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        # The control CLI already redacts its errors. Do not echo its stderr,
        # because this adapter must never turn a source path into a log field.
        raise RuntimeError("intake control command failed")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("intake control returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("intake control returned an invalid response")
    return payload


def cmd_register(args: argparse.Namespace) -> None:
    payload = run_control([
        "source", "register",
        "--key", SOURCE_KEY,
        "--name", "Diary Markdown",
        "--kind", "file",
        "--domain", "life",
        "--dataset", "diary",
        "--owner-scope", "personal",
        "--privacy-class", "restricted",
        "--retention-class", "personal",
        "--ingest-mode", "manual",
        "--status", "planned",
        "--description", "Canonical private daily diary Markdown source",
    ])
    json_print(payload, args.as_json)


def cmd_activate(args: argparse.Namespace) -> None:
    payload = run_control(["source", "set-status", SOURCE_KEY, "active"])
    json_print(payload, args.as_json)


def cmd_ingest(args: argparse.Namespace) -> None:
    entry_date = parse_entry_date(args.date)
    path = resolve_entry_path(entry_date, args.entry)
    raw = path.read_bytes()
    if len(raw) > MAX_ENTRY_BYTES:
        raise ValueError("diary entry exceeds the 2 MiB safety limit")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("diary entry must be UTF-8 Markdown") from exc

    store = get_store()
    source = source_policy(store)
    if not source or source["status"] != "active":
        if not source:
            raise ValueError("diary source is not registered; run diary-intake-cli.py register")
        raise ValueError(f"diary source is {source['status']}; activate it before ingest")
    if (
        source["domain"] != "life"
        or source["dataset"] != "diary"
        or source["privacy_class"] != "restricted"
        or source["retention_class"] != "personal"
    ):
        raise ValueError("diary source policy does not match the restricted adapter contract")

    digest = hashlib.sha256(raw).hexdigest()
    entry_token = slug(path.stem)
    intake_key = f"diary-{entry_date.isoformat()}-{entry_token}-{digest[:12]}"
    input_ref = f"diary:{entry_date.isoformat()}:{entry_token}"
    idempotency_key = f"diary-sha256-{digest}"
    existing = intake_row(store, intake_key)

    if existing and existing["status"] == "verified":
        run_control(["repair", intake_key])  # an earlier run may have lost its last event
        json_print({
            "status": "already_verified",
            "intake_key": intake_key,
            "entry_date": entry_date.isoformat(),
            "idempotent": True,
        }, args.as_json)
        return

    if existing and existing["status"] in {"failed", "rejected"}:
        run_control(["retry", intake_key, "--actor", "diary-adapter"])
    elif existing and existing["status"] == "landed":
        run_control([
            "verify", intake_key,
            "--data-lake-uri", args.data_lake_uri,
            "--actor", "diary-adapter",
        ])
        json_print({
            "status": "verified",
            "intake_key": intake_key,
            "entry_date": entry_date.isoformat(),
            "idempotent": True,
        }, args.as_json)
        return
    elif existing and existing["status"] not in {"queued"}:
        raise ValueError(f"diary intake is already {existing['status']}")

    if not existing:
        try:
            run_control([
                "enqueue",
                "--source", SOURCE_KEY,
                "--input-ref", input_ref,
                "--idempotency-key", idempotency_key,
                "--intake-key", intake_key,
                "--source-batch-ref", f"sha256:{digest}",
                "--domain", "life",
                "--dataset", "diary",
                "--schema-version", "1",
                "--payload-kind", "markdown",
                "--privacy-class", "restricted",
                "--retention-class", "personal",
                "--requested-by", "human",
            ])
        except RuntimeError:
            # A concurrent retry may have inserted the deterministic request.
            # Re-read by intake key before surfacing a genuine failure.
            existing = intake_row(store, intake_key)
            if not existing:
                raise

    run_control(["claim", intake_key, "--worker", "diary-adapter"])
    try:
        lake_result = ingest_payload(
            raw,
            [{
                "id": f"{entry_date.isoformat()}:{path.name}",
                "entry_date": entry_date.isoformat(),
                "entry_name": path.name,
                "format": "markdown",
            }],
            source=SOURCE_KEY,
            domain="life",
            dataset="diary",
            data_lake_uri=args.data_lake_uri,
            input_format="markdown",
            schema_version="1",
            source_record_id_field="id",
            event_time_field="entry_date",
            content_type="text/markdown",
            metadata={
                "entry_date": entry_date.isoformat(),
                "entry_name": path.name,
                "format": "markdown",
            },
            privacy_class="restricted",
            retention_class="personal",
        )
    except Exception as exc:  # noqa: BLE001 - convert to bounded queue error
        try:
            run_control([
                "fail", intake_key,
                "--error-code", "lake_write_failed",
                "--error-message", "Diary lake write failed; inspect provider-safe runtime logs",
                "--worker", "diary-adapter",
                "--actor", "diary-adapter",
            ])
        except Exception:
            pass
        raise RuntimeError("diary lake write failed") from exc

    run_control([
        "land", intake_key,
        "--lake-run-id", str(lake_result["run_id"]),
        "--manifest-key", str(lake_result["manifest_key"]),
        "--raw-key", str(lake_result["raw_key"]),
        "--bronze-key", str(lake_result["bronze_key"]),
        "--raw-sha256", digest,
        "--record-count", str(lake_result["record_count"]),
        "--worker", "diary-adapter",
        "--actor", "diary-adapter",
    ])
    run_control([
        "verify", intake_key,
        "--data-lake-uri", args.data_lake_uri,
        "--actor", "diary-adapter",
    ])
    json_print({
        "status": "verified",
        "intake_key": intake_key,
        "entry_date": entry_date.isoformat(),
        "record_count": int(lake_result["record_count"]),
        "idempotent": False,
    }, args.as_json)


def add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", dest="as_json", help="Print privacy-safe JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    register = sub.add_parser("register", help="Register the built-in Diary Markdown source as planned")
    add_json_flag(register)

    activate = sub.add_parser("activate", help="Activate the Diary Markdown source")
    add_json_flag(activate)

    ingest = sub.add_parser("ingest", help="Archive one canonical daily Markdown entry")
    ingest.add_argument("--date", required=True)
    ingest.add_argument("--entry", required=True, help="One Markdown filename inside the date directory")
    ingest.add_argument("--data-lake-uri", default=DEFAULT_LAKE_URI)
    add_json_flag(ingest)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "register":
            cmd_register(args)
        elif args.command == "activate":
            cmd_activate(args)
        elif args.command == "ingest":
            cmd_ingest(args)
        else:
            parser.error("unknown command")
    except (ValueError, RuntimeError, ClientConfigError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
