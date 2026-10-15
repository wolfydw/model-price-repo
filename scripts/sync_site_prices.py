#!/usr/bin/env python3
"""Publish site-token rates from native LiteLLM and RMB Dify cards. No FX."""
import argparse
import copy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
from html import unescape
import json
import logging
from pathlib import Path
import re
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger(__name__)
PRICE_FIELDS = {'input': 'input_cost_per_token', 'output': 'output_cost_per_token',
                'cache_read': 'cache_read_input_token_cost',
                'cache_write': 'cache_creation_input_token_cost',
                'cache_write_1h': 'cache_creation_input_token_cost_above_1hr'}
WESTERN = {'openai', 'anthropic', 'gemini', 'xai'}


def digest(body):
    return hashlib.sha256(body).hexdigest()


def number(value):
    if isinstance(value, bool):
        raise ValueError('boolean price')
    n = Decimal(str(value))
    if not n.is_finite() or n < 0:
        raise ValueError('non-finite or negative price')
    return n


class Fetcher:
    """Bounded conditional downloads; cache is persisted by the existing workflow."""
    def __init__(self, root):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.total = 0

    def get(self, url, max_age=0):
        key = digest(url.encode())
        data, meta = self.root / key, self.root / (key + '.json')
        old = json.loads(meta.read_text()) if meta.exists() else {}
        now = datetime.now(timezone.utc).timestamp()
        if data.exists() and max_age and now - old.get('checked', 0) < max_age:
            return data.read_bytes()
        headers = {'User-Agent': 'ydw-site-prices/1', 'Accept': '*/*'}
        if old.get('etag'):
            headers['If-None-Match'] = old['etag']
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
                limit = (4 if '/BerriAI/litellm/' in url else 2) * 1024 * 1024
                body = r.read(limit + 1)
                if len(body) > limit:
                    raise ValueError('source exceeds bounded download limit')
                self.total += len(body)
                if self.total > 8 * 1024 * 1024:
                    raise ValueError('sync exceeds 8 MiB')
                data.write_bytes(body)
                old = {'etag': r.headers.get('ETag'), 'checked': now}
        except urllib.error.HTTPError as error:
            if error.code != 304 or not data.exists():
                raise
            body = data.read_bytes()
            old['checked'] = now
        meta.write_text(json.dumps(old))
        return body


def dify_card(body, expected):
    d = yaml.safe_load(body)
    if not isinstance(d, dict) or d.get('model') != expected:
        raise ValueError('Dify model identity mismatch')
    pricing = d.get('pricing')
    if pricing is None:
        return {}, d
    if pricing.get('currency', '').upper() not in {'RMB', 'CNY'}:
        raise ValueError('Dify card is not RMB/CNY')
    unit = number(pricing['unit'])
    if unit not in {Decimal('0.001'), Decimal('0.000001'), Decimal('1')}:
        raise ValueError('unsupported Dify pricing.unit')
    card = {field: float(number(pricing[name]) * unit)
            for name, field in PRICE_FIELDS.items() if name in pricing}
    return card, d


