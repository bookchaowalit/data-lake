"""Bounded discovery capture and replay through the shared local lake adapter.

Domain repositories own parsers and exact source policies. This module owns
transport, source locks, capture lineage and failure state, never domain facts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

from data_lake import product_adapter as lake

VERSION = 1
USER_AGENT = 'SoloEmpireDiscovery/0.1 (+https://github.com/bookchaowalit)'
MAX_BYTES = 2_000_000


class CaptureError(ValueError):
    pass


def lock_capture_file(lock, *, platform=None):
    """Acquire the per-source lock without blocking on POSIX or Windows."""
    platform = platform or os.name
    if platform == 'nt':
        import msvcrt

        # msvcrt locks a byte range, so keep byte zero present and lock it.
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b'\0')
            lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CaptureError('redirect requires source policy review')


def public_url(url, *, allow_query=False):
    value = urlsplit(url)
    if value.scheme != 'https' or not value.hostname or value.username or value.password or (value.query and not allow_query) or value.fragment or value.port:
        raise CaptureError('invalid canonical source URL')
    return value


def fetch_url(source):
    """Build a reviewed source URL with an explicit, static query only."""
    base = source['fetch_url']
    public_url(base)
    query = source.get('fetch_query')
    if query is None:
        return base
    if not isinstance(query, dict) or not query:
        raise CaptureError('invalid source query')
    for key, value in query.items():
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', key):
            raise CaptureError('invalid source query key')
        if not isinstance(value, (str, int)) or isinstance(value, bool) or not str(value):
            raise CaptureError('invalid source query value')
    encoded = urlencode(sorted(query.items()))
    parts = public_url(base)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, encoded, ''))


def get(url, *, accept, attempts=2, allow_query=False):
    public_url(url, allow_query=allow_query)
    for attempt in range(attempts):
        try:
            request = Request(url, headers={'User-Agent': USER_AGENT, 'Accept': accept})
            with build_opener(NoRedirect).open(request, timeout=15) as response:
                content_type = response.headers.get('Content-Type', '').split(';')[0]
                raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES or not raw:
                    raise CaptureError('response size outside limit')
                return raw, content_type
        except HTTPError as exc:
            # No rapid retry of 429, auth failures, missing sources or redirects.
            if exc.code not in {500, 502, 503, 504} or attempt + 1 == attempts:
                raise CaptureError('source HTTP failure') from None
        except (URLError, TimeoutError, OSError):
            if attempt + 1 == attempts:
                raise CaptureError('source transport failure') from None
        time.sleep(2)
    raise CaptureError('source unavailable')


def fetch(source):
    url = fetch_url(source)
    has_query = bool(urlsplit(url).query)
    if source['access'] == 'html':
        robots_url = source.get('robots_url') or ('https://' + urlsplit(source['fetch_url']).netloc + '/robots.txt')
        raw, kind = get(robots_url, accept='text/plain')
        if kind != 'text/plain':
            raise CaptureError('robots response is not plain text')
        robots = RobotFileParser()
        robots.parse(raw.decode('utf-8').splitlines())
        if not robots.can_fetch(USER_AGENT, url):
            raise CaptureError('source disallowed by robots')
        delay = robots.crawl_delay(USER_AGENT) or 1
        if delay > 10:
            raise CaptureError('crawl delay exceeds this bounded runner')
        time.sleep(delay)
    if has_query:
        raw, kind = get(url, accept=source['content_type'], allow_query=True)
    else:
        raw, kind = get(url, accept=source['content_type'])
    if kind != source['content_type']:
        raise CaptureError('unexpected source content type')
    # Do not archive session tokens embedded in public HTML. Select a supported
    # public API instead; exact source bytes must not be silently redacted.
    if re.search(rb'csrf[-_]token|authenticity_token|access_token|-----BEGIN [A-Z ]*PRIVATE KEY', raw, re.I):
        raise CaptureError('sensitive source marker; capture refused')
    return raw


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    temporary.replace(path)


def read_state(path):
    return json.loads(path.read_text()) if path.exists() else {}


def storage_paths(repo, lake_path, state_dir, *, create=False):
    # This first lane is local only; no implicit production R2/environment target.
    root = Path(lake_path).expanduser().resolve()
    state = Path(state_dir).expanduser().resolve()
    if '://' in lake_path:
        raise CaptureError('local lake path required')
    if create:
        state.mkdir(parents=True, exist_ok=True)
    return root, state


def replay(source, state, root, normalize, validate):
    if state.get('status') != 'ok':
        raise CaptureError('source has no successful current capture')
    expected_prefix = 'control/manifests/source=' + source['product'] + '/'
    key = state['manifest_key']
    if not key.startswith(expected_prefix) or '..' in Path(key).parts:
        raise CaptureError('manifest outside product boundary')
    from data_lake.storage import ObjectStore
    store = ObjectStore(str(root))
    manifest = json.loads(store.get_bytes(key))
    if manifest['source'] != source['product'] or manifest['metadata'].get('provider') != source['id']:
        raise CaptureError('manifest source mismatch')
    if manifest['metadata'].get('product_schema_version') != source['schema_version']:
        raise CaptureError('manifest contract version mismatch')
    raw_key = manifest['raw']['key']
    if not raw_key.startswith('landing/source=' + source['product'] + '/'):
        raise CaptureError('raw source boundary mismatch')
    raw = store.get_bytes(raw_key)
    if hashlib.sha256(raw).hexdigest() != manifest['raw']['sha256']:
        raise CaptureError('capture checksum mismatch')
    # A landing file alone is not a successful lake capture.
    bronze_key = manifest['bronze']['key']
    prefix = 'bronze/domain=' + source['domain'] + '/dataset=source_captures/schema_version=1/'
    if not bronze_key.startswith(prefix) or '/source=' + source['product'] + '/' not in bronze_key:
        raise CaptureError('Bronze source boundary mismatch')
    bronze = store.get_bytes(bronze_key)
    if hashlib.sha256(bronze).hexdigest() != manifest['bronze']['sha256']:
        raise CaptureError('Bronze checksum mismatch')
    payload = normalize(raw, source, state['checked_at'])
    for item in payload['items']:
        item['provenance'].update(raw_object_key=raw_key, bronze_manifest_key=key)
    validate(payload)
    return payload


def acquire(source, root, state_dir, normalize, validate, *, fetcher=fetch, now=None):
    if not source.get('enabled') or source.get('permission_status') != 'reviewed-public-read':
        raise CaptureError('source not enabled and reviewed')
    now = now or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    state_path = state_dir / (source['id'] + '.json')
    with (state_dir / (source['id'] + '.lock')).open('a+b') as lock:
        lock_capture_file(lock)
        previous = read_state(state_path)
        if previous.get('last_attempt_at'):
            elapsed = (datetime.fromisoformat(now.replace('Z','+00:00')) - datetime.fromisoformat(previous['last_attempt_at'].replace('Z','+00:00'))).total_seconds()
            # A reviewed source query is part of the capture policy. Allow one
            # immediate migration capture when a source gains or changes its
            # explicit static query; subsequent attempts remain rate-limited.
            query_changed = source.get('fetch_query') is not None and previous.get('fetch_query') != source.get('fetch_query')
            if elapsed < source['min_interval_seconds'] and not query_changed:
                if previous.get('status') == 'ok':
                    replay(source, previous, root, normalize, validate)
                    return {'source':source['id'], 'status':'cached', 'checked_at':previous['checked_at'], 'count':previous['count']}
                raise CaptureError('source retry cooldown active')
        state = {'source':source['id'], 'status':'failed', 'last_attempt_at':now}
        if source.get('fetch_query') is not None:
            state['fetch_query'] = source['fetch_query']
        atomic_json(state_path, state)
        try:
            raw = fetcher(source)
            contract = lake.LakeProductContract(source=source['product'], domain=source['domain'], product_schema_version=source['schema_version'], project_root=Path(__file__).resolve().parents[3], privacy_class='public', retention_class='operational')
            # Capture document metadata first. Domain normalization only runs
            # after exact raw bytes, Bronze and manifest have been persisted.
            result = lake.ingest_to_lake(contract, raw=raw, records=[{'id':source['id'], 'source_url':source['source_url']}], dataset='source_captures', data_lake_uri=str(root), content_type=source['content_type'], input_format='html' if source['access']=='html' else 'json', provider=source['id'], metadata={'permission_reviewed_at':source['reviewed_at'], 'capture_contract':'discovery.capture.v1'})
            state.update(manifest_key=result['manifest_key'], checked_at=now, status='ok')
            payload = replay(source, state, root, normalize, validate)
            state['count'] = len(payload['items'])
            atomic_json(state_path, state)
            return {'source':source['id'],'status':'captured','checked_at':now,'count':state['count']}
        except Exception:
            state['status'] = 'quarantined' if state.get('manifest_key') else 'failed'
            atomic_json(state_path, state)
            raise CaptureError('capture failed; inspect source state and replay tests') from None


def run(source, normalize, validate, argv=None):
    parser = argparse.ArgumentParser(description='Explicit source capture and read-only lake replay')
    parser.add_argument('command', choices=['acquire','records','status'])
    parser.add_argument('--lake', required=True, help='Explicit local lake directory')
    parser.add_argument('--state-dir', required=True, help='Product-local control directory')
    args = parser.parse_args(argv)
    try:
        root, state_dir = storage_paths(source['product'], args.lake, args.state_dir, create=args.command=='acquire')
        if args.command == 'acquire':
            output = acquire(source, root, state_dir, normalize, validate)
        else:
            state = read_state(state_dir / (source['id']+'.json'))
            output = replay(source, state, root, normalize, validate) if args.command=='records' else state
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, RuntimeError):
        print('Discovery operation failed; no synthetic fallback was used.', file=sys.stderr)
        return 2
