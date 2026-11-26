"""Effect tests use the wire dictionary seen by a model, not format names."""
import json
from pathlib import Path
import unittest

from app.reasoning_detection import (
    detect_model, MAX_EFFECT_REQUESTS, PROBE_QUESTION, probe_answer_correct,
)
from app.thinking_formats import format_parameters


def observation(amount=0, correct=True, metric="reasoningTokens"):
    return {"reasoningTokens": amount if metric == "reasoningTokens" else None,
            "thinkingChars": amount if metric == "thinkingChars" else amount * 4,
            "thinking": amount > 0, "content": True,
            "answer": "24" if correct else "25", "correct": correct,
            "finishReason": "stop"}


class FakeModel:
    def __init__(self, mode):
        self.mode, self.calls = mode, []

    def __call__(self, effort, style, cap):
        params = format_parameters(style, effort)
        self.calls.append(params)
        return self.respond(params)

    def respond(self, params):
        """Respond to the actual downstream wire, also used by HTTP fixtures."""
        nested = params.get("chat_template_kwargs", {})
        level = params.get("reasoning_effort")
        if self.mode == "all-effort400" and (level is not None or "reasoning_effort" in nested):
            raise ValueError("unsupported parameter reasoning_effort")
        if self.mode in ("native", "degrading", "disappearing"):
            amounts = {"none": 0, "minimal": 16, "low": 16, "medium": 40,
                       "high": 90, "xhigh": 90, "max": 200}
            if self.mode == "degrading" and level and level != "none":
                return observation(90, False)
            if self.mode == "disappearing" and level and level != "none":
                return observation(0)
            if level is not None:
                return observation(amounts.get(level, 0))
            if "enable_thinking" in params:
                return observation(90 if params["enable_thinking"] else 0)
            return observation(40 if self.mode == "disappearing" else 0)
        if self.mode == "nested":
            if "enable_thinking" in nested:
                return observation({"none": 0, "minimal": 16, "low": 16, "medium": 40,
                    "high": 90, "xhigh": 90, "max": 200}.get(nested.get("reasoning_effort"), 0)
                    if nested["enable_thinking"] else 0)
            return observation(0)
        if self.mode in ("ignored200", "litellm-ignored"):
            # Simulate a proxy accepting/mapping every effort while the model
            # ignores its mapped flag. Status and acceptance prove nothing.
            upstream = {"enable_thinking": level != "none"} if level is not None else params
            del upstream
            return observation(50)
        if self.mode == "unobservable":
            return {"thinking": False, "content": True, "thinkingChars": 0,
                    "reasoningTokens": None, "answer": "24", "correct": True, "finishReason": "stop"}
        field = {"all-effort400": "enable_thinking", "thinking": "enable_thinking",
                 "reasoning": "enable_reasoning", "template": "thinking",
                 "deepseek": "type"}.get(self.mode)
        target = nested if self.mode == "template" else params.get("thinking", {}) if self.mode == "deepseek" else params
        enabled = target.get(field) in (True, "enabled")
        return observation(80 if enabled else 0)


