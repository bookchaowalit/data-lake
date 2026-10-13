#!/usr/bin/env python3
"""Collect administrator-approved public catalogs, commit to lake, then publish."""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from data_lake.ingest import canonical_json, ingest_payload
    from data_lake.storage import ObjectStore
else:
    from .ingest import canonical_json, ingest_payload
    from .storage import ObjectStore

SCHEMA = 'solo-empire.platform-integrations.v1'
MAX_BYTES = 2 * 1024 * 1024
DEADLINE_SECONDS = 15
CONFIG = Path(__file__).resolve().parents[3] / 'systems/ai-data/platform-integration-sources.json'
PLATFORM_IDS = {'codex-app', 'codex-cli', 'claude-code', 'claude-web', 'claude-desktop'}
ID = re.compile(r'[a-z0-9][a-z0-9-]{0,95}\Z')


class CollectionError(ValueError):
    """Fixed public failure code; never embeds source payload or paths."""


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise CollectionError('duplicate_field')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(CollectionError('invalid_json')))
    except (ValueError, UnicodeError) as exc:
        raise CollectionError('invalid_json') from exc


def public_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) <= 32 for c in value):
        raise CollectionError('invalid_public_url')
    try:
        p = urlsplit(value)
        if p.scheme != 'https' or not p.hostname or p.username or p.password or p.query or p.fragment or p.port not in (None, 443):
            raise ValueError()
        if p.hostname == 'localhost' or '.' not in p.hostname or p.hostname.endswith(('.local', '.internal')):
            raise ValueError()
        try: ipaddress.ip_address(p.hostname)
        except ValueError: pass
        else: raise ValueError()
    except ValueError as exc:
        raise CollectionError('invalid_public_url') from exc
    return value


def capture_timestamp(value):
    try:
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', value): raise ValueError()
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp > datetime.now(timezone.utc) + timedelta(minutes=5): raise ValueError()
    except ValueError as exc:
        raise CollectionError('invalid_capture_timestamp') from exc
    return value


def load_config(path):
    try:
        config = strict_json(Path(path).read_bytes())
        if set(config) != {'schema_version', 'platforms', 'sources'} or config['schema_version'] != 'platform-integration-sources.v1': raise ValueError()
        if not isinstance(config['platforms'], list) or {p['id'] for p in config['platforms']} != PLATFORM_IDS or len(config['platforms']) != 5: raise ValueError()
        for p in config['platforms']:
            if set(p) != {'id', 'name', 'mcp_transports', 'docs_url'} or not isinstance(p['name'], str): raise ValueError()
            if not isinstance(p['mcp_transports'], list) or not set(p['mcp_transports']) <= {'stdio', 'sse', 'streamable_http'}: raise ValueError()
            public_url(p['docs_url'])
        if not isinstance(config['sources'], list) or not config['sources']: raise ValueError()
        seen = set()
        for s in config['sources']:
            if set(s) != {'id','owner','url','parser','platforms','permission','privacy_class','retention_class','freshness_hours','aliases'}: raise ValueError()
            if not isinstance(s['id'], str) or not ID.fullmatch(s['id']) or s['id'] in seen: raise ValueError()
            seen.add(s['id'])
            public_url(s['url'])
            if urlsplit(s['url']).hostname != 'raw.githubusercontent.com': raise ValueError()
            if s['parser'] not in {'codex_marketplace','claude_marketplace','mcp_config'}: raise ValueError()
            expected = {'codex_marketplace': {'codex-app','codex-cli'}, 'claude_marketplace': {'claude-code'}, 'mcp_config': PLATFORM_IDS}[s['parser']]
            if not isinstance(s['platforms'], list) or not s['platforms'] or not set(s['platforms']) <= expected or len(set(s['platforms'])) != len(s['platforms']): raise ValueError()
            if s['permission'] != 'public_catalog_read' or s['privacy_class'] != 'public' or s['retention_class'] != 'archival' or s['freshness_hours'] != 24: raise ValueError()
            if not isinstance(s['owner'], str) or not s['owner'] or not isinstance(s['aliases'], dict): raise ValueError()
            for name, app_ids in s['aliases'].items():
                if not ID.fullmatch(name): raise ValueError()
                if not isinstance(app_ids, list) or not app_ids or len(set(app_ids)) != len(app_ids) or any(not isinstance(a,str) or not ID.fullmatch(a) for a in app_ids): raise ValueError()
        return config
    except Exception as exc:
        raise CollectionError('invalid_source_config') from exc


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_public(url):
    """Bound the caller even if a server trickles HTTP headers indefinitely.

    The daemon only downloads bounded public bytes; it cannot publish or write
    lake objects. On timeout the run fails and CLI exit terminates the daemon.
    """
    public_url(url)
    if urlsplit(url).hostname != 'raw.githubusercontent.com': raise CollectionError('source_not_allowlisted')
    outcome = []
    def download():
        try: outcome.append(_fetch_public(url))
        except Exception as exc: outcome.append(exc)
    worker = threading.Thread(target=download,daemon=True)
    worker.start()
    worker.join(DEADLINE_SECONDS)
    if worker.is_alive(): raise CollectionError('source_deadline')
    if isinstance(outcome[0],Exception): raise outcome[0]
    return outcome[0]


