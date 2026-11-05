"""Pure discovery fixtures: no credentials, app, HTTP or model calls."""
import unittest

from app.reasoning_detection import (
    EFFORT_CANDIDATES, allowed_levels, detect_model, is_effort_rejection, metadata_levels,
)
from app.thinking_formats import format_parameters, valid_format


INVALID = "__umeko_invalid_effort__"


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
        self.assertEqual(calls, [(INVALID, "openai", 1), ("medium", "openai", 1), ("off", "openai", 1)])

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
        self.assertNotIn(("low", "qwen", 16), calls)
        self.assertNotIn(("off", "qwen", 16), calls)

    def test_acceptance_or_one_token_silence_does_not_prove_format(self):
        result = detect_model(lambda *args: observation())
        self.assertEqual(result["format"]["state"], "failed")
        self.assertIsNone(result["format"]["format"])
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
        self.assertEqual(calls[0], ("Custom-B", "openai", 1))
        calls.clear()
        result = detect_model(request, manual_format="chat-template")
        self.assertEqual(calls, [(INVALID, "chat-template", 1)])
        self.assertEqual(result["levels"]["levels"], ["low", "high"])
        self.assertEqual(result["format"]["source"], "manual")
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
        self.assertEqual(calls.count(("medium", "openai", 1)), 1)
        self.assertTrue(all(cap == 1 for _, _, cap in calls))

    def test_no_enum_finds_valid_on_effort_when_medium_rejected(self):
        calls = []
        def request(effort, format, cap):
            calls.append((effort, format, cap))
            if effort not in ("low", "high", "off"):
                raise ValueError("reasoning_effort invalid")
            return observation(thinking=effort != "off", content=effort == "off")
        result = detect_model(request)
        self.assertTrue(result["format"]["offVerified"])
        self.assertEqual(result["levels"]["levels"], ["low", "high"])
        self.assertEqual(calls.count(("low", "openai", 1)), 1)

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
        self.assertFalse(any(format == "qwen" for _, format, _ in calls))
        calls.clear()
        result = detect_model(request, protocol="responses")
        self.assertEqual(calls, [(INVALID, "responses", 1)])
        self.assertEqual(result["format"]["format"], "responses")
        self.assertFalse(result["format"]["verified"])


if __name__ == "__main__":
    unittest.main()
