#!/usr/bin/env python3
"""Regression tests for safe Brave bookmark grouping."""

from __future__ import annotations

import json
import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts"))

from sync.organize_brave_bookmarks import GROUP_ORDER, organize_profile


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="solo-empire-bookmark-organizer-") as temp:
        profile = Path(temp) / "Default"
        profile.mkdir()
        path = profile / "Bookmarks"
        path.write_text(
            json.dumps(
                {
                    "roots": {
                        "bookmark_bar": {
                            "children": [
                                {"id": "1", "name": "Homer", "type": "url", "url": "https://homer.local/"},
                                {"id": "2", "name": "Anki", "type": "url", "url": "https://ankiweb.net/"},
                                {"id": "3", "name": "Draw", "type": "url", "url": "https://quickposes.com/"},
                                {"id": "4", "name": "Music", "type": "url", "url": "https://music.youtube.com/"},
                                {"id": "5", "name": "Blender", "type": "url", "url": "https://studio.blender.org/"},
                                {"id": "6", "name": "Code", "type": "url", "url": "https://refactoring.guru/"},
                            ]
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        preview = organize_profile(path)
        assert preview["moved"] == 6
        assert preview["changed"] is True
        assert not list(profile.glob("Bookmarks.solo-empire-*.bak"))

        applied = organize_profile(path, apply=True, check_process=False)
        assert applied["applied"] is True
        assert Path(applied["backup"]).is_file()
        payload = json.loads(path.read_text(encoding="utf-8"))
        folders = payload["roots"]["bookmark_bar"]["children"]
        assert [folder["name"] for folder in folders] == list(GROUP_ORDER)
        assert all(len(folder["children"]) == 1 for folder in folders)

        second = organize_profile(path, apply=True, check_process=False)
        assert second["moved"] == 0
        assert "backup" not in second

    print("brave_bookmark_organizer_test: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
