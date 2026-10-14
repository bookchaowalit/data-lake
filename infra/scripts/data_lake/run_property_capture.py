#!/usr/bin/env python3
"""Run a bounded TG Condo RSS capture and land it in the property lake.

TG Condo publishes an official condo-for-rent RSS feed; it is the only
property source approved for scheduled collection (robots.txt allows it, the
site publishes no terms that restrict feed use, and DDproperty, PropertyHub,
LivingInsider, ZmyHome, and ENNXO remain held). The career-job-scraper
repository owns the feed adapter and writes its local CSV projection. This
parent runner limits the capture to one feed request, keeps public-agent
contact enrichment disabled, drops every contact column before the lake, and
commits the listing metadata as Bronze ``domain=property/dataset=
property_listings``. It never submits forms, logs in, or follows listing pages.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import io
import json
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "infra" / "scripts"
DEFAULT_LAKE_URI = str(ROOT / "data" / "lake-local" / "scraping-captures-v2")
DEFAULT_LOCK_PATH = ROOT / "data" / "property-feeds.lock"
DEFAULT_LOG_DIR = ROOT / "data" / "logs" / "property-capture"
MAX_CHILD_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_CAPTURE_BYTES = 4 * 1024 * 1024

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from data_lake.capture_lock import acquire_lock as _acquire_lock  # noqa: E402
from data_lake.workspace import OWNER_ROOT  # noqa: E402

PROPERTY_SCRAPING_REL = "public/book-apps/tools/career-job-scraper"
PROPERTY_SCRAPING = OWNER_ROOT / PROPERTY_SCRAPING_REL

# Contact enrichment is held until terms, retention, and a storage basis are
# documented. Personal contact columns must stay empty, and no lead or contact
# column (including the collector's placeholder defaults) reaches the lake.
PERSONAL_CONTACT_FIELDS = (
    "contact_name",
    "contact_phone",
    "contact_email",
    "contact_line",
    "contact_facebook",
    "contact_instagram",
    "contact_tiktok",
    "contact_social_urls",
    "contact_evidence",
)
LEAD_FIELDS = (
    *PERSONAL_CONTACT_FIELDS,
    "contact_role",
    "co_agent_status",
    "contact_source_url",
    "contact_confidence",
    "contact_public",
    "lead_review_status",
    "review_decision",
    "reviewed_at",
    "reviewer_id",
    "outreach_status",
    "retention_until",
    "terms_basis_ref",
)
CONTACT_ENV = (
    "TGCONDO_CONTACT_STORAGE_APPROVED",
    "TGCONDO_RETENTION_UNTIL",
    "TGCONDO_TERMS_BASIS_REF",
)
LISTING_FIELDS = (
    "scraped_at",
    "title",
    "type",
    "listing_type",
    "url",
    "price_raw",
    "price",
    "bedrooms",
    "bathrooms",
    "area_sqm",
    "location",
    "description",
    "source_channel",
    "source_platform",
)


@dataclass(frozen=True)
class PropertyCapture:
    """The approved bounded TG Condo RSS slice for the property product."""

    source_job: str = "tgcondo_condo_rent"
    feed_url: str = "https://www.tgcondo.com/Property-Types/condo-for-rent?format=feed&type=rss"
    limit: int = 40
    schedule: str = "45 */6 * * *"
    cron_tag: str = "book-property-scraping-feeds"
    timeout_seconds: float = 120.0

    @property
    def output_dir(self) -> Path:
        return PROPERTY_SCRAPING / "data" / "exported"

    @property
    def capture_path(self) -> Path:
        return self.output_dir / f"{self.source_job}.csv"

    @property
    def registry_path(self) -> str:
        return f"projects/product/engineering/book-dev/github/bookchaowalit/{PROPERTY_SCRAPING_REL}/data/exported/{self.source_job}.csv"


PROPERTY_CAPTURE = PropertyCapture()


class PropertyCycleError(RuntimeError):
    """A bounded property cycle failed a safe operational gate."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class LockBusyError(PropertyCycleError):
    """Another property cycle owns the source lock."""


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def validate_lake_uri(lake_uri: str) -> None:
    """Require an explicit existing writable local lake or a URI scheme."""
    if not str(lake_uri).strip():
        raise PropertyCycleError("lake_uri_required")
    if "://" in str(lake_uri):
        return
    path = Path(lake_uri).expanduser()
    if not path.is_absolute():
        # Ingest resolves relative paths against another working directory.
        raise PropertyCycleError("lake_uri_not_absolute")
    if not path.is_dir() or not os.access(path, os.W_OK):
        raise PropertyCycleError("lake_unavailable")


