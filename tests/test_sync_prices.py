"""Offline regressions for namespaced Gemini pricing and published output."""

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
        self.source = {
            "input_cost_per_token": 2e-6,
            "output_cost_per_token": 1e-5,
            "cache_read_input_token_cost": 1e-7,
            "input_cost_per_token_priority": 3.6e-6,
            "litellm_provider": "gemini",
            "supported_endpoints": ["/v1beta/models"],
        }

    def test_filter_includes_namespaced_and_legacy_gemini(self):
        keys = {
            "gemini/gemini-4-argon",
            "gemini/gemini-future-only",
            "gemini-3.1-pro-preview",
            "claude-test",
            "gpt-test",
        }
        rejected = {
            "vertex_ai/gemini-4-argon",
            "github_copilot/gemini-4-argon",
            "gemini/sample_spec",
        }
        upstream = {key: copy.deepcopy(self.source) for key in keys | rejected}
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

    def test_additive_sync_preserves_existing_prices_and_accepts_new_fields(self):
        self.assertEqual("additive", self.config["sync_mode"])
        self.assertFalse(self.config["update_existing"])
        existing = {"gemini-legacy": {"input_cost_per_token": 7e-6}}
        upstream = {
            "gemini-legacy": {"input_cost_per_token": 9e-6, "max_input_tokens": 12345},
            "gemini/gemini-4-argon": copy.deepcopy(self.source),
        }
        result, _ = sync_prices.merge_models(
            existing, upstream, self.config["sync_mode"], self.config["update_existing"]
        )
        self.assertEqual(7e-6, result["gemini-legacy"]["input_cost_per_token"])
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


if __name__ == "__main__":
    unittest.main()
