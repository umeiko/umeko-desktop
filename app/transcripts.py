"""Read-only presentation of the active branch in Pi's native JSONL files.

Pi remains the sole owner of transcript writes, context assembly and branching.
"""
import json
from pathlib import Path


def tool_view(tool_id, name, arguments, cwd, result=None):
    path = arguments.get("path") or arguments.get("file_path") or arguments.get("filePath") or ""
    if not isinstance(path, str) or "://" in path:
        path = ""
    if path:
        value = Path(path).expanduser()
        path = str((value if value.is_absolute() else Path(cwd) / value).resolve())
    return {"id": tool_id, "name": name, "arguments": arguments, "path": path,
        "state": "running" if result is None else "error" if result.get("isError") else "done",
        "result": content_text(result.get("content", []))[:8192] if result else ""}


def content_text(content):
    return content if isinstance(content, str) else "\n".join(block.get("text", "") for block in content if block.get("type") == "text")


def content_thinking(content):
    return "\n".join(block.get("thinking", "") for block in content if block.get("type") == "thinking") if isinstance(content, list) else ""


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
    messages, tree = [], []
    results = {e["message"].get("toolCallId"): e["message"] for e in branch if e.get("type") == "message" and e.get("message", {}).get("role") == "toolResult"}
    for entry in reversed(branch):
        if entry.get("type") != "message":
            continue
        message = entry.get("message", {})
        content = message.get("content", "")
        text = content_text(content)
        thinking = content_thinking(content)
        text = text or message.get("errorMessage", "")
        role = message.get("role", "")
        tree.append({"id": entry["id"], "role": role, "text": text[:80]})
        calls = [block for block in content if isinstance(block, dict) and block.get("type") == "toolCall"] if isinstance(content, list) else []
        if role in ("user", "assistant") and (text or thinking or calls):
            row = {"role": role, "text": text, "error": bool(message.get("errorMessage")), "entryId": entry["id"]}
            if thinking:
                row["thinking"] = thinking
            if calls:
                row["tools"] = [tool_view(call["id"], call["name"], call.get("arguments", {}), cwd, results.get(call["id"])) for call in calls]
                for tool in row["tools"]:
                    if tool["id"] not in results: tool["state"] = "interrupted"
            messages.append(row)
    return messages, tree