def require_dependencies() -> None:
    """Fail before the feed request when the parent runtime is incomplete."""
    missing: list[str] = []
    for module in ("duckdb", "pyarrow", "httpx", "bs4", "feedparser"):
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(module)
    if missing:
        raise PropertyCycleError("dependencies_missing")


def require_workspace() -> None:
    if not (PROPERTY_SCRAPING / "scripts/scrape_tgcondo_rss.py").is_file():
        raise PropertyCycleError("scraper_workspace_missing")


@contextmanager
def acquire_lock(path: Path, *, timeout_seconds: float = 0.0) -> Iterator[None]:
    """Acquire an advisory lock and fail closed after a bounded wait."""
    with _acquire_lock(
        path,
        timeout_seconds=timeout_seconds,
        busy_error=LockBusyError,
    ):
        yield


def _write_log(log_dir: Path, name: str, output: str) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    encoded = output.encode("utf-8", errors="replace")
    if len(encoded) > MAX_CHILD_OUTPUT_BYTES:
        encoded = encoded[-MAX_CHILD_OUTPUT_BYTES:]
        prefix = b"[output truncated to the last 2 MiB]\n"
    else:
        prefix = b""
    with (log_dir / name).open("ab") as handle:
        handle.write(f"\n[{utc_now_iso()}]\n".encode("utf-8"))
        handle.write(prefix)
        handle.write(encoded)
        if not encoded.endswith(b"\n"):
            handle.write(b"\n")


def _safe_counts(output: str) -> dict[str, int]:
    """Extract aggregate counts without returning listing rows or payloads."""
    counts: dict[str, int] = {}
    matches = [int(value) for value in re.findall(r"Saved (\d+) listings to", output)]
    if matches:
        counts["listings"] = max(matches)
    return counts


def _safe_env() -> dict[str, str]:
    """Disable paid, external-write, and contact-enrichment paths."""
    env = {
        **os.environ,
        "FREE_ONLY": "true",
        "ALLOW_PAID_PROVIDERS": "false",
        "ALLOW_EXTERNAL_WRITES": "false",
        "ALLOW_REFRESH": "false",
        "PYTHONPATH": os.pathsep.join(
            [str(PROPERTY_SCRAPING), str(SCRIPTS)]
            + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else [])
        ),
    }
    for name in CONTACT_ENV:
        env.pop(name, None)
    return env


def _run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: float,
) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output = "\n".join(
            part for part in (exc.stdout or "", exc.stderr or "") if isinstance(part, str)
        )
        return 124, output, "child_timeout"
    except OSError as exc:
        return 127, "", f"child_{type(exc).__name__}"
    return completed.returncode, (completed.stdout or ""), (completed.stderr or "")


def _file_signature(path: Path) -> tuple[int, int] | None:
    """Return a small change marker without reading capture payloads."""
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_mtime_ns, stat.st_size


