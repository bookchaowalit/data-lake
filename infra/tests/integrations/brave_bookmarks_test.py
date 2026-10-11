#!/usr/bin/env python3
"""Regression tests for the Brave bookmark lake-first adapter."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts" / "utils"))
sys.path.insert(0, str(ROOT / "infra" / "scripts"))

from sync.sync_brave_bookmarks import list_bookmarks, sync_bookmarks  # noqa: E402


def _write_profile(root: Path, *, title: str = "OpenAI", include_second: bool = True) -> None:
    profile = root / "Default"
    profile.mkdir(parents=True, exist_ok=True)
    children = [
        {
            "date_added": "13300000000000000",
            "guid": "guid-openai",
            "id": "1",
            "name": title,
            "type": "url",
            "url": "https://openai.com/",
        }
    ]
    if include_second:
        children.append(
            {
                "children": [
                    {
                        "date_added": "13300000000000001",
                        "guid": "guid-repo",
                        "id": "2",
                        "name": "Repository",
                        "type": "url",
                        "url": "https://github.com/",
                    }
                ],
                "id": "3",
                "name": "Work",
                "type": "folder",
            }
        )
    payload = {
        "checksum": "fixture",
        "roots": {
            "bookmark_bar": {
                "children": children,
                "name": "Bookmark Bar",
                "type": "folder",
            },
            "other": {"children": [], "name": "Other Bookmarks", "type": "folder"},
            "synced": {"children": [], "name": "Synced Bookmarks", "type": "folder"},
        },
        "version": 1,
    }
    (profile / "Bookmarks").write_text(json.dumps(payload), encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="solo-empire-brave-test-") as temp:
        root = Path(temp)
        bookmarks_root = root / "Brave-Browser"
        lake_root = root / "lake"

        _write_profile(bookmarks_root)
        first = sync_bookmarks(bookmarks_root=bookmarks_root, data_lake_uri=str(lake_root))
        assert first["status"] == "success"
        assert first["records_read"] == 2
        assert first["records_persisted"] == 2
        assert (lake_root / "landing").is_dir()
        assert (lake_root / "bronze").is_dir()
        assert (lake_root / "control" / "manifests").is_dir()

        dry = sync_bookmarks(bookmarks_root=bookmarks_root, data_lake_uri=str(lake_root), dry_run=True)
        assert dry["status"] == "dry_run"

        _write_profile(bookmarks_root, title="OpenAI Platform", include_second=False)
        found = list_bookmarks("OpenAI", bookmarks_root=bookmarks_root)
        assert len(found) == 1
        assert found[0]["title"] == "OpenAI Platform"
        assert list_bookmarks("github", bookmarks_root=bookmarks_root) == []

    print("brave_bookmarks_test: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
