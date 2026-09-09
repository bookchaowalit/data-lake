#!/usr/bin/env python3
"""Replay existing scraper captures into the shared Bronze data lake.

The scraper repositories own collection and their local CSV files are
projections. This command makes the current captures useful to the existing
read-only product APIs without contacting upstream providers:

    capture CSV -> immutable landing bytes -> Bronze Parquet -> API -> UI

Each input is identified by its product contract. Re-running the command with
unchanged bytes is idempotent because the lake uses the capture checksum as
the batch identity. The event timestamps are preserved; an old capture is
reported as stale by the API instead of being made to look fresh.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "infra" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from data_lake.ingest import ingest_payload  # noqa: E402
from data_lake.product_adapter import LakeProductContract, write_lineage  # noqa: E402


@dataclass(frozen=True)
class CaptureSpec:
    product: str
    source: str
    domain: str
    schema_version: str
    dataset: str
    path: str
    id_fields: tuple[str, ...]
    event_time_field: str
    history: bool = False


CAPTURES: tuple[CaptureSpec, ...] = (
    CaptureSpec(
        "crypto",
        "book-crypto-data",
        "market",
        "crypto.v1",
        "crypto_prices",
        "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-crypto-data/data/exported/crypto_prices.csv",
        ("coin_id", "currency"),
        "updated_at",
    ),
    CaptureSpec(
        "crypto",
        "book-crypto-data",
        "market",
        "crypto.v1",
        "crypto_prices",
        "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-crypto-data/data/exported/crypto_history.csv",
        ("coin_id", "currency"),
        "date",
        True,
    ),
    CaptureSpec(
        "stocks",
        "book-stock-data",
        "market",
        "stock.v1",
        "stock_prices",
        "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-stock-data/data/exported/stock_prices.csv",
        ("symbol",),
        "updated_at",
    ),
    CaptureSpec(
        "stocks",
        "book-stock-data",
        "market",
        "stock.v1",
        "stock_history",
        "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-stock-data/data/exported/stock_history.csv",
        ("symbol",),
        "date",
        True,
    ),
    CaptureSpec(
        "fx",
        "book-fx-data",
        "market",
        "fx.v1",
        "exchange_rates",
        "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-fx-data/data/exported/exchange_rates.csv",
        ("base", "currency"),
        "updated_at",
    ),
    CaptureSpec(
        "fx",
        "book-fx-data",
        "market",
        "fx.v1",
        "exchange_history",
        "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-fx-data/data/exported/exchange_history.csv",
        ("base", "currency"),
        "date",
        True,
    ),
    CaptureSpec(
        "defi",
        "book-defi-data",
        "market",
        "defi.v1",
        "defi_yields",
        "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-defi-data/data/exported/defi_yields.csv",
        ("pool_id",),
        "captured_at",
    ),
    CaptureSpec(
        "defi",
        "book-defi-data",
        "market",
        "defi.v1",
        "defi_yields_history",
        "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-defi-data/data/exported/defi_yields_history.csv",
        ("pool_id",),
        "captured_at",
        True,
    ),
    CaptureSpec(
        "flights",
        "book-flight-data",
        "travel",
        "flight.v1",
        "flight_prices",
        "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-flight-data/data/exported/flight_prices.csv",
        ("origin", "destination", "departure"),
        "scraped_at",
    ),
    CaptureSpec(
        "flights",
        "book-flight-data",
        "travel",
        "flight.v1",
        "flight_prices_history",
        "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-flight-data/data/exported/flight_prices_history.csv",
        ("origin", "destination", "departure"),
        "date",
        True,
    ),
    CaptureSpec(
        "seo",
        "book-seo-data",
        "seo",
        "seo.v1",
        "seo_rankings",
        "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-seo-data/data/exported/seo_rankings.csv",
        ("url",),
        "captured_at",
    ),
    CaptureSpec(
        "seo",
        "book-seo-data",
        "seo",
        "seo.v1",
        "seo_rankings_history",
        "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-seo-data/data/exported/seo_rankings_history.csv",
        ("url",),
        "captured_at",
        True,
    ),
    CaptureSpec(
        "ai_tools",
        "book-ai-tools-data",
        "ai-tools",
        "ai_tools.v1",
        "ai_tools",
        "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-ai-tools-data/data/exported/ai_tools.csv",
        ("tool_id",),
        "captured_at",
    ),
    CaptureSpec(
        "ai_tools",
        "book-ai-tools-data",
        "ai-tools",
        "ai_tools.v1",
        "ai_tools_history",
        "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-ai-tools-data/data/exported/ai_tools_history.csv",
        ("tool_id",),
        "captured_at",
        True,
    ),
    CaptureSpec(
        "news",
        "book-news-scraping",
        "news",
        "news.v1",
        "articles",
        "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-news-scraping/data/exported/matichon_news.csv",
        ("source", "article_id"),
        "captured_at",
    ),
    CaptureSpec(
        "news",
        "book-news-scraping",
        "news",
        "news.v1",
        "articles_history",
        "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-news-scraping/data/exported/matichon_news_history.csv",
        ("source", "article_id"),
        "captured_at",
        True,
    ),
    CaptureSpec(
        "news",
        "book-news-scraping",
        "news",
        "news.v1",
        "articles",
        "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-news-scraping/data/exported/notebookspec_tech.csv",
        ("source", "article_id"),
        "captured_at",
    ),
    CaptureSpec(
        "news",
        "book-news-scraping",
        "news",
        "news.v1",
        "articles_history",
        "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-news-scraping/data/exported/notebookspec_tech_history.csv",
        ("source", "article_id"),
        "captured_at",
        True,
    ),
    CaptureSpec(
        "news",
        "book-news-scraping",
        "news",
        "news.v1",
        "articles",
        "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-news-scraping/data/exported/thai_business_news.csv",
        ("source", "article_id"),
        "captured_at",
    ),
    CaptureSpec(
        "news",
        "book-news-scraping",
        "news",
        "news.v1",
        "articles_history",
        "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-news-scraping/data/exported/thai_business_news_history.csv",
        ("source", "article_id"),
        "captured_at",
        True,
    ),
    CaptureSpec(
        "news",
        "book-news-scraping",
        "news",
        "news.v1",
        "articles",
        "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-news-scraping/data/exported/thai_tech_news.csv",
        ("source", "article_id"),
        "captured_at",
    ),
    CaptureSpec(
        "news",
        "book-news-scraping",
        "news",
        "news.v1",
        "articles_history",
        "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-news-scraping/data/exported/thai_tech_news_history.csv",
        ("source", "article_id"),
        "captured_at",
        True,
    ),
)


def _records(raw: bytes, id_fields: Iterable[str], event_time_field: str | None = None) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    fields = tuple(id_fields)
    headers = reader.fieldnames or []
    required = set(fields) | ({event_time_field} if event_time_field else set())
    if len(headers) != len(set(headers)) or not required.issubset(headers):
        raise ValueError("Capture headers do not match the replay contract")
    records: list[dict[str, Any]] = []
    for index, row in enumerate(reader, start=2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"Malformed CSV at row {index}")
        normalized = {str(key): value for key, value in row.items()}
        parts = [str(normalized[field]).strip() for field in fields]
        if not parts or any(not part or "|" in part for part in parts):
            raise ValueError(f"Missing or ambiguous identity at row {index}")
        if event_time_field:
            stamp = str(normalized[event_time_field]).strip()
            try:
                parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                if len(stamp) != 10 and parsed.tzinfo is None:
                    raise ValueError("Timestamp requires a timezone")
            except ValueError:
                raise ValueError(f"Invalid event timestamp at row {index}") from None
        normalized["id"] = "|".join(parts)
        records.append(normalized)
    return records


def _map_records(spec: CaptureSpec, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map an approved capture to the domain product's published semantics.

    News captures retain the source fields while adding stable headline,
    canonical URL, publisher, and attribution markers for ``news.v1``.
    The SEO scheduler keeps the historical ``seo_rankings`` filename, but its
    approved source is an owned-page reachability check, not a SERP provider.
    Preserve the raw fields while filling the ``seo.v1`` provenance fields so
    consumers never mistake an empty rank for a collected ranking.
    """
    if spec.product == "news":
        mapped: list[dict[str, Any]] = []
        for row in records:
            item = dict(row)
            title = str(row.get("title") or "").strip()
            url = str(row.get("url") or "").strip()
            source = str(row.get("source") or "").strip()
            observed_at = str(row.get(spec.event_time_field) or "").strip()
            item.update(
                {
                    "headline": title,
                    "canonical_url": url,
                    "publisher": source,
                    "observed_at": observed_at,
                    "capture_kind": "rss_article",
                    "source_feed_url": str(row.get("source_url") or "").strip(),
                    "id": str(row.get("id") or ""),
                }
            )
            mapped.append(item)
        return mapped
    if spec.product != "seo":
        return records
    mapped: list[dict[str, Any]] = []
    for row in records:
        status_raw = str(row.get("http_status") or "").strip()
        try:
            status = int(status_raw)
        except ValueError:
            status = 0
        page_status = str(row.get("data_status") or "").strip().lower()
        reachable = 200 <= status < 400 and page_status == "ok"
        url = str(row.get("url") or "").strip()
        domain = str(row.get("domain") or "").strip().lower()
        observed_at = str(row.get(spec.event_time_field) or "").strip()
        item = dict(row)
        item.update(
            {
                "keyword": f"owned-page|{url}",
                "target_domain": domain,
                "location": "global",
                "device": "desktop",
                "provider": str(row.get("source") or "public_page_check").strip(),
                "found": "true" if reachable else "false",
                "rank": "",
                "best_rank": "",
                "result_url": url,
                "best_url": url,
                "result_title": str(row.get("title") or "").strip(),
                "best_title": str(row.get("title") or "").strip(),
                "total_results": "",
                "observed_at": observed_at,
                "capture_kind": "owned_page_provenance",
                "page_http_status": status,
                "page_canonical_url": str(row.get("canonical") or "").strip(),
                "page_content_length": str(row.get("content_length") or "").strip(),
                "page_data_status": page_status,
                "id": str(row.get("id") or url),
            }
        )
        mapped.append(item)
    return mapped