def project_listing_csv(raw: bytes) -> tuple[bytes, int]:
    """Return listing-only CSV bytes; fail closed if contact data is present.

    The lake receives the projection, so no contact column (even an empty
    one) is landed while contact storage remains unapproved. Unknown columns
    fail closed so a collector change cannot silently widen the lake schema.
    """
    if len(raw) > MAX_CAPTURE_BYTES:
        raise PropertyCycleError("capture_too_large")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        headers = list(reader.fieldnames or [])
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error):
        raise PropertyCycleError("capture_malformed") from None
    if not {"url", "scraped_at"}.issubset(headers):
        raise PropertyCycleError("capture_headers_mismatch")
    unknown = sorted(set(headers) - set(LISTING_FIELDS) - set(LEAD_FIELDS))
    if unknown:
        raise PropertyCycleError("capture_headers_mismatch")
    for row in rows:
        if None in row:
            raise PropertyCycleError("capture_malformed")
        if any(str(row.get(field) or "").strip() for field in PERSONAL_CONTACT_FIELDS):
            raise PropertyCycleError("contact_fields_present")
    if not rows:
        raise PropertyCycleError("capture_empty")
    fields = [field for field in LISTING_FIELDS if field in headers]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fields})
    return out.getvalue().encode("utf-8"), len(rows)


def ingest_listings(capture: PropertyCapture, *, lake_uri: str) -> dict[str, Any]:
    """Commit the listing-only projection as Bronze property_listings."""
    from data_lake import ingest_scraping_captures as captures

    try:
        with capture.capture_path.open("rb") as handle:
            raw = handle.read(MAX_CAPTURE_BYTES + 1)
    except OSError:
        raise PropertyCycleError("capture_missing") from None
    projected, rows = project_listing_csv(raw)
    spec = captures.CaptureSpec(
        "property",
        "book-property-scraping",
        "property",
        "property.v1",
        "property_listings",
        capture.registry_path,
        ("url",),
        "scraped_at",
    )
    previous_dir = os.getcwd()
    try:
        result = captures.ingest_capture(spec, lake_uri=lake_uri, raw_override=projected)
    except (OSError, ValueError, RuntimeError) as exc:
        raise PropertyCycleError(f"ingest_{type(exc).__name__}") from None
    finally:
        os.chdir(previous_dir)
    return {
        "records": int(result.get("record_count") or rows),
        "manifest_existed": bool(result.get("manifest_existed")),
        "run_id": result.get("run_id"),
    }


