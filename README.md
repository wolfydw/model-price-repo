# model-price-repo

Filtered model pricing data for CRS and sub2api projects. Syncs from the upstream [litellm](https://github.com/BerriAI/litellm) pricing file on a schedule, applying configurable prefix filters to keep only the models you actually use.

## How it works

A GitHub Actions workflow runs every 10 minutes, offset to minutes 7/17/27/37/47/57
(and on a push to main or manual trigger). GitHub can delay scheduled runs.

1. Download LiteLLM's public pricing file once.
2. Select both the model-key prefix and the native `litellm_provider`.
3. Replace matching cards completely, including changed prices and removed fields.
4. Copy native namespace cards to bare model IDs.
5. Apply remaining legacy aliases/custom definitions only when no native card exists.
6. Fill documented missing official fields, then apply explicit site pricing exclusions.
7. Publish JSON and SHA-256 together, committing only when content changes.

## Source policy

| Family | Accepted provider | Native keys | Bare IDs |
|---|---|---|---|
| OpenAI | `openai` | `gpt-`, `o1-`, `o3`, `o4-` | Native keys already bare |
| Anthropic | `anthropic` | `claude-` | Native keys already bare |
| Gemini Developer API | `gemini` | `gemini/` | Automatically strip namespace |
| xAI | `xai` | `xai/` | Automatically strip namespace |
| DeepSeek international | `deepseek` | `deepseek/` | Automatically strip namespace |
| Z.AI international | `zai` | `zai/` | Automatically strip namespace |
| Kimi international | `moonshot` | `moonshot/` | Automatically strip namespace |

Vertex, Bedrock, Azure, OpenRouter, and other reseller channels are never used as
native replacement prices. In particular, LiteLLM's bare Gemini keys can be
Vertex entries; Gemini aliases here come from `gemini/` instead. Native Grok,
GLM and Kimi aliases include all source fields, such as cache and context tiers.

All published rates follow LiteLLM's USD units. Domestic CNY prices are not
converted using a fixed exchange rate. LiteLLM is a third-party catalogue;
provider selection does not certify every field against current official docs.

The 2026-10-15 inventory covers **34 enabled sale models and 51 configured IDs**.
**49/51** have a price card: 46 native exact IDs (including namespace copies),
plus three explicitly configured endpoint/site aliases. `deepseek-v4.1-flash` and
bare `gpt-image-2.5` have no exact native entry and remain absent. Reseller
prices and adjacent versions are not substituted. If an exact native entry is
added later, normal selection imports it automatically. The enabled sale scope
has 30 exact native cards, two aliases and two unresolved IDs.

`gemini-3.1-pro` remains a configured alias of `gemini-3.1-pro-preview`.
`codex-auto-review` remains a site alias of `gpt-5.6-luna`; the disabled
`gpt-5.3-codex-spark` configuration also remains an alias of `gpt-5.3-codex`.
These aliases are not independently verified official model prices. Existing per-image retail group prices belong to the
application and are not replaced by per-image-token prices in this catalogue.

Kimi K3's missing cache-write fees are filled from its reviewed international
[official price page](https://platform.kimi.ai/docs/pricing/chat.md):
$3/MTok at 5min and $6/MTok at 1h. These are missing-field defaults, so any future
explicit upstream value (including zero) wins. There is no blanket cache-write
or cache-TTL inference. For the four configured GLM models and DeepSeek V4
Flash/Pro, unverified per-token cache-write zeroes are explicitly removed from
both native and bare cards; free cache storage does not establish a per-token
write fee. Other legacy custom cards only apply without a native
match; they are not asserted to be current official prices.

The complete [51-model source review](docs/2026-10-15-native-source-review.md)
and [field comparison JSON](docs/2026-10-15-native-source-comparison.json) record
the initial migration and its limits.

## Configuration

All settings live in [`config.json`](config.json):

| Field | Description |
|---|---|
| `upstream_url` | LiteLLM public pricing JSON |
| `output_file`, `hash_file` | Published JSON and matching SHA-256 |
| `sync_mode` | `additive` retains unmatched legacy IDs; `full` removes them |
| `update_existing` | `true`: replace accepted existing cards on every sync |
| `prefix_filters` | Initial key-prefix filter |
| `provider_prefixes` | Required provider-to-native-prefix mapping |
| `namespace_aliases` | Prefixes removed when copying native cards to bare IDs |
| `exclude_patterns` | Excluded key substrings |
| `aliases` | Explicit remaining endpoint/site aliases; native exact cards win |
| `custom_models` | Legacy fallback cards; native cards win |
| `official_field_defaults` | Reviewed missing fees, with official URL/date |
| `excluded_model_fields` | Explicit site exceptions applied after all other rules |

An upstream fetch/parse failure or empty selection aborts without publishing.
If individual native IDs disappear, additive mode retains their last published
card; retention is not proof of current availability or pricing. Publishing
JSON and SHA-256 in one commit keeps readers on a matching version.

Offline tests run before every synchronization and cover provider separation,
price changes, removed fields, aliases, legacy override precedence, missing
models, explicit zero, verified cache gaps, idempotence, and SHA-256 output.

### GPT-6.1 Sol pricing policy

This fork intentionally uses the same per-token rates for `gpt-6.1-sol` at all
input lengths. Its `excluded_model_fields` rule removes every
`*_above_272k_tokens*` field, including Standard, Batch, Flex, Priority, and
Ultrafast input, output, cache-read, and cache-write surcharges. Base prices,
context limits, and other models remain unchanged. This is a local pricing
override; it does not change the provider's charges.

Exclusions run after upstream merging, aliases, and custom definitions, so
scheduled synchronization cannot restore these fields.

## Running locally

```bash
python3 scripts/sync_prices.py --config config.json --repo-root .
```

No pip dependencies — uses Python standard library only.

## CRS integration

Point CRS to the raw output file from this repo:

```
MODEL_PRICES_URL=https://raw.githubusercontent.com/<owner>/model-price-repo/main/model_prices_and_context_window.json
```

The output JSON structure is identical to what litellm produces (model key -> pricing object), so CRS `pricingService.js` works without changes.

## License

[MIT](LICENSE)
