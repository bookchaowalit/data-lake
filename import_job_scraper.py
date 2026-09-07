#!/usr/bin/env python3
"""Import ``job.v1`` records into Solo Empire's raw opportunity backlog.

The job scraper remains collection-only. book-job-data owns the file capture →
Bronze boundary; this adapter consumes its API and, with an explicit
``--apply``, appends new UNTRIAGED rows to the backlog. It never prepares,
sends, or submits an application and never reads the opportunity contract.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts" / "utils"))
from job_client import fetch_jobs  # noqa: E402


BACKLOG_CSV = ROOT / "opportunities" / "data" / "opportunity-backlog.csv"
BACKLOG_MD = ROOT / "opportunities" / "inventory" / "OPPORTUNITY-BACKLOG.md"
FIELDS = [
    "id",
    "lane",
    "category",
    "engagement",
    "title",
    "location",
    "compensation",
    "state",
    "source_url",
    "last_verified",
]
ALLOWED_QUALIFICATION_STATUSES = {"PASS", "VERIFY"}
DEFAULT_IMPORT_STATUSES = "PASS"
REQUIRED_QUALIFICATION_FIELDS = {
    "qualification_status",
    "policy_version",
    "employment_type",
    "work_arrangement",
    "thailand_eligibility",
    "concurrent_employment",
    "engagement_boundary",
    "application_readiness",
    "qualification_reasons",
}


def value(row: dict[str, str], *names: str) -> str:
    for name in names:
        item = (row.get(name) or "").strip()
        if item:
            return item
    return ""


def canonical_url(url: str) -> str:
    """Remove fragments and tracking query strings for stable deduplication."""
    url = url.strip()
    if not url:
        return ""
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return url.rstrip("/").lower()
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def classify(row: dict[str, str], source: str) -> tuple[str, str]:
    career_lane = value(row, "search_lane")
    if career_lane in {"remote_career", "relocation"}:
        return career_lane.replace("_", "-"), "International career"
    text = " ".join(
        (
            value(row, "title", "company", "name"),
            value(row, "tags", "skills", "keyword", "category"),
            value(row, "notes", "description"),
        )
    ).lower()

    if any(word in text for word in ("shopify", "ecommerce", "e-commerce", "woocommerce")):
        return "ecommerce-growth", "Shopify/ecommerce"
    if any(word in text for word in ("llm", "genai", "gen ai", "openai", "chatbot", "machine learning")) or re.search(r"\bai\b", text):
        return "engineering-ai", "AI/full-stack"
    if any(word in text for word in ("api", "integration", "etl", "webhook")):
        return "engineering-api", "API/integration"
    if any(word in text for word in ("scrap", "crawler", "crawling", "automation", "n8n", "zapier")):
        return "leadership-automation", "Automation/scraping"
    if any(word in text for word in ("seo", "marketing", "content")):
        return "ecommerce-growth", "SEO/content"
    if source == "pipeline":
        return "freelance-marketplace", "Freelance marketplace"
    return "engineering-general", "Full-stack/software"


def read_rows(limit: int) -> tuple[list[dict[str, str]], str]:
    """Read the policy-qualified dataset and reject stale producer schemas."""
    result = fetch_jobs(dataset="job_matches", limit=max(1, limit))
    if result.data_status not in {"ok", "stale"} or not result.items:
        detail = result.error_message or f"job_matches data_status={result.data_status}"
        raise RuntimeError(detail)
    rows = [dict(row) for row in result.items[:limit]]
    invalid = [
        index
        for index, row in enumerate(rows, 1)
        if any(not str(row.get(field) or "").strip() for field in REQUIRED_QUALIFICATION_FIELDS)
        or str(row.get("qualification_status") or "").strip().upper()
        not in ALLOWED_QUALIFICATION_STATUSES
    ]
    if invalid:
        sample = ",".join(str(index) for index in invalid[:5])
        raise RuntimeError(f"job_matches missing/invalid qualification evidence at row(s): {sample}")
    return rows, result.source


def select_qualified_rows(rows: list[dict[str, str]], statuses: set[str]) -> list[dict[str, str]]:
    return [
        row
        for row in rows
        if str(row.get("qualification_status") or "").strip().upper() in statuses
    ]


def normalize_row(row: dict[str, str], source: str, item_id: str, verified: str) -> dict[str, str] | None:
    title = value(row, "title", "job_title", "position", "company", "name")
    url = value(row, "url", "source_url", "apply_url", "link")
    if not title or not url:
        return None
    lane, category = classify(row, source)
    location = value(row, "location", "locations", "job_location") or "Location to verify"
    compensation = value(row, "salary", "compensation", "rate", "budget", "value") or "Rate to verify"
    employment_type = value(row, "employment_type") or "Unknown engagement"
    qualification_status = value(row, "qualification_status").upper()
    engagement = f"{employment_type} opportunity ({qualification_status})"
    return {
        "id": item_id,
        "lane": lane,
        "category": category,
        "engagement": engagement,
        "title": re.sub(r"\s+", " ", title).strip(),
        "location": re.sub(r"\s+", " ", location).strip(),
        "compensation": re.sub(r"\s+", " ", compensation).strip(),
        "state": "UNTRIAGED",
        "source_url": url.strip(),
        "last_verified": value(row, "posted", "created_date", "scraped_at")[:10] or verified,
    }


def markdown_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def markdown_row(row: dict[str, str]) -> str:
    lane = row["lane"].replace("-", "/").title()
    source = urlsplit(row["source_url"]).netloc or "source"
    return (
        f"| `{row['id']}` | {lane} | {markdown_escape(row['category'])} | "
        f"{markdown_escape(row['engagement'])} | {markdown_escape(row['title'])} | "
        f"{markdown_escape(row['location'])} | {markdown_escape(row['compensation'])} | "
        f"`{row['state']}` | [{source}]({row['source_url']}) |"
    )


def apply_rows(rows: list[dict[str, str]]) -> None:
    with BACKLOG_CSV.open(newline="", encoding="utf-8") as handle:
        existing = list(csv.DictReader(handle))
    with BACKLOG_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(existing)
        writer.writerows(rows)

    content = BACKLOG_MD.read_text(encoding="utf-8")
    marker = "## Live scan notes"
    if marker not in content:
        raise RuntimeError(f"Cannot update Markdown backlog: marker {marker!r} is missing")
    insertion = "\n".join(markdown_row(row) for row in rows) + "\n"
    content = content.replace(marker, insertion + "\n" + marker, 1)
    BACKLOG_MD.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-rows", type=int, default=200, help="Maximum rows to inspect (default: 200)")
    parser.add_argument(
        "--statuses",
        default=DEFAULT_IMPORT_STATUSES,
        help="Qualified statuses to import (default: PASS; opt in to VERIFY explicitly; REJECT is never allowed)",
    )
    parser.add_argument("--apply", action="store_true", help="Append new rows to the CSV and Markdown backlog")
    args = parser.parse_args()

    statuses = {item.strip().upper() for item in args.statuses.split(",") if item.strip()}
    if not statuses or not statuses.issubset(ALLOWED_QUALIFICATION_STATUSES):
        parser.error("--statuses must contain only PASS and/or VERIFY")

    with BACKLOG_CSV.open(newline="", encoding="utf-8") as handle:
        existing = list(csv.DictReader(handle))
    existing_urls = {canonical_url(row.get("source_url", "")) for row in existing}
    existing_ids = {row.get("id", "") for row in existing}
    today = date.today().isoformat()
    source = "job_matches"
    new_rows: list[dict[str, str]] = []
    sequence = 1
    try:
        loaded_rows, load_source = read_rows(max(0, args.max_rows))
        source_rows = select_qualified_rows(loaded_rows, statuses)
    except RuntimeError as exc:
        print(f"job.v1 unavailable: {exc}", file=sys.stderr)
        return 2
    for raw in source_rows:
        normalized_url = canonical_url(value(raw, "url", "source_url", "apply_url", "link"))
        if not normalized_url or normalized_url in existing_urls:
            continue
        while f"SCRAPER-{today.replace('-', '')}-{sequence:03d}" in existing_ids:
            sequence += 1
        item_id = f"SCRAPER-{today.replace('-', '')}-{sequence:03d}"
        row = normalize_row(raw, source, item_id, today)
        sequence += 1
        if row is None:
            continue
        existing_urls.add(normalized_url)
        existing_ids.add(item_id)
        new_rows.append(row)

    print(f"Source: book-job-data :8109 (job.v1/job_matches via {load_source})")
    print(f"Qualification statuses: {','.join(sorted(statuses))}")
    print(f"New backlog rows: {len(new_rows)}")
    for row in new_rows[:20]:
        print(f"- {row['id']}: {row['title']} [{row['source_url']}]")
    if len(new_rows) > 20:
        print(f"... and {len(new_rows) - 20} more")
    if args.apply and new_rows:
        apply_rows(new_rows)
        print(f"Applied to {BACKLOG_CSV} and {BACKLOG_MD}")
    elif new_rows:
        print("Preview only. Re-run with --apply to write the backlog.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