def _lineage_contract(spec: CaptureSpec, lake_uri: str) -> LakeProductContract:
    return LakeProductContract(
        source=spec.source,
        domain=spec.domain,
        product_schema_version=spec.schema_version,
        privacy_class="public",
        retention_class="operational-plus-history" if spec.history else "operational",
        bronze_schema_version="1",
        project_root=ROOT,
        data_lake_uri=lake_uri,
        lineage_filename="lake_lineage.json",
        datasets=tuple(sorted({item.dataset for item in CAPTURES if item.product == spec.product})),
    )


def ingest_capture(spec: CaptureSpec, *, lake_uri: str, validate_only: bool = False, update_lineage: bool = False) -> dict[str, Any]:
    path = ROOT / spec.path
    with path.open("rb") as capture:
        raw = capture.read(32 * 1024 * 1024 + 1)
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError("Capture exceeds 32 MiB replay limit")
    records = _map_records(spec, _records(raw, spec.id_fields, spec.event_time_field))
    if not records:
        raise ValueError(f"capture is empty: {spec.path}")
    if validate_only:
        return {"product": spec.product, "dataset": spec.dataset, "record_count": len(records), "validated": True}
    result = ingest_payload(
        raw,
        records,
        source=spec.source,
        domain=spec.domain,
        dataset=spec.dataset,
        data_lake_uri=lake_uri,
        input_format="csv",
        schema_version="1",
        source_record_id_field="id",
        event_time_field=spec.event_time_field,
        content_type="text/csv",
        metadata={
            "adapter": spec.source,
            "capture_mapping_version": (
                "4" if spec.product == "news" else "3" if spec.product == "seo" else "2"
            ),
            "event_time_field": spec.event_time_field,
            "id_fields": list(spec.id_fields),
            "product": spec.product,
            "product_schema_version": spec.schema_version,
            "capture_path": spec.path,
            "dataset_role": "history" if spec.history else "snapshot",
        },
        privacy_class="public",
        retention_class="operational-plus-history" if spec.history else "operational",
    )
    # Keep the product's ignored local lineage projection in sync so its
    # metadata endpoint can show the same lake run as the shared API read.
    if update_lineage:
        write_lineage(
            _lineage_contract(spec, lake_uri),
            result,
            dataset=spec.dataset,
            data_dir=ROOT / Path(spec.path).parents[1],
        )
    return {
        "product": spec.product,
        "dataset": spec.dataset,
        "capture_path": spec.path,
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
    parser.add_argument("--lake-uri", default=str(ROOT / "data" / "lake-local" / "scraping-captures-v2"))
    parser.add_argument("--product", action="append", choices=sorted({spec.product for spec in CAPTURES}))
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--validate-only", action="store_true", help="Validate captures without writing lake or lineage artifacts")
    parser.add_argument("--update-lineage", action="store_true", help="Update product-local lineage projections after reconciliation")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Conditional/blocked sources require a separate source-owner decision;
    # this operational replay never treats their presence as approval.
    # SEO is approved for owned-page provenance only; news is approved for
    # publisher RSS/Atom captures with attribution. AI directory reuse and
    # flight collection remain held behind their source-owner gates.
    approved = {"crypto", "stocks", "fx", "defi", "seo", "news"}
    selected = set(args.product or approved)
    if not args.validate_only and selected - approved:
        print("Replay held: selected sources require source permission and consumer mapping review.", file=sys.stderr)
        return 1
    results: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    for spec in CAPTURES:
        if spec.product not in selected:
            continue
        path = ROOT / spec.path
        if not path.is_file():
            skipped.append({"product": spec.product, "dataset": spec.dataset, "path": spec.path})
            continue
        try:
            results.append(ingest_capture(spec, lake_uri=args.lake_uri, validate_only=args.validate_only, update_lineage=args.update_lineage))
        except (OSError, ValueError, RuntimeError) as exc:
            errors.append({"product": spec.product, "dataset": spec.dataset, "error": type(exc).__name__})
    summary = {"lake_uri": args.lake_uri, "validate_only": args.validate_only, "results": results, "skipped": skipped, "errors": errors}
    if args.as_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Scraping capture replay: {len(results)} dataset(s) {'validated' if args.validate_only else 'committed'}")
        for item in results:
            state = "validated" if args.validate_only else "existing" if item["manifest_existed"] else "new"
            print(f"  {item['product']}/{item['dataset']}: {item['record_count']} record(s), {state}")
        for item in skipped:
            print(f"  skipped missing: {item['product']}/{item['dataset']}")
        for item in errors:
            print(f"  failed: {item['product']}/{item['dataset']} ({item['error']}); immutable prior mappings require an isolated replay/reconciliation, not overwrite")
    return 1 if errors or skipped or not results else 0


if __name__ == "__main__":
    raise SystemExit(main())