def run_capture(
    capture: PropertyCapture = PROPERTY_CAPTURE,
    *,
    lake_uri: str,
    log_dir: Path,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Collect one bounded RSS snapshot and ingest the listing projection."""
    require_workspace()
    child_timeout = timeout_seconds if timeout_seconds is not None else capture.timeout_seconds
    if child_timeout <= 0:
        raise ValueError("child timeout must be positive")
    previous_capture = _file_signature(capture.capture_path)
    collector_command = [
        sys.executable,
        str(PROPERTY_SCRAPING / "scripts/scrape_tgcondo_rss.py"),
        "--feed-url",
        capture.feed_url,
        "--limit",
        str(capture.limit),
        "--output-dir",
        str(capture.output_dir),
    ]
    started = time.monotonic()
    code, stdout, stderr = _run_command(
        collector_command,
        cwd=PROPERTY_SCRAPING,
        env=_safe_env(),
        timeout_seconds=child_timeout,
    )
    _write_log(log_dir, "collector.log", stdout + stderr)
    if code != 0:
        return {
            "status": "failed",
            "error": "collector_timeout" if code == 124 else "collector_failed",
            "duration_seconds": round(time.monotonic() - started, 3),
        }
    current_capture = _file_signature(capture.capture_path)
    if current_capture is None:
        return {
            "status": "failed",
            "error": "capture_missing",
            "duration_seconds": round(time.monotonic() - started, 3),
        }
    if previous_capture is not None and current_capture == previous_capture:
        return {
            "status": "failed",
            "error": "capture_unchanged",
            "duration_seconds": round(time.monotonic() - started, 3),
        }
    try:
        ingested = ingest_listings(capture, lake_uri=lake_uri)
    except PropertyCycleError as exc:
        _write_log(log_dir, "ingest.log", exc.code)
        return {
            "status": "failed",
            "error": exc.code,
            "duration_seconds": round(time.monotonic() - started, 3),
            "counts": _safe_counts(stdout),
        }
    _write_log(log_dir, "ingest.log", json.dumps(ingested, sort_keys=True))
    counts = _safe_counts(stdout)
    counts["ingested_records"] = ingested["records"]
    return {
        "status": "ok",
        "duration_seconds": round(time.monotonic() - started, 3),
        "counts": counts,
        "lake": {"run_id": ingested["run_id"], "existing": ingested["manifest_existed"]},
    }


def run_property_cycle(
    *,
    lake_uri: str,
    capture: PropertyCapture = PROPERTY_CAPTURE,
    lock_path: Path = DEFAULT_LOCK_PATH,
    log_dir: Path = DEFAULT_LOG_DIR,
    attempts: int = 2,
    retry_backoff_seconds: float = 1.0,
    lock_timeout_seconds: float = 0.0,
    timeout_seconds: float | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run the collector/ingest chain with finite retries."""
    if attempts < 1:
        raise ValueError("attempts must be positive")
    if retry_backoff_seconds < 0:
        raise ValueError("retry backoff must be non-negative")
    started_at = utc_now_iso()
    if dry_run:
        return {
            "status": "dry-run",
            "product": "property",
            "attempts": 0,
            "started_at": started_at,
            "completed_at": utc_now_iso(),
            "plan": {
                "source_job": capture.source_job,
                "feed_url": capture.feed_url,
                "limit": capture.limit,
                "dataset": "property_listings",
                "contact_enrichment": "disabled",
                "network": "not-used",
                "writes": "not-used",
            },
            "result": {},
        }
    validate_lake_uri(lake_uri)
    require_dependencies()
    try:
        with acquire_lock(lock_path, timeout_seconds=lock_timeout_seconds):
            result: dict[str, Any] = {}
            for attempt in range(1, attempts + 1):
                result = run_capture(
                    capture,
                    lake_uri=lake_uri,
                    log_dir=log_dir,
                    timeout_seconds=timeout_seconds,
                )
                result["attempt"] = attempt
                # Gate failures (contact data, header drift) are not transient.
                if result["status"] == "ok" or result.get("error") in {
                    "contact_fields_present",
                    "capture_headers_mismatch",
                }:
                    break
                if attempt < attempts and retry_backoff_seconds:
                    time.sleep(retry_backoff_seconds * (2 ** (attempt - 1)))
            return {
                "status": result.get("status", "failed"),
                "product": "property",
                "attempts": int(result.get("attempt", 0)),
                "started_at": started_at,
                "completed_at": utc_now_iso(),
                "result": result,
            }
    except LockBusyError as exc:
        return {
            "status": "locked",
            "product": "property",
            "attempts": 0,
            "error": exc.code,
            "started_at": started_at,
            "completed_at": utc_now_iso(),
            "result": {},
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lake-uri",
        default=os.environ.get("SOLO_EMPIRE_DATA_LAKE_URI", DEFAULT_LAKE_URI),
    )
    parser.add_argument("--lock-path", type=Path, default=DEFAULT_LOCK_PATH)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--retry-backoff-seconds", type=float, default=1.0)
    parser.add_argument("--lock-timeout-seconds", type=float, default=0.0)
    parser.add_argument("--timeout-seconds", type=float, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Print the bounded plan without collection or writes")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_property_cycle(
            lake_uri=args.lake_uri,
            lock_path=args.lock_path,
            log_dir=args.log_dir,
            attempts=args.attempts,
            retry_backoff_seconds=args.retry_backoff_seconds,
            lock_timeout_seconds=args.lock_timeout_seconds,
            timeout_seconds=args.timeout_seconds,
            dry_run=args.dry_run,
        )
    except (PropertyCycleError, ValueError) as exc:
        report = {
            "status": "blocked",
            "error": exc.code if isinstance(exc, PropertyCycleError) else type(exc).__name__,
            "product": "property",
            "attempts": 0,
            "started_at": utc_now_iso(),
            "completed_at": utc_now_iso(),
            "result": {},
        }
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        result = report.get("result", {})
        print(
            "property capture: "
            f"{report['status']} (attempt={report.get('attempts', 0)}, "
            f"error={report.get('error', result.get('error', 'none'))})"
        )
    return (
        0
        if report["status"] in {"ok", "dry-run"}
        else 2
        if report["status"] in {"locked", "blocked"}
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