class ReasoningEffectTests(unittest.TestCase):
    results = {}

    def run_model(self, mode, **kwargs):
        model = FakeModel(mode)
        result = detect_model(model, **kwargs)
        self.assertLessEqual(len(model.calls), MAX_EFFECT_REQUESTS)
        self.assertEqual(len(model.calls), len({json.dumps(p, sort_keys=True) for p in model.calls}))
        self.assertEqual(result["format"]["requestCount"], len(model.calls))
        self.results[mode] = result
        return result

    def test_question_answer_and_pure_mappings(self):
        self.assertIn("integer", PROBE_QUESTION)
        self.assertTrue(probe_answer_correct("24"))
        self.assertFalse(probe_answer_correct("25"))
        expected = {"qwen-switch": {"enable_thinking": True},
                    "reasoning-switch": {"enable_reasoning": True},
                    "deepseek-switch": {"thinking": {"type": "enabled"}},
                    "template-thinking": {"chat_template_kwargs": {"thinking": True}}}
        for style, params in expected.items():
            self.assertEqual(format_parameters(style, "high"), params)
            self.assertNotIn("reasoning_effort", format_parameters(style, "off"))

    def test_all_effort_400_still_discovers_pure_switch(self):
        result = self.run_model("all-effort400")
        self.assertEqual(result["format"]["format"], "qwen-switch")
        self.assertTrue(result["format"]["offVerified"])
        self.assertEqual(result["levels"]["levels"], ["high"])
        self.assertTrue(result["levels"]["verified"])

    def test_accepted_ignored_and_litellm_mapping_do_not_verify(self):
        for mode in ("ignored200", "litellm-ignored"):
            result = self.run_model(mode)
            self.assertFalse(result["format"]["verified"])
            self.assertFalse(result["format"]["offVerified"])
            self.assertFalse(result["levels"]["verified"])
            self.assertEqual(result["levels"]["levels"], [])
            self.assertEqual(result["format"]["requestCount"], 26)

    def test_independent_pure_switches(self):
        for mode, style in (("thinking", "qwen-switch"), ("reasoning", "reasoning-switch"),
                            ("template", "template-thinking"), ("deepseek", "deepseek-switch")):
            result = self.run_model(mode)
            self.assertEqual(result["format"]["format"], style)
            self.assertEqual(result["levels"]["levels"], ["high"])
            self.assertTrue(result["format"]["offVerified"])
            self.assertEqual(result["format"]["degradingStyles"], [])

    def test_wrong_or_disappearing_native_uses_safe_switch(self):
        for mode in ("degrading", "disappearing"):
            result = self.run_model(mode)
            self.assertEqual(result["format"]["format"], "qwen-switch")
            self.assertTrue(result["format"]["offVerified"])
            self.assertEqual(result["levels"]["levels"], ["high"])
            self.assertEqual(result["format"]["degradingStyles"][0]["format"], "openai-none")
            self.assertTrue(result["format"]["degradingStyles"][0]["reason"])

    def test_distinct_native_levels_merge_equal_amounts_and_preserve_evidence(self):
        result = self.run_model("native")
        self.assertEqual(result["format"]["format"], "openai-none")
        self.assertTrue(result["levels"]["verified"])
        self.assertTrue(result["format"]["offVerified"])
        self.assertEqual(result["levels"]["levels"], ["none", "low", "medium", "high", "max"])
        self.assertEqual(result["levels"]["aliases"]["minimal"], "low")
        self.assertEqual(result["levels"]["aliases"]["xhigh"], "high")
        self.assertEqual(result["format"]["requestCount"], 8)
        self.assertEqual(result["levels"]["evidence"][0]["parameters"], {})
        self.assertEqual(result["levels"]["evidence"][0]["answer"], "24")

    def test_nested_effort_has_measured_levels(self):
        result = self.run_model("nested")
        self.assertEqual(result["format"]["format"], "chat-template")
        self.assertTrue(result["format"]["offVerified"])
        self.assertGreater(len(result["levels"]["levels"]), 1)
        self.assertTrue(result["levels"]["verified"])

    def test_unobservable_reasoning_keeps_unverified_fallback(self):
        result = self.run_model("unobservable")
        self.assertEqual(result["levels"]["source"], "fallback")
        self.assertFalse(result["levels"]["verified"])
        self.assertFalse(result["format"]["verified"])

    def test_manual_values_and_format_remain_authority(self):
        result = self.run_model("thinking", manual_levels=["Vendor-B", "Vendor-A"],
                                manual_format="qwen-switch")
        self.assertEqual(result["levels"]["source"], "manual")
        self.assertEqual(result["levels"]["levels"], ["Vendor-B", "Vendor-A"])
        self.assertEqual(result["format"]["source"], "manual")
        self.assertEqual(result["format"]["format"], "qwen-switch")

    def test_missing_off_usage_and_zero_usage_with_visible_reasoning(self):
        for on_tokens in (None, 0, 30):
            with self.subTest(on_tokens=on_tokens):
                def request(effort, style, cap):
                    params = format_parameters(style, effort)
                    on = params.get("enable_thinking") is True
                    return {"reasoningTokens": on_tokens if on else None,
                            "thinkingChars": 120 if on else 0, "thinking": on,
                            "answer": "24", "correct": True, "finishReason": "stop"}
                result = detect_model(request)
                self.assertEqual(result["format"]["format"], "qwen-switch")
                self.assertTrue(result["format"]["offVerified"])
                self.assertEqual(result["levels"]["levels"], ["high"])

    def test_distinct_50_75_100_remain_three_observed_groups(self):
        def request(effort, style, cap):
            level = format_parameters(style, effort).get("reasoning_effort")
            return observation({"none": 0, "minimal": 50, "low": 50, "medium": 75,
                                "high": 75, "xhigh": 75, "max": 100}.get(level, 75))
        result = detect_model(request)
        self.assertEqual(result["levels"]["levels"], ["none", "low", "high", "max"])
        self.assertEqual(result["levels"]["aliases"]["medium"], "high")
        self.assertEqual(result["format"]["requestCount"], 8)
        self.results["distinct-counts"] = result

    def test_wrong_off_is_rejected_and_truncation_is_insufficient(self):
        for truncated in (False, True):
            with self.subTest(truncated=truncated):
                def request(effort, style, cap):
                    params = format_parameters(style, effort)
                    if params.get("reasoning_effort") == "none":
                        value = observation(0, False)
                        value["finishReason"] = "length" if truncated else "stop"
                        return value
                    if "reasoning_effort" in params:
                        return observation(50)
                    if "enable_thinking" in params:
                        return observation(50 if params["enable_thinking"] else 0)
                    return observation(0)
                result = detect_model(request)
                self.assertEqual(result["format"]["format"], "qwen-switch")
                self.assertTrue(result["format"]["offVerified"])
                if truncated:
                    self.assertTrue(result["format"]["insufficientEvidence"])
                    self.assertFalse(result["format"]["degradingStyles"])
                else:
                    self.assertIn("off control", result["format"]["degradingStyles"][0]["reason"])

    def test_unobservable_fallback_retains_enum_or_accepted_efforts_without_repeating(self):
        for enum in (False, True):
            with self.subTest(enum=enum):
                calls = []
                supported = ["level1", "level3"] if enum else ["low", "high"]
                def request(effort, style, cap):
                    params = format_parameters(style, effort)
                    calls.append(params)
                    level = params.get("reasoning_effort")
                    nested_level = params.get("chat_template_kwargs", {}).get("reasoning_effort")
                    supplied = level if level is not None else nested_level
                    if supplied is not None and supplied not in supported:
                        suffix = " expected one of 'level1', 'level3'" if enum else " invalid"
                        raise ValueError("reasoning_effort" + suffix)
                    return observation(0)
                result = detect_model(request)
                self.assertEqual(result["levels"]["levels"], supported)
                self.assertEqual(result["levels"]["source"], "fallback")
                self.assertFalse(result["levels"]["verified"])
                self.assertEqual(len(calls), len({json.dumps(p, sort_keys=True) for p in calls}))
                self.assertLessEqual(len(calls), MAX_EFFECT_REQUESTS)

    def test_failed_baseline_has_no_invented_fallback_levels(self):
        class Unauthorized(Exception):
            status_code = 401
        calls = []
        def request(*args):
            calls.append(args)
            raise Unauthorized("unauthorized")
        result = detect_model(request)
        self.assertEqual(result["levels"]["state"], "failed")
        self.assertEqual(result["levels"]["levels"], [])
        self.assertEqual(len(calls), 1)

    def test_unobservable_nested_enum_retains_matching_wire_style(self):
        def request(effort, style, cap):
            params = format_parameters(style, effort)
            if "reasoning_effort" in params:
                raise ValueError("unsupported parameter reasoning_effort")
            nested = params.get("chat_template_kwargs", {})
            if "reasoning_effort" in nested and nested["reasoning_effort"] not in ("level1", "level3"):
                raise ValueError("reasoning_effort expected one of 'level1', 'level3'")
            return observation(0)
        result = detect_model(request)
        self.assertEqual(result["levels"]["levels"], ["level1", "level3"])
        self.assertEqual(result["format"]["format"], "chat-template")
        self.assertFalse(result["format"]["verified"])

    def test_native_protocol_marks_evidence_and_unobserved_menu_unverified(self):
        calls = []
        def request(effort, style, cap):
            calls.append((format_parameters(style, effort), cap))
            if effort == "__umeko_invalid_effort__":
                raise ValueError("reasoning_effort expected one of 'low', 'high'")
            return {"thinking": False, "content": True}
        result = detect_model(request, protocol="anthropic")
        for part in result.values():
            self.assertEqual(part["evidenceVersion"], 1)
            self.assertEqual(part["requestCount"], len(calls))
            self.assertTrue(part["evidence"])
        self.assertFalse(result["levels"]["verified"])
        self.assertFalse(result["format"]["verified"])
        self.assertEqual(result["levels"]["levels"], ["low", "high"])

    def test_native_grades_keep_separate_pure_off_when_none_is_rejected(self):
        calls = []
        def request(effort, style, cap):
            params = format_parameters(style, effort)
            calls.append(params)
            level = params.get("reasoning_effort")
            if level == "none":
                raise ValueError("reasoning_effort invalid")
            if level is not None:
                return observation({"minimal": 20, "low": 20, "medium": 50,
                                    "high": 50, "xhigh": 100, "max": 100}[level])
            if "enable_thinking" in params:
                return observation(50 if params["enable_thinking"] else 0)
            return observation(50)
        result = detect_model(request)
        self.assertEqual(result["format"]["format"], "openai-none")
        self.assertEqual(result["format"]["offFormat"], "qwen-switch")
        self.assertTrue(result["format"]["offVerified"])
        self.assertTrue(result["format"]["verified"])
        self.assertEqual(result["levels"]["levels"], ["low", "high", "max"])
        self.assertEqual(len(calls), 10)

    def test_zero_character_fallback_sorts_before_positive_token_groups(self):
        def request(effort, style, cap):
            level = format_parameters(style, effort).get("reasoning_effort")
            if level == "none":
                value = observation(0)
                value["reasoningTokens"] = None
                return value
            return observation({"minimal": 20, "low": 20, "medium": 50,
                "high": 50, "xhigh": 100, "max": 100}.get(level, 60))
        result = detect_model(request)
        self.assertEqual(result["levels"]["levels"], ["none", "low", "high", "max"])
        self.assertEqual(result["levels"]["evidence"][1]["metric"], "thinkingChars")
        self.assertEqual(result["format"]["onEffort"], "max")
        self.assertTrue(result["format"]["offVerified"])

    def test_nonmonotonic_native_amounts_do_not_verify_graded_levels(self):
        calls = []
        def request(effort, style, cap):
            params = format_parameters(style, effort)
            calls.append(params)
            level = params.get("reasoning_effort")
            if level == "none":
                value = observation(0)
                value["reasoningTokens"] = None
                return value
            return observation({"minimal": 67, "low": 67, "medium": 99,
                "high": 72, "xhigh": 72, "max": 59}.get(level, 57))
        result = detect_model(request)
        self.assertEqual(result["levels"]["levels"], ["none", "low", "medium", "high", "max"])
        self.assertFalse(result["levels"]["verified"])
        self.assertEqual(result["levels"]["levelStatus"], "non-monotonic")
        self.assertIn("unconfirmed", result["levels"]["uncertaintyReason"])
        self.assertTrue(result["format"]["verified"])
        self.assertTrue(result["format"]["offVerified"])
        self.assertEqual(result["format"]["format"], "openai-none")
        self.assertEqual(len(calls), 8)

    @classmethod
    def tearDownClass(cls):
        import os
        output = os.environ.get("UMEKO_FAKE_RESULTS")
        if output:
            Path(output).write_text(json.dumps(cls.results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
