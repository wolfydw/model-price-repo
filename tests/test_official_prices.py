import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import official_prices as official
import sync_prices


class OfficialPricingTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / 'official-prices.json').read_text())
        self.bodies = {kind: (ROOT / 'tests/fixtures' / name).read_bytes()
                       for kind, name in [('deepseek', 'deepseek.html'), ('glm', 'glm.md'), ('kimi', 'kimi.txt')]}

    def test_all_domestic_fees_are_official_cny_numbers_without_fx(self):
        expected = {'glm-5.1': (6, 24, 1.3), 'glm-5.2': (8, 28, 2),
                    'glm-5.3': (8, 28, 2), 'glm-5.3-flash': (.8, 2.8, .23),
                    'kimi-k3': (20, 100, 2), 'deepseek-flash': (1, 4, .02),
                    'deepseek-v4-pro': (4.5, 13.5, .15)}
        for spec in self.config['models']:
            card = official.official_card(spec['adapter'], spec['model'], self.bodies[spec['adapter']], self.config['calendar'])
            for field, value in zip(['input_cost_per_token', 'output_cost_per_token', 'cache_read_input_token_cost'], expected[spec['model']]):
                self.assertAlmostEqual(value, card[field] * 1e6)
        kimi = official.official_card('kimi', 'kimi-k3', self.bodies['kimi'], self.config['calendar'])
        self.assertEqual(20e-6, kimi['cache_creation_input_token_cost'])
        self.assertEqual(40e-6, kimi['cache_creation_input_token_cost_above_1hr'])
        glm = official.official_card('glm', 'glm-5.1', self.bodies['glm'], self.config['calendar'])
        self.assertEqual(32000, glm['pricing_rules']['context_tiers'][0]['min_tokens'])
        flash = official.official_card('deepseek', 'deepseek-flash', self.bodies['deepseek'], self.config['calendar'])
        self.assertEqual(2, flash['pricing_rules']['time_pricing']['periods'][0]['multiplier'])

    def test_aliases_refresh_and_source_failure_cannot_restore_international_fees(self):
        specs = copy.deepcopy(self.config)
        specs['models'] = [s for s in specs['models'] if s['model'] == 'glm-5.3']
        base = {key: {'input_cost_per_token': .001, 'output_cost_per_token': .002,
                      'cache_creation_input_token_cost': 99, 'max_input_tokens': 200000}
                for key in specs['models'][0]['targets']}
        base['gpt-unaffected'] = {'input_cost_per_token': 2e-6}
        first = copy.deepcopy(base)
        self.assertEqual([], official.apply_official_prices(first, {}, specs, lambda url: self.bodies['glm']))
        for key in specs['models'][0]['targets']:
            self.assertEqual(8e-6, first[key]['input_cost_per_token'])
            self.assertEqual('USD', first[key]['currency'])
            self.assertEqual('CNY', first[key]['pricing_source']['source_currency'])
            self.assertNotIn('cache_creation_input_token_cost', first[key])
        self.assertEqual(base['gpt-unaffected'], first['gpt-unaffected'])
        second = copy.deepcopy(base)
        self.assertEqual([], official.apply_official_prices(second, first, specs, lambda url: self.bodies['glm']))
        self.assertEqual(first, second)
        changed = self.bodies['glm'].replace(b'| GLM-5.3 | 1M | 8 |', b'| GLM-5.3 | 1M | 9 |')
        third = copy.deepcopy(base)
        official.apply_official_prices(third, first, specs, lambda url: changed)
        self.assertEqual(9e-6, third['glm-5.3']['input_cost_per_token'])
        failed = copy.deepcopy(base)
        def fail(url):
            raise OSError('fixture source unavailable')
        self.assertTrue(official.apply_official_prices(failed, third, specs, fail))
        self.assertEqual(third, failed)

    def test_unknown_official_shape_is_not_a_new_price(self):
        for kind, model, changed in [
                ('glm', 'glm-5.1', self.bodies['glm'].replace(b'32K', b'64K')),
                ('deepseek', 'deepseek-v4-pro', b'unknown table'),
                ('kimi', 'kimi-k3', b'unknown table')]:
            with self.assertRaises(ValueError):
                official.official_card(kind, model, changed, self.config['calendar'])

    def test_pipeline_compares_final_output_and_publishes_matching_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {'upstream_url': 'fixture', 'output_file': 'prices.json', 'hash_file': 'prices.sha256',
                      'sync_mode': 'additive', 'prefix_filters': ['glm-', 'gpt-'], 'update_existing': True}
            spec = copy.deepcopy(self.config)
            spec['models'] = [s for s in spec['models'] if s['model'] == 'glm-5.3']
            spec['models'][0]['targets'] = ['glm-5.3']
            (root / 'config.json').write_text(json.dumps(config))
            (root / 'official.json').write_text(json.dumps(spec))
            upstream = {'glm-5.3': {'input_cost_per_token': 1.4e-6, 'output_cost_per_token': 4.4e-6},
                        'gpt-stable': {'input_cost_per_token': 2e-6}}
            args = ['sync_prices.py', '--repo-root', temporary, '--official-config', 'official.json']
            with patch.object(sync_prices.sys, 'argv', args), patch.object(sync_prices, 'fetch_upstream', return_value=upstream), patch.object(official.Fetcher, 'get', return_value=self.bodies['glm']), patch('builtins.print') as report:
                sync_prices.main()
                first = (root / 'prices.json').read_bytes()
                self.assertEqual(8e-6, json.loads(first)['glm-5.3']['input_cost_per_token'])
                self.assertEqual(sync_prices.compute_hash(first), (root / 'prices.sha256').read_text().strip())
                sync_prices.main()
                self.assertEqual(first, (root / 'prices.json').read_bytes())
                report.assert_any_call('CHANGED=false')
