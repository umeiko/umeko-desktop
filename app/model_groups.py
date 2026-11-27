"""The private Pi model group and its configured provider/model pairs."""

from .model_capabilities import normalize_model
from .model_reasoning import reasoning_levels, reconcile_effort

GROUP_PROVIDER = "@umeko-model-group"
# Physical model aliases cannot contain whitespace.
GROUP_MODEL = "@umeko/model group"
GROUP_SELECTION = (GROUP_PROVIDER, GROUP_MODEL)
MAX_MEMBERS = 16


def member_key(row):
    return row.get("provider"), row.get("model")


def configured_members(data, *, internal_ready=True):
    """Resolve members in priority order, retaining stale rows for settings."""
    group = data.get("modelGroup", {})
    providers = {p["id"]: p for p in data["providers"]
                 if p["api"] not in ("image", "speech", "video") and (p["api"] != "internal" or internal_ready)}
    for member in group.get("members", [])[:MAX_MEMBERS]:
        provider, alias = member_key(member)
        account = providers.get(provider)
        model = next((m for m in account["models"] if m["alias"] == alias), None) if account else None
        yield member, account, model


def descriptor(data, *, internal_ready=True):
    if not data.get("modelGroup", {}).get("enabled"):
        return None
    resolved = [(provider, normalize_model(model)) for _, provider, model in configured_members(data, internal_ready=internal_ready) if model]
    if not resolved:
        return None
    retries = []
    for provider, _ in resolved:
        raw = (provider or {}).get("streamMaxRetries")
        retries.append(int(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) and 0 <= raw <= 100 else 5)
    return {"id": GROUP_MODEL, "contextWindow": min(row["contextWindow"] for _, row in resolved),
            "input": ["text", "image"] if any(row["vision"] for _, row in resolved) else ["text"],
            "streamMaxRetries": max(retries, default=5)}


def settings(data, *, internal_ready=True):
    enabled = data.get("modelGroup", {}).get("enabled", False)
    members = []
    for member, provider, model in configured_members(data, internal_ready=internal_ready):
        row = {**member, "available": bool(model)}
        if model:
            row.update(providerName=provider["name"], levels=reasoning_levels(model))
            row["effort"] = reconcile_effort(row.get("effort", "off"), row["levels"])
        members.append(row)
    choices = [{"provider": provider["id"], "providerName": provider["name"],
                "model": model["alias"], "levels": reasoning_levels(model)}
               for provider in data["providers"]
               if provider["api"] not in ("image", "speech", "video") and (provider["api"] != "internal" or internal_ready)
               for model in provider["models"]]
    return {"enabled": enabled, "ready": enabled and any(row["available"] for row in members),
            "members": members, "choices": choices, "limit": MAX_MEMBERS}
