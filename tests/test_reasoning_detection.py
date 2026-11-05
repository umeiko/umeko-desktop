"""Pure discovery fixtures: no credentials, app, HTTP or model calls."""
import unittest

from app.reasoning_detection import (
    EFFORT_CANDIDATES, allowed_levels, detect_model, is_effort_rejection, metadata_levels,
)
from app.thinking_formats import format_parameters, valid_format


INVALID = "__umeko_invalid_effort__"
OPENAI_FORMATS = ["qwen", "deepseek", "chat-template", "openai-none", "openai"]
ANTHROPIC_FORMATS = ["deepseek", "anthropic-adaptive", "qwen", "chat-template", "openai-none", "anthropic"]


def observation(thinking=False, content=False):
    return {"thinking": thinking, "content": content}


def enum_error(levels):
    return ValueError("reasoning_effort: expected one of " + ", ".join(repr(x) for x in levels))


class ThinkingFormatTests(unittest.TestCase):
    def test_exact_raw_effort_and_separate_off(self):
        self.assertEqual(format_parameters("openai", "off"), {})
        self.assertEqual(format_parameters("openai-none", "off"), {"reasoning_effort": "none"})
        self.assertEqual(format_parameters("chat-template", "vendor-custom"), {
            "chat_template_kwargs": {"enable_thinking": True, "reasoning_effort": "vendor-custom"}})
        self.assertEqual(format_parameters("chat-template", "off"), {
            "chat_template_kwargs": {"enable_thinking": False}})
        self.assertEqual(format_parameters("qwen", "off"), {"enable_thinking": False})
        self.assertEqual(format_parameters("deepseek", "none"), {
            "thinking": {"type": "enabled"}, "reasoning_effort": "none"})
        self.assertEqual(format_parameters("deepseek", "off"), {"thinking": {"type": "disabled"}})
        self.assertEqual(format_parameters("anthropic-adaptive", "high"), {
            "thinking": {"type": "adaptive"}, "reasoning_effort": "high"})
        for protocol in ("anthropic", "responses"):
            self.assertEqual(format_parameters(protocol, "custom"), {"reasoning_effort": "custom"})
        self.assertFalse(valid_format("guessed-provider"))
        with self.assertRaises(ValueError):
            format_parameters("guessed-provider", "low")


