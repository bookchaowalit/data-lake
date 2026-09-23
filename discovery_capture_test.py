"""Offline capture failure, lineage and transport tests with real local Parquet."""
import importlib
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'infra/scripts'))
from discovery import capture_runtime as runtime
from discovery.portfolio import select_items
from datetime import datetime, timezone


class CaptureTests(unittest.TestCase):
    def setUp(self):
        manifest=json.loads((ROOT/'systems/architecture/discovery-portfolio-v1.json').read_text())
        product=next(p for p in manifest['products'] if p['domain']=='scholarship')
        repo=ROOT/product['local_path']
        if not repo.exists():self.skipTest('ignored source pilot absent')
        sys.path.insert(0,str(repo/'src'))
        self.domain=importlib.import_module('book_scholarship_data.capture')
        self.source=self.domain.resource('source.json')
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lake=Path(self.tmp.name)/'lake'
        self.control=Path(self.tmp.name)/'control';self.control.mkdir()
        self.raw=b'<h1>Chevening in Thailand</h1><p>Open for applications until 6 October 2026, at 11:00 (UTC)</p>'
        self.clock='2026-09-07T00:00:00Z'

    def capture(self, raw=None, now=None):
        return runtime.acquire(self.source,self.lake,self.control,self.domain.normalize,self.domain.validate,fetcher=lambda _: self.raw if raw is None else raw,now=now or self.clock)

    def state(self):
        return json.loads((self.control/(self.source['id']+'.json')).read_text())

    def test_capture_lock_is_nonblocking_and_preserves_the_lock_file(self):
        lock_path = self.control / 'source.lock'
        with lock_path.open('a+b') as first:
            runtime.lock_capture_file(first)
            with lock_path.open('a+b') as second:
                with self.assertRaises(OSError):
                    runtime.lock_capture_file(second)

    def test_windows_capture_lock_uses_a_persistent_first_byte(self):
        lock_path = self.control / 'windows-source.lock'
        calls = []
        msvcrt = SimpleNamespace(
            LK_NBLCK=17,
            locking=lambda fd, operation, length: calls.append((fd, operation, length)),
        )
        with patch.dict(sys.modules, {'msvcrt': msvcrt}):
            with lock_path.open('a+b') as lock:
                runtime.lock_capture_file(lock, platform='nt')
        self.assertEqual(lock_path.read_bytes(), b'\0')
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1:], (msvcrt.LK_NBLCK, 1))

    def test_landing_bronze_before_replay_and_idempotent(self):
        self.assertEqual(self.capture()['status'],'captured')
        before=sorted(str(p) for p in self.lake.rglob('*') if p.is_file())
        self.assertEqual(self.capture()['status'],'cached')
        self.capture(now='2026-09-07T07:00:00Z')
        self.assertEqual(before,sorted(str(p) for p in self.lake.rglob('*') if p.is_file()))
        with patch('socket.socket',side_effect=AssertionError('network forbidden')):
            payload=runtime.replay(self.source,self.state(),self.lake,self.domain.normalize,self.domain.validate)
        self.assertEqual(payload['items'][0]['provenance']['checked_at'],'2026-09-07T07:00:00Z')
        manifest=json.loads((self.lake/self.state()['manifest_key']).read_text())
        self.assertEqual((self.lake/manifest['raw']['key']).read_bytes(),self.raw)
        self.assertTrue((self.lake/manifest['bronze']['key']).is_file())

    def test_invalid_source_quarantined_without_projection(self):
        with self.assertRaises(runtime.CaptureError):self.capture(raw=b'<h1>Unexpected redesign</h1>')
        self.assertEqual(self.state()['status'],'quarantined')
        self.assertTrue((self.lake/self.state()['manifest_key']).is_file())
        with self.assertRaises(runtime.CaptureError):
            runtime.replay(self.source,self.state(),self.lake,self.domain.normalize,self.domain.validate)

    def test_failure_does_not_fall_back_to_old_success(self):
        self.capture()
        def fail(_):raise runtime.CaptureError('unavailable')
        with self.assertRaises(runtime.CaptureError):
            runtime.acquire(self.source,self.lake,self.control,self.domain.normalize,self.domain.validate,fetcher=fail,now='2026-09-07T07:00:00Z')
        self.assertEqual(self.state()['status'],'failed')
        with self.assertRaises(runtime.CaptureError):self.capture(now='2026-09-07T07:01:00Z')

    def test_corrupted_raw_rejected(self):
        self.capture();state=self.state()
        manifest=json.loads((self.lake/state['manifest_key']).read_text())
        (self.lake/manifest['raw']['key']).write_bytes(b'corrupted')
        with self.assertRaises(runtime.CaptureError):runtime.replay(self.source,state,self.lake,self.domain.normalize,self.domain.validate)

    def test_missing_bronze_rejected(self):
        self.capture();state=self.state()
        manifest=json.loads((self.lake/state['manifest_key']).read_text())
        (self.lake/manifest['bronze']['key']).unlink()
        with self.assertRaises(RuntimeError):runtime.replay(self.source,state,self.lake,self.domain.normalize,self.domain.validate)

    def test_redirect_and_sensitive_payload_refused(self):
        with self.assertRaises(runtime.CaptureError):runtime.NoRedirect().redirect_request(None,None,302,'',{},'https://elsewhere.invalid')
        source=dict(self.source,access='govuk-api')
        with patch.object(runtime,'get',return_value=(b'<meta name="csrf-token" content="synthetic">','text/html')):
            with self.assertRaises(runtime.CaptureError):runtime.fetch(source)

    def test_robots_disallow(self):
        with patch.object(runtime,'get',return_value=(b'User-agent: *\nDisallow: /\n','text/plain')):
            with self.assertRaises(runtime.CaptureError):runtime.fetch(self.source)

    def test_source_specific_robots_url_is_honored(self):
        source = dict(self.source, robots_url='https://policy.example/robots.txt')
        calls = []

        def get(url, *, accept):
            calls.append(url)
            if url == source['robots_url']:
                return b'User-agent: *\nAllow: /\n', 'text/plain'
            return self.raw, 'text/html'

        with patch.object(runtime, 'get', side_effect=get), patch.object(runtime.time, 'sleep'):
            self.assertEqual(runtime.fetch(source), self.raw)
        self.assertEqual(calls[0], source['robots_url'])

    def test_static_source_query_is_canonical_and_explicit(self):
        source = dict(self.source, fetch_query={'stages': 'tender', 'limit': '100'})
        expected = self.source['fetch_url'] + '?limit=100&stages=tender'
        self.assertEqual(
            runtime.fetch_url(source),
            expected,
        )
        with self.assertRaises(runtime.CaptureError):
            runtime.fetch_url(dict(self.source, fetch_query={'cursor': object()}))
        with self.assertRaises(runtime.CaptureError):
            runtime.public_url('https://example.org/source?token=synthetic')

    def test_query_policy_migration_allows_one_immediate_capture(self):
        source = dict(self.source, fetch_query={'stages': 'tender', 'limit': '100'})
        self.assertEqual(
            runtime.acquire(
                source,
                self.lake,
                self.control,
                self.domain.normalize,
                self.domain.validate,
                fetcher=lambda _: self.raw,
                now=self.clock,
            )['status'],
            'captured',
        )
        state_path = self.control / (source['id'] + '.json')
        state = json.loads(state_path.read_text())
        state.pop('fetch_query')
        state_path.write_text(json.dumps(state))
        self.assertEqual(
            runtime.acquire(
                source,
                self.lake,
                self.control,
                self.domain.normalize,
                self.domain.validate,
                fetcher=lambda _: self.raw,
                now=self.clock,
            )['status'],
            'captured',
        )

    def test_cross_product_manifest_refused(self):
        self.capture();state=self.state();state['manifest_key']='control/manifests/source=another/test.json'
        with self.assertRaises(runtime.CaptureError):runtime.replay(self.source,state,self.lake,self.domain.normalize,self.domain.validate)

    def test_unreviewed_source_never_fetched(self):
        source=dict(self.source,permission_status='unknown')
        with self.assertRaises(runtime.CaptureError):
            runtime.acquire(source,self.lake,self.control,self.domain.normalize,self.domain.validate,fetcher=lambda _:self.fail('fetch forbidden'))

    def test_portfolio_open_filter_deadline_and_staleness(self):
        self.capture()
        payload=runtime.replay(self.source,self.state(),self.lake,self.domain.normalize,self.domain.validate)
        self.assertEqual(len(select_items(payload,datetime(2026,9,7,tzinfo=timezone.utc),open_only=True)),1)
        self.assertEqual(select_items(payload,datetime(2026,9,12,tzinfo=timezone.utc),open_only=True),[])
        payload['items'][0].pop('record_kind', None)
        self.assertEqual(len(select_items(payload,datetime(2026,9,7,tzinfo=timezone.utc),open_only=True)),1)
        payload['items'][0]['record_kind']='directory'
        self.assertEqual(select_items(payload,datetime(2026,9,7,tzinfo=timezone.utc),open_only=True),[])
        payload['items'][0]['record_kind']='program'
        payload['items'][0]['deadline']={'kind':'unknown','at':None}
        payload['items'][0]['availability']={'kind':'continuous','starts_at':'2026-08-01T00:00:00Z','ends_at':None}
        self.assertEqual(len(select_items(payload,datetime(2026,9,7,tzinfo=timezone.utc),open_only=True)),1)
        payload['items'][0]['availability']={'kind':'scheduled','starts_at':'2026-10-01T00:00:00Z','ends_at':None}
        self.assertEqual(select_items(payload,datetime(2026,9,7,tzinfo=timezone.utc),open_only=True),[])
        selected=select_items(payload,datetime(2026,9,7,tzinfo=timezone.utc))
        self.assertEqual(selected[0]['availability'],'scheduled')
        self.assertEqual(selected[0]['availability_starts_at'],'2026-10-01T00:00:00Z')
        self.assertGreater(selected[0]['days_until_start'],23)
        self.assertEqual(len(select_items(payload,datetime(2026,9,7,tzinfo=timezone.utc),starting_within_days=30)),1)
        self.assertEqual(select_items(payload,datetime(2026,9,7,tzinfo=timezone.utc),starting_within_days=20),[])
        self.assertEqual(len(select_items(payload,datetime(2026,9,7,tzinfo=timezone.utc),upcoming_within_days=30)),1)
        deadline_item=deepcopy(payload['items'][0])
        deadline_item['id']='fixed-deadline'
        deadline_item['title']='Fixed deadline opportunity'
        deadline_item['availability']={'kind':'unknown','starts_at':None,'ends_at':None}
        deadline_item['deadline']={'kind':'fixed','at':'2026-09-16T10:00:00Z'}
        payload['items'].append(deadline_item)
        upcoming=select_items(payload,datetime(2026,9,7,tzinfo=timezone.utc),upcoming_within_days=10)
        self.assertEqual([row['item']['id'] for row in upcoming],['fixed-deadline'])
        self.assertEqual(upcoming[0]['queue_reasons'],['deadline'])
        self.assertGreater(upcoming[0]['days_until_deadline'],8)
        with self.assertRaises(ValueError):
            select_items(payload,datetime(2026,9,7,tzinfo=timezone.utc),starting_within_days=-1)
        with self.assertRaises(ValueError):
            select_items(payload,datetime(2026,9,7,tzinfo=timezone.utc),upcoming_within_days=-1)


if __name__=='__main__':unittest.main()
