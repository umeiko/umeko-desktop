"""Read-only presentation of the active branch in Pi's native JSONL files.

Pi remains the sole owner of transcript writes, context assembly and branching.
"""
import json
import math
from pathlib import Path
from uuid import UUID
from .chatbox import result_media


def tool_view(tool_id, name, arguments, cwd, result=None):
    path = arguments.get("path") or arguments.get("file_path") or arguments.get("filePath") or ""
    if not isinstance(path, str) or "://" in path:
        path = ""
    if path:
        value = Path(path).expanduser()
        path = str((value if value.is_absolute() else Path(cwd) / value).resolve())
    row = {"id": tool_id, "name": name, "arguments": arguments, "path": path,
        "state": "running" if result is None else "error" if result.get("isError") else "done",
        "result": content_text(result.get("content", []))[:8192] if result else ""}
    media = result_media(name, result)
    if media: row["media"] = media
    return row


def content_text(content):
    return content if isinstance(content, str) else "\n".join(block.get("text", "") for block in content if block.get("type") == "text")


def content_thinking(content):
    return "\n".join(block.get("thinking", "") for block in content if block.get("type") == "thinking") if isinstance(content, list) else ""


def compaction_view(entry):
    """Read legacy receipts and typed transitions without changing native data."""
    if entry.get("type") != "custom" or entry.get("customType") != "umeko-compaction":
        return None
    details = entry.get("data")
    if not isinstance(details, dict):
        return None
    before, after = details.get("before"), details.get("after")
    if details.get("version") == 1:
        if any(type(number) is not int or number < 0 for number in (before, after)):
            return None
        text = f"已压缩：{before} → {after} tokens"
    elif details.get("version") == 2:
        event_id = details.get("eventId")
        try:
            if not isinstance(event_id, str):
                return None
            UUID(event_id)
        except (ValueError, AttributeError):
            return None
        if (details.get("state") not in ("running", "success", "failure")
                or details.get("mode") not in ("manual", "auto")
                or details.get("afterEstimated") is not True
                or any(number is not None and (type(number) not in (int, float)
                       or not math.isfinite(number) or number < 0) for number in (before, after))
                or not isinstance(details.get("summary"), str)
                or not isinstance(details.get("error"), str)):
            return None
        text = ""
    else:
        return None
    return {"role": "assistant", "text": text, "error": False,
            "customType": "umeko-compaction", "compaction": dict(details),
            "entryId": entry["id"], "timestamp": entry.get("timestamp")}


def compaction_status(row, active_compactions=()):
    """Resolve unfinished history against this session's live event identities.

    None preserves native states for the shared disposable index/cache. Returned
    history failures are copies, so a live snapshot can read the same raw row.
    """
    if row is None or active_compactions is None:
        return row
    details = row.get("compaction")
    if (row.get("customType") != "umeko-compaction" or not isinstance(details, dict)
            or details.get("version") != 2 or details.get("state") != "running"
            or details.get("eventId") in active_compactions):
        return row
    return {**row, "compaction": {**details, "state": "failure", "error": "Compaction interrupted"}}


def preview(file):
    entries = []
    cwd = str(Path(file).parent)
    with Path(file).open(encoding="utf-8") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except ValueError:
                continue  # A concurrently written final line may be incomplete.
            if entry.get("type") == "session":
                cwd = entry.get("cwd") or cwd
            elif entry.get("id"):
                entries.append(entry)
    index = {entry["id"]: entry for entry in entries}
    branch, visited = [], set()
    current = entries[-1] if entries else None
    while current and current["id"] not in visited:
        visited.add(current["id"])
        branch.append(current)
        current = index.get(current.get("parentId"))
    return present(list(reversed(branch)), cwd)


