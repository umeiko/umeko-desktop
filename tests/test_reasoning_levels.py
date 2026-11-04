import unittest

from app.reasoning_levels import (
    EFFORT_CANDIDATES, OPENROUTER_EFFORTS, allowed_levels, clamp_effort,
    detect_levels, effort_options, is_effort_rejection, metadata_levels,
    normalize_levels, normalize_reasoning,
)


class ReasoningConfigurationTests(unittest.TestCase):
    def test_old_configs_default_unknown_without_model_name_guesses(self):
        self.assertEqual(normalize_reasoning({"upstream": "gpt-5"}), {
            "reasoningLevels": [], "reasoningLevelsAuto": True,
            "reasoningDetection": {"state": "unknown", "levels": []},
        })

    def test_manual_order_and_cache_survive_an_old_editor(self):
        manual = normalize_reasoning({"reasoningLevels": ["high", "off", "low", "high"],
            "reasoningDetection": {"state": "known", "source": "probe", "levels": ["medium"]}})
        self.assertFalse(manual["reasoningLevelsAuto"])
        self.assertEqual(manual["reasoningLevels"], ["high", "low"])
        self.assertEqual(normalize_reasoning({"alias": "edited"}, manual), manual)
        automatic = normalize_reasoning({"reasoningLevelsAuto": True}, manual)
        self.assertTrue(automatic["reasoningLevelsAuto"])
        self.assertEqual(automatic["reasoningDetection"], manual["reasoningDetection"])

    def test_partial_cache_updates_preserve_levels_on_failure(self):
        old = {"reasoningLevels": ["low", "high"], "reasoningLevelsAuto": True,
               "reasoningDetection": {"state": "known", "levels": ["low", "high"]}}
        result = normalize_reasoning({"reasoningDetection": {
            "state": "failed", "levels": [], "error": "network timeout"}}, old)
        self.assertEqual(result["reasoningLevels"], ["low", "high"])
        result = normalize_reasoning({"reasoningDetection": {
            "state": "known", "levels": ["medium"]}}, old)
        self.assertEqual(result["reasoningLevels"], ["medium"])

    def test_probing_is_preserved_for_live_normalization(self):
        self.assertEqual(normalize_reasoning({"reasoningDetection": {
            "state": "probing", "levels": []}})["reasoningDetection"]["state"], "probing")

    def test_rejected_efforts_survive_normalization_and_older_editor(self):
        saved = normalize_reasoning({"reasoningLevels": ["low"], "reasoningLevelsAuto": True,
            "reasoningDetection": {"state": "known", "levels": ["low"],
                                   "rejected": ["high", "high", "xhigh"]}})
        self.assertEqual(saved["reasoningDetection"]["rejected"], ["high", "xhigh"])
        self.assertEqual(normalize_reasoning({"alias": "edited"}, saved), saved)
        for invalid in ("high", [None], [""]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                normalize_reasoning({"reasoningDetection": {"state": "known", "rejected": invalid}})

    def test_validation_and_off_separation(self):
        for raw in ("low", None, [1], [""], ["a\n"]):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                normalize_levels(raw)
        with self.assertRaises(ValueError):
            normalize_reasoning({"reasoningLevelsAuto": "false"})
        self.assertEqual(effort_options(["none", "low"]), [
            {"value": "off", "label": "关闭"}, {"value": "none", "label": "none"},
            {"value": "low", "label": "low"}])

    def test_clamping_keeps_raw_supported_values_and_prefers_lower_tie(self):
        self.assertEqual(clamp_effort("medium", ["high", "low"]), "low")
        self.assertEqual(clamp_effort("xhigh", ["low", "high"]), "high")
        self.assertEqual(clamp_effort("ultra", ["max"]), "max")
        self.assertEqual(clamp_effort("vendor-custom", ["vendor-custom"]), "vendor-custom")
        self.assertEqual(clamp_effort("off", ["low"]), "off")
        self.assertEqual(clamp_effort("high", []), "off")


class ReasoningMetadataTests(unittest.TestCase):
    def test_deepseek_does_not_infer_support_from_undocumented_supported_flag(self):
        self.assertIsNone(metadata_levels({"effort": {"supported": False}}))
        self.assertEqual(metadata_levels({"effort": {"supported": False, "supported_levels": ["high", "low"]}}),
                         ["low", "high"])

    def test_only_explicit_supported_fields_are_used(self):
        self.assertEqual(metadata_levels({"capabilities": {"effort": {
            "supported": True, "high": {"supported": True}, "low": {"supported": True},
            "medium": {"supported": False}}}}), ["low", "high"])
        self.assertEqual(metadata_levels({"capabilities": {"effort": {"supported": False}}}), [])
        self.assertEqual(metadata_levels({"effort": {"supported_levels": ["max", "low", "high"]}}),
                         ["low", "high", "max"])
        self.assertEqual(metadata_levels({"reasoning": {"supported_efforts": ["high", "none", "low"]}}),
                         ["none", "low", "high"])
        self.assertEqual(metadata_levels({"reasoning": {"supported_efforts": None}}), list(OPENROUTER_EFFORTS))
        self.assertEqual(metadata_levels({"reasoningLevels": ["custom", "high", "low"]}),
                         ["low", "high", "custom"])
        for row in ({"reasoning": True}, {"reasoning": {}}, {"supported_parameters": ["reasoning"]},
                    {"id": "reasoning-super-max"}, {"reasoning": {"supported_efforts": "high"}},
                    {"capabilities": {"effort": {"high": {}}}}):
            with self.subTest(row=row):
                self.assertIsNone(metadata_levels(row))


class ReasoningProbeTests(unittest.TestCase):
    def test_structured_enum_is_effort_scoped(self):
        error = {"error": {"param": "reasoning_effort", "message": "invalid enum value",
                           "allowed": ["high", "low", "off"]}}
        self.assertEqual(allowed_levels(error), ["low", "high"])
        self.assertIsNone(allowed_levels({"error": {"message": "invalid reasoning_effort",
                                                   "field": "mode", "allowed": ["chat", "text"]}}))
        self.assertEqual(allowed_levels('{"error":{"param":"reasoning_effort",'
            '"message":"invalid value","enum":["medium","low"]}}'), ["low", "medium"])
        self.assertEqual(allowed_levels({"type": "error", "error": {"param": "reasoning_effort",
            "message": "Unsupported value for reasoning_effort: 'xhigh'. Supported values are: 'low', 'high'."}}),
            ["low", "high"])
        self.assertEqual(allowed_levels({"detail": [{"type": "literal_error",
            "loc": ["body", "reasoning_effort"], "msg": "Input should be 'low' or 'high'"}]}),
            ["low", "high"])

    def test_common_quoted_enum_errors(self):
        for error in ("Invalid reasoning_effort. Supported values are: 'low', 'medium', 'high'.",
                      "reasoning_effort: Input should be 'low', 'medium' or 'high'",
                      "Invalid effort: expected one of ['low', 'medium', 'high']"):
            with self.subTest(error=error):
                self.assertEqual(allowed_levels(error), ["low", "medium", "high"])
        self.assertIsNone(allowed_levels("Invalid reasoning_effort value 'anything'"))

    def test_enum_short_circuit_uses_one_request(self):
        calls = []
        def request(effort):
            calls.append(effort)
            raise ValueError("Invalid reasoning_effort; allowed values: 'high', 'low'")
        self.assertEqual(detect_levels(request), {"state": "known", "source": "probe", "levels": ["low", "high"]})
        self.assertEqual(calls, ["__umeko_invalid_effort__"])

    def test_candidate_fallback_checks_the_complete_documented_vocabulary(self):
        calls = []
        def request(effort):
            calls.append(effort)
            if effort not in ("low", "high", "ultra"):
                raise ValueError("Invalid reasoning_effort value")
        self.assertEqual(detect_levels(request), {"state": "known", "source": "probe",
                                                 "levels": ["low", "high", "ultra"]})
        self.assertEqual(calls, ["__umeko_invalid_effort__", *EFFORT_CANDIDATES])

    def test_explicit_no_parameter_requires_successful_baseline(self):
        calls = []
        def request(effort):
            calls.append(effort)
            if effort is not None:
                raise ValueError("Unsupported parameter: reasoning_effort")
        self.assertEqual(detect_levels(request), {"state": "known", "source": "probe", "levels": [], "noParameter": True})
        self.assertEqual(calls, ["__umeko_invalid_effort__", None])
        def failed_baseline(effort):
            if effort is not None:
                raise ValueError("Unsupported parameter: reasoning_effort")
            raise ValueError("authentication failed")
        self.assertEqual(detect_levels(failed_baseline)["state"], "failed")

    def test_accepted_invalid_value_is_reported_as_weak_acceptance_evidence(self):
        result = detect_levels(lambda effort: None)
        self.assertEqual(result["levels"], list(EFFORT_CANDIDATES))
        self.assertTrue(result["invalidAccepted"])

    def test_all_candidates_rejected_require_a_successful_baseline(self):
        for baseline_succeeds in (True, False):
            with self.subTest(baseline_succeeds=baseline_succeeds):
                calls = []
                def request(effort):
                    calls.append(effort)
                    if effort is not None:
                        raise ValueError("Invalid reasoning_effort value")
                    if not baseline_succeeds:
                        raise ValueError("authentication failed")
                result = detect_levels(request)
                self.assertEqual(calls, ["__umeko_invalid_effort__", *EFFORT_CANDIDATES, None])
                self.assertEqual(result["levels"], [])
                self.assertEqual(result["state"], "known" if baseline_succeeds else "failed")
                if baseline_succeeds:
                    self.assertTrue(result["noParameter"])
                else:
                    self.assertNotIn("noParameter", result)

    def test_unrelated_failures_never_prove_unsupported_effort(self):
        for message in ("Invalid API key for reasoning_effort request", "reasoning_effort rate limit exceeded",
                        "reasoning_effort timeout", "Invalid max_tokens cap during reasoning_effort probe",
                        "Internal server error", "Invalid effort: network connection failed"):
            with self.subTest(message=message):
                calls = []
                def request(effort):
                    calls.append(effort)
                    raise ValueError(message)
                self.assertFalse(is_effort_rejection(message))
                self.assertEqual(detect_levels(request)["state"], "failed")
                self.assertEqual(len(calls), 1)

    def test_failure_mid_probe_keeps_confirmed_acceptance_but_not_known_state(self):
        def request(effort):
            if effort == "minimal":
                raise ValueError("timeout")
            if effort != "none":
                raise ValueError("Invalid reasoning_effort value")
        result = detect_levels(request)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["levels"], ["none"])


if __name__ == "__main__":
    unittest.main()
