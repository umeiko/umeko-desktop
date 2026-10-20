"""Small offline image-input defaults; explicit per-model choices always win."""
import re

from .model_context import normalize_context


def vision_suggestion(model_name: str) -> dict:
    name = re.sub(r"[\s_/:]+", "-", str(model_name).strip().lower())
    # Specialized audio / embedding endpoints do not use this chat image path.
    if re.search(r"(?:^|-)(?:embedding\w*|rerank\w*|tts|transcribe\w*|whisper|audio|realtime)(?=$|-)", name):
        return {"vision": False, "matched": True}
    positive = (
        r"(?:^|-)(?:vision|vl\d*|internvl\d*|llava)(?=$|-)",
        r"(?:^|-)k3(?:-256k?)?(?=$|-(?!\d))",
        r"(?:^|-)kimi-(?:k2\.[578]|for-coding(?:-highspeed)?)(?=$|-)",
        r"(?:^|-)gpt-(?:4o|4\.1|4-turbo|4-vision|5(?:\.\d+)?)(?=$|-)",
        r"(?:^|-)claude-(?:(?:3|4|5)(?:-|$)|(?:sonnet|opus|haiku)-(?:3|4|5)(?:-|$))",
        r"(?:^|-)gemini-(?:1\.5|2(?:\.\d+)?|3(?:\.\d+)?)(?=$|-)",
        r"(?:^|-)qwen3\.[5678](?=$|-)",
        r"(?:^|-)glm-4(?:\.\d+)?v(?=$|-)",
        r"(?:^|-)glm-5\.3-flash(?=$|-)",
        r"(?:^|-)deepseek-flash(?=$|-)",
    )
    if any(re.search(pattern, name) for pattern in positive):
        return {"vision": True, "matched": True}
    negative = (
        r"(?:^|-)deepseek-(?:chat|reasoner|coder|r1|v[34](?:\.\d+)?)(?=$|-)",
        r"(?:^|-)qwen(?:2(?:\.5)?|3)?-(?:coder|instruct|plus|turbo|max)(?=$|-)",
        r"(?:^|-)kimi-k2(?=$|-)",
        r"(?:^|-)gpt-(?:3\.5|4)(?=$|-)",
        r"(?:^|-)glm-(?:4|5)(?:\.\d+)?(?=$|-)",
    )
    return {"vision": False, "matched": any(re.search(pattern, name) for pattern in negative)}


def normalize_vision(model: dict, previous: dict | None = None) -> dict:
    source = model if "vision" in model or "visionAuto" in model else previous or model
    automatic = source.get("visionAuto", "vision" not in source)
    if not isinstance(automatic, bool):
        raise ValueError("视觉的自动设置必须为 true 或 false")
    vision = vision_suggestion(model.get("upstream", ""))["vision"] if automatic else source.get("vision")
    if not isinstance(vision, bool):
        raise ValueError("视觉能力必须为 true 或 false")
    return {"vision": vision, "visionAuto": automatic}


def normalize_model(model: dict, previous: dict | None = None) -> dict:
    return {**normalize_context(model, previous), **normalize_vision(model, previous)}