def _fetch_public(url):
    public_url(url)
    if urlsplit(url).hostname != 'raw.githubusercontent.com': raise CollectionError('source_not_allowlisted')
    deadline = time.monotonic() + DEADLINE_SECONDS
    try:
        with build_opener(NoRedirect()).open(Request(url, headers={'Accept':'application/json', 'User-Agent':'SoloEmpirePublicCatalog/1'}), timeout=DEADLINE_SECONDS) as response:
            if response.status != 200: raise CollectionError('source_fetch_failed')
            length = response.headers.get('Content-Length')
            if length is not None and (not length.isdecimal() or int(length) > MAX_BYTES): raise CollectionError('source_too_large')
            chunks, size = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0: raise CollectionError('source_deadline')
                # Reset socket timeout to the remaining total request budget.
                sock = getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
                if sock is not None: sock.settimeout(remaining)
                # HTTPResponse.read1 returns after one underlying read, so a
                # trickling body cannot hide inside a buffered read until full.
                reader = getattr(response, 'read1', response.read)
                chunk = reader(min(65536, MAX_BYTES + 1 - size))
                if time.monotonic() > deadline: raise CollectionError('source_deadline')
                if not chunk: break
                size += len(chunk)
                if size > MAX_BYTES: raise CollectionError('source_too_large')
                chunks.append(chunk)
            return b''.join(chunks)
    except CollectionError: raise
    except Exception as exc: raise CollectionError('source_fetch_failed') from exc


