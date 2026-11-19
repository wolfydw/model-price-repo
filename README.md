# model-price-repo

Cloud pricing catalog for ydw.cool. One existing GitHub Actions workflow continues to synchronize overseas model prices every ten minutes. Domestic prices are maintained only from tables explicitly supplied by the owner as of 2026-10-24.

## Domestic manual pricing

The single source is [manual-prices.json](manual-prices.json). Enter prices per million tokens in the existing USD ledger convention, without exchange conversion. The owner supplies all replacements; this repository does not fetch domestic official websites or accept domestic LiteLLM prices.

The publisher filters domestic upstream entries before merging and applies manual prices after every automatic alias, legacy override, field exclusion and cache completion. It removes stale manufacturer peak/context rules from explicitly supplied cards. Future domestic model prices are not automatically introduced. The source date, policy and exact owner model are attached to each generated card.

Unprovided existing domestic cards are frozen in the same file, marked frozen_pending_owner_manual. They retain their existing rates and rules until an owner supplied replacement is available. In particular, kimi-k3 and kimi-k3-1 remain separate exact names; glm-5.1 and kimi-k3 currently retain their frozen existing prices. To replace one, remove its covered targets from frozen_models and add the explicit owner card to models. Adding a price card does not change production model allowlists.

The 2026-10-24 owner table contains eleven exact model cards. Kimi K3.1 Pro cache write 13/26 is recorded as default/one-hour TTL. DeepSeek V4 Flash and V4.1 Flash have distinct owner prices, without automatic manufacturer peak multipliers.

On 2026-11-15 the owner approved a twelfth exact card, `deepseek-v4.1-flash-1017`, using the current `deepseek-flash` input / output / cache-write / cache-read prices of 2 / 8 / 1 / 0.04 USD per million tokens. Its bare and `deepseek/` keys use an independent numeric manual entry. Future changes to `deepseek-flash` do not update this snapshot; no automatic inheritance logic was added.

## Overseas automatic pricing

The existing native provider selection, complete-card updates, aliases and GPT pricing overrides remain in config.json. As of 2026-10-25, GPT-6.1 Sol again retains its native pricing tiers above 272K prompt tokens: input/cache rates are 2x and output rates are 1.5x their corresponding base tier, including Standard, Batch, Flex, Priority and Ultrafast. The domestic manual layer has final authority over domestic cards; overseas cards continue automatic synchronization. This change affects future billing after the existing production hot reload and does not recalculate historical charges.

## Publish and verify

GPT-6.2 input / output / cache-read prices prefer the native OpenAI cards:
Sol is 2 / 10 / 0.1 and Astra is 8 / 40 / 0.4 USD per million tokens,
without group multipliers. The initial relay quotes are no longer used.
Strictly above 272,000 input tokens, the whole request uses 2x input/cache
and 1.5x output prices. When a native text or cache-read tier is missing,
reviewed defaults use the current base rate without overriding published tiers.
Cache writes also use the native generation's prices, without inheriting fields
from GPT-6.1 Sol or GPT-6 Astra. Standard short / 12h writes are 2.5 / 5 for Sol
and 10 / 20 for Astra, in USD per million tokens. Sub2API applies the default
Ultra Fast promotional multiplier and its expiration at request time, retaining
explicit channel overrides. Domestic manual prices retain final authority.

Run the existing publisher:

    python3 scripts/sync_prices.py --config config.json --repo-root .

The production configuration rejects --official-config before making any network request. Archived official parsers and fixtures remain for offline historical regressions only. The workflow no longer restores official source caches or calls domestic websites.

The publisher emits model_prices_and_context_window.json and its SHA-256 in one commit. The deployment repository locks source commit and file hashes in patches/official-pricing-source.json. Regression execution on the production host uses scripts/ydw.sh check; the registered maintenance suite runs the publishing repository's offline tests, including test_manual_prices.py. Do not bypass the host resource lock with a direct test runner.

Before changing the published catalog, create a protected backup with the deployment maintenance entry point. After publishing, verify all supplied prices, no stale manufacturer time rules, unchanged model allowlists/multipliers, and the production in-memory default-pricing API after its normal hot reload. Rollback restores the preceding publication commit and matching deployment lock; it never recalculates historical balances.

## License

See [LICENSE](LICENSE). This repository is based on Wei-Shaw/model-price-repo and the native LiteLLM pricing catalog.
