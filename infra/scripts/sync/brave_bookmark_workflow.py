#!/usr/bin/env python3
"""Safe Brave bookmark proposals, review, application, and maintenance.

The live Brave profile remains the browser source of truth. This workflow adds
an explicit proposal boundary for URLs found by an agent or by the user:

    propose -> review/approve -> apply when Brave is closed -> lake sync

Proposal JSON is private runtime state under ``data/runtime`` and is never
written to Git. The command never stores raw chat content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_ROOT / "utils"))
sys.path.insert(0, str(SCRIPTS_ROOT))

from _env import PROJECT_ROOT  # noqa: E402
from sync.organize_brave_bookmarks import (  # noqa: E402
    GROUP_ORDER,
    SUBFOLDER_ORDER,
    _max_numeric_id,
    _brave_running,
    _organize_payload,
    append_url_to_folder,
    discover_profile_files,
    write_profile_payload,
)
from sync.sync_brave_bookmarks import (  # noqa: E402
    DEFAULT_BOOKMARKS_ROOT,
    DEFAULT_DATA_LAKE_URI,
    sync_bookmarks,
)


SCHEMA_VERSION = 1
DEFAULT_RUNTIME_DIR = Path(
    os.environ.get(
        "SOLO_EMPIRE_BOOKMARK_RUNTIME",
        str(PROJECT_ROOT / "data" / "runtime" / "browser-bookmarks"),
    )
)
SECRET_PATTERNS = (
    re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret)\s*[=:]"),
    re.compile(r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|AKIA[0-9A-Z]{12,})"),
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._-]{12,}"),
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_path(runtime_dir: Path, proposal_id: str) -> Path:
    return runtime_dir / "inbox" / f"{proposal_id}.json"


def _safe_text(value: str, *, field: str, maximum: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must not be empty")
    if len(text) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    if "\x00" in text:
        raise ValueError(f"{field} contains an invalid character")
    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        raise ValueError(f"{field} is secret-shaped and was rejected")
    return text


def normalize_url(raw_url: str) -> str:
    """Validate a bookmark URL without following it or making a network call."""
    raw = _safe_text(raw_url, field="url", maximum=4096)
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url must be an absolute http(s) URL")
    if parsed.username or parsed.password or "@" in parsed.netloc:
        raise ValueError("url must not contain embedded credentials")
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            parsed.query,
            parsed.fragment,
        )
    )


def _allowed_folder_paths() -> dict[str, tuple[str, str]]:
    return {
        f"{group}/{subfolder}": (group, subfolder)
        for group in GROUP_ORDER
        for subfolder in SUBFOLDER_ORDER[group]
    }


def normalize_folder_path(raw_folder: str | None, *, node: dict[str, Any]) -> tuple[str, str]:
    if raw_folder:
        value = "/".join(part.strip() for part in str(raw_folder).strip("/").split("/") if part.strip())
        allowed = _allowed_folder_paths().get(value)
        if allowed is None:
            raise ValueError("folder must be an approved Solo Empire folder/subfolder path")
        return allowed

    # Import lazily to keep this workflow's validation dependency narrow.
    from sync.organize_brave_bookmarks import classify_bookmark_path

    return classify_bookmark_path(node)


def _proposal_id(profile: str, url: str) -> str:
    digest = hashlib.sha256(f"{profile}\0{url}".encode("utf-8")).hexdigest()[:20]
    return f"brave-{digest}"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        temporary_path = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary_path, path)


def _load_proposal(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported bookmark proposal schema")
    required = ("proposal_id", "profile", "title", "url", "folder_path", "status")
    if any(not payload.get(key) for key in required):
        raise ValueError("bookmark proposal is missing a required field")
    if payload.get("status") not in {"candidate", "approved", "applied", "rejected"}:
        raise ValueError("bookmark proposal has an invalid status")
    return payload


def _load_proposals(runtime_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    inbox = runtime_dir / "inbox"
    if not inbox.is_dir():
        return [], []
    proposals: list[dict[str, Any]] = []
    warnings: list[str] = []
    for path in sorted(inbox.glob("*.json")):
        try:
            proposals.append(_load_proposal(path))
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            warnings.append(f"invalid:{path.name}:{type(exc).__name__}")
    return proposals, warnings


def _summary(proposal: dict[str, Any]) -> dict[str, Any]:
    """Return a non-sensitive proposal summary; never print its URL."""
    return {
        "proposal_id": proposal["proposal_id"],
        "profile": proposal["profile"],
        "folder_path": proposal["folder_path"],
        "status": proposal["status"],
        "source_kind": proposal.get("source_kind", "unknown"),
    }


def propose(args: argparse.Namespace) -> dict[str, Any]:
    url = normalize_url(args.url)
    title = _safe_text(args.title, field="title", maximum=300)
    profile = _safe_text(args.profile, field="profile", maximum=160)
    source_kind = _safe_text(args.source_kind, field="source_kind", maximum=64)
    source_ref = _safe_text(args.source_ref, field="source_ref", maximum=500) if args.source_ref else None
    reason = _safe_text(args.reason, field="reason", maximum=500) if args.reason else None
    node = {"name": title, "url": url, "type": "url"}
    folder = normalize_folder_path(args.folder, node=node)
    proposal_id = _proposal_id(profile, url)
    runtime_dir = args.runtime_dir
    path = _json_path(runtime_dir, proposal_id)

    if path.is_file():
        existing = _load_proposal(path)
        if existing.get("url") != url:
            raise ValueError("proposal id collision detected; inspect the private inbox")
        if existing.get("status") in {"applied", "rejected"}:
            return {**_summary(existing), "status": "duplicate"}
        proposal = {
            **existing,
            "title": title,
            "folder_path": list(folder),
            "source_kind": source_kind,
            "source_ref": source_ref,
            "reason": reason,
            "updated_at": _now(),
        }
        result_status = "updated"
    else:
        proposal = {
            "schema_version": SCHEMA_VERSION,
            "proposal_id": proposal_id,
            "status": "candidate",
            "profile": profile,
            "title": title,
            "url": url,
            "folder_path": list(folder),
            "source_kind": source_kind,
            "source_ref": source_ref,
            "reason": reason,
            "created_at": _now(),
            "updated_at": _now(),
        }
        result_status = "created"
    _write_json(path, proposal)
    return {**_summary(proposal), "status": result_status}


def review(args: argparse.Namespace) -> dict[str, Any]:
    proposals, warnings = _load_proposals(args.runtime_dir)
    if args.approve or args.reject:
        proposal_id = args.approve or args.reject
        path = _json_path(args.runtime_dir, proposal_id)
        if not path.is_file():
            raise FileNotFoundError(f"bookmark proposal not found: {proposal_id}")
        proposal = _load_proposal(path)
        if proposal.get("status") not in {"candidate", "approved"}:
            raise ValueError("only candidate or approved proposals can be reviewed")
        proposal["status"] = "approved" if args.approve else "rejected"
        proposal["updated_at"] = _now()
        proposal["reviewed_at"] = _now()
        _write_json(path, proposal)
        return {"status": proposal["status"], **_summary(proposal)}

    counts: dict[str, int] = {}
    for proposal in proposals:
        status = str(proposal.get("status"))
        counts[status] = counts.get(status, 0) + 1
    return {
        "status": "success",
        "counts": counts,
        "proposals": [_summary(proposal) for proposal in proposals],
        "warnings": warnings,
    }


def _new_bookmark_node(proposal: dict[str, Any], next_id: int) -> dict[str, Any]:
    chromium_timestamp = str(int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 11_644_473_600_000_000)
    return {
        "date_added": chromium_timestamp,
        "date_modified": chromium_timestamp,
        "guid": str(uuid.uuid4()),
        "id": str(next_id),
        "name": proposal["title"],
        "type": "url",
        "url": proposal["url"],
    }


def _apply_approved(
    *,
    bookmarks_root: Path,
    runtime_dir: Path,
    profile_filter: str | None,
    check_process: bool,
    skip_if_running: bool,
) -> dict[str, Any]:
    proposals, warnings = _load_proposals(runtime_dir)
    approved = [
        proposal
        for proposal in proposals
        if proposal.get("status") == "approved"
        and (profile_filter is None or proposal.get("profile") == profile_filter)
    ]
    if check_process and _brave_running():
        if skip_if_running:
            return {
                "status": "skipped_browser_running",
                "approved": len(approved),
                "applied": 0,
                "warnings": warnings,
            }
        raise RuntimeError("Brave is running; close all Brave windows before applying bookmark changes")

    profiles = discover_profile_files(bookmarks_root)
    by_profile: dict[str, list[dict[str, Any]]] = {}
    for proposal in approved:
        by_profile.setdefault(str(proposal["profile"]), []).append(proposal)

    profile_results: list[dict[str, Any]] = []
    applied = 0
    organized = 0
    duplicates = 0
    for profile_name, path in profiles:
        if profile_name not in by_profile and profile_filter not in {None, profile_name}:
            continue
        original_raw = path.read_bytes()
        try:
            payload = json.loads(original_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid Brave bookmark JSON ({type(exc).__name__})") from exc
        if not isinstance(payload, dict):
            raise ValueError("invalid Brave bookmark structure")

        updated, organization = _organize_payload(payload)
        organization_changed = bool(organization.get("changed"))
        profile_proposals = by_profile.get(profile_name, [])
        proposal_results: list[dict[str, Any]] = []
        next_id = _max_numeric_id(payload) + 1
        for proposal in profile_proposals:
            node = _new_bookmark_node(proposal, next_id)
            next_id += 1
            folder_path = tuple(str(part) for part in proposal["folder_path"])
            added = append_url_to_folder(updated, folder_path, node)
            if added:
                proposal_results.append({"proposal_id": proposal["proposal_id"], "result": "added"})
                applied += 1
            else:
                proposal_results.append({"proposal_id": proposal["proposal_id"], "result": "duplicate"})
                duplicates += 1

        changed = organization_changed or bool(proposal_results and any(item["result"] == "added" for item in proposal_results))
        backup = None
        if changed:
            if check_process and _brave_running():
                if skip_if_running:
                    return {
                        "status": "skipped_browser_running",
                        "approved": len(approved),
                        "applied": 0,
                        "warnings": warnings,
                    }
                raise RuntimeError("Brave started while bookmark changes were being prepared")
            backup = write_profile_payload(path, original_raw, updated, check_process=False)
            organized += int(organization_changed)
        for proposal in profile_proposals:
            result = next(item["result"] for item in proposal_results if item["proposal_id"] == proposal["proposal_id"])
            proposal["status"] = "applied"
            proposal["apply_result"] = result
            proposal["applied_at"] = _now()
            proposal["updated_at"] = _now()
            _write_json(_json_path(runtime_dir, str(proposal["proposal_id"])), proposal)
        profile_results.append(
            {
                "profile": profile_name,
                "organized": organization_changed,
                "proposals": proposal_results,
                "backup_created": bool(backup),
            }
        )

    return {
        "status": "success",
        "approved": len(approved),
        "applied": applied,
        "duplicates": duplicates,
        "organized": organized,
        "profiles": profile_results,
        "warnings": warnings,
    }


def apply(args: argparse.Namespace) -> dict[str, Any]:
    result = _apply_approved(
        bookmarks_root=args.bookmarks_root,
        runtime_dir=args.runtime_dir,
        profile_filter=args.profile,
        check_process=True,
        skip_if_running=False,
    )
    if result.get("status") == "success":
        result["sync"] = sync_bookmarks(
            bookmarks_root=args.bookmarks_root,
            data_lake_uri=args.data_lake_uri,
        )
    return result


def maintain(args: argparse.Namespace) -> dict[str, Any]:
    try:
        profiles = discover_profile_files(args.bookmarks_root)
    except FileNotFoundError:
        return {
            "status": "skipped_profile_unavailable",
            "sync": {"status": "skipped_profile_unavailable"},
            "organization": [],
            "apply": {"status": "not_attempted"},
        }

    sync_result = sync_bookmarks(
        bookmarks_root=args.bookmarks_root,
        data_lake_uri=args.data_lake_uri,
    )
    organization: list[dict[str, Any]] = []
    for profile_name, path in profiles:
        if args.profile and profile_name != args.profile:
            continue
        from sync.organize_brave_bookmarks import organize_profile

        organization.append(organize_profile(path, apply=False))

    apply_result: dict[str, Any] = {"status": "preview_only"}
    if args.auto:
        apply_result = _apply_approved(
            bookmarks_root=args.bookmarks_root,
            runtime_dir=args.runtime_dir,
            profile_filter=args.profile,
            check_process=True,
            skip_if_running=True,
        )
        if apply_result.get("status") == "success" and (
            apply_result.get("applied", 0) or apply_result.get("organized", 0)
        ):
            sync_result = sync_bookmarks(
                bookmarks_root=args.bookmarks_root,
                data_lake_uri=args.data_lake_uri,
                )

    return {
        "status": "success",
        "sync": {
            "status": sync_result.get("status"),
            "profiles": sync_result.get("profiles"),
            "records_read": sync_result.get("records_read"),
            "records_persisted": sync_result.get("records_persisted"),
        },
        "organization": [
            {
                "profile": item.get("profile"),
                "moved": item.get("moved", 0),
                "changed": item.get("changed", False),
                "groups": item.get("groups", {}),
                "subgroups": item.get("subgroups", {}),
            }
            for item in organization
        ],
        "apply": apply_result,
    }


def _add_common_path_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")

    propose_parser = subparsers.add_parser("propose", help="Create an AI/user bookmark candidate")
    propose_parser.add_argument("--url", required=True)
    propose_parser.add_argument("--title", required=True)
    propose_parser.add_argument("--profile", default="Default")
    propose_parser.add_argument("--folder", help="Approved folder/subfolder path")
    propose_parser.add_argument("--source-kind", default="ai_discovery")
    propose_parser.add_argument("--source-ref")
    propose_parser.add_argument("--reason")
    propose_parser.add_argument("--json", action="store_true", dest="as_json")
    _add_common_path_args(propose_parser)

    review_parser = subparsers.add_parser("review", help="List or approve/reject private proposals")
    review_group = review_parser.add_mutually_exclusive_group()
    review_group.add_argument("--approve")
    review_group.add_argument("--reject")
    review_parser.add_argument("--json", action="store_true", dest="as_json")
    _add_common_path_args(review_parser)

    apply_parser = subparsers.add_parser("apply", help="Apply approved proposals and organize Brave")
    apply_parser.add_argument("--bookmarks-root", type=Path, default=DEFAULT_BOOKMARKS_ROOT)
    apply_parser.add_argument("--data-lake-uri", default=DEFAULT_DATA_LAKE_URI)
    apply_parser.add_argument("--profile")
    apply_parser.add_argument("--json", action="store_true", dest="as_json")
    _add_common_path_args(apply_parser)

    maintain_parser = subparsers.add_parser("maintain", help="Sync and optionally auto-apply when Brave is closed")
    maintain_parser.add_argument("--bookmarks-root", type=Path, default=DEFAULT_BOOKMARKS_ROOT)
    maintain_parser.add_argument("--data-lake-uri", default=DEFAULT_DATA_LAKE_URI)
    maintain_parser.add_argument("--profile")
    maintain_parser.add_argument("--auto", action="store_true", help="Apply organization and approved proposals if Brave is closed")
    maintain_parser.add_argument("--json", action="store_true", dest="as_json")
    _add_common_path_args(maintain_parser)

    return parser


def main(argv: list[str] | None = None) -> int:
    raw_args = list(argv if argv is not None else sys.argv[1:])
    if not raw_args or raw_args[0].startswith("-"):
        raw_args.insert(0, "maintain")
    parser = build_parser()
    args = parser.parse_args(raw_args)
    try:
        if args.command == "propose":
            result = propose(args)
        elif args.command == "review":
            result = review(args)
        elif args.command == "apply":
            result = apply(args)
        else:
            result = maintain(args)
        if args.as_json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(f"Brave bookmark workflow: {result.get('status', 'success')}")
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        result = {"status": "error", "error": type(exc).__name__}
        if getattr(args, "as_json", False):
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(f"Brave bookmark workflow failed: {result['error']}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
