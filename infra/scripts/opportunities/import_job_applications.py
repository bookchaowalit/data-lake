#!/usr/bin/env python3
"""Preview/import confirmed application metadata into the canonical tracker.

Consumes the explicit confirmed_applications.json export from application_review.
No network, database, raw receipt contents, or application sends.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
# The tracker lives in the bookchaowalit/solo-opportunities repository (docs/ subtree).
OPPORTUNITIES_REPO = Path(os.environ.get(
    'SOLO_OPPORTUNITIES_ROOT',
    str(ROOT / 'projects/product/engineering/book-dev/github/bookchaowalit/private/solo-opportunities'),
))
TRACKER = OPPORTUNITIES_REPO / 'docs/applications/JOB-TRACKER.md'
PLACEHOLDER = '| — | — | — | — | No verified applications recorded in this tracker | — | — | — | Start from the central inventory after a real submission. |'


def validate(rows) -> list[dict]:
    if not isinstance(rows, list):
        raise ValueError('Expected confirmed application metadata list')
    confirmed, seen = [], set()
    for row in rows:
        if row.get('schema_version') != 'confirmed-application.v1' or row.get('status') != 'submitted':
            raise ValueError('Only confirmed-application.v1 submitted records can be imported')
        url = str(row.get('url', ''))
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Invalid source URL')
        for field in ('receipt_sha256', 'resume_sha256', 'cover_letter_sha256', 'packet_sha256'):
            if not re.fullmatch('[a-f0-9]{64}', str(row.get(field, ''))):
                raise ValueError('Missing confirmed receipt/material hash')
        for field in ('company', 'title'):
            if not str(row.get(field, '')).strip():
                raise ValueError('Missing application identity')
        submitted = datetime.fromisoformat(row['submitted_at'])
        if submitted.tzinfo is None or submitted > datetime.now(timezone.utc):
            raise ValueError('Invalid submission time')
        if date.fromisoformat(row['followup_date']) < submitted.date():
            raise ValueError('Follow-up precedes submission')
        if url in seen:
            continue
        seen.add(url)
        confirmed.append(row)
    return confirmed


def render_import(content: str, rows: list[dict]) -> tuple[str, int]:
    additions = []
    def cell(value):
        return str(value).replace('\n', ' ').replace('\r', ' ').replace('|', '\\|').replace('<', '&lt;').replace('>', '&gt;')
    for row in validate(rows):
        app_id = 'APP-' + hashlib.sha256(row['url'].encode()).hexdigest()[:16]
        if f'`{app_id}`' in content:
            continue
        # Plain source URL in Notes avoids interpreting upstream text as Markdown links.
        notes = (f"source: {row['url']} ; resume: {row['resume_sha256'][:12]} ; "
                 f"cover: {row['cover_letter_sha256'][:12]} ; receipt: {row['receipt_sha256'][:12]} ; "
                 'next: check response and follow up')
        additions.append('| ' + ' | '.join(map(cell, [f'`{app_id}`', '—', 'ATS/manual', row['company'],
            row['title'], row['submitted_at'][:10], 'submitted', row['followup_date'], notes])) + ' |')
    if not additions:
        return content, 0
    marker = '\n## Application status values'
    if marker not in content or '| Application ID |' not in content:
        raise ValueError('Canonical tracker table structure changed; review before importing')
    before, after = content.split(marker, 1)
    before = before.replace(PLACEHOLDER + '\n', '').rstrip()
    return before + '\n' + '\n'.join(additions) + '\n\n' + marker.lstrip('\n') + after, len(additions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='Explicit confirmed metadata export')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        updated, count = render_import(TRACKER.read_text(), json.loads(args.input.read_text()))
        if args.apply and count:
            with tempfile.NamedTemporaryFile('w', dir=TRACKER.parent, delete=False, encoding='utf-8') as handle:
                handle.write(updated)
                temporary = Path(handle.name)
            temporary.replace(TRACKER)
        print(json.dumps({'new_confirmed_applications': count, 'applied': bool(args.apply and count)}))
        return 0
    except (ValueError, KeyError, OSError, TypeError):
        print('Import blocked: invalid export or tracker structure', flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
