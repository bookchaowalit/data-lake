#!/usr/bin/env python3
"""Regression tests for the gated Brave bookmark workflow."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts" / "utils"))
sys.path.insert(0, str(ROOT / "infra" / "scripts"))

from sync import brave_bookmark_workflow as workflow  # noqa: E402


def _write_profile(root: Path) -> Path:
    profile = root / "Default"
    profile.mkdir(parents=True, exist_ok=True)
    path = profile / "Bookmarks"
    path.write_text(
        json.dumps(
            {
                "roots": {
                    "bookmark_bar": {
                        "children": [
                            {"id": "1", "name": "Anki", "type": "url", "url": "https://ankiweb.net/"},
                            {"id": "2", "name": "GitHub", "type": "url", "url": "https://github.com/"},
                        ],
                        "name": "Bookmark Bar",
                        "type": "folder",
                    },
                    "other": {"children": [], "name": "Other Bookmarks", "type": "folder"},
                    "synced": {"children": [], "name": "Synced Bookmarks", "type": "folder"},
                },
                "version": 1,
            }
        ),
        encoding="utf-8",
    )
    return path


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="solo-empire-bookmark-workflow-") as temp:
        root = Path(temp)
        bookmarks_root = root / "Brave-Browser"
        runtime_dir = root / "runtime"
        lake_root = root / "lake"
        profile_path = _write_profile(bookmarks_root)

        proposal_args = argparse.Namespace(
            url="https://example.com/knowledge",
            title="Knowledge Web App",
            profile="Default",
            folder="04 - Learning/Business & Systems",
            source_kind="ai_discovery",
            source_ref="technology-watch",
            reason="Useful reference for future business-systems learning",
            runtime_dir=runtime_dir,
        )
        proposed = workflow.propose(proposal_args)
        assert proposed["status"] == "created"
        assert "url" not in proposed
        proposal_id = proposed["proposal_id"]

        private_proposal = runtime_dir / "inbox" / f"{proposal_id}.json"
        assert private_proposal.is_file()
        assert "https://example.com/knowledge" in private_proposal.read_text(encoding="utf-8")

        try:
            workflow.propose(
                argparse.Namespace(
                    url="https://example.com/?token=secret-value",
                    title="Unsafe URL",
                    profile="Default",
                    folder=None,
                    source_kind="ai_discovery",
                    source_ref=None,
                    reason=None,
                    runtime_dir=runtime_dir,
                )
            )
        except ValueError as exc:
            assert "secret-shaped" in str(exc)
        else:
            raise AssertionError("secret-shaped URL was accepted")

        reviewed = workflow.review(
            argparse.Namespace(runtime_dir=runtime_dir, approve=proposal_id, reject=None)
        )
        assert reviewed["status"] == "approved"

        original_running = workflow._brave_running
        workflow._brave_running = lambda: False
        try:
            applied = workflow.apply(
                argparse.Namespace(
                    bookmarks_root=bookmarks_root,
                    runtime_dir=runtime_dir,
                    profile=None,
                    data_lake_uri=str(lake_root),
                )
            )
        finally:
            workflow._brave_running = original_running

        assert applied["status"] == "success"
        assert applied["applied"] == 1
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
        bar = payload["roots"]["bookmark_bar"]
        learning = next(folder for folder in bar["children"] if folder["name"] == "04 - Learning")
        business = next(folder for folder in learning["children"] if folder["name"] == "Business & Systems")
        assert business["children"][0]["url"] == "https://example.com/knowledge"

        listed = workflow.review(argparse.Namespace(runtime_dir=runtime_dir, approve=None, reject=None))
        assert listed["counts"]["applied"] == 1

        # The scheduler must never write while Brave is running.
        workflow._brave_running = lambda: True
        try:
            skipped = workflow._apply_approved(
                bookmarks_root=bookmarks_root,
                runtime_dir=runtime_dir,
                profile_filter=None,
                check_process=True,
                skip_if_running=True,
            )
        finally:
            workflow._brave_running = original_running
        assert skipped["status"] == "skipped_browser_running"

    print("brave_bookmark_workflow_test: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
