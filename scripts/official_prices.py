"""Official domestic CNY numeric fees, published in the compatible USD catalog.
No exchange conversion. Overseas quotes retain the LiteLLM pipeline.
"""
import copy
from decimal import Decimal
import hashlib
from html import unescape
import json
from pathlib import Path
import re
import urllib.error
import urllib.request

POLICY = 'official_cny_numeric_as_usd_no_fx'


def number(value):
    if isinstance(value, bool):
        raise ValueError('boolean price')
    n = Decimal(str(value))
    if not n.is_finite() or n < 0:
        raise ValueError('invalid price')
    return n


class Fetcher:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.total = 0
        # Fixed cache bound; every response is at most 2 MiB.
        files = sorted(self.directory.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        for file in files[64:]:
            if file.is_file():
                file.unlink()

    def get(self, url):
        key = hashlib.sha256(url.encode()).hexdigest()
        path = self.directory / key
        meta_path = self.directory / (key + '.json')
        metadata = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        headers = {'User-Agent': 'model-price-repo/official', 'Accept': '*/*'}
        if path.exists() and metadata.get('etag'):
            headers['If-None-Match'] = metadata['etag']
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as response:
                body = response.read(2 * 1024 * 1024 + 1)
                self.total += len(body)
                if len(body) > 2 * 1024 * 1024 or self.total > 8 * 1024 * 1024:
                    raise ValueError('bounded official download size exceeded')
                path.write_bytes(body)
                meta_path.write_text(json.dumps({'etag': response.headers.get('ETag')}))
        except urllib.error.HTTPError as error:
            if error.code != 304 or not path.exists():
                raise
            body = path.read_bytes()
        return body



def official_card(kind, model, body, calendar):
    text = body.decode('utf-8')
    if kind == 'glm':
        for label in ('输入单价（元/百万 Tokens）', '输出单价（元/百万 Tokens）', '缓存命中（元/百万 Tokens）'):
            if label not in text:
                raise ValueError('GLM official fee unit changed')
        rows, labels = [], []
        for line in text.splitlines():
            cells = [x.strip() for x in line.split('|')[1:-1]]
            if cells and cells[0].lower() == model:
                if len(cells) < 6 or cells[4] != '限时免费':
                    raise ValueError('unsupported GLM fee dimension')
                labels.append(cells[1].replace(chr(92), ''))
                rows.append(dict(zip(('input_cost_per_token', 'output_cost_per_token', 'cache_read_input_token_cost'),
                                     (float(number(cells[i])) / 1e6 for i in (2, 3, 5)))))
        if len(rows) != (2 if model == 'glm-5.1' else 1):
            raise ValueError('GLM official table shape changed')
        card = rows[0]
        if len(rows) == 2:
            if labels != ['输入长度 [0, 32K)', '输入长度 ≥32K']:
                raise ValueError('GLM official boundary changed')
            # Use decimal K (1,000 tokens), consistent with the existing catalog.
            # The official label is 32K; no binary-token boundary is stated.
            card['pricing_rules'] = {'context_tiers': [{'min_tokens': 32000, **rows[1]}]}
        return card
    if kind == 'kimi':
        match = re.search(r'\["' + re.escape(model) + r'",\s*"1M tokens"([^\n]+)', text)
        if not match:
            raise ValueError('Kimi official model missing')
        vals = re.findall(r'¥([0-9.]+)', match[1])
        if len(vals) != 5:
            raise ValueError('Kimi official fee shape changed')
        return dict(zip(('cache_creation_input_token_cost', 'cache_creation_input_token_cost_above_1hr',
                         'cache_read_input_token_cost', 'input_cost_per_token', 'output_cost_per_token'),
                        (float(number(v)) / 1e6 for v in vals)))
    if kind == 'deepseek':
        plain = unescape(re.sub('<[^>]+>', ' ', text))
        if not re.search(r'模型\s+deepseek-flash\s*(?:\(1\))?\s+deepseek-v4-pro', plain):
            raise ValueError('DeepSeek official model columns changed')
        schedule = re.search(r'北京时间周一至周五（不含中国法定节假日）\s*(\d+:\d+)\s*-\s*(\d+:\d+)、(\d+:\d+)\s*-\s*(\d+:\d+)', plain)
        if not schedule:
            raise ValueError('DeepSeek official time rule changed')
        rows, row_labels = [], []
        for row in re.findall(r'<tr\b[^>]*>.*?</tr>', text, re.S):
            vals = re.findall(r'([0-9]+(?:\.[0-9]+)?)\s*元', unescape(re.sub('<[^>]+>', ' ', row)))
            if vals:
                if len(vals) != 2:
                    raise ValueError('DeepSeek official fee columns changed')
                rows.append([float(number(v)) / 1e6 for v in vals])
                row_labels.append(re.sub(r'\s+', '', unescape(re.sub('<[^>]+>', ' ', row))))
        if len(rows) != 6:
            raise ValueError('DeepSeek official fee rows changed')
        expected_labels = [('百万tokens输入', '缓存命中', '空闲时段'), ('高峰时段',),
                           ('百万tokens输入', '缓存未命中', '空闲时段'), ('高峰时段',),
                           ('百万tokens输出', '空闲时段'), ('高峰时段',)]
        if any(any(label not in row for label in expected) for row, expected in zip(row_labels, expected_labels)):
            raise ValueError('DeepSeek official fee labels or units changed')
        col = 1 if model == 'deepseek-v4-pro' else 0
        ratios = [rows[b + 1][col] / rows[b][col] for b in (0, 2, 4)]
        if any(abs(r - ratios[0]) > 1e-10 for r in ratios) or ratios[0] < 1:
            raise ValueError('DeepSeek peak fee ratios differ')
        hours = schedule.groups()
        return {'input_cost_per_token': rows[2][col], 'output_cost_per_token': rows[4][col],
                'cache_read_input_token_cost': rows[0][col],
                'pricing_rules': {'time_pricing': {'timezone': 'Asia/Shanghai', 'weekdays_only': True,
                    'periods': [{'start_time': a.zfill(5), 'end_time': b.zfill(5), 'multiplier': ratios[0]}
                                for a, b in ((hours[0], hours[1]), (hours[2], hours[3]))]},
                    'calendar': calendar}}
    raise ValueError('unknown official adapter')


def fee_fields(card):
    return {k: copy.deepcopy(v) for k, v in card.items()
            if 'cost' in k or k.startswith('long_context_') or k in {'pricing_rules', 'off_peak_pricing'}}


def with_fees(base, fees, source):
    card = copy.deepcopy(base)
    for name in fee_fields(card):
        card.pop(name, None)
    card.update(copy.deepcopy(fees))
    card.update(currency='USD', pricing_source=copy.deepcopy(source))
    return card


def apply_official_prices(data, previous, config, fetch):
    warnings = []
    responses = {}
    for spec in config['models']:
        try:
            url = spec['url']
            if url not in responses:
                try:
                    responses[url] = fetch(url)
                except Exception as error:
                    responses[url] = error
            body = responses[url]
            if isinstance(body, Exception):
                raise body
            fees = official_card(spec['adapter'], spec['model'], body, config['calendar'])
            source = {'project': 'official', 'policy': POLICY, 'source': url,
                      'source_currency': 'CNY', 'published_currency': 'USD',
                      'sha256': hashlib.sha256(body).hexdigest()}
            updates = {}
            for key in spec['targets']:
                base = data.get(key, previous.get(key))
                if not isinstance(base, dict):
                    raise ValueError('model identity missing: ' + key)
                updates[key] = with_fees(base, fees, source)
            data.update(updates)
        except Exception as error:
            warnings.append(spec['model'] + ': ' + str(error))
            for key in spec['targets']:
                old = previous.get(key, {})
                source = old.get('pricing_source', {})
                if source.get('policy') == POLICY:
                    data[key] = with_fees(data.get(key, old), fee_fields(old), source)
    return warnings
