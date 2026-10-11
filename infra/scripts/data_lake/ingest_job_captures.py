#!/usr/bin/env python3
"""Control-plane adapter for the owned ``book-job-data`` capture ingest.

The job product owns normalization and the ``job.v1`` contract.  This small
adapter only gives the repository operator a safe, shared-lake command and
keeps the public product implementation in its own boundary.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "infra" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from data_lake.workspace import OWNER_ROOT, WORKSPACE  # noqa: E402

JOB_REPOSITORY = OWNER_ROOT / "public/book-apps/tools/book-job-data"
if str(JOB_REPOSITORY / "src") not in sys.path:
    sys.path.insert(0, str(JOB_REPOSITORY / "src"))

from book_job_data import ingest as job_ingest  # noqa: E402


DEFAULT_LAKE_URI = str(ROOT / "data" / "lake-local" / "scraping-captures-v2")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", dest="inputs")
    parser.add_argument("--data-lake-uri", default=DEFAULT_LAKE_URI)
    parser.add_argument("--provider", default="book-job-scraping")
    parser.add_argument("--project-csv", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    forwarded = ["--data-lake-uri", args.data_lake_uri, "--provider", args.provider]
    inputs = [Path(value).expanduser().resolve() for value in (args.inputs or [])]
    if not inputs:
        inputs = [path.resolve() for path in job_ingest.default_inputs()]
        # ``career_postings.csv`` is an approved book-job-scraping capture that
        # the generic Track B ingest already normalizes as job_postings. Keep
        # the parent operator adapter explicit so the default task does not
        # silently omit that source while the public job-data boundary remains
        # collection-only.
        career_capture = OWNER_ROOT / "public/book-apps/tools/book-job-scraping/data/career_postings.csv"
        if career_capture.is_file() and career_capture.resolve() not in inputs:
            inputs.append(career_capture.resolve())
    # The owned ingest records input_path in manifest metadata. Run from the
    # repository root and pass repo-relative paths so a Task invocation and a
    # direct shell invocation produce identical metadata for the same bytes.
    for path in inputs:
        try:
            stable_path = path.relative_to(WORKSPACE)
            forwarded.extend(("--input", stable_path.as_posix()))
        except ValueError:
            forwarded.extend(("--input", path.as_posix()))
    if args.project_csv:
        forwarded.append("--project-csv")
    if args.dry_run:
        forwarded.append("--dry-run")
    previous_dir = Path.cwd()
    try:
        os.chdir(WORKSPACE)
        return int(job_ingest.main(forwarded))
    finally:
        os.chdir(previous_dir)


if __name__ == "__main__":
    raise SystemExit(main())
