#!/usr/bin/env python3
"""Organize direct Brave Bookmark Bar URLs into Solo Empire folders.

The command is dry-run by default. ``--apply`` is required to write back to
Brave, and refuses to run while Brave is open. A timestamped backup is created
beside the source file before the atomic replacement.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_ROOT / "utils"))
sys.path.insert(0, str(SCRIPTS_ROOT))

from _env import PROJECT_ROOT  # noqa: E402
from sync.sync_brave_bookmarks import (  # noqa: E402
    DEFAULT_BOOKMARKS_ROOT,
    discover_profile_files,
)


GROUP_ORDER = (
    "00 - Solo Empire & Operations",
    "01 - Development & Engineering",
    "02 - Design & Creative Assets",
    "03 - Art Practice & References",
    "04 - Learning",
    "05 - Media & Entertainment",
)


SUBFOLDER_ORDER: dict[str, tuple[str, ...]] = {
    GROUP_ORDER[0]: (
        "Internal Systems",
        "Automation & AI",
        "Infrastructure & Cloud",
        "Unsorted & Review",
    ),
    GROUP_ORDER[1]: (
        "Software Engineering",
        "Source Control & Collaboration",
        "DevOps & Platform",
        "Unsorted & Review",
    ),
    GROUP_ORDER[2]: (
        "Design Tools & Assets",
        "3D, Motion & Media",
        "Unsorted & Review",
    ),
    GROUP_ORDER[3]: (
        "Drawing Practice",
        "Reference & Inspiration",
        "Unsorted & Review",
    ),
    GROUP_ORDER[4]: (
        "Courses & Documentation",
        "AI & Data",
        "Business & Systems",
        "Spaced Repetition",
        "Unsorted & Review",
    ),
    GROUP_ORDER[5]: (
        "Video & Music",
        "Reading & Comics",
        "Unsorted & Review",
    ),
}


# Keep classification deterministic and provider-neutral. These are routing
# hints, not an attempt to infer private browsing history or visit content.
CLASSIFICATION_RULES: tuple[tuple[tuple[str, str], tuple[str, ...], tuple[str, ...]], ...] = (
    ((GROUP_ORDER[0], "Internal Systems"), ("homer.local", "prefect.cloud", "proxmox", "portainer", "frappe", "erpnext", "n8n"), ("solo empire", "proxmox", "erpnext", "frappe")),
    ((GROUP_ORDER[0], "Automation & AI"), ("openai.com", "chatgpt.com", "claude.ai", "anthropic.com", "zapier.com", "make.com"), ("automation", "ai assistant", "chatgpt", "claude")),
    ((GROUP_ORDER[0], "Infrastructure & Cloud"), ("localhost", "127.0.0.1", "192.168."), ("server", "infrastructure", "homelab")),
    ((GROUP_ORDER[1], "Source Control & Collaboration"), ("github.com", "gitlab.com", "bitbucket.org", "perforce.com", "plasticscm.com"), ("github", "gitlab", "source control")),
    ((GROUP_ORDER[1], "Software Engineering"), ("refactoring.guru", "stackoverflow.com", "developer.mozilla.org", "npmjs.com", "pypi.org", "python.org"), ("software engineering", "programming", "coding")),
    ((GROUP_ORDER[1], "DevOps & Platform"), ("vercel.com", "cloudflare.com", "docker.com", "kubernetes.io", "aws.amazon.com", "zeplin.io"), ("devops", "cloud", "deployment", "platform")),
    ((GROUP_ORDER[2], "Design Tools & Assets"), ("figma.com", "canva.com", "adobe.com", "unsplash.com", "pexels.com", "freepik.com"), ("design", "creative asset", "stock")),
    ((GROUP_ORDER[2], "3D, Motion & Media"), ("blender.org", "blenderstudio.cn", "studio.blender.org"), ("blender", "3d", "motion")),
    ((GROUP_ORDER[3], "Drawing Practice"), ("line-of-action.com", "quickposes.com", "adorkastock.com"), ("figure drawing", "gesture", "drawing practice")),
    ((GROUP_ORDER[3], "Reference & Inspiration"), ("artstation.com", "behance.net"), ("art reference", "artist reference", "inspiration")),
    ((GROUP_ORDER[4], "Spaced Repetition"), ("ankiweb.net", "remnote.com"), ("anki", "spaced repetition", "flashcard")),
    ((GROUP_ORDER[4], "Courses & Documentation"), ("coursera.org", "udemy.com", "edx.org", "khanacademy.org", "pluralsight.com", "readthedocs.io", "roadmap.sh"), ("course", "documentation", "tutorial", "learning")),
    ((GROUP_ORDER[4], "AI & Data"), ("huggingface.co", "kaggle.com", "arxiv.org", "paperswithcode.com", "dbt.com"), ("machine learning", "data engineering", "data", "ai research")),
    ((GROUP_ORDER[4], "Business & Systems"), ("asana.com", "linear.app", "notion.so", "hubspot.com", "erpnext.com"), ("business system", "crm", "erp", "project management")),
    ((GROUP_ORDER[5], "Video & Music"), ("youtube.com", "spotify.com", "netflix.com"), ("music", "video", "entertainment")),
    ((GROUP_ORDER[5], "Reading & Comics"), ("comicbookreadingorders.com", "goodreads.com"), ("comic", "reading", "book")),
)


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def classify_bookmark_path(node: dict[str, Any]) -> tuple[str, str]:
    """Map a URL node to a stable top-level group and subfolder."""
    url = str(node.get("url") or "").strip()
    title = str(node.get("name") or "").lower()
    host = _host(url)

    if host.startswith("192.168."):
        return GROUP_ORDER[0], "Infrastructure & Cloud"
    for (group, subfolder), host_tokens, title_tokens in CLASSIFICATION_RULES:
        if any(token in host for token in host_tokens) or any(token in title for token in title_tokens):
            return group, subfolder
    return GROUP_ORDER[2], "Unsorted & Review"


def classify_bookmark(node: dict[str, Any]) -> str:
    """Backward-compatible top-level classification helper."""
    return classify_bookmark_path(node)[0]


def _brave_running() -> bool:
    for process_name in ("brave", "brave-browser", "brave-browser-stable"):
        result = subprocess.run(
            ["pgrep", "-x", process_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            return True
    return False


def _chromium_timestamp() -> str:
    unix_microseconds = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
    return str(unix_microseconds + 11_644_473_600_000_000)


def _new_folder(name: str, node_id: int, timestamp: str) -> dict[str, Any]:
    return {
        "children": [],
        "date_added": timestamp,
        "date_modified": timestamp,
        "id": str(node_id),
        "name": name,
        "type": "folder",
    }


def _max_numeric_id(node: Any) -> int:
    maximum = 0
    if isinstance(node, dict):
        raw_id = str(node.get("id") or "")
        if raw_id.isdigit():
            maximum = int(raw_id)
        children = node.get("children")
        if isinstance(children, list):
            maximum = max([maximum, *(_max_numeric_id(child) for child in children)])
    elif isinstance(node, list):
        maximum = max([maximum, *(_max_numeric_id(child) for child in node)])
    return maximum


def _collect_folder_urls(
    folder: dict[str, Any],
    folder_path: tuple[str, ...],
    records: list[tuple[dict[str, Any], tuple[str, ...]]],
) -> None:
    children = folder.get("children")
    if not isinstance(children, list):
        return
    for child in children:
        if not isinstance(child, dict):
            continue
        if child.get("type") == "url":
            records.append((child, folder_path))
        elif child.get("type") == "folder":
            name = str(child.get("name") or "").strip()
            _collect_folder_urls(child, (*folder_path, name) if name else folder_path, records)


def _index_folders(
    folder: dict[str, Any],
    folder_path: tuple[str, ...],
    index: dict[tuple[str, ...], dict[str, Any]],
) -> None:
    index.setdefault(folder_path, folder)
    children = folder.get("children")
    if not isinstance(children, list):
        return
    for child in children:
        if isinstance(child, dict) and child.get("type") == "folder":
            name = str(child.get("name") or "").strip()
            if name:
                _index_folders(child, (*folder_path, name), index)


def _organize_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    roots = payload.get("roots")
    if not isinstance(roots, dict):
        raise ValueError("invalid Brave bookmark structure: roots is missing")
    bookmark_bar = roots.get("bookmark_bar")
    if not isinstance(bookmark_bar, dict) or not isinstance(bookmark_bar.get("children"), list):
        raise ValueError("invalid Brave bookmark structure: bookmark_bar is missing")

    children = list(bookmark_bar["children"])
    records: list[tuple[dict[str, Any], tuple[str, ...]]] = []
    existing_groups: dict[str, dict[str, Any]] = {}
    for node in children:
        if not isinstance(node, dict):
            continue
        if node.get("type") == "url":
            records.append((node, ()))
        elif node.get("type") == "folder" and str(node.get("name") or "") in GROUP_ORDER:
            group_name = str(node.get("name"))
            existing_groups.setdefault(group_name, node)
            _collect_folder_urls(node, (group_name,), records)

    if not records:
        return payload, {"moved": 0, "changed": False, "groups": {}}

    existing_folders: dict[tuple[str, ...], dict[str, Any]] = {}
    for group_name, group_node in existing_groups.items():
        _index_folders(group_node, (group_name,), existing_folders)

    max_id = _max_numeric_id(payload)
    timestamp = _chromium_timestamp()
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    moved = 0
    for node, current_path in records:
        target_path = classify_bookmark_path(node)
        grouped.setdefault(target_path, []).append(copy.deepcopy(node))
        if tuple(current_path[:2]) != target_path:
            moved += 1

    next_id = max_id + 1

    def folder_for(path: tuple[str, ...]) -> dict[str, Any]:
        nonlocal next_id
        existing = existing_folders.get(path)
        if existing is not None:
            node = copy.deepcopy(existing)
        else:
            node = _new_folder(path[-1], next_id, timestamp)
            next_id += 1
        node["children"] = []
        return node

    group_nodes: list[dict[str, Any]] = []
    subgroup_counts: dict[str, dict[str, int]] = {}
    for group_name in GROUP_ORDER:
        sub_nodes: list[dict[str, Any]] = []
        for subfolder in SUBFOLDER_ORDER[group_name]:
            urls = grouped.get((group_name, subfolder), [])
            if not urls:
                continue
            sub_node = folder_for((group_name, subfolder))
            sub_node["children"] = urls
            sub_nodes.append(sub_node)
        if not sub_nodes:
            continue
        group_node = folder_for((group_name,))
        group_node["children"] = sub_nodes
        group_nodes.append(group_node)
        subgroup_counts[group_name] = {
            str(node["name"]): len(node.get("children") or []) for node in sub_nodes
        }

    untouched = [
        node
        for node in children
        if not (isinstance(node, dict) and node.get("type") == "url")
        and not (isinstance(node, dict) and str(node.get("name")) in GROUP_ORDER)
    ]
    updated_children = group_nodes + untouched
    changed = updated_children != children
    if not changed:
        return payload, {
            "moved": 0,
            "changed": False,
            "groups": {group: sum(subgroups.values()) for group, subgroups in subgroup_counts.items()},
            "subgroups": subgroup_counts,
        }

    bookmark_bar["children"] = updated_children
    bookmark_bar["date_modified"] = timestamp
    for group_node in group_nodes:
        group_node["date_modified"] = timestamp
        for sub_node in group_node.get("children", []):
            sub_node["date_modified"] = timestamp
    summary = {
        "moved": moved,
        "changed": True,
        "groups": {group: sum(subgroups.values()) for group, subgroups in subgroup_counts.items()},
        "subgroups": subgroup_counts,
    }
    return payload, summary


def _iter_urls(node: Any) -> list[dict[str, Any]]:
    if not isinstance(node, dict):
        return []
    if node.get("type") == "url":
        return [node]
    children = node.get("children")
    if not isinstance(children, list):
        return []
    result: list[dict[str, Any]] = []
    for child in children:
        result.extend(_iter_urls(child))
    return result


def append_url_to_folder(
    payload: dict[str, Any],
    folder_path: tuple[str, ...],
    bookmark: dict[str, Any],
) -> bool:
    """Append one URL to a bookmark-bar folder path unless the URL exists."""
    roots = payload.get("roots")
    bookmark_bar = roots.get("bookmark_bar") if isinstance(roots, dict) else None
    if not isinstance(bookmark_bar, dict) or not isinstance(bookmark_bar.get("children"), list):
        raise ValueError("invalid Brave bookmark structure: bookmark_bar is missing")
    if not folder_path or any(not str(part).strip() for part in folder_path):
        raise ValueError("folder_path must contain at least one non-empty folder")
    if any(str(bookmark.get("url") or "") == str(existing.get("url") or "") for existing in _iter_urls(bookmark_bar)):
        return False

    max_id = _max_numeric_id(payload)
    next_id = max_id + 1
    parent = bookmark_bar
    parent_path: list[str] = []
    timestamp = _chromium_timestamp()
    for name in folder_path:
        parent_path.append(name)
        children = parent.setdefault("children", [])
        existing = next(
            (
                child
                for child in children
                if isinstance(child, dict)
                and child.get("type") == "folder"
                and str(child.get("name") or "") == name
            ),
            None,
        )
        if existing is None:
            existing = _new_folder(name, next_id, timestamp)
            next_id += 1
            children.append(existing)
        parent = existing
    parent.setdefault("children", []).append(copy.deepcopy(bookmark))
    parent["date_modified"] = timestamp
    bookmark_bar["date_modified"] = timestamp
    return True


def write_profile_payload(
    path: Path,
    original_raw: bytes,
    updated: dict[str, Any],
    *,
    check_process: bool = True,
) -> str:
    """Atomically write a Brave profile after a process/hash safety check."""
    if check_process and _brave_running():
        raise RuntimeError("Brave is running; close all Brave windows before applying bookmark changes")

    current_raw = path.read_bytes()
    if hashlib.sha256(current_raw).digest() != hashlib.sha256(original_raw).digest():
        raise RuntimeError("Brave Bookmarks changed during preparation; rerun the command")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = path.with_name(f"Bookmarks.solo-empire-{timestamp}.bak")
    shutil.copy2(path, backup_path)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=".Bookmarks.solo-empire-", delete=False
    ) as handle:
        temporary_path = Path(handle.name)
        json.dump(updated, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary_path, path)
    return str(backup_path)


def organize_profile(path: Path, *, apply: bool = False, check_process: bool = True) -> dict[str, Any]:
    """Preview or apply one profile, returning counts only (never URLs)."""
    original_raw = path.read_bytes()
    try:
        payload = json.loads(original_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid Brave bookmark JSON ({type(exc).__name__})") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid Brave bookmark structure")

    updated, summary = _organize_payload(payload)
    result: dict[str, Any] = {
        "profile": path.parent.name,
        "path": str(path),
        **summary,
    }
    if not apply or not summary["changed"]:
        return result
    if check_process and _brave_running():
        raise RuntimeError("Brave is running; close all Brave windows before --apply")

    result["backup"] = write_profile_payload(
        path,
        original_raw,
        updated,
        check_process=check_process,
    )
    result["applied"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bookmarks-root", type=Path, default=DEFAULT_BOOKMARKS_ROOT)
    parser.add_argument("--profile", help="Only organize this profile, e.g. Default")
    parser.add_argument("--apply", action="store_true", help="Write the organization after Brave is closed")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    try:
        profiles = discover_profile_files(args.bookmarks_root)
        if args.profile:
            profiles = [(name, path) for name, path in profiles if name == args.profile]
            if not profiles:
                raise FileNotFoundError(f"Brave profile not found: {args.profile}")
        results = [organize_profile(path, apply=args.apply) for _name, path in profiles]
        output: dict[str, Any] = {
            "status": "success",
            "mode": "apply" if args.apply else "dry_run",
            "profiles": results,
            "moved": sum(int(item.get("moved", 0)) for item in results),
        }
        if args.as_json:
            print(json.dumps(output, ensure_ascii=False))
        else:
            print(f"Brave bookmark organization: {output['mode']} | moved {output['moved']} bookmark(s)")
            for item in results:
                print(f"  {item['profile']}: {item['groups']}")
        return 0
    except Exception as exc:
        output = {"status": "error", "error": type(exc).__name__}
        if args.as_json:
            print(json.dumps(output, ensure_ascii=False))
        else:
            print(f"Brave bookmark organization failed: {output['error']}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