def present(entries, cwd, active_compactions=()):
    """Project an already ordered branch or a bounded group and its tool results."""
    messages, tree = [], []
    call_rows, subagents, compactions = {}, [], {}
    previous_assistant = None
    omissions = {e['targetId'] for e in entries if e.get('type') == 'context_edit' and e.get('replacement') is None}
    results = {e["message"].get("toolCallId"): e["message"] for e in entries if e.get("type") == "message" and e.get("message", {}).get("role") == "toolResult"}
    deliveries = [e["data"] for e in entries if e.get("type") == "custom" and e.get("customType") == "umeko-chatbox" and isinstance(e.get("data"), dict) and e["data"].get("version") == 1 and isinstance(e["data"].get("toolCallId"), str) and isinstance(e["data"].get("items"), list)]
    for entry in entries:
        receipt = compaction_view(entry)
        if receipt:
            details = receipt["compaction"]
            if details.get("version") == 2:
                previous = compactions.get(details["eventId"])
                if previous is not None:
                    previous["compaction"] = details
                    continue
                compactions[details["eventId"]] = receipt
            messages.append(receipt)
            continue
        if entry.get("type") != "message":
            data = entry.get("data")
            if entry.get("type") == "custom" and entry.get("customType") == "umeko-subagent" and isinstance(data, dict) and data.get("version") == 1:
                tool = data.get("tool")
                if isinstance(tool, dict) and tool.get("name") == "subagent" and isinstance(tool.get("id"), str) and isinstance(tool.get("subagent"), dict):
                    subagents.append((data, previous_assistant))
            continue
        message = entry.get("message", {})
        if entry['id'] in omissions and message.get('role') == 'assistant' and message.get('stopReason') == 'error':
            continue
        content = message.get("content", "")
        text = content_text(content)
        thinking = content_thinking(content)
        text = text or ("" if message.get("stopReason") == "aborted" else message.get("errorMessage", ""))
        role = message.get("role", "")
        tree.append({"id": entry["id"], "role": role, "text": text[:80]})
        calls = [block for block in content if isinstance(block, dict) and block.get("type") == "toolCall"] if isinstance(content, list) else []
        if role in ("user", "assistant") and (text or thinking or calls):
            row = {"role": role, "text": text, "error": message.get("stopReason") != "aborted" and bool(message.get("errorMessage")), "entryId": entry["id"], "timestamp": message.get("timestamp") or entry.get("timestamp")}
            if role == "assistant":
                row["stopReason"] = message.get("stopReason", "")
            if thinking:
                row["thinking"] = thinking
            if calls:
                row["tools"] = []
                for call in calls:
                    call_rows[call["id"]] = row
                    tool = tool_view(call["id"], call["name"], call.get("arguments", {}), cwd, results.get(call["id"]))
                    if tool["id"] not in results: tool["state"] = "interrupted"
                    row["tools"].append(tool)
                    row["tools"].extend({"id":item["toolCallId"], "name":"submit_to_chatbox", "arguments":{}, "path":"", "state":"done", "result":"已提交到聊天框", "media":item["items"][:12]} for item in deliveries if item["toolCallId"].startswith(call["id"] + "/"))
            messages.append(row)
            if role == "assistant":
                previous_assistant = row
    # Pi persists snapshots separately from assistant messages. A continuation
    # updates the original child's row even when it was launched in a later turn.
    children = {}
    launches = {e['data']['toolCallId'] for e in entries if e.get('type') == 'custom' and
        e.get('customType') == 'umeko-subagent-link' and isinstance(e.get('data'), dict) and
        e['data'].get('version') == 1 and isinstance(e['data'].get('toolCallId'), str)}
    for data, fallback in subagents:
        snapshot = data["tool"]
        call_id = data.get("toolCallId")
        owner = call_rows.get(call_id) if isinstance(call_id, str) else None
        owner = owner if owner is not None else fallback
        child = children.get(snapshot["id"])
        if child is None:
            if owner is None:
                continue
            child = {}
            children[snapshot["id"]] = child
            tools = owner.setdefault("tools", [])
            position = next((i for i, tool in enumerate(tools) if tool["id"] == call_id), len(tools))
            tools.insert(position, child)
        child.update(snapshot)
        child["arguments"] = dict(snapshot.get("arguments") or {})
        child["subagent"] = dict(snapshot["subagent"])
        child.setdefault("path", "")
        if isinstance(call_id, str):
            launches.add(call_id)
    for row in messages:
        if "tools" in row:
            row["tools"] = [tool for tool in row["tools"] if not (tool.get("name") == "subagent" and tool["id"] in launches and tool["id"] not in children)]
    return [compaction_status(row, active_compactions) for row in messages], tree