def parse_capture(spec, raw, captured_at):
    capture_timestamp(captured_at)
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES: raise CollectionError('source_too_large')
    value = strict_json(raw)
    if not isinstance(value, dict): raise CollectionError('invalid_source_schema')
    manual = spec['parser'] == 'mcp_config'
    allowed = ({'mcpServers'} if 'mcpServers' in value else set(value)) if manual else ({'name','interface','plugins'} if spec['parser'] == 'codex_marketplace' else {'$schema','name','description','owner','renames','plugins'})
    if set(value) - allowed: raise CollectionError('invalid_source_schema')
    entries = value.get('mcpServers', value) if manual else value.get('plugins')
    if (manual and not isinstance(entries, dict)) or (not manual and not isinstance(entries, list)):
        raise CollectionError('invalid_source_schema')
    entries = list(entries.items()) if manual else [(p.get('name') if isinstance(p,dict) else None,p) for p in entries]
    seen, rows = set(), []
    for name, entry in entries:
        if not isinstance(name,str) or not ID.fullmatch(name) or name in seen or not isinstance(entry,dict): raise CollectionError('invalid_source_schema')
        seen.add(name)
        apps = spec['aliases'].get(name, [])
        endpoint = None
        availability = 'available'
        restricted = False
        if manual:
            # Approved public references may declare variable placeholders. They
            # are archived verbatim but never resolved or projected. Literal
            # header/env values are rejected before any public lake write.
            for field in ('headers','env'):
                placeholders = entry.get(field,{})
                if not isinstance(placeholders,dict) or any(not isinstance(v,str) or not re.fullmatch(r'(?:Bearer )?\$\{[A-Za-z_][A-Za-z0-9_]*\}',v) for v in placeholders.values()): raise CollectionError('private_source_fields')
            if set(entry) - {'url','type','command','args','headers','env'}: raise CollectionError('invalid_source_schema')
            if 'url' not in entry: continue  # command sources are never executed or inferred
            endpoint = public_url(entry['url'])
            if entry.get('type', 'http') not in {'http','sse','streamable-http'}: raise CollectionError('invalid_source_schema')
        else:
            allowed_entry = {'name','description','author','category','source','homepage','policy','interface','platforms','supportedPlatforms','version','tags','displayName','keywords','lspServers','skills','strict'}
            if set(entry) - allowed_entry: raise CollectionError('invalid_source_schema')
            # Unrecognized surface restrictions fail closed rather than claim CLI support.
            surfaces = entry.get('platforms', entry.get('supportedPlatforms'))
            if surfaces is not None:
                if not isinstance(surfaces,list) or not surfaces or any(s not in {'desktop','cli','codex-app','codex-cli','claude-code'} for s in surfaces): raise CollectionError('invalid_surface_restriction')
                restricted = True
            policy = entry.get('policy', {})
            if not isinstance(policy,dict): raise CollectionError('invalid_source_schema')
            installation = policy.get('installation', 'AVAILABLE')
            if installation != 'AVAILABLE': availability = 'unknown'
        for platform in spec['platforms']:
            state = availability
            if restricted and platform not in surfaces and {'codex-app':'desktop','codex-cli':'cli'}.get(platform) not in surfaces: state = 'unknown'
            for app in apps:
                rows.append({'platform_id':platform,'app_id':app,'channel':'manual_mcp' if manual else 'plugin','availability':state,'entry_id':name,'endpoint_url':endpoint,'evidence_url':spec['url'],'captured_at':captured_at})
    return rows


def sha(raw): return hashlib.sha256(raw).hexdigest()


def verified_manifest(store, result, expected_raw, source_id=None):
    key = result['manifest_key']
    if not key.startswith('control/manifests/') or '..' in key.split('/'): raise CollectionError('invalid_manifest_key')
    body = store.get_bytes(key)
    manifest = strict_json(body)
    for part in ('raw','bronze'):
        data = store.get_bytes(manifest[part]['key'])
        if sha(data) != manifest[part]['sha256'] or len(data) != manifest[part]['bytes']: raise CollectionError('artifact_corrupt')
        if part == 'raw' and data != expected_raw: raise CollectionError('artifact_corrupt')
    lineage = {'manifest_key':key,'manifest_sha256':sha(body),'raw_sha256':manifest['raw']['sha256'],'bronze_sha256':manifest['bronze']['sha256']}
    if source_id: lineage = {'source_id':source_id, **lineage}
    return lineage


