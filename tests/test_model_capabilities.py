import unittest

from app.model_capabilities import normalize_model, normalize_vision, vision_suggestion


class VisionTests(unittest.TestCase):
    def test_recognizes_image_models_without_enabling_every_chat_model(self):
        for name in ("kimi k3", "k3-256", "k3-256k", "kimi-k2.5", "kimi-for-coding-highspeed",
                     "gpt-4o-mini", "gpt-4.1", "gpt-5.4-mini", "claude-3-5-sonnet", "claude-sonnet-4-6",
                     "gemini-2.5-flash", "qwen3-vl-plus", "qwen3.5-plus", "Qwen/Qwen2.5-VL-72B-Instruct",
                     "deepseek-flash", "deepseek-v4-flash-vision-exp", "zai-org/GLM-4.6V", "glm-5.3-flash"):
            with self.subTest(name=name):
                self.assertEqual(vision_suggestion(name), {"vision": True, "matched": True})
        for name in ("deepseek-v4-flash", "deepseek-reasoner", "qwen3-coder-plus", "kimi-k2", "gpt-4o-mini-tts", "glm-4.7", "glm-5.3"):
            with self.subTest(name=name):
                self.assertEqual(vision_suggestion(name), {"vision": False, "matched": True})
        for name in ("", "default", "k30", "k3-2560", "private-gateway", "my-gpt-4.11"):
            self.assertEqual(vision_suggestion(name), {"vision": False, "matched": False})

    def test_manual_choice_wins_over_model_names_and_survives_old_editor(self):
        model = {"upstream": "k3", "alias": "text-only"}
        self.assertEqual(normalize_vision(model), {"vision": True, "visionAuto": True})
        manual = {**model, "vision": False, "visionAuto": False}
        self.assertEqual(normalize_vision({"upstream": "gpt-4o"}, manual), {"vision": False, "visionAuto": False})
        self.assertEqual(normalize_vision({"upstream": "gpt-4o", "visionAuto": True}, manual), {"vision": True, "visionAuto": True})
        self.assertTrue(normalize_vision({"upstream": "private", "vision": True})["vision"])
        combined = normalize_model({**model, "contextWindow": "256K", "contextWindowAuto": False, "vision": False})
        self.assertEqual(combined, {"contextWindow": 262144, "contextWindowAuto": False, "vision": False, "visionAuto": False})
        for bad in ({"vision": "false"}, {"visionAuto": "false"}, {"visionAuto": False}):
            with self.assertRaises(ValueError):
                normalize_vision({"upstream": "k3", **bad})
