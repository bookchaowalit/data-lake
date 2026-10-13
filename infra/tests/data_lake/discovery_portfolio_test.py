"""Offline ownership and local scaffold checks; no live source claims."""
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'infra' / 'scripts'))
from data_lake.workspace import product_path  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / 'systems/architecture/discovery-portfolio-v1.json'
CATEGORY_REGISTRY = ROOT / 'systems/architecture/discovery-category-registry-v1.json'


class DiscoveryPortfolioTests(unittest.TestCase):
    def setUp(self):
        self.portfolio = json.loads(MANIFEST.read_text())
        self.products = self.portfolio['products']
        self.registry = json.loads(CATEGORY_REGISTRY.read_text())

    def test_unique_domain_ownership(self):
        self.assertEqual(len(self.products), 14)
        for key in ('id', 'domain', 'local_path', 'schema_version'):
            self.assertEqual(len({p[key] for p in self.products}), len(self.products))
        categories = [c for p in self.products for c in p['categories']]
        self.assertEqual(len(categories), len(set(categories)))
        for product in self.products:
            self.assertEqual(product['live_sources_enabled'], product['domain'] in {'scholarship','grant','freebie','deal','benefit','competition','bounty','startup-program','paid-study','mobility-program','procurement','learning-program','partnership','creator-program'})
            self.assertIsNone(product['remote_url'])
            self.assertIsNone(product['last_known_commit'])
            self.assertEqual(product['consumer_integration'], 'local-cli' if product['live_sources_enabled'] else 'planned')
            capabilities = product.get('enabled_category_capabilities', [])
            self.assertEqual(len(capabilities), len(set(capabilities)))
            self.assertTrue(set(capabilities) <= set(product['categories']))
            self.assertNotIn('..', Path(product['local_path']).parts)
            self.assertFalse(Path(product['local_path']).is_absolute())
            # Checkout folders follow the domain-first repository names (2026-10-13);
            # the product id stays the contract id.
            self.assertEqual(Path(product['local_path']).name, 'opportunity-' + product['id'].removeprefix('book-'))

    def test_catalog_staging_matches_manifest(self):
        catalog = yaml.safe_load((ROOT / 'repository-catalog/registries/projects.yaml').read_text())
        staging = {p['id']: p for p in catalog['local_staging']}
        published = {p['id'] for p in catalog['projects']}
        for product in self.products:
            self.assertNotIn(product['id'], published)
            self.assertEqual(staging[product['id']]['local_path'], product['local_path'])
            self.assertEqual(staging[product['id']]['schema_version'], product['schema_version'])
            self.assertEqual(staging[product['id']]['status'], product['status'])

    def test_existing_contracts_remain_separate(self):
        contracts = {p.get('contract') for p in self.portfolio['reuse_existing']}
        self.assertTrue({'job.v1', 'flight.v1'} <= contracts)
        self.assertNotIn('opportunity.v1', contracts)
        self.assertFalse({'job.v1'} & {p['schema_version'] for p in self.products})

    def test_local_checkouts_are_independent_and_explicitly_synthetic(self):
        present = [p for p in self.products if product_path(p['local_path']).exists()]
        if not present:
            self.skipTest('Ignored local scaffolds absent; manifest-only checkout')
        self.assertEqual(len(present), len(self.products), 'Partial local scaffold creation')
        for product in present:
            with self.subTest(product=product['id']):
                repo = product_path(product['local_path'])
                self.assertTrue((repo / '.git').is_dir())
                result = subprocess.run(['git', '-C', str(repo), 'rev-parse', '--show-toplevel'], capture_output=True, text=True, check=True)
                self.assertEqual(Path(result.stdout.strip()).resolve(), repo.resolve())
                package = repo / 'src' / product['id'].replace('-', '_')
                schema = json.loads((package / 'schema.json').read_text())
                self.assertEqual(schema['properties']['schema_version']['const'], product['schema_version'])
                terms = schema['properties']['items']['items']['properties']['terms']
                self.assertEqual(set(terms['required']), set(product['domain_fields']))
                fixture = json.loads((package / 'demo.json').read_text())
                self.assertEqual(fixture['data_status'], 'fixture')
                sources = json.loads((repo / 'sources.json').read_text())
                self.assertEqual(sources['network_enabled'], product['live_sources_enabled'])
                self.assertEqual(sources['enabled_sources'], product.get('enabled_source_ids', []))
                self.assertEqual(sources.get('enabled_category_capabilities', []), product.get('enabled_category_capabilities', []))
                self.assertTrue((repo / 'tests/test_contract.py').is_file())

    def test_category_registry_matches_manifest_and_keeps_uncovered_work_explicit(self):
        self.assertEqual(self.registry['contract'], 'discovery.category-registry.v1')
        by_id = {product['product_id']: product for product in self.registry['products']}
        self.assertEqual(set(by_id), {product['id'] for product in self.products})
        allowed = {'observed-live', 'adapter-capable', 'source-registration-required'}
        declared = 0
        observed = 0
        registered = 0
        pending = 0
        for product in self.products:
            entry = by_id[product['id']]
            self.assertEqual(entry['domain'], product['domain'])
            categories = entry['categories']
            self.assertEqual([row['id'] for row in categories], product['categories'])
            enabled_sources = set(product.get('enabled_source_ids') or [])
            for row in categories:
                self.assertIn(row['state'], allowed)
                self.assertTrue(set(row['source_ids']) <= enabled_sources)
                declared += 1
                observed += row['state'] == 'observed-live'
                registered += bool(row['source_ids'])
                pending += row['state'] == 'source-registration-required'
        self.assertEqual(self.registry['summary'], {
            'declared_categories': declared,
            'observed_live': observed,
            'registered_adapter_capabilities': registered,
            'adapter_capable_without_current_record': registered - observed,
            'source_registration_required': pending,
        })
        self.assertEqual(self.registry['summary']['declared_categories'], 76)
        self.assertEqual(self.registry['summary']['observed_live'], 73)
        self.assertEqual(self.registry['summary']['registered_adapter_capabilities'], 76)
        self.assertEqual(self.registry['summary']['adapter_capable_without_current_record'], 3)
        self.assertEqual(self.registry['summary']['source_registration_required'], 0)

    def test_child_cli_uses_utf8_for_unicode_json_on_windows(self):
        sys.path.insert(0, str(ROOT / 'infra' / 'scripts'))
        from discovery import portfolio

        calls = []

        def completed(args, **kwargs):
            calls.append(kwargs)
            return subprocess.CompletedProcess(args, 0, stdout='{}', stderr='')

        with patch.object(portfolio.subprocess, 'run', side_effect=completed):
            with redirect_stdout(StringIO()):
                result = portfolio.main(['status', '--domain', 'scholarship'])

        self.assertEqual(result, 1)
        self.assertTrue(calls)
        for kwargs in calls:
            self.assertEqual(kwargs.get('encoding'), 'utf-8')
            self.assertEqual(kwargs['env'].get('PYTHONIOENCODING'), 'utf-8')

    def test_coverage_command_is_offline_and_filterable(self):
        script = ROOT / 'infra/scripts/discovery/portfolio.py'
        result = subprocess.run(
            ['python3', str(script), 'coverage', '--domain', 'learning-program'],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload['contract'], 'discovery.portfolio.coverage.v1')
        self.assertEqual(payload['summary']['declared_categories'], 6)
        self.assertEqual(payload['summary']['source_registration_required'], 0)
        pending = subprocess.run(
            ['python3', str(script), 'coverage', '--state', 'source-registration-required'],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        pending_payload = json.loads(pending.stdout)
        self.assertEqual(pending_payload['summary']['declared_categories'], 0)
        self.assertEqual(pending_payload['summary']['source_registration_required'], 0)

    def test_generic_sources_have_a_valid_conservative_adapter(self):
        """Every newly registered generic source must normalize without facts."""
        import importlib
        import sys

        for product in self.products:
            repo = product_path(product['local_path'])
            if not repo.exists():
                continue
            sys.path.insert(0, str(repo / 'src'))
            package = product['id'].replace('-', '_')
            capture = importlib.import_module(package + '.capture')
            for source_id in product.get('enabled_source_ids', []):
                source = capture.source_config(source_id)
                if not source.get('generic_html'):
                    continue
                with self.subTest(product=product['id'], source=source_id):
                    markers = ' '.join(source.get('required_markers') or [])
                    if source.get('access') == 'govuk-api':
                        raw = json.dumps({
                            'title': source['title'],
                            'description': markers,
                            'base_path': urlsplit(source['fetch_url']).path.removeprefix('/api/content'),
                            'details': {},
                        }).encode()
                    else:
                        raw = ('<h1>{}</h1><p>{}</p>'.format(source['title'], markers)).encode()
                    payload = capture.normalize(raw, source, '2026-09-08T00:00:00Z')
                    for item in payload['items']:
                        item['provenance'].update(
                            raw_object_key='landing/test',
                            bronze_manifest_key='control/manifests/test',
                        )
                    self.assertEqual(capture.validate(payload)['schema_version'], source['schema_version'])


if __name__ == '__main__':
    unittest.main()
