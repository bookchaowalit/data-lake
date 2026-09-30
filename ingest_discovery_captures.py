#!/usr/bin/env python3
"""Replay technology-discovery captures into one ``discovery.v1`` Bronze set.

``book-job-scraping`` remains a collection-only producer.  This adapter reads
its four approved public captures locally, preserves the exact CSV bytes in
the shared lake, and publishes a normalized ``technology_signals`` snapshot
plus ``technology_signals_history``.  It never contacts a provider and never
writes to a scraper or consumer database.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "infra" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from data_lake.ingest import ingest_payload  # noqa: E402


SOURCE_ROOT = (
    ROOT
    / "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools"
    / "book-job-scraping/data/exported"
)
SOURCE_NAME = "book-discovery-data"
DOMAIN = "discovery"
SCHEMA_VERSION = "discovery.v1"
SNAPSHOT_DATASET = "technology_signals"
HISTORY_DATASET = "technology_signals_history"


@dataclass(frozen=True)
class CaptureSpec:
    source_id: str
    filename: str
    id_field: str
    observed_field: str
    captured_field: str
    signal_kind: str
    publisher: str
    source_url: str
    history: bool = False

    @property
    def dataset(self) -> str:
        return HISTORY_DATASET if self.history else SNAPSHOT_DATASET


CAPTURES: tuple[CaptureSpec, ...] = (
    CaptureSpec(
        "github_trending",
        "github_trending.csv",
        "name",
        "updated_at",
        "scraped_at",
        "repository",
        "GitHub",
        "https://api.github.com/search/repositories",
    ),
    CaptureSpec(
        "github_trending",
        "github_trending_history.csv",
        "name",
        "date",
        "date",
        "repository",
        "GitHub",
        "https://api.github.com/search/repositories",
        True,
    ),
    CaptureSpec(
        "hackernews",
        "hackernews_top.csv",
        "id",
        "time",
        "",
        "story",
        "Hacker News",
        "https://hacker-news.firebaseio.com/v0",
    ),
    CaptureSpec(
        "hackernews",
        "hackernews_history.csv",
        "id",
        "time",
        "scraped_at",
        "story",
        "Hacker News",
        "https://hacker-news.firebaseio.com/v0",
        True,
    ),
    CaptureSpec(
        "devto_articles",
        "devto_articles.csv",
        "id",
        "published_at",
        "",
        "article",
        "DEV Community",
        "https://dev.to/api/articles",
    ),
    CaptureSpec(
        "devto_articles",
        "devto_history.csv",
        "id",
        "published_at",
        "scraped_at",
        "article",
        "DEV Community",
        "https://dev.to/api/articles",
        True,
    ),
    CaptureSpec(
        "producthunt_top",
        "producthunt_top.csv",
        "url",
        "published_at",
        "",
        "product",
        "Product Hunt",
        "https://www.producthunt.com/feed",
    ),
    CaptureSpec(
        "producthunt_top",
        "producthunt_history.csv",
        "url",
        "published_at",
        "scraped_at",
        "product",
        "Product Hunt",
        "https://www.producthunt.com/feed",
        True,
    ),
)


def normalize_timestamp(value: Any) -> str:
    """Return a deterministic UTC ISO timestamp for source date variants."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
        else:
            return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_csv(path: Path) -> tuple[bytes, list[dict[str, str]]]:
    raw = path.read_bytes()
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError("Capture exceeds 32 MiB replay limit")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    headers = reader.fieldnames or []
    if len(headers) != len(set(headers)):
        raise ValueError(f"Duplicate capture headers: {path.name}")
    rows: list[dict[str, str]] = []
    for index, row in enumerate(reader, start=2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"Malformed CSV at row {index}: {path.name}")
        rows.append({str(key): str(value or "") for key, value in row.items()})
    return raw, rows


def _key(row: dict[str, str], spec: CaptureSpec, row_number: int) -> str:
    value = row.get(spec.id_field, "").strip()
    if not value or "|" in value:
        raise ValueError(f"Missing or ambiguous identity at row {row_number}: {spec.filename}")
    return value


def _capture_lookup(source_root: Path = SOURCE_ROOT) -> dict[tuple[str, str], str]:
    """Use history capture timestamps for snapshots that omit scrape time."""
    lookup: dict[tuple[str, str], str] = {}
    for spec in CAPTURES:
        if not spec.history:
            continue
        path = source_root / spec.filename
        if not path.is_file():
            continue
        _, rows = _read_csv(path)
        for number, row in enumerate(rows, start=2):
            key = _key(row, spec, number)
            field = spec.captured_field or spec.observed_field
            timestamp = normalize_timestamp(row.get(field))
            if timestamp:
                current = lookup.get((spec.source_id, key), "")
                if timestamp > current:
                    lookup[(spec.source_id, key)] = timestamp
    return lookup


def _canonical_url(spec: CaptureSpec, row: dict[str, str], key: str) -> str:
    url = row.get("url", "").strip()
    if url:
        return url
    if spec.source_id == "github_trending":
        return f"https://github.com/{key}"
    if spec.source_id == "hackernews":
        return f"https://news.ycombinator.com/item?id={key}"
    return ""


