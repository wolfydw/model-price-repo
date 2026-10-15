# model-price-repo

A filtered model-price catalog compatible with the existing CRS/Sub2API USD
pricing JSON. One GitHub Actions workflow checks every ten minutes, at minutes
7/17/27/37/47/57, and on pushes or manual triggers. Scheduled runs may be delayed.

## Pricing policy

- Overseas models: native OpenAI, Anthropic, Gemini Developer API and xAI quotes
  from LiteLLM, selected by both provider and model-key prefix. Reseller prices
  do not replace native prices.
- Configured domestic models: direct DeepSeek, GLM and Kimi official websites.
  Preserve the official **CNY numerical amounts**, normalize the model-token
  measurement unit, and publish them as `currency: USD`. There is no FX step.
  This is the site's pricing policy, not a claim about the provider's official
  dollar quotation. For example, CNY 8 per million becomes USD-labeled 8 per
  million (`input_cost_per_token: 0.000008`).
- LiteLLM still supplies capabilities and model metadata. Domestic official fees
  are applied last, so international prices and legacy custom overrides cannot
  overwrite them. Missing official fee dimensions stay absent; they are not
  inferred from cache-storage promotions or an exchange rate.

The existing `model_prices_and_context_window.json` URL and matching `.sha256`
remain the publishing interface. Per-model `pricing_source` records the official
URL, CNY provenance, numeric-preservation policy and document hash. Optional
`pricing_rules` records exact context tiers and manufacturer peak periods.
The consuming Sub2API customization reads those rules and removes its former
DeepSeek fixed rates, Pro-as-Flash rule and family-price fallback. Its USD
accounting, quotas and existing operator overrides remain intact.

DeepSeek Flash names explicitly share the current `deepseek-flash` price card;
Pro has an independent card. GLM-5.1 carries both context tiers, while Kimi K3
includes separate five-minute and one-hour cache-creation fees. The government
holiday calendar currently covers **2026** and must be updated for later years.
Provider model IDs and aliases are exact entries, not guesses from family names.
New catalog models do not change the application's sale allowlists.

## Synchronization and failures

1. Fetch LiteLLM and apply native selection, namespace aliases, legacy defaults
   and existing site exclusions.
2. Fetch the three domestic official documents serially and parse their exact
   model entries and supported fee dimensions.
3. Replace the domestic fee set and copy it to all explicitly configured aliases.
   Keep unaffected model metadata and overseas prices.
4. Compare the **final** JSON with the previous output; publish JSON and SHA-256
   in one commit only when content changes.

A failed or changed official document retains that model's last complete
successful official fee card. It cannot fall back silently to international
rates. Other sources may still update. A failed LiteLLM download preserves the
existing catalog while allowing valid official updates. Unknown source shapes
produce workflow warnings; an initial run without usable catalog data fails.

Requests use twenty-second timeouts. LiteLLM is capped at 4 MiB; each official
document at 2 MiB, with an 8 MiB official batch limit. Conditional source caches
are bounded. No additional hosted service or local collection daemon is needed.
Dify and the withdrawn site-token feed are not part of this pipeline.

## Configuration and local use

[`config.json`](config.json) controls the compatible LiteLLM filter, native
providers, aliases, legacy defaults, output paths and site exclusions.
[`official-prices.json`](official-prices.json) controls the domestic official
URLs, parsers, exact aliases, pricing policy and government holiday calendar.

```bash
python3 scripts/sync_prices.py --config config.json --repo-root . --official-config official-prices.json
```

Synchronization and offline tests use only the Python standard library. CI runs
all tests before publishing, including source fixtures, provider separation,
repricing, alias copying, source failures, absent fee fields, final-output
idempotence and matching hashes. Historical source reviews are under `docs/`.

## Existing site exceptions

GPT-6.1 Sol retains a flat context price: `*_above_272k_tokens*` fields are
removed for Standard, Batch, Flex, Priority and Ultrafast. This is a site policy,
not a statement that the provider removed its surcharge. Other models and
base prices are unaffected.

Configured endpoint/site aliases such as `codex-auto-review` keep their existing
meaning. Bare `gpt-image-2.5` remains unresolved in the catalog; the application's
independent per-image retail group prices are not replaced by token prices.

## License

[MIT](LICENSE)