def publish(config, captures, captured_at, lake_uri, output):
    try:
        capture_timestamp(captured_at)
        if set(captures) != {s['id'] for s in config['sources']}: raise CollectionError('missing_capture')
        # Parse all captures before writing any lake objects. Rejected bytes remain
        # in the caller-owned capture directory, never in a public quarantine.
        parsed = [(s, parse_capture(s, captures[s['id']], captured_at)) for s in config['sources']]
        rows = sorted([r for _, rs in parsed for r in rs], key=lambda r:(r['platform_id'],r['app_id'],r['channel'],r['entry_id']))
        grains = [(r['platform_id'],r['app_id'],r['channel'],r['entry_id']) for r in rows]
        if len(grains) != len(set(grains)): raise CollectionError('duplicate_capability')
        store, sources = ObjectStore(lake_uri), []
        for spec, records in parsed:
            result = ingest_payload(captures[spec['id']], records or [{'captured_at':captured_at,'catalog_empty':True}], source=spec['id'], domain='integrations', dataset='platform_integration_captures', data_lake_uri=lake_uri, schema_version=SCHEMA, privacy_class='public', retention_class='archival', event_time_field='captured_at', metadata={'provider':spec['id']+'-'+captured_at,'captured_at':captured_at,'source_url':spec['url']})
            sources.append(verified_manifest(store,result,captures[spec['id']],spec['id']))
        normalized = {'schema_version':SCHEMA,'captured_at':captured_at,'platforms':config['platforms'],'capabilities':rows,'source_manifests':sources}
        raw = (canonical_json(normalized)+'\n').encode()
        result = ingest_payload(raw, rows or [{'captured_at':captured_at,'catalog_empty':True}], source='platform-integrations',domain='integrations',dataset='platform_integrations',data_lake_uri=lake_uri,schema_version=SCHEMA,privacy_class='public',retention_class='archival',event_time_field='captured_at',metadata={'provider':'platform-integrations-'+captured_at,'captured_at':captured_at})
        lineage = {'dataset':'platform_integrations',**verified_manifest(store,result,raw),'source_manifests':sources}
        # Check every reference again immediately before publication.
        for spec, _ in parsed:
            source = next(s for s in sources if s['source_id'] == spec['id'])
            if verified_manifest(store, source, captures[spec['id']],spec['id']) != source: raise CollectionError('artifact_corrupt')
        if verified_manifest(store,result,raw) != {k:lineage[k] for k in ('manifest_key','manifest_sha256','raw_sha256','bronze_sha256')}: raise CollectionError('artifact_corrupt')
        snapshot = {k: normalized[k] for k in ('schema_version','captured_at','platforms','capabilities')}
        snapshot['lineage'] = lineage
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(dir=output.parent,prefix='.platform-integrations-',delete=False) as handle:
                temp_name = handle.name
                handle.write((canonical_json(snapshot)+'\n').encode())
                # This artifact contains public metadata and must remain readable
                # when a root-owned Docker COPY is served by an unprivileged API.
                os.fchmod(handle.fileno(), 0o644)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name,output)
        finally:
            if temp_name and os.path.exists(temp_name): os.unlink(temp_name)
        return snapshot
    except Exception as exc:
        raise CollectionError('collection_failed') from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--fetch',action='store_true')
    mode.add_argument('--capture-dir',type=Path)
    parser.add_argument('--captured-at')
    parser.add_argument('--source-config',type=Path,default=CONFIG)
    parser.add_argument('--lake-uri',required=True)
    parser.add_argument('--output',required=True,type=Path)
    args = parser.parse_args()
    try:
        config = load_config(args.source_config)
        if args.capture_dir and not args.captured_at: raise CollectionError('original_capture_timestamp_required')
        stamp = capture_timestamp(args.captured_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z'))
        captures = {}
        for spec in config['sources']:
            if args.fetch: captures[spec['id']] = fetch_public(spec['url'])
            else:
                path = args.capture_dir / (spec['id']+'.json')
                if path.is_symlink() or path.stat().st_size > MAX_BYTES: raise CollectionError('invalid_capture_file')
                captures[spec['id']] = path.read_bytes()
        snapshot = publish(config,captures,stamp,args.lake_uri,args.output)
        print(canonical_json({'status':'success','schema_version':SCHEMA,'captured_at':stamp,'capability_count':len(snapshot['capabilities']),'lineage':snapshot['lineage']}))
        return 0
    except Exception as exc:
        code = str(exc) if isinstance(exc,CollectionError) else 'collection_failed'
        print(canonical_json({'status':'error','error':code,'quarantine':'retain_original_capture_locally','publication':'previous_preserved'}))
        return 1


if __name__ == '__main__': sys.exit(main())
