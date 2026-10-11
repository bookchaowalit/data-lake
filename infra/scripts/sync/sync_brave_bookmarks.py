#!/usr/bin/env python3
"""Sync local Brave bookmarks into the Solo Empire data lake.

The direction is intentionally one-way: Brave JSON -> immutable lake objects. The adapter never writes back to Brave.

Examples:
    python3 sync_brave_bookmarks.py --dry-run --json
    python3 sync_brave_bookmarks.py --json
    python3 sync_brave_bookmarks.py --search "openai"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_ROOT / "utils"))
sys.path.insert(0, str(SCRIPTS_ROOT))

from _env import PROJECT_ROOT  # noqa: E402
from data_lake.ingest import ingest_payload  # noqa: E402


DEFAULT_BOOKMARKS_ROOT = Path(
    os.environ.get(
        "BRAVE_BOOKMARKS_ROOT",
        str(Path.home() / ".config" / "BraveSoftware" / "Brave-Browser"),
    )
)
DEFAULT_DATA_LAKE_URI = os.environ.get(
    "SOLO_EMPIRE_DATA_LAKE_URI",
    os.environ.get("DATA_LAKE_URI", str(PROJECT_ROOT / "data" / "lake")),
)
LAKE_SOURCE = "brave"
LAKE_DOMAIN = "knowledge"
LAKE_DATASET = "browser_bookmarks"
LAKE_TABLE = "bronze/domain=knowledge/dataset=browser_bookmarks/schema_version=1"


@dataclass(frozen=True)
class ProfileSnapshot:
    profile_name: str
    path: Path
    raw: bytes
    records: tuple[dict[str, Any], ...]


def discover_profile_files(bookmarks_root: Path) -> list[tuple[str, Path]]:
    """Find Brave profile bookmark files without reading browser credentials."""
    root = bookmarks_root.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Brave profile directory not found: {root}")

    profiles = [
        (path.parent.name, path)
        for path in sorted(root.glob("*/Bookmarks"))
        if path.is_file()
    ]
    if not profiles:
        raise FileNotFoundError(f"No Brave Bookmarks files found under: {root}")
    return profiles


def _stable_bookmark_id(profile_name: str, node: dict[str, Any], folder_path: str) -> str:
    guid = str(node.get("guid") or "").strip()
    if guid:
        identity = f"{profile_name}\0guid\0{guid}"
    else:
        # Older Chromium files may not have GUIDs. URL + folder keeps a title
        # edit from creating a duplicate, while remaining deterministic.
        identity = f"{profile_name}\0url\0{folder_path}\0{node.get('url', '')}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return f"{profile_name}:{digest}"


def _walk_nodes(
    profile_name: str,
    node: dict[str, Any],
    parent_path: tuple[str, ...],
    records: list[dict[str, Any]],
    position: int = 0,
) -> None:
    node_type = str(node.get("type") or "")
    node_name = str(node.get("name") or "").strip()
    current_path = parent_path
    if node_type == "folder" and node_name:
        current_path = (*parent_path, node_name)

    children = node.get("children")
    if isinstance(children, list):
        for position, child in enumerate(children):
            if isinstance(child, dict):
                _walk_nodes(profile_name, child, current_path, records, position)

    if node_type != "url":
        return

    url = str(node.get("url") or "").strip()
    if not url:
        return
    folder_path = "/".join(current_path)
    title = node_name or url
    records.append(
        {
            "id": _stable_bookmark_id(profile_name, node, folder_path),
            "guid": str(node.get("guid") or "") or None,
            "profile": profile_name,
            "title": title,
            "url": url,
            "folder_path": folder_path,
            "position": position,
            "date_added": str(node.get("date_added") or "") or None,
            "date_modified": str(node.get("date_modified") or "") or None,
        }
    )


def parse_bookmarks(profile_name: str, raw: bytes) -> list[dict[str, Any]]:
    """Flatten URL nodes while retaining folder paths and source identifiers."""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid Brave bookmark JSON ({type(exc).__name__})") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("roots"), dict):
        raise ValueError("invalid Brave bookmark structure")

    records: list[dict[str, Any]] = []
    for root_name, root in sorted(payload["roots"].items()):
        if not isinstance(root, dict):
            continue
        label = str(root.get("name") or root_name).strip()
        _walk_nodes(profile_name, root, (label,) if label else (), records)
    return records


def read_profiles(bookmarks_root: Path) -> list[ProfileSnapshot]:
    snapshots: list[ProfileSnapshot] = []
    for profile_name, path in discover_profile_files(bookmarks_root):
        raw = path.read_bytes()
        records = tuple(parse_bookmarks(profile_name, raw))
        snapshots.append(ProfileSnapshot(profile_name, path, raw, records))
    return snapshots


def _event_id(bookmark_id: str) -> str:
    return hashlib.sha256(f"{LAKE_SOURCE}\0{bookmark_id}".encode("utf-8")).hexdigest()


def _safe_lake_result(result: dict[str, Any], profile_name: str) -> dict[str, Any]:
    return {
        "profile": profile_name,
        "run_id": result.get("run_id"),
        "record_count": result.get("record_count", 0),
        "raw_key": result.get("raw_key"),
        "bronze_key": result.get("bronze_key"),
        "manifest_key": result.get("manifest_key"),
    }


def sync_bookmarks(
    *,
    bookmarks_root: Path = DEFAULT_BOOKMARKS_ROOT,
    data_lake_uri: str = DEFAULT_DATA_LAKE_URI,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Read all Brave profiles and ingest them into the data lake idempotently."""
    snapshots = read_profiles(bookmarks_root)
    total_records = sum(len(snapshot.records) for snapshot in snapshots)
    result: dict[str, Any] = {
        "pipeline": "brave_bookmarks",
        "status": "dry_run" if dry_run else "success",
        "profiles": len(snapshots),
        "records_read": total_records,
        "profile_records": {
            snapshot.profile_name: len(snapshot.records) for snapshot in snapshots
        },
    }
    if dry_run:
        return result

    lake_runs: list[dict[str, Any]] = []
    for snapshot in snapshots:
        if not snapshot.records:
            continue
        lake_result = ingest_payload(
            snapshot.raw,
            list(snapshot.records),
            source=LAKE_SOURCE,
            domain=LAKE_DOMAIN,
            dataset=LAKE_DATASET,
            data_lake_uri=data_lake_uri,
            input_format="json",
            schema_version="1",
            source_record_id_field="id",
            metadata={
                "adapter": "sync_brave_bookmarks",
                "contract": "browser_bookmarks.v1",
                "profile": snapshot.profile_name,
            },
            privacy_class="private",
            retention_class="operational",
        )
        lake_runs.append(_safe_lake_result(lake_result, snapshot.profile_name))
    result["records_persisted"] = total_records
    result["lake_runs"] = lake_runs
    return result


