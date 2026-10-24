# model-price-repo

Cloud pricing catalog for ydw.cool. One existing GitHub Actions workflow continues to synchronize overseas model prices every ten minutes. Domestic prices are maintained only from tables explicitly supplied by the owner as of 2026-10-24.

## Domestic manual pricing

The single source is [manual-prices.json](manual-prices.json). Enter prices per million tokens in the existing USD ledger convention, without exchange conversion. The owner supplies all replacements; this repository does not fetch domestic official websites or accept domestic LiteLLM prices.

The publisher filters domestic upstream entries before merging and applies manual prices after every automatic alias, legacy override, field exclusion and cache completion. It removes stale manufacturer peak/context rules from explicitly supplied cards. Future domestic model prices are not automatically introduced. The source date, policy and exact owner model are attached to each generated card.

Unprovided existing domestic cards are frozen in the same file, marked frozen_pending_owner_manual. They retain their existing rates and rules until an owner supplied replacement is available. In particular, kimi-k3 and kimi-k3-1 remain separate exact names; glm-5.1 and kimi-k3 currently retain their frozen existing prices. To replace one, remove its covered targets from frozen_models and add the explicit owner card to models. Adding a price card does not change production model allowlists.

The 2026-10-24 owner table contains eleven exact model cards. Kimi K3.1 Pro cache write 13/26 is recorded as default/one-hour TTL. DeepSeek V4 Flash and V4.1 Flash have distinct owner prices, without automatic manufacturer peak multipliers.

## Overseas automatic pricing

The existing native provider selection, complete-card updates, aliases, GPT pricing overrides and GPT-6.1 Sol flat context policy remain in config.json. The domestic manual layer has final authority; all overseas cards remain under their existing automatic policies.

## Publish and verify

Run the existing publisher:

    python3 scripts/sync_prices.py --config config.json --repo-root .

The production configuration rejects --official-config before making any network request. Archived official parsers and fixtures remain for offline historical regressions only. The workflow no longer restores official source caches or calls domestic websites.

The publisher emits model_prices_and_context_window.json and its SHA-256 in one commit. The deployment repository locks source commit and file hashes in patches/official-pricing-source.json. Regression execution on the production host uses scripts/ydw.sh check; the registered maintenance suite runs the publishing repository's offline tests, including test_manual_prices.py. Do not bypass the host resource lock with a direct test runner.

Before changing the published catalog, create a protected backup with the deployment maintenance entry point. After publishing, verify all supplied prices, no stale manufacturer time rules, unchanged model allowlists/multipliers, and the production in-memory default-pricing API after its normal hot reload. Rollback restores the preceding publication commit and matching deployment lock; it never recalculates historical balances.

## License

See [LICENSE](LICENSE). This repository is based on Wei-Shaw/model-price-repo and the native LiteLLM pricing catalog.
