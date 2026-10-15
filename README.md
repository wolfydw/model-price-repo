# model-price-repo

Filtered model pricing data for CRS and sub2api projects. Syncs from the upstream [litellm](https://github.com/BerriAI/litellm) pricing file on a schedule, applying configurable prefix filters to keep only the models you actually use.

## How it works

A GitHub Actions workflow runs every 10 minutes (and on manual trigger):

1. Downloads the full `model_prices_and_context_window.json` from litellm
2. Filters models by the prefix rules in `config.json`
3. Merges new models into the existing output (additive — never removes)
4. Applies alias mappings and custom model definitions
5. Removes explicitly excluded model fields after all merges and overrides
6. Writes the output JSON + SHA-256 hash, commits only if content changed

## Configuration

All settings live in [`config.json`](config.json):

| Field | Description |
|---|---|
| `upstream_url` | URL to the upstream litellm pricing JSON |
| `output_file` | Output filename (default: `model_prices_and_context_window.json`) |
| `hash_file` | SHA-256 hash filename for change detection |
| `sync_mode` | `"additive"` (only add new) or `"full"` (replace each run) |
| `update_existing` | Whether to update pricing data for models already in the output |
| `prefix_filters` | List of prefixes — a model key must start with one to be included |
| `exclude_patterns` | Substring patterns to exclude (applied before prefix matching) |
| `excluded_model_fields` | Map exact model keys to field-name glob patterns removed after all merges and overrides |
| `aliases` | Map alias model keys to existing source models (deep copy pricing) |
| `custom_models` | Manually defined pricing objects, always injected |

### Adding new model prefixes

Edit the `prefix_filters` array in `config.json`:

```json
{
  "prefix_filters": [
    "claude-",
    "gpt-",
    "your-new-prefix/"
  ]
}
```

### Adding aliases

Aliases create copies of an existing model's pricing under a new key:

```json
{
  "aliases": {
    "claude-opus-4-6-thinking": {
      "source": "claude-opus-4-6",
      "description": "Thinking variant, same pricing"
    }
  }
}
```

If the source model doesn't exist in the filtered data, the alias is skipped with a warning.

### Gemini Developer API keys

This fork includes both legacy `gemini-` keys and Gemini Developer API keys
under `gemini/`. Prefix filters match the complete upstream key, so `gemini-`
alone does not include `gemini/gemini-4-argon` or future namespaced models.
An explicit `gemini-4-argon` alias copies the complete
`gemini/gemini-4-argon` entry for consumers that use the bare model ID.
Vertex AI and GitHub Copilot entries are separate channels and are not selected
by this prefix.

The existing additive policy remains in effect: `update_existing: false`
preserves existing field values while accepting new models and missing fields.
Scheduled synchronization does not guarantee that every price is current or
verified against provider documentation. Changes to existing prices require a
separate review of the configuration or data.

The synchronization workflow runs the offline regression tests before fetching
and publishing data. GitHub scheduled runs can be delayed; after creating a
fork, enable its Actions workflow and trigger the first run manually.

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
