import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('site_prices', ROOT / 'scripts/sync_site_prices.py')
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)


class SitePricingTests(unittest.TestCase):
    def test_dify_units_and_zero_are_not_currency_conversions(self):
        for unit, amount, expected in [('0.001', '0.008', 8e-6), ('0.000001', '8', 8e-6)]:
            body = f'model: glm\npricing:\n  input: "{amount}"\n  output: "0"\n  currency: RMB\n  unit: "{unit}"\n'
            result, _ = site.dify_card(body, 'glm')
            self.assertEqual(expected, result['input_cost_per_token'])
            self.assertEqual(0, result['output_cost_per_token'])
            self.assertNotIn('cache_creation_input_token_cost', result)

    def test_rejects_overseas_dify_and_wrong_identity(self):
        for body in ['model: other\n', 'model: glm\npricing: {input: 1, unit: 0.001, currency: USD}']:
            with self.assertRaises(ValueError):
                site.dify_card(body, 'glm')

    def test_both_sources_update_and_single_source_failure_retains_prices(self):
        config = {'litellm_url': 'lite', 'dify_commit_url': 'commit',
                  'western_prefixes': {'openai': ['gpt-']},
                  'domestic': {'glm-5.3': {'model': 'glm-5.3', 'path': 'models/glm.yaml', 'adapter': 'glm',
                      'provider': 'zhipuai', 'official_url': 'official', 'aliases': ['glm-alias']}},
                  'required_domestic': ['glm-5.3'], 'calendar': {}, 'aliases': {}}
        prices = {'input': 8, 'output': 28, 'lite': 2}
        fail = set()
        def fetch(url, *args):
            if url in fail:
                raise OSError('fixture unavailable')
            if url == 'lite':
                return json.dumps({'gpt-test': {'litellm_provider': 'openai', 'input_cost_per_token': prices['lite'] / 1e6}}).encode()
            if url == 'commit':
                return json.dumps({'sha': 'a' * 40}).encode()
            if url == 'official':
                return f'| GLM-5.3 | 1M | {prices["input"]} | {prices["output"]} | 限时免费 | 2 |\n'.encode()
            return f'model: glm-5.3\npricing: {{input: {prices["input"]}, output: {prices["output"]}, unit: 0.000001, currency: RMB}}'.encode()
        first, errors = site.generate(config, None, fetch)
        self.assertEqual([], errors)
        prices.update(input=10, lite=4)
        second, _ = site.generate(config, first, fetch)
        self.assertEqual(10e-6, second['models']['glm-alias']['input_cost_per_token'])
        self.assertEqual(4e-6, second['models']['gpt-test']['input_cost_per_token'])
        fail.add('commit')
        prices['lite'] = 6
        third, errors = site.generate(config, second, fetch)
        self.assertTrue(errors)
        self.assertEqual(second['models']['glm-5.3'], third['models']['glm-5.3'])
        self.assertEqual(6e-6, third['models']['gpt-test']['input_cost_per_token'])
        fourth, _ = site.generate(config, third, fetch)
        self.assertEqual(third, fourth)

    def test_published_domestic_and_overseas_have_expected_units(self):
        path = ROOT / 'ydw-site-prices-v1.json'
        if not path.exists():
            self.skipTest('initial publish is not generated yet')
        bundle = site.validate(json.loads(path.read_text()))
        self.assertEqual('site_token', bundle['settlement_unit'])
        self.assertEqual('CNY_per_token', bundle['models']['glm-5.3']['reference']['quote_unit'])
        self.assertGreaterEqual(bundle['models']['glm-5.3']['input_cost_per_token'], 0)
        self.assertGreaterEqual(bundle['models']['kimi-k3']['cache_creation_input_token_cost_above_1hr'],
                                bundle['models']['kimi-k3']['cache_creation_input_token_cost'])
        self.assertEqual(32768, bundle['models']['glm-5.1']['site_context_tiers'][0]['min_tokens'])
        self.assertTrue(bundle['models']['glm-5.3']['site_cache_creation_as_input'])

    def test_unknown_official_rules_are_rejected(self):
        glm = ('| GLM-5.1 | 输入长度 \\[0, 32K) | 6 | 24 | 限时免费 | 1.3 |\n'
               '| GLM-5.1 | 输入长度 ≥32K | 8 | 28 | 限时免费 | 2 |\n')
        self.assertEqual(32768, site.official_card('glm', 'glm-5.1', glm.encode())['site_context_tiers'][0]['min_tokens'])
        for changed in [glm.replace('32K', '64K'), glm.replace('限时免费', '1')]:
            with self.assertRaises(ValueError):
                site.official_card('glm', 'glm-5.1', changed.encode())
        with self.assertRaises(ValueError):
            site.official_card('deepseek', 'deepseek-v4-pro', b'<table>unknown identity</table>')
