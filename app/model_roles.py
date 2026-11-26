"""Model role selections shared by the desktop and the Agent Bus."""

from .model_groups import GROUP_MODEL, GROUP_PROVIDER

SESSION_ROLES = ("planningModel", "executionModel", "coordinatorModel", "memberDefaultModel")


def model_choices(gateway):
    rows = [dict(row, label=row["id"], group=False) for row in gateway.models()]
    group = getattr(gateway, "model_group_descriptor", lambda: None)()
    if group is not None:
        rows.append(dict(group, providerID=GROUP_PROVIDER, owned_by="", label="Model group", group=True))
    return rows


def select_route(gateway, alias):
    # Match the exact routes offered by the host, including the virtual group.
    route = next((row for row in model_choices(gateway) if row["id"] == alias), None)
    if route is None:
        raise ValueError("请选择已配置的模型或已启用的模型组")
    return route


def member_model(explicit, default, caller_model, selected_model):
    if explicit:
        return explicit
    if caller_model == GROUP_MODEL:
        return GROUP_MODEL
    return default or caller_model or selected_model


def session_model_roles(record, data):
    meta = data.get("sessionMeta", {}).get(record.id, {})
    raw = meta.get("modelRoles", getattr(record, "draft_model_roles", {}))
    if not isinstance(raw, dict):
        return {}
    return {role: raw[role] for role in SESSION_ROLES if isinstance(raw.get(role), str) and raw[role]}
