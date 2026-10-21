"""Stable message rows: streaming updates never reset the conversation list."""
import copy
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from .message_attachments import split_attachments
from .chatbox import media_view


class ChatModel(QAbstractListModel):
    MessageRole = Qt.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []

    def roleNames(self):
        return {self.MessageRole: b"modelData"}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.DisplayRole):
        if index.isValid() and role == self.MessageRole and index.row() < len(self.rows):
            return self.rows[index.row()]

    def update(self, messages):
        messages = self.project(messages)
        common = min(len(messages), len(self.rows))
        for row in range(common):
            if self.rows[row] != messages[row]:
                self.rows[row] = copy.deepcopy(messages[row])
                self.dataChanged.emit(self.index(row), self.index(row), [self.MessageRole])
        if len(messages) > len(self.rows):
            self.beginInsertRows(QModelIndex(), len(self.rows), len(messages) - 1)
            self.rows.extend(copy.deepcopy(messages[len(self.rows):]))
            self.endInsertRows()
        elif len(messages) < len(self.rows):
            self.beginRemoveRows(QModelIndex(), len(messages), len(self.rows) - 1)
            del self.rows[len(messages):]
            self.endRemoveRows()

    @staticmethod
    def project(messages):
        """Keep ordered process steps under one assistant, leaving Pi's log intact."""
        rows = []
        for message in messages:
            current = dict(message)
            if current.get("role") == "user":
                current["text"], attachments = split_attachments(current.get("text", ""))
                if attachments:
                    current["attachments"] = attachments
            if current.get("role") == "assistant":
                steps = []
                if current.get("thinking"):
                    steps.append({"kind": "thinking", "text": current["thinking"]})
                if current.get("text"):
                    steps.append({"kind": "text", "text": current["text"], "error": current.get("error", False)})
                if current.get("tools"):
                    current["tools"] = [dict(tool) for tool in current["tools"]]
                    batch = []
                    for tool in current["tools"]:
                        batch.append(tool)
                        if tool.get("name") == "submit_to_chatbox" and tool.get("media"):
                            steps.append({"kind": "tools", "tools": batch})
                            steps.append({"kind": "media", "items": media_view(tool["media"]), "toolId": tool["id"]})
                            batch = []
                    if batch: steps.append({"kind": "tools", "tools": batch})
                current["activity"] = steps
            if (rows and current.get("role") == rows[-1].get("role") == "assistant"
                    and (rows[-1].get("tools") or current.get("tools"))):
                group = rows[-1]
                steps = current["activity"]
                # Adjacent operations with no intervening prose share a batch.
                if group["activity"] and steps and group["activity"][-1]["kind"] == steps[0]["kind"] == "tools":
                    group["activity"][-1]["tools"] = group["activity"][-1]["tools"] + steps[0]["tools"]
                    steps = steps[1:]
                group["activity"].extend(steps)
                group["tools"] = group.get("tools", []) + current.get("tools", [])
                group["text"] = current.get("text", "")
                group["error"] = group.get("error", False) or current.get("error", False)
                if current.get("timestamp"): group["timestamp"] = current["timestamp"]
            else:
                rows.append(current)
        for row in rows:
            for index, step in enumerate(row.get("activity", [])):
                step["blockOffset"] = index * 10000
        return rows
