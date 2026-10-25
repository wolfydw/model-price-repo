"""Offline regressions for model pricing policies and published output."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("sync_prices", ROOT / "scripts/sync_prices.py")
sync_prices = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync_prices)


class GeminiPricingTests(unittest.TestCase):
    def setUp(self):
        self.config = sync_prices.load_config(str(ROOT / "config.json"))
        self.config.pop("manual_pricing_file", None)
        self.source = {
            "input_cost_per_token": 2e-6,
            "output_cost_per_token": 1e-5,
            "cache_read_input_token_cost": 1e-7,
            "input_cost_per_token_priority": 3.6e-6,
            "litellm_provider": "gemini",
            "supported_endpoints": ["/v1beta/models"],
        }

    def test_filter_keeps_native_channels_and_rejects_vertex_bare_ids(self):
        keys = {
            "gemini/gemini-4-argon",
            "gemini/gemini-future-only",
        }
        rejected = {
            "vertex_ai/gemini-4-argon",
            "github_copilot/gemini-4-argon",
            "gemini/sample_spec",
            "gemini-3.1-pro-preview",
        }
        upstream = {key: copy.deepcopy(self.source) for key in keys | rejected}
        upstream["gemini-3.1-pro-preview"]["litellm_provider"] = "vertex_ai-language-models"
        filtered = sync_prices.filter_upstream(upstream, self.config)
        self.assertEqual(keys, set(filtered))

    def test_bare_argon_alias_copies_the_developer_api_entry(self):
        developer = "gemini/gemini-4-argon"
        data = {developer: copy.deepcopy(self.source)}
        aliases = {"gemini-4-argon": self.config["aliases"]["gemini-4-argon"]}
        sync_prices.apply_aliases(data, aliases)
        self.assertEqual(data[developer], data["gemini-4-argon"])
        data["gemini-4-argon"]["supported_endpoints"].append("alias-only")
        self.assertEqual(["/v1beta/models"], data[developer]["supported_endpoints"])

    def test_native_updates_replace_stale_prices_and_removed_fields(self):
        self.assertEqual("additive", self.config["sync_mode"])
        self.assertTrue(self.config["update_existing"])
        existing = {"gemini-legacy": {"input_cost_per_token": 7e-6, "removed_fee": 1}}
        upstream = {
            "gemini-legacy": {"input_cost_per_token": 9e-6, "max_input_tokens": 12345},
            "gemini/gemini-4-argon": copy.deepcopy(self.source),
        }
        result, _ = sync_prices.merge_models(
            existing, upstream, self.config["sync_mode"], self.config["update_existing"]
        )
        self.assertEqual(9e-6, result["gemini-legacy"]["input_cost_per_token"])
        self.assertNotIn("removed_fee", result["gemini-legacy"])
        self.assertEqual(12345, result["gemini-legacy"]["max_input_tokens"])
        self.assertEqual(self.source, result["gemini/gemini-4-argon"])

    def test_sync_publishes_matching_hash_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            # Keep unrelated custom-model aliases out of this two-model fixture.
            config = copy.deepcopy(self.config)
            config["aliases"] = {"gemini-4-argon": config["aliases"]["gemini-4-argon"]}
            config["custom_models"] = {}
            (root / "config.json").write_text(json.dumps(config), encoding="utf-8")
            upstream = {
                "gemini/gemini-4-argon": copy.deepcopy(self.source),
                "vertex_ai/gemini-4-argon": {"input_cost_per_token": 99e-6},
            }
            arguments = ["sync_prices.py", "--repo-root", temporary]
            with patch.object(sync_prices, "fetch_upstream", return_value=upstream), \
                    patch.object(sync_prices.sys, "argv", arguments), \
                    patch("builtins.print") as report:
                sync_prices.main()
                output = root / self.config["output_file"]
                hash_file = root / self.config["hash_file"]
                first = output.read_bytes()
                published = json.loads(first)
                self.assertEqual(self.source, published["gemini/gemini-4-argon"])
                self.assertEqual(self.source, published["gemini-4-argon"])
                self.assertNotIn("vertex_ai/gemini-4-argon", published)
                self.assertEqual(hashlib.sha256(first).hexdigest(), hash_file.read_text().strip())
                with patch.object(sync_prices, "write_output", wraps=sync_prices.write_output) as write:
                    sync_prices.main()
                self.assertEqual(first, output.read_bytes())
                self.assertEqual(hash_file.read_text().strip(), write.call_args.args[-1])
                report.assert_any_call("CHANGED=false")


class XaiPricingTests(unittest.TestCase):
    def setUp(self):
        self.config = sync_prices.load_config(str(ROOT / "config.json"))
        self.config.pop("manual_pricing_file", None)
        self.source = {
            "input_cost_per_token": 2e-6,
            "output_cost_per_token": 6e-6,
            "cache_read_input_token_cost": 0.5e-6,
            "input_cost_per_token_above_200k_tokens": 4e-6,
            "output_cost_per_token_above_200k_tokens": 12e-6,
            "cache_read_input_token_cost_above_200k_tokens": 1e-6,
            "input_cost_per_image_token": 2e-6,
            "litellm_provider": "xai",
            "supported_endpoints": ["/v1/chat/completions"],
        }

    def test_filter_selects_xai_namespace_without_other_providers(self):
        included = {"xai/grok-4.7", "xai/grok-future"}
        excluded = {"openrouter/x-ai/grok-4.7", "azure_ai/grok-4.7", "xai/sample_spec"}
        upstream = {key: copy.deepcopy(self.source) for key in included | excluded}
        self.assertEqual(included, set(sync_prices.filter_upstream(upstream, self.config)))

    def test_bare_alias_copies_complete_exact_card_independently(self):
        data = {"xai/grok-4.7": copy.deepcopy(self.source)}
        sync_prices.apply_aliases(data, {"grok-4.7": self.config["aliases"]["grok-4.7"]})
        self.assertEqual(self.source, data["grok-4.7"])
        data["grok-4.7"]["supported_endpoints"].append("alias-only")
        self.assertEqual(self.source, data["xai/grok-4.7"])

    def test_sync_keeps_existing_prices_and_publishes_alias_with_valid_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = copy.deepcopy(self.config)
            config["aliases"] = {"grok-4.7": config["aliases"]["grok-4.7"]}
            config["custom_models"] = {}
            (root / "config.json").write_text(json.dumps(config), encoding="utf-8")
            existing = {"grok-4.6": {"input_cost_per_token": 7e-6}}
            output = root / config["output_file"]
            output.write_text(json.dumps(existing), encoding="utf-8")
            hash_file = root / config["hash_file"]
            hash_file.write_text(hashlib.sha256(output.read_bytes()).hexdigest() + "\n")
            upstream = {
                "xai/grok-4.7": self.source,
                "azure_ai/grok-4.7": {"input_cost_per_token": 99e-6},
            }
            with patch.object(sync_prices, "fetch_upstream", side_effect=lambda url: copy.deepcopy(upstream)), \
                    patch.object(sync_prices.sys, "argv", ["sync_prices.py", "--repo-root", temporary]), \
                    patch("builtins.print") as report:
                sync_prices.main()
                first = output.read_bytes()
                published = json.loads(first)
                self.assertEqual({**existing, "xai/grok-4.7": self.source, "grok-4.7": self.source}, published)
                self.assertEqual(hashlib.sha256(first).hexdigest(), hash_file.read_text().strip())
                sync_prices.main()
                self.assertEqual(first, output.read_bytes())
                report.assert_any_call("CHANGED=false")


class NativePolicyTests(unittest.TestCase):
    def setUp(self):
        self.config = sync_prices.load_config(str(ROOT / "config.json"))
        self.config.pop("manual_pricing_file", None)

    def test_all_seven_native_providers_are_selected_without_reseller_prices(self):
        cards = {
            "gpt-new": {"litellm_provider": "openai"},
            "claude-new": {"litellm_provider": "anthropic"},
            "gemini/gemini-new": {"litellm_provider": "gemini"},
            "xai/grok-new": {"litellm_provider": "xai"},
            "deepseek/deepseek-new": {"litellm_provider": "deepseek"},
            "zai/glm-new": {"litellm_provider": "zai"},
            "moonshot/kimi-new": {"litellm_provider": "moonshot"},
        }
        wrong = {
            "gpt-reseller": {"litellm_provider": "azure"},
            "gemini/gemini-reseller": {"litellm_provider": "vertex_ai"},
            "xai/grok-reseller": {"litellm_provider": "openrouter"},
            "zai/glm-no-provider": {},
        }
        filtered = sync_prices.filter_upstream({**cards, **wrong}, self.config)
        self.assertEqual(cards, filtered)
        aliases = sync_prices.apply_native_aliases(filtered, copy.deepcopy(cards), self.config["namespace_aliases"])
        self.assertEqual({"gemini-new", "grok-new", "deepseek-new", "glm-new", "kimi-new"}, aliases)

    def test_live_repricing_removes_stale_fees_and_beats_legacy_overrides(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = copy.deepcopy(self.config)
            config["aliases"] = {"grok-4.7": {"source": "legacy-grok"}}
            config["custom_models"] = {"grok-4.7": {"input_cost_per_token": 99e-6}}
            (root / "config.json").write_text(json.dumps(config), encoding="utf-8")
            output = root / config["output_file"]
            original = {"legacy-grok": {"input_cost_per_token": 77e-6}}
            output.write_text(json.dumps(original), encoding="utf-8")
            card = {"litellm_provider": "xai", "input_cost_per_token": 2e-6, "cache_read_input_token_cost": 0.5e-6}
            upstream = {"xai/grok-4.7": card}
            with patch.object(sync_prices, "fetch_upstream", side_effect=lambda url: copy.deepcopy(upstream)), \
                    patch.object(sync_prices.sys, "argv", ["sync_prices.py", "--repo-root", temporary]), \
                    patch("builtins.print"):
                sync_prices.main()
                self.assertEqual(card, json.loads(output.read_text())["grok-4.7"])
                card["input_cost_per_token"] = 3e-6
                del card["cache_read_input_token_cost"]
                sync_prices.main()
                published = json.loads(output.read_text())
                self.assertEqual(card, published["grok-4.7"])
                self.assertEqual(card, published["xai/grok-4.7"])
                self.assertEqual(original["legacy-grok"], published["legacy-grok"])
                raw = output.read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), (root / config["hash_file"]).read_text().strip())
                upstream.clear()
                upstream["gpt-other"] = {"litellm_provider": "openai", "input_cost_per_token": 1e-6}
                sync_prices.main()
                self.assertEqual(card, json.loads(output.read_text())["grok-4.7"])

    def test_configured_gpt_5_6_sol_pricing_overrides_only_that_native_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = copy.deepcopy(self.config)
            config["aliases"] = {}
            config["namespace_aliases"] = []
            config["custom_price_override_models"] = ["gpt-5.6-sol"]
            config["custom_models"] = {
                "gpt-5.6-sol": {
                    "input_cost_per_token": 5e-6,
                    "cache_read_input_token_cost": 0.5e-6,
                    "cache_creation_input_token_cost": 6.25e-6,
                    "output_cost_per_token": 30e-6,
                    "max_input_tokens": 111,
                },
                "gpt-5.6-other": {"input_cost_per_token": 99e-6},
            }
            (root / "config.json").write_text(json.dumps(config), encoding="utf-8")
            output = root / config["output_file"]
            upstream = {
                "gpt-5.6-sol": {
                    "litellm_provider": "openai", "input_cost_per_token": 4e-6,
                    "cache_read_input_token_cost": 0.4e-6,
                    "cache_creation_input_token_cost": 5e-6,
                    "output_cost_per_token": 20e-6, "max_input_tokens": 922000,
                },
                "gpt-5.6-other": {
                    "litellm_provider": "openai", "input_cost_per_token": 7e-6,
                },
            }
            arguments = ["sync_prices.py", "--repo-root", temporary]
            with patch.object(sync_prices, "fetch_upstream", side_effect=lambda url: copy.deepcopy(upstream)), \
                    patch.object(sync_prices.sys, "argv", arguments), \
                    patch("builtins.print"):
                sync_prices.main()
                first = json.loads(output.read_text())
                self.assertEqual(5e-6, first["gpt-5.6-sol"]["input_cost_per_token"])
                self.assertEqual(0.5e-6, first["gpt-5.6-sol"]["cache_read_input_token_cost"])
                self.assertEqual(6.25e-6, first["gpt-5.6-sol"]["cache_creation_input_token_cost"])
                self.assertEqual(30e-6, first["gpt-5.6-sol"]["output_cost_per_token"])
                self.assertEqual(922000, first["gpt-5.6-sol"]["max_input_tokens"])
                self.assertEqual(7e-6, first["gpt-5.6-other"]["input_cost_per_token"])
                upstream["gpt-5.6-sol"]["input_cost_per_token"] = 3e-6
                sync_prices.main()
                published = json.loads(output.read_text())
                self.assertEqual(5e-6, published["gpt-5.6-sol"]["input_cost_per_token"])
                self.assertEqual(7e-6, published["gpt-5.6-other"]["input_cost_per_token"])

    def test_published_gpt_5_6_sol_prices_match_configured_upstream_card(self):
        config = sync_prices.load_config(str(ROOT / "config.json"))
        data = json.loads((ROOT / config["output_file"]).read_text())
        prices = {key: value for key, value in config["custom_models"]["gpt-5.6-sol"].items()
                  if "cost" in key or "price" in key}
        for key, value in prices.items():
            self.assertEqual(value, data["gpt-5.6-sol"][key], key)
        raw = (ROOT / config["output_file"]).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         (ROOT / config["hash_file"]).read_text().strip())

    def test_unknown_native_models_do_not_borrow_reseller_or_adjacent_model_prices(self):
        upstream = {
            "together_ai/deepseek-ai/DeepSeek-V4.1-Flash": {"litellm_provider": "together_ai", "input_cost_per_token": 9e-6},
            "deepseek/deepseek-v4-flash": {"litellm_provider": "deepseek", "input_cost_per_token": 0.3e-6},
            "gpt-image-2.5-flare": {"litellm_provider": "openai", "input_cost_per_image_token": 8e-6},
        }
        filtered = sync_prices.filter_upstream(upstream, self.config)
        sync_prices.apply_native_aliases(filtered, copy.deepcopy(filtered), self.config["namespace_aliases"])
        sync_prices.apply_aliases(filtered, self.config["aliases"], set(filtered))
        self.assertNotIn("deepseek-v4.1-flash", filtered)
        self.assertNotIn("gpt-image-2.5", filtered)

    def test_verified_missing_kimi_fees_yield_to_future_upstream_values(self):
        data = {"kimi-k3": {"cache_creation_input_token_cost": 0.0}}
        sync_prices.fill_official_fields(data, self.config["official_field_defaults"], {"kimi-k3"})
        self.assertEqual(0.0, data["kimi-k3"]["cache_creation_input_token_cost"])
        self.assertEqual(6e-6, data["kimi-k3"]["cache_creation_input_token_cost_above_1hr"])
        data["kimi-k3"]["cache_creation_input_token_cost_above_1hr"] = 9e-6
        sync_prices.fill_official_fields(data, self.config["official_field_defaults"], {"kimi-k3"})
        self.assertEqual(9e-6, data["kimi-k3"]["cache_creation_input_token_cost_above_1hr"])

    def test_missing_source_keeps_last_good_card_without_reseller_fallback(self):
        existing = {"grok-4.7": {"input_cost_per_token": 2e-6}}
        filtered = sync_prices.filter_upstream({"azure_ai/grok-4.7": {"litellm_provider": "azure_ai", "input_cost_per_token": 99e-6}}, self.config)
        merged, _ = sync_prices.merge_models(existing, filtered, self.config["sync_mode"], self.config["update_existing"])
        sync_prices.apply_native_aliases(merged, filtered, self.config["namespace_aliases"])
        self.assertEqual(existing, merged)


class DeepSeekOfficialMappingTests(unittest.TestCase):
    def setUp(self):
        self.config = sync_prices.load_config(str(ROOT / "config.json"))
        self.config.pop("manual_pricing_file", None)
        self.source = {
            "litellm_provider": "deepseek",
            "source": "https://api-docs.deepseek.com/quick_start/pricing",
            "input_cost_per_token": 0.3e-6,
            "output_cost_per_token": 1.2e-6,
            "cache_read_input_token_cost": 0.006e-6,
            "cache_creation_input_token_cost": 0.0,
            "off_peak_pricing": {
                "input_cost_per_token": 0.15e-6,
                "output_cost_per_token": 0.6e-6,
                "cache_read_input_token_cost": 0.003e-6,
                "windows": [{"hours_utc": ["00:00-01:00"], "weekdays": [1, 2, 3, 4, 5]}],
            },
            "max_input_tokens": 1000000,
            "supports_vision": True,
        }

    def test_official_flash_mapping_tracks_complete_card_and_preserves_pro(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = copy.deepcopy(self.config)
            config["aliases"] = {"deepseek-v4.1-flash": config["aliases"]["deepseek-v4.1-flash"]}
            config["custom_models"] = {}
            (root / "config.json").write_text(json.dumps(config))
            upstream = {
                "deepseek/deepseek-flash": copy.deepcopy(self.source),
                "deepseek/deepseek-v4-pro": {"litellm_provider": "deepseek", "input_cost_per_token": 1.32e-6},
            }
            with patch.object(sync_prices, "fetch_upstream", side_effect=lambda url: copy.deepcopy(upstream)), \
                    patch.object(sync_prices.sys, "argv", ["sync_prices.py", "--repo-root", temporary]), \
                    patch("builtins.print") as report:
                sync_prices.main()
                output = root / config["output_file"]
                published = json.loads(output.read_text())
                expected = copy.deepcopy(self.source)
                del expected["cache_creation_input_token_cost"]
                self.assertEqual(expected, published["deepseek-v4.1-flash"])
                self.assertEqual(expected, published["deepseek/deepseek-flash"])
                self.assertEqual(expected, published["deepseek-flash"])
                self.assertEqual(1.32e-6, published["deepseek-v4-pro"]["input_cost_per_token"])
                first = output.read_bytes()
                sync_prices.main()
                self.assertEqual(first, output.read_bytes())
                report.assert_any_call("CHANGED=false")
                upstream["deepseek/deepseek-flash"]["off_peak_pricing"]["input_cost_per_token"] = 0.12e-6
                del upstream["deepseek/deepseek-flash"]["supports_vision"]
                sync_prices.main()
                changed = json.loads(output.read_text())["deepseek-v4.1-flash"]
                self.assertEqual(0.12e-6, changed["off_peak_pricing"]["input_cost_per_token"])
                self.assertNotIn("supports_vision", changed)
                del upstream["deepseek/deepseek-flash"]
                sync_prices.main()
                self.assertEqual(changed, json.loads(output.read_text())["deepseek-v4.1-flash"])
                self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(),
                                 (root / config["hash_file"]).read_text().strip())

    def test_future_exact_native_card_wins_over_official_endpoint_alias(self):
        filtered = {
            "deepseek/deepseek-flash": self.source,
            "deepseek/deepseek-v4.1-flash": {"litellm_provider": "deepseek", "input_cost_per_token": 0.2e-6},
        }
        data = copy.deepcopy(filtered)
        bare = sync_prices.apply_native_aliases(data, filtered, self.config["namespace_aliases"])
        sync_prices.apply_aliases(data, self.config["aliases"], set(filtered) | bare)
        self.assertEqual(filtered["deepseek/deepseek-v4.1-flash"], data["deepseek-v4.1-flash"])

    def test_published_manual_prices_preserve_distinct_owner_model_cards(self):
        cards = json.loads((ROOT / self.config["output_file"]).read_text())
        manual = json.loads((ROOT / 'manual-prices.json').read_text())
        from manual_prices import FIELDS
        from decimal import Decimal
        for spec in manual['models'].values():
            for target in spec['targets']:
                for field, key in FIELDS.items():
                    if field in spec:
                        self.assertEqual(float(Decimal(str(spec[field])) / Decimal(1000000)), cards[target][key])
                self.assertNotIn('pricing_rules', cards[target])
        self.assertNotEqual(cards['deepseek-v4-flash']['input_cost_per_token'],
                            cards['deepseek-v4.1-flash']['input_cost_per_token'])


class LongContextSolPricingTests(unittest.TestCase):
    def setUp(self):
        self.config = sync_prices.load_config(str(ROOT / "config.json"))
        self.config.pop("manual_pricing_file", None)
        fields = (
            "input_cost_per_token", "cache_read_input_token_cost",
            "cache_creation_input_token_cost", "output_cost_per_token",
        )
        tiers = {
            "": (2e-6, 1e-7, 2.5e-6, 1e-5),
            "_batches": (1e-6, 5e-8, 1.25e-6, 5e-6),
            "_flex": (1e-6, 5e-8, 1.25e-6, 5e-6),
            "_priority": (4e-6, 2e-7, 5e-6, 2e-5),
            "_ultrafast": (1.2e-5, 6e-7, 1.5e-5, 6e-5),
        }
        self.base = {field + tier: rate for tier, rates in tiers.items()
                     for field, rate in zip(fields, rates)}
        self.premiums = {
            field + "_above_272k_tokens" + tier: 99e-6
            for tier in tiers for field in fields
        }

    def test_exclusions_preserve_sol_context_tiers_and_other_models(self):
        expected = {
            **self.base,
            "cache_creation_input_token_cost_above_1hr": 4e-6,
            "max_input_tokens": 922000,
        }
        other = {**self.base, **self.premiums}
        data = {
            "gpt-6.1-sol": {**expected, **self.premiums},
            "gpt-other": copy.deepcopy(other),
        }
        removed = sync_prices.remove_excluded_model_fields(
            data, self.config["excluded_model_fields"]
        )
        self.assertEqual(0, removed)
        self.assertEqual({**expected, **self.premiums}, data["gpt-6.1-sol"])
        self.assertEqual(other, data["gpt-other"])

    def test_repeated_sync_restores_native_context_tiers_over_stale_custom_prices(self):
        upstream = {
            "gpt-6.1-sol": {**self.base, **self.premiums, "max_input_tokens": 922000,
                            "litellm_provider": "openai"},
            "gpt-other": {**self.base, **self.premiums, "litellm_provider": "openai"},
        }
        for mode in ("additive", "full"):
            with self.subTest(sync_mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                config = copy.deepcopy(self.config)
                config["sync_mode"] = mode
                config["provider_prefixes"] = {"openai": ["gpt-"]}
                config["namespace_aliases"] = []
                config["aliases"] = {}
                config["custom_models"] = {
                    "gpt-6.1-sol": {"input_cost_per_token_above_272k_tokens": 88e-6}
                }
                (root / "config.json").write_text(json.dumps(config), encoding="utf-8")
                output = root / config["output_file"]
                existing = copy.deepcopy(upstream)
                for field in self.premiums:
                    existing["gpt-6.1-sol"].pop(field)
                output.write_text(json.dumps(existing), encoding="utf-8")
                hash_file = root / config["hash_file"]
                hash_file.write_text(hashlib.sha256(output.read_bytes()).hexdigest() + "\n")
                arguments = ["sync_prices.py", "--repo-root", temporary]
                with patch.object(sync_prices, "fetch_upstream",
                                  side_effect=lambda url: copy.deepcopy(upstream)), \
                        patch.object(sync_prices.sys, "argv", arguments), \
                        patch("builtins.print") as report:
                    sync_prices.main()
                    first = output.read_bytes()
                    published = json.loads(first)
                    self.assertEqual(upstream["gpt-6.1-sol"], published["gpt-6.1-sol"])
                    self.assertEqual(upstream["gpt-other"], published["gpt-other"])
                    self.assertEqual(hashlib.sha256(first).hexdigest(),
                                     hash_file.read_text().strip())
                    sync_prices.main()
                    self.assertEqual(first, output.read_bytes())
                    report.assert_any_call("CHANGED=false")

    def test_published_sol_prices_and_hash(self):
        raw = (ROOT / self.config["output_file"]).read_bytes()
        entry = json.loads(raw)["gpt-6.1-sol"]
        for field in self.base:
            self.assertGreater(entry[field], 0, field)
        for field in self.premiums:
            self.assertGreater(entry[field], 0, field)
            base_field = field.replace("_above_272k_tokens", "")
            multiplier = 1.5 if field.startswith("output_cost_per_token") else 2
            self.assertAlmostEqual(entry[base_field] * multiplier, entry[field], places=12)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         (ROOT / self.config["hash_file"]).read_text().strip())


if __name__ == "__main__":
    unittest.main()