class ReasoningDetectionTests(unittest.TestCase):
    def test_parser_reuses_only_effort_scoped_enum(self):
        self.assertEqual(allowed_levels(enum_error(["high", "low"])), ["low", "high"])
        self.assertEqual(allowed_levels({"error": {"loc": ["body", "reasoning_effort"],
            "msg": "Input should be 'low', 'medium' or 'high'"}}), ["low", "medium", "high"])
        self.assertIsNone(allowed_levels({"error": {"param": "model", "allowed": ["a", "b"],
            "message": "invalid reasoning_effort"}}))
        for text in ("invalid API key reasoning_effort", "reasoning_effort timeout",
                     "reasoning_effort invalid max_tokens", "network error"):
            self.assertFalse(is_effort_rejection(ValueError(text)))
        self.assertEqual(metadata_levels({"reasoning": {"supported_efforts": None}}),
                         ["none", "minimal", "low", "medium", "high", "xhigh", "max"])

    def test_enum_and_actual_on_off_stop_at_one(self):
        calls = []
        def request(effort, format, cap):
            calls.append((effort, format, cap))
            if effort == INVALID:
                raise enum_error(["high", "medium", "low"])
            return observation(thinking=effort != "off", content=effort == "off")
        result = detect_model(request)
        self.assertEqual(result["levels"]["levels"], ["low", "medium", "high"])
        self.assertTrue(result["levels"]["verified"])
        self.assertTrue(result["format"]["offVerified"])
        self.assertEqual(result["format"]["format"], "openai-none")
        self.assertEqual(result["format"]["offFormat"], "openai-none")
        self.assertEqual(result["format"]["onEffort"], "high")
        self.assertEqual(result["format"]["status"], "on-off-verified")
        self.assertEqual(result["format"]["formatsTried"], OPENAI_FORMATS)
        self.assertEqual(calls, [(INVALID, "openai", 1),
            *((effort, format, 1) for format in OPENAI_FORMATS for effort in ("high", "off")),
            (INVALID, "openai-none", 1)])

    def test_native_effort_pair_precedes_extension_and_omission(self):
        calls = []
        def request(effort, format, cap):
            calls.append((effort, format, cap))
            return observation(thinking=effort != "off" and format in ("qwen", "openai-none", "openai"),
                               content=effort == "off")
        facts = detect_model(request, advertised_levels=["medium", "high"], caps=(1,))["format"]
        self.assertEqual(facts["formatsTried"], OPENAI_FORMATS)
        self.assertEqual([format for effort, format, _ in calls if effort == "high"], OPENAI_FORMATS)
        self.assertEqual([format for effort, format, _ in calls if effort == "off"], OPENAI_FORMATS)
        self.assertEqual(facts["format"], "openai-none")
        self.assertEqual(facts["offFormat"], "openai-none")
        self.assertEqual(facts["status"], "on-off-verified")
        self.assertTrue(facts["verified"])
        self.assertEqual(next(item for item in facts["offSwitchesTried"] if item["format"] == "openai-none")
                         ["parameters"], {"reasoning_effort": "none"})

    def test_late_rate_limit_or_timeout_is_failed_instead_of_cannot_disable(self):
        class RateLimitError(Exception):
            status_code = 429
        for error in (RateLimitError("request rate limited"), TimeoutError("network timeout")):
            with self.subTest(error=type(error).__name__):
                def request(effort, format, cap):
                    if effort == INVALID:
                        raise enum_error(["low", "high"])
                    if effort == "off" and format == "deepseek":
                        raise error
                    return observation(thinking=True)
                facts = detect_model(request)["format"]
                self.assertEqual(facts["state"], "failed")
                self.assertEqual(facts["status"], "unknown")
                self.assertIsNone(facts["offSupported"])
                self.assertFalse(facts["offVerified"])
                self.assertNotEqual(facts["status"], "cannot-disable")
                self.assertIn(str(error), facts["error"])
                self.assertTrue(facts["onAttempts"])
                off_attempts = {item["format"]: item for item in facts["offSwitchesTried"]}
                self.assertEqual(off_attempts["qwen"]["status"], "still-thinking")
                self.assertIn(str(error), off_attempts["deepseek"]["error"])

    def test_silent_levels_use_documented_fallback_and_only_ctk_proves_switch(self):
        calls = []
        def request(effort, format, cap):
            calls.append((effort, format, cap))
            if effort == INVALID:
                return observation()
            return observation(thinking=format == "chat-template" and effort != "off",
                               content=effort == "off")
        result = detect_model(request)
        self.assertEqual(result["format"]["format"], "chat-template")
        self.assertTrue(result["format"]["verified"])
        self.assertEqual(result["levels"]["levels"], list(EFFORT_CANDIDATES[:-1]))
        self.assertFalse(result["levels"]["verified"])
        self.assertTrue(result["levels"]["invalidAccepted"])
        self.assertEqual(sum(e == INVALID for e, _, _ in calls), 2)
        self.assertFalse(any(e == "ultra" for e, _, _ in calls))

    def test_qwen_format_and_missing_observation_expansion(self):
        calls = []
        def request(effort, format, cap):
            calls.append((effort, format, cap))
            if effort == INVALID:
                raise enum_error(["low", "high"])
            return {"thinkingChars": 1 if format == "qwen" and effort != "off" and cap >= 4 else 0,
                    "contentChars": 1 if effort == "off" and cap >= 4 else 0}
        result = detect_model(request)
        self.assertEqual(result["format"]["format"], "qwen")
        self.assertEqual(result["format"]["outputCap"], 4)
        self.assertEqual(result["format"]["onEffort"], "high")
        self.assertNotIn(("high", "qwen", 16), calls)
        self.assertNotIn(("off", "qwen", 16), calls)

    def test_acceptance_or_one_token_silence_does_not_prove_format(self):
        result = detect_model(lambda *args: observation())
        self.assertEqual(result["format"]["state"], "known")
        self.assertEqual(result["format"]["format"], "openai")
        self.assertEqual(result["format"]["status"], "on-not-observable")
        self.assertFalse(result["format"]["onObserved"])
        self.assertFalse(result["format"]["offSupported"])
        self.assertFalse(result["format"]["verified"])
        self.assertEqual(result["levels"]["state"], "known")
        self.assertFalse(result["levels"]["verified"])

    def test_real_on_without_working_off_is_retained_honestly(self):
        calls = []
        def request(effort, format, cap):
            calls.append((effort, format, cap))
            return observation(thinking=True)
        result = detect_model(request, advertised_levels=["low"])
        self.assertEqual(result["format"]["format"], "openai")
        self.assertTrue(result["format"]["onObserved"])
        self.assertFalse(result["format"]["verified"])
        self.assertFalse(result["format"]["offVerified"])
        self.assertFalse(result["format"]["offSupported"])
        self.assertEqual(result["format"]["status"], "cannot-disable")
        self.assertEqual(result["format"]["formatsTried"], OPENAI_FORMATS)
        self.assertEqual(result["format"]["offSwitchesTried"], [
            {"format": format, "parameters": format_parameters(format, "off"),
             "status": "still-thinking", "thinkingObserved": True,
             "ordinaryContentObserved": False, "outputCap": 1}
            for format in OPENAI_FORMATS])
        self.assertTrue(all(cap == 1 for _, _, cap in calls))

    def test_manual_fields_are_independent_and_preserve_names(self):
        calls = []
        def request(effort, format, cap):
            calls.append((effort, format, cap))
            if effort == INVALID:
                raise enum_error(["high", "low"])
            return observation(thinking=effort != "off", content=effort == "off")
        result = detect_model(request, manual_levels=["Custom-B", "Custom-A"])
        self.assertEqual(result["levels"]["levels"], ["Custom-B", "Custom-A"])
        self.assertEqual(calls[0], ("Custom-B", "qwen", 1))
        calls.clear()
        result = detect_model(request, manual_format="chat-template")
        self.assertEqual(calls, [(INVALID, "chat-template", 1)])
        self.assertEqual(result["levels"]["levels"], ["low", "high"])
        self.assertEqual(result["format"]["source"], "manual")
        self.assertIsNone(result["format"]["offSupported"])
        self.assertEqual(result["format"]["formatsTried"], [])
        calls.clear()
        detect_model(request, manual_levels=[], manual_format="qwen")
        self.assertEqual(calls, [])

    def test_new_wire_error_enum_and_no_repeat_initial_invalid(self):
        calls = []
        def request(effort, format, cap):
            calls.append((effort, format, cap))
            if format != "chat-template":
                raise ValueError("unsupported parameter reasoning_effort")
            if effort == INVALID or effort not in ("fast", "off"):
                raise enum_error(["fast"])
            return observation(thinking=effort == "fast", content=effort == "off")
        result = detect_model(request)
        self.assertEqual(result["format"]["format"], "chat-template")
        self.assertEqual(result["levels"]["levels"], ["fast"])
        self.assertEqual(calls.count((INVALID, "openai", 1)), 1)
        self.assertEqual(calls.count((INVALID, "chat-template", 1)), 1)

    def test_no_enum_probes_union_only_after_selected_wire(self):
        calls = []
        def request(effort, format, cap):
            calls.append((effort, format, cap))
            if effort not in ("medium", "max", "off"):
                raise ValueError("reasoning_effort invalid")
            return observation(thinking=effort != "off", content=effort == "off")
        result = detect_model(request)
        self.assertEqual(result["levels"]["levels"], ["medium", "max"])
        self.assertTrue(result["levels"]["verified"])
        selected = result["format"]["format"]
        self.assertEqual(result["format"]["onEffort"], "max")
        self.assertEqual(calls.count(("medium", selected, 1)), 1)
        self.assertEqual(calls.count(("max", selected, 1)), 1)
        self.assertTrue(all(cap == 1 for _, _, cap in calls))

    def test_no_enum_finds_valid_on_effort_when_max_rejected(self):
        calls = []
        def request(effort, format, cap):
            calls.append((effort, format, cap))
            if effort not in ("low", "high", "off"):
                raise ValueError("reasoning_effort invalid")
            return observation(thinking=effort != "off", content=effort == "off")
        result = detect_model(request)
        self.assertTrue(result["format"]["offVerified"])
        self.assertEqual(result["levels"]["levels"], ["low", "high"])
        self.assertEqual(calls.count(("high", "qwen", 1)), 1)
        self.assertEqual(result["format"]["onEffort"], "high")
        self.assertEqual(calls[1], ("max", "qwen", 1))

    def test_strongest_probe_effort_descends_after_rejection_without_rewriting_custom_names(self):
        for mode in ("declared", "max-rejected", "manual-custom"):
            with self.subTest(mode=mode):
                calls = []
                def request(effort, format, cap):
                    calls.append((effort, format, cap))
                    if mode == "max-rejected" and effort == "max":
                        raise enum_error(["low", "high"])
                    return observation(thinking=effort != "off", content=effort == "off")
                arguments = ({"manual_levels": ["vendor-a", "vendor-z"]}
                             if mode == "manual-custom" else
                             {"advertised_levels": ["low", "high", "max"]})
                result = detect_model(request, caps=(1,), **arguments)
                expected = {"declared": "max", "max-rejected": "high", "manual-custom": "vendor-a"}[mode]
                self.assertEqual(result["format"]["onEffort"], expected)
                on_requests = [effort for effort, format, cap in calls if format == "qwen" and effort != "off"]
                self.assertEqual(on_requests, ["max", "high"] if mode == "max-rejected" else [expected])
                if mode == "manual-custom":
                    self.assertEqual(result["levels"]["levels"], ["vendor-a", "vendor-z"])
                    self.assertEqual(result["levels"]["source"], "manual")
                    self.assertEqual({effort for effort, _, _ in calls if effort != "off"}, {"vendor-a"})

    def test_unrelated_error_fails_without_trying_candidate_values(self):
        for message in ("unauthorized", "network timeout", "max_tokens must be at least 32"):
            calls = []
            def request(*args):
                calls.append(args)
                raise ValueError(message)
            result = detect_model(request)
            self.assertEqual(result["levels"]["state"], "failed")
            self.assertEqual(result["format"]["state"], "failed")
            self.assertEqual(len(calls), 1)

    def test_native_protocol_markers(self):
        calls = []
        def request(effort, format, cap):
            calls.append((effort, format, cap))
            if effort == INVALID:
                raise enum_error(["medium", "high"])
            return observation(thinking=format == "anthropic-adaptive" and effort != "off",
                               content=effort == "off")
        result = detect_model(request, protocol="anthropic")
        self.assertEqual(result["format"]["format"], "anthropic-adaptive")
        self.assertTrue(result["format"]["offVerified"])
        self.assertEqual(result["format"]["formatsTried"], ANTHROPIC_FORMATS)
        self.assertEqual([format for effort, format, _ in calls if effort == "off"], ANTHROPIC_FORMATS)
        calls.clear()
        result = detect_model(request, protocol="responses")
        self.assertEqual(calls, [(INVALID, "responses", 1)])
        self.assertEqual(result["format"]["format"], "responses")
        self.assertFalse(result["format"]["verified"])

    def test_all_off_switches_are_tried_even_when_on_is_rejected_or_invisible(self):
        calls = []
        def request(effort, format, cap):
            calls.append((effort, format, cap))
            if effort != "off" and format in ("qwen", "deepseek"):
                raise ValueError("thinking control is not supported")
            return observation(content=effort == "off")
        result = detect_model(request, advertised_levels=["high"], caps=(1, 4))
        facts = result["format"]
        self.assertEqual([format for effort, format, _ in calls if effort == "off"], OPENAI_FORMATS)
        self.assertEqual(facts["status"], "on-not-observable")
        self.assertTrue(facts["offSupported"])
        self.assertFalse(facts["onObserved"])
        self.assertFalse(facts["verified"])
        self.assertEqual([item["status"] for item in facts["onAttempts"]],
                         ["rejected", "rejected", "not-observable", "not-observable", "not-observable"])
        self.assertTrue(all(item["status"] == "disabled" for item in facts["offSwitchesTried"]))
        self.assertTrue(all(item["outputCap"] == 1 for item in facts["offSwitchesTried"]))

    def test_later_paired_qwen_wins_over_first_on_and_hybrid(self):
        def request(effort, format, cap):
            if effort == "off":
                return observation(thinking=format != "qwen", content=format == "qwen")
            return observation(thinking=format in ("deepseek", "qwen"))
        result = detect_model(request, advertised_levels=["low", "medium", "high"], protocol="anthropic")
        facts = result["format"]
        self.assertEqual(facts["format"], "qwen")
        self.assertEqual(facts["offFormat"], "qwen")
        self.assertEqual(facts["onAttempts"][0]["format"], "deepseek")
        self.assertTrue(facts["onAttempts"][0]["thinkingObserved"])
        self.assertEqual(facts["offSwitchesTried"][0]["status"], "still-thinking")
        self.assertEqual(facts["onEffort"], "high")
        self.assertEqual(facts["status"], "on-off-verified")
        self.assertTrue(facts["verified"])

    def test_hybrid_on_and_off_formats_are_both_reported(self):
        def request(effort, format, cap):
            if effort == "off":
                return observation(thinking=format != "deepseek", content=format == "deepseek")
            return observation(thinking=format == "qwen")
        facts = detect_model(request, advertised_levels=["high"])["format"]
        self.assertEqual(facts["format"], "qwen")
        self.assertEqual(facts["offFormat"], "deepseek")
        self.assertTrue(facts["offSupported"])
        self.assertTrue(facts["verified"])
        self.assertEqual(facts["status"], "on-off-verified")

    def test_chat_template_real_observation_needs_cap_four(self):
        calls = []
        def request(effort, format, cap):
            calls.append((effort, format, cap))
            if format != "chat-template":
                return observation(thinking=effort == "off")
            return observation(thinking=effort != "off" and cap >= 4,
                               content=effort == "off" and cap >= 4)
        facts = detect_model(request, advertised_levels=["low", "high"], caps=(1, 4, 16))["format"]
        self.assertEqual(facts["format"], "chat-template")
        self.assertEqual(facts["offFormat"], "chat-template")
        self.assertEqual(facts["outputCap"], 4)
        self.assertEqual(facts["onEffort"], "high")
        self.assertNotIn(("high", "chat-template", 16), calls)
        self.assertNotIn(("off", "chat-template", 16), calls)
        self.assertEqual(facts["status"], "on-off-verified")


if __name__ == "__main__":
    unittest.main()