def official_card(kind, model, body):
    """Small audited parsers, explicit identity/units; shape changes fail closed."""
    text = body.decode('utf-8')
    if kind == 'glm':
        rows = []
        labels = []
        for line in text.splitlines():
            cells = [x.strip() for x in line.split('|')[1:-1]]
            if cells and cells[0].lower() == model:
                if len(cells) < 6 or cells[4] != '限时免费':
                    raise ValueError('unsupported GLM fee dimensions')
                labels.append(cells[1].replace('\\', ''))
                vals = [float(number(cells[i])) / 1e6 for i in (2, 3, 5)]
                rows.append(dict(zip(('input_cost_per_token', 'output_cost_per_token', 'cache_read_input_token_cost'), vals)))
        if len(rows) != (2 if model == 'glm-5.1' else 1):
            raise ValueError('official GLM table shape changed')
        if model == 'glm-5.1' and labels != ['输入长度 [0, 32K)', '输入长度 ≥32K']:
            raise ValueError('official GLM context boundary changed')
        result = rows[0]
        if len(rows) == 2:
            result['site_context_tiers'] = [{'min_tokens': 32768, **rows[1]}]
        return result
    if kind == 'kimi':
        match = re.search(r'\["' + re.escape(model) + r'",\s*"1M tokens"([^\n]+)', text)
        if not match:
            raise ValueError('official Kimi table missing')
        vals = re.findall(r'¥([0-9.]+)', match[1])
        if len(vals) != 5:
            raise ValueError('official Kimi fee shape changed')
        return dict(zip(('cache_creation_input_token_cost', 'cache_creation_input_token_cost_above_1hr',
                         'cache_read_input_token_cost', 'input_cost_per_token', 'output_cost_per_token'),
                        (float(number(v)) / 1e6 for v in vals)))
    if kind == 'deepseek':
        plain_doc = unescape(re.sub('<[^>]+>', ' ', text))
        if not re.search(r'模型\s+deepseek-flash\s*(?:\(1\))?\s+deepseek-v4-pro', plain_doc):
            raise ValueError('official DeepSeek model columns changed')
        if not re.search(r'北京时间周一至周五（不含中国法定节假日）\s*9:00\s*-\s*12:00、14:00\s*-\s*18:00', plain_doc):
            raise ValueError('official DeepSeek peak schedule changed')
        rows = []
        for row in re.findall(r'<tr\b[^>]*>.*?</tr>', text, re.S):
            plain = unescape(re.sub('<[^>]+>', ' ', row))
            vals = re.findall(r'([0-9]+(?:\.[0-9]+)?)\s*元', plain)
            if vals:
                if len(vals) != 2:
                    raise ValueError('official DeepSeek column shape changed')
                rows.append([float(number(v)) / 1e6 for v in vals])
        if len(rows) != 6 or '法定节假日' not in text:
            raise ValueError('official DeepSeek time/price table changed')
        col = 1 if model == 'deepseek-v4-pro' else 0
        for base, peak in ((0, 1), (2, 3), (4, 5)):
            if abs(rows[peak][col] - rows[base][col] * 2) > 1e-12:
                raise ValueError('DeepSeek peak ratio changed')
        return {'input_cost_per_token': rows[2][col], 'output_cost_per_token': rows[4][col],
                'cache_read_input_token_cost': rows[0][col], 'site_peak_multiplier': 2}
    raise ValueError('unknown official adapter')


def reconcile(dify, official):
    # The official table supplies absent fees and corrects stale Dify values.
    # Every cycle re-reads both sources; no hand-written permanent fee overlay.
    return {**dify, **official}


def validate(bundle):
    if bundle.get('schema_version') != 1 or bundle.get('settlement_unit') != 'site_token':
        raise ValueError('invalid site bundle envelope')
    if not bundle.get('models'):
        raise ValueError('empty site bundle')
    for name, card in bundle['models'].items():
        if not isinstance(card, dict) or not card.get('reference'):
            raise ValueError('missing provenance: ' + name)
        if not any('cost' in k for k in card):
            raise ValueError('missing fees: ' + name)
        for field, value in card.items():
            if 'cost' in field and isinstance(value, (int, float)):
                number(value)
        for tier in card.get('site_context_tiers', []):
            for key, value in tier.items():
                number(value)
    return bundle