def map_records(
    spec: CaptureSpec,
    rows: Iterable[dict[str, str]],
    *,
    capture_lookup: dict[tuple[str, str], str] | None = None,
) -> list[dict[str, Any]]:
    """Normalize one source capture while retaining its source fields."""
    lookup = capture_lookup or {}
    mapped: list[dict[str, Any]] = []
    for number, row in enumerate(rows, start=2):
        key = _key(row, spec, number)
        observed = normalize_timestamp(row.get(spec.observed_field))
        captured = normalize_timestamp(row.get(spec.captured_field))
        if not captured and not spec.history:
            captured = lookup.get((spec.source_id, key), "")
        if not captured:
            captured = observed
        if not captured:
            raise ValueError(f"Missing capture timestamp at row {number}: {spec.filename}")
        if not observed:
            observed = captured
        item: dict[str, Any] = dict(row)
        item.update(
            {
                "id": f"{spec.source_id}|{key}",
                "signal_id": key,
                "source": spec.source_id,
                "signal_kind": spec.signal_kind,
                "title": row.get("title", "").strip() or row.get("name", "").strip(),
                "canonical_url": _canonical_url(spec, row, key),
                "publisher": spec.publisher,
                "source_url": spec.source_url,
                "description": row.get("description", "").strip(),
                "observed_at": observed,
                "captured_at": captured,
                "capture_kind": "history_snapshot" if spec.history else "current_snapshot",
                "record_kind": "technology_signal",
                "attribution_required": True,
            }
        )
        mapped.append(item)
    return mapped


def _contract(data_lake_uri: str) -> dict[str, Any]:
    return {
        "source": SOURCE_NAME,
        "domain": DOMAIN,
        "schema_version": SCHEMA_VERSION,
        "datasets": [SNAPSHOT_DATASET, HISTORY_DATASET],
        "data_lake_uri": data_lake_uri,
    }


def ingest_capture(
    spec: CaptureSpec,
    *,
    lake_uri: str,
    source_root: Path = SOURCE_ROOT,
    capture_lookup: dict[tuple[str, str], str],
    validate_only: bool = False,
) -> dict[str, Any]:
    path = source_root / spec.filename
    raw, rows = _read_csv(path)
    records = map_records(spec, rows, capture_lookup=capture_lookup)
    if not records:
        raise ValueError(f"capture is empty: {spec.filename}")
    if validate_only:
        return {"source": spec.source_id, "dataset": spec.dataset, "record_count": len(records), "validated": True}
    result = ingest_payload(
        raw,
        records,
        source=SOURCE_NAME,
        domain=DOMAIN,
        dataset=spec.dataset,
        data_lake_uri=lake_uri,
        input_format="csv",
        schema_version="1",
        source_record_id_field="id",
        event_time_field="captured_at",
        content_type="text/csv",
        metadata={
            "adapter": SOURCE_NAME,
            "capture_mapping_version": "1",
            "capture_source": spec.source_id,
            "capture_path": str(path.relative_to(ROOT)),
            "source_url": spec.source_url,
            "dataset_role": "history" if spec.history else "snapshot",
            "privacy_class": "public",
            "retention_class": "operational-plus-history" if spec.history else "operational",
        },
        privacy_class="public",
        retention_class="operational-plus-history" if spec.history else "operational",
    )
    return {
        "source": spec.source_id,
        "dataset": spec.dataset,
        "capture_path": str(path.relative_to(ROOT)),
        "record_count": len(records),
        "run_id": result.get("run_id"),
        "raw_key": result.get("raw_key"),
        "bronze_key": result.get("bronze_key"),
        "manifest_key": result.get("manifest_key"),
        "raw_existed": result.get("raw_existed"),
        "bronze_existed": result.get("bronze_existed"),
        "manifest_existed": result.get("manifest_existed"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lake-uri", default=str(ROOT / "data" / "lake-local" / "scraping-captures-v2")
    )
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--source", action="append", choices=sorted({item.source_id for item in CAPTURES}))
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writes; report missing captures without failing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    validate_only = args.validate_only or args.dry_run
    selected = set(args.source or {item.source_id for item in CAPTURES})
    source_root = args.source_root.resolve()
    capture_lookup = _capture_lookup(source_root)
    results: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    for spec in CAPTURES:
        if spec.source_id not in selected:
            continue
        path = source_root / spec.filename
        if not path.is_file():
            skipped.append({"source": spec.source_id, "dataset": spec.dataset, "path": str(path.relative_to(ROOT))})
            continue
        try:
            results.append(
                ingest_capture(
                    spec,
                    lake_uri=args.lake_uri,
                    source_root=source_root,
                    capture_lookup=capture_lookup,
                    validate_only=validate_only,
                )
            )
        except (OSError, ValueError, RuntimeError) as exc:
            errors.append({"source": spec.source_id, "dataset": spec.dataset, "error": type(exc).__name__})
    summary = {
        **_contract(args.lake_uri),
        "validate_only": validate_only,
        "dry_run": args.dry_run,
        "results": results,
        "skipped": skipped,
        "errors": errors,
    }
    if args.as_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        state = "validated" if validate_only else "committed"
        print(f"Discovery capture replay: {len(results)} dataset(s) {state}")
        for item in results:
            status = "validated" if validate_only else "existing" if item.get("manifest_existed") else "new"
            print(f"  {item['source']}/{item['dataset']}: {item['record_count']} record(s), {status}")
        for item in skipped:
            print(f"  skipped missing: {item['source']}/{item['dataset']}")
        for item in errors:
            print(f"  failed: {item['source']}/{item['dataset']} ({item['error']})")
    # A dry-run is a non-writing readiness plan: missing local captures are
    # reported in the JSON/text result but do not make the plan command fail.
    return 1 if errors or (not args.dry_run and (skipped or not results)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