def list_bookmarks(
    query: str | None,
    *,
    bookmarks_root: Path = DEFAULT_BOOKMARKS_ROOT,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Search the live Brave profiles read-only (no local database projection)."""
    needle = (query or "").lower()
    matches: list[dict[str, Any]] = []
    for snapshot in read_profiles(bookmarks_root):
        for record in snapshot.records:
            haystack = f"{record['title']} {record['url']} {record['folder_path']}".lower()
            if needle and needle not in haystack:
                continue
            matches.append(
                {
                    "bookmark_id": record["id"],
                    "profile_name": record["profile"],
                    "title": record["title"],
                    "url": record["url"],
                    "folder_path": record["folder_path"],
                }
            )
    matches.sort(key=lambda item: (item["profile_name"], item["folder_path"], item["title"]))
    return matches[: max(1, min(limit, 1000))]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bookmarks-root", type=Path, default=DEFAULT_BOOKMARKS_ROOT)
    parser.add_argument("--data-lake-uri", default=DEFAULT_DATA_LAKE_URI)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--search", help="Search the live Brave profiles instead of syncing")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.search is not None:
            result: Any = {
                "status": "success",
                "pipeline": "brave_bookmarks",
                "bookmarks": list_bookmarks(
                    args.search,
                    bookmarks_root=args.bookmarks_root,
                    limit=args.limit,
                ),
            }
        else:
            result = sync_bookmarks(
                bookmarks_root=args.bookmarks_root,
                data_lake_uri=args.data_lake_uri,
                dry_run=args.dry_run,
            )
        if args.as_json:
            print(json.dumps(result, ensure_ascii=False))
        elif args.search is not None:
            for bookmark in result["bookmarks"]:
                print(
                    f"{bookmark['title']} — {bookmark['url']} "
                    f"({bookmark['profile_name']}/{bookmark['folder_path']})"
                )
            print(f"Found {len(result['bookmarks'])} bookmark(s)")
        else:
            print(
                f"Brave bookmarks: {result['status']} | "
                f"{result['records_read']} read, "
                f"{result.get('records_persisted', 0)} ingested"
            )
        return 0
    except Exception as exc:
        result = {
            "status": "error",
            "pipeline": "brave_bookmarks",
            "error": type(exc).__name__,
        }
        if args.as_json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(f"Brave bookmark sync failed: {result['error']}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
