"""Owner supplied domestic prices; no network requests or exchange conversion."""
import copy
from decimal import Decimal

FIELDS = {'input': 'input_cost_per_token', 'output': 'output_cost_per_token',
          'cache_write': 'cache_creation_input_token_cost',
          'cache_read': 'cache_read_input_token_cost',
          'cache_write_1h': 'cache_creation_input_token_cost_above_1hr'}
POLICY = 'owner_manual_numeric_as_usd_no_fx'


def managed(model, card, policy):
    return (str(model).lower().startswith(tuple(policy['managed_prefixes'])) or
            isinstance(card, dict) and card.get('litellm_provider') in policy['managed_providers'])


def fee_field(name):
    return ('cost' in name or 'price' in name or name.startswith('long_context_') or
            name in {'pricing_rules', 'off_peak_pricing', 'provider_specific_entry'})


def validate(policy):
    if (policy.get('policy') != POLICY or policy.get('automatic_collection') is not False or
            policy.get('unit') != 'per_million_tokens' or policy.get('currency') != 'USD'):
        raise ValueError('Invalid manual pricing policy')
    if not policy.get('updated_on') or not policy.get('source') or not policy.get('models'):
        raise ValueError('Manual prices require owner source, date and nonempty model table')
    targets = set()
    for model, spec in policy['models'].items():
        if not managed(model, {}, policy) or spec.get('provider') not in policy['managed_providers']:
            raise ValueError('Manual model must belong to a managed domestic provider: ' + model)
        if model not in spec.get('targets', []):
            raise ValueError('Exact manual model target missing: ' + model)
        if not all(field in spec for field in ('input', 'output', 'cache_write', 'cache_read')):
            raise ValueError('Manual model requires four explicit prices: ' + model)
        for field in FIELDS:
            if field not in spec:
                continue
            if isinstance(spec[field], bool):
                raise ValueError('Boolean manual price')
            value = Decimal(str(spec[field]))
            if not value.is_finite() or value < 0:
                raise ValueError('Invalid manual price: ' + model)
        for target in spec['targets']:
            if target in targets or not managed(target, {}, policy):
                raise ValueError('Duplicate or unmanaged manual target: ' + target)
            targets.add(target)
    for model, card in policy.get('frozen_models', {}).items():
        if model in targets or not isinstance(card, dict) or not managed(model, card, policy):
            raise ValueError('Invalid frozen model: ' + model)


def apply_manual_prices(data, policy):
    validate(policy)
    previous = copy.deepcopy(data)
    for key in list(data):
        if managed(key, data[key], policy):
            del data[key]
    for key, snapshot in policy.get('frozen_models', {}).items():
        card = copy.deepcopy(snapshot)
        card['pricing_source'] = {
            'policy': 'frozen_pending_owner_manual', 'frozen_on': policy['updated_on'],
            'source': 'Existing price frozen pending an owner supplied replacement',
            'previous_source': copy.deepcopy(snapshot.get('pricing_source'))}
        data[key] = card
    for model, spec in policy['models'].items():
        for target in spec['targets']:
            card = copy.deepcopy(previous.get(target, previous.get(model, {})))
            if not isinstance(card, dict):
                card = {}
            for field in list(card):
                if fee_field(field):
                    del card[field]
            card.update({FIELDS[field]: float(Decimal(str(spec[field])) / Decimal(1000000))
                         for field in FIELDS if field in spec})
            card.update(mode='chat', litellm_provider=spec['provider'], currency='USD',
                        pricing_source={'policy': POLICY, 'project': 'owner_manual',
                                        'source': policy['source'], 'updated_on': policy['updated_on'],
                                        'model': model, 'source_unit': policy['unit']})
            data[target] = card
    return data