def generate(config, previous, fetch):
    previous = previous or {'models': {}}
    models = copy.deepcopy(previous['models'])
    sources = copy.deepcopy(previous.get('sources', {}))
    errors = []
    # Native western cards only: domestic international prices never enter here.
    try:
        lite_body = fetch(config['litellm_url'])
        upstream = json.loads(lite_body)
        accepted = {k: v for k, v in upstream.items() if isinstance(v, dict)
                    and v.get('litellm_provider') in WESTERN
                    and any(k.startswith(p) for p in config['western_prefixes'][v['litellm_provider']])}
        if not accepted:
            raise ValueError('no native western prices')
        for key, value in accepted.items():
            card = copy.deepcopy(value)
            card['reference'] = {'project': 'litellm', 'quote_unit': 'USD_per_token',
                                 'source': value.get('source', config['litellm_url']), 'sha256': digest(lite_body)}
            card['currency'] = 'USD'  # external reference display only
            models[key] = card
            for prefix in ('gemini/', 'xai/'):
                if key.startswith(prefix):
                    models[key[len(prefix):]] = copy.deepcopy(card)
        sources['litellm'] = {'sha256': digest(lite_body)}
    except Exception as error:
        errors.append('litellm: ' + str(error))

    try:
        commit = json.loads(fetch(config['dify_commit_url']))['sha']
        if not re.fullmatch('[0-9a-f]{40}', commit):
            raise ValueError('invalid Dify commit')
    except Exception as error:
        errors.append('dify: ' + str(error))
        commit = None
    for name, spec in config['domestic'].items():
        if commit is None:
            continue
        try:
            url = f"https://raw.githubusercontent.com/langgenius/dify-official-plugins/{commit}/{spec['path']}"
            dify_body = fetch(url)
            base, metadata = dify_card(dify_body, spec['model'])
            official_url = spec['official_url']
            official_body = fetch(official_url, 3600)
            official = official_card(spec['adapter'], name, official_body)
            card = reconcile(base, official)
            if spec['adapter'] in {'glm', 'deepseek'}:
                card['site_cache_creation_as_input'] = True
            card.update(litellm_provider=spec['provider'], mode='chat', currency='CNY',
                        supports_prompt_caching=True,
                        max_input_tokens=metadata.get('model_properties', {}).get('context_size', 0))
            card['reference'] = {'project': 'dify', 'quote_unit': 'CNY_per_token', 'source': official_url,
                                 'dify_source': url, 'commit': commit, 'dify_sha256': digest(dify_body),
                                 'official_sha256': digest(official_body),
                                 'official_fields': sorted(official),
                                 'verified_at': previous.get('models', {}).get(name, {}).get('reference', {}).get('verified_at')}
            corrections = {key: {'dify': base[key], 'official': value}
                           for key, value in official.items()
                           if key in base and base[key] != value}
            if corrections:
                card['reference']['dify_corrections'] = corrections
            # Verification time only changes when the checked source content changes.
            prior = previous.get('models', {}).get(name, {}).get('reference', {})
            if prior.get('official_sha256') != digest(official_body) or not card['reference']['verified_at']:
                card['reference']['verified_at'] = datetime.now(timezone.utc).isoformat()
            models[name] = card
            for alias in spec.get('aliases', []):
                models[alias] = copy.deepcopy(card)
        except Exception as error:
            errors.append(name + ': ' + str(error))
    if commit:
        sources['dify'] = {'commit': commit}
    for alias, source in config.get('aliases', {}).items():
        if source in models:
            models[alias] = copy.deepcopy(models[source])
    for key in ('gpt-6.1-sol',):
        if key in models:
            for field in list(models[key]):
                if '_above_272k_tokens' in field:
                    del models[key][field]
    # The current archive has no exact bare GPT Image 2.5; its independent
    # per-image group quote remains the application-owned billing source.
    missing = sorted(set(config['required_domestic']) - models.keys())
    if missing:
        raise ValueError('no previous usable domestic cards: ' + ', '.join(missing))
    bundle = validate({'schema_version': 1, 'settlement_unit': 'site_token',
                       'models': models, 'sources': sources, 'calendar': config['calendar']})
    return bundle, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo-root', type=Path, default=ROOT)
    args = parser.parse_args()
    config = json.loads((args.repo_root / 'site-pricing-config.json').read_text())
    output = args.repo_root / 'ydw-site-prices-v1.json'
    previous = json.loads(output.read_text()) if output.exists() else None
    fetcher = Fetcher(args.repo_root / '.cache/site-sources')
    bundle, errors = generate(config, previous, fetcher.get)
    body = (json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n').encode()
    changed = not output.exists() or output.read_bytes() != body
    if changed:
        temporary = output.with_suffix('.tmp')
        temporary.write_bytes(body)
        temporary.replace(output)
    (args.repo_root / 'ydw-site-prices-v1.sha256').write_text(digest(body) + '\n')
    for error in errors:
        print('::warning::' + error)
    print(f'SITE_CHANGED={str(changed).lower()}')
    print(f'SITE_HASH={digest(body)}')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
