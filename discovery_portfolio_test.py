"""Offline ownership and local scaffold checks; no live source claims."""
import json
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / 'systems/architecture/discovery-portfolio-v1.json'


class DiscoveryPortfolioTests(unittest.TestCase):
    def setUp(self):
        self.portfolio = json.loads(MANIFEST.read_text())
        self.products = self.portfolio['products']

    def test_unique_domain_ownership(self):
        self.assertEqual(len(self.products), 14)
        for key in ('id', 'domain', 'local_path', 'schema_version'):
            self.assertEqual(len({p[key] for p in self.products}), len(self.products))
        categories = [c for p in self.products for c in p['categories']]
        self.assertEqual(len(categories), len(set(categories)))
        for product in self.products:
            self.assertEqual(product['live_sources_enabled'], product['domain'] in {'scholarship','grant','freebie','benefit','competition','bounty','startup-program','paid-study','mobility-program','procurement'})
            self.assertIsNone(product['remote_url'])
            self.assertIsNone(product['last_known_commit'])
            self.assertEqual(product['consumer_integration'], 'local-cli' if product['live_sources_enabled'] else 'planned')
            self.assertNotIn('..', Path(product['local_path']).parts)
            self.assertFalse(Path(product['local_path']).is_absolute())
            self.assertTrue(product['local_path'].endswith('/' + product['id']))

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
        present = [p for p in self.products if (ROOT / p['local_path']).exists()]
        if not present:
            self.skipTest('Ignored local scaffolds absent; manifest-only checkout')
        self.assertEqual(len(present), len(self.products), 'Partial local scaffold creation')
        for product in present:
            with self.subTest(product=product['id']):
                repo = ROOT / product['local_path']
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
                self.assertTrue((repo / 'tests/test_contract.py').is_file())


if __name__ == '__main__':
    unittest.main()
