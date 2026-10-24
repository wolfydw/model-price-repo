"""Owner manual prices remain authoritative across scheduled overseas syncs."""
import copy
from decimal import Decimal
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import manual_prices as manual
import official_prices
import sync_prices


class ManualPricingTests(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads((ROOT / 'manual-prices.json').read_text())
        self.config = json.loads((ROOT / 'config.json').read_text())

    def test_owner_table_is_exact_and_has_no_automatic_fee_rules(self):
        expected = {'deepseek-v4-flash': (3,9,1,.1), 'deepseek-v4-pro': (9,27,4.5,.3),
                    'deepseek-v4.1-flash': (2,8,1,.04), 'glm-5.2': (8,28,8,2),
                    'glm-5.3': (8,28,8,2), 'glm-5.3-flash': (.8,2.8,.8,.23),
                    'hy3': (1,4,1,.25), 'hy4': (6,18,6,.3),
                    'minimax-m3': (2.1,8.4,2.1,.42), 'kimi-k3-1': (20,100,20,2),
                    'kimi-k3.1-pro': (13,68,13,1.3)}
        self.assertEqual(set(expected), set(self.policy['models']))
        data = {'deepseek-v4-flash': {'pricing_rules': {'stale': True},
                'input_cost_per_token_priority': 99, 'max_input_tokens': 1000000}}
        manual.apply_manual_prices(data, self.policy)
        for model, fees in expected.items():
            spec = self.policy['models'][model]
            self.assertEqual(fees, tuple(spec[k] for k in ('input','output','cache_write','cache_read')))
            for target in spec['targets']:
                for key, value in zip(('input','output','cache_write','cache_read'), fees):
                    self.assertEqual(float(Decimal(str(value))/Decimal(1000000)), data[target][manual.FIELDS[key]])
                self.assertNotIn('pricing_rules', data[target])
                self.assertNotIn('input_cost_per_token_priority', data[target])
                self.assertEqual(manual.POLICY, data[target]['pricing_source']['policy'])
        self.assertEqual(26e-6, data['kimi-k3.1-pro']['cache_creation_input_token_cost_above_1hr'])
        self.assertIn('kimi-k3', data)
        self.assertEqual('frozen_pending_owner_manual', data['kimi-k3']['pricing_source']['policy'])
        self.assertEqual(1000000, data['deepseek-v4-flash']['max_input_tokens'])

    def test_frozen_models_and_overseas_cards_are_preserved(self):
        foreign = {'input_cost_per_token': 123e-6, 'litellm_provider': 'openai'}
        data = {'gpt-unaffected': copy.deepcopy(foreign),
                'glm-unapproved-future': {'litellm_provider': 'zai', 'input_cost_per_token': 99}}
        manual.apply_manual_prices(data, self.policy)
        self.assertEqual(foreign, data['gpt-unaffected'])
        self.assertNotIn('glm-unapproved-future', data)
        for model, card in self.policy['frozen_models'].items():
            self.assertEqual({k:v for k,v in card.items() if k!='pricing_source'},
                             {k:v for k,v in data[model].items() if k!='pricing_source'})
        first = copy.deepcopy(data)
        manual.apply_manual_prices(data, self.policy)
        self.assertEqual(first, data)

    def test_repeated_live_sync_cannot_change_manual_prices_or_fetch_websites(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = copy.deepcopy(self.config)
            config['custom_models'] = {}; config['aliases'] = {}; config['official_field_defaults'] = {}
            (root/'config.json').write_text(json.dumps(config))
            (root/'manual-prices.json').write_text(json.dumps(self.policy))
            upstream = {'gpt-manual-audit-fixture': {'litellm_provider':'openai','input_cost_per_token':2e-6},
                        'deepseek/deepseek-v4-flash': {'litellm_provider':'deepseek','input_cost_per_token':999},
                        'zai/glm-new-unapproved': {'litellm_provider':'zai','input_cost_per_token':999}}
            args = ['sync_prices.py','--repo-root',directory]
            with patch.object(sync_prices.sys,'argv',args), patch.object(sync_prices,'fetch_upstream',side_effect=lambda url:copy.deepcopy(upstream)), patch.object(official_prices.Fetcher,'get',side_effect=AssertionError('Domestic fetch forbidden')) as fetch, patch('builtins.print'):
                sync_prices.main()
                output = root/config['output_file']; first = output.read_bytes()
                data = json.loads(first)
                domestic = {k:v for k,v in data.items() if manual.managed(k,v,self.policy)}
                self.assertNotIn('zai/glm-new-unapproved',data)
                self.assertEqual(3e-6,data['deepseek-v4-flash']['input_cost_per_token'])
                sync_prices.main(); self.assertEqual(first,output.read_bytes())
                upstream['gpt-manual-audit-fixture']['input_cost_per_token'] = 4e-6
                sync_prices.main(); data = json.loads(output.read_bytes())
                self.assertEqual(4e-6,data['gpt-manual-audit-fixture']['input_cost_per_token'])
                self.assertEqual(domestic,{k:v for k,v in data.items() if manual.managed(k,v,self.policy)})
                self.assertEqual(sync_prices.compute_hash(output.read_bytes()),(root/config['hash_file']).read_text().strip())
                fetch.assert_not_called()

    def test_official_cli_cannot_reenable_collection_in_manual_mode(self):
        with patch.object(sync_prices.sys,'argv',['sync_prices.py','--repo-root',str(ROOT),'--official-config','official-prices.json']), patch.object(sync_prices,'fetch_upstream') as fetch:
            with self.assertRaisesRegex(ValueError,'cannot enable official'):
                sync_prices.main()
            fetch.assert_not_called()
        workflow = (ROOT/'.github/workflows/sync-model-pricing.yml').read_text()
        self.assertNotIn('--official-config', workflow)
        self.assertNotIn('.cache/official-sources', workflow)

    def test_invalid_or_incomplete_owner_prices_fail_before_mutation(self):
        for mutation in ('negative','nan','bool','missing','duplicate','automatic'):
            policy=copy.deepcopy(self.policy);spec=policy['models']['hy3']
            if mutation=='negative':spec['input']=-1
            if mutation=='nan':spec['input']='NaN'
            if mutation=='bool':spec['input']=True
            if mutation=='missing':del spec['cache_write']
            if mutation=='duplicate':spec['targets'].append('hy3')
            if mutation=='automatic':policy['automatic_collection']=True
            data={'gpt-unchanged':{'input_cost_per_token':1}}
            with self.assertRaises(ValueError):manual.apply_manual_prices(data,policy)
            self.assertEqual({'gpt-unchanged':{'input_cost_per_token':1}},data)
