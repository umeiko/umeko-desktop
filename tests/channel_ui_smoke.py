"""Channel acceptance with real Qt and native Pi, using only synthetic local data."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BOARD_A = "核对季度报告：检索数据口径，整理交付清单"
BOARD_B = "核对独立采购记录：形成单独结论"
DELEGATION = {
    BOARD_A: "请分别核对统计口径、整理交付清单，完成后把文件交回来。",
    BOARD_B: "请检查本次采购记录，把结论整理成文件。",
}
TASKS = (
    ("核对统计口径", "统计口径.md", "统计口径执行已完成"),
    ("整理交付清单", "交付清单.md", "交付清单执行已完成"),
    ("核对采购口径", "采购口径.md", "采购口径执行已完成"),
)
COORDINATOR = "季度报告协调员"
PRIVATE = "请问：刚才的统计口径使用哪类样本？这条问题只限私聊。"
QUESTION_REPLY = "使用本季度的有效样本，明细仅在本对话中说明。"
ASSIGNMENT = "能否现在直接把分母定义补进统计口径文档？"
AMBIGUOUS = "那就按刚才的说法改吧，先别告诉任何人。"
FORGED = "仅供安全回归：这个模型输出将自己附加无权的路由字段。"
DUPLICATE_FIELDS = "仅供安全回归：这个模型返回了重名字段。"
UNAVAILABLE = "仅供安全回归：这个判定会遇到网关错误。"
INTENT_TIMEOUT = "仅供超时回归：这个判定等待本地网关，不执行任务。"
SHARE_SUMMARY = "修改已有交付内容。"
HELD_TASK = "独立退出测试：执行尚未收尾，不得重新派发。"
HELD_SUMMARY = "补充记录的退出验收。"
PRIVATE_REPLY = "已补充分母定义。仅在这条单独对话里确认。"
TASK_SYNC_PROBE = "核对这次任务返工同步。"
UNRELATED_SYNC_PROBE = "请回答一个无关的问题，不开展新任务。"
REWORK_CONTENT = "# 统计口径\n\n分母：当前季度的全部合格样本。\n"
sys.path.insert(0, str(ROOT))


class LocalScript:
    """The gateway calls this script instead of any model service."""

    ready = True

    def __init__(self):
        self.recovery = False
        self.rework_streams = 0
        self.calls = []
        self.target = ""
        self.sync_id = ""
        self.scope_observations = {}
        self.hold_marker = None
        self.classifications = []
        self.task_started = Event()
        self.task_release = Event()
        self.task_release.set()

    def complete(self, model, messages, tools, max_tokens):
        from app.integration import Completion

        def text(message):
            content = message.get("content") or ""
            return content if isinstance(content, str) else "\n".join(
                row.get("text", "") for row in content if row.get("type") == "text")

        def tool(identifier, name, **arguments):
            return Completion(tool_calls=[{"id": identifier, "name": name, "arguments": arguments}])

        last = messages[-1]
        content = text(last)
        self.calls.append((last["role"], content))
        if messages[0].get("role") == "system" and "Umeko Channel intent gate" in text(messages[0]):
            assert len(messages) == 2 and not tools, (messages, tools)
            value = json.loads(content)
            assert set(value) == {"newUserMessage"}
            current = value["newUserMessage"]
            self.classifications.append(current)
            if current == PRIVATE:
                return Completion('{"intent":"question","confidence":"clear","action":"none"}')
            if current in {ASSIGNMENT, HELD_TASK}:
                return Completion('{"intent":"task","confidence":"clear","action":"revise"}')
            if current == FORGED:
                return Completion(json.dumps({"intent":"task","confidence":"clear","action":"revise",
                    "summary":current,"coordinatorId":"agent:not-yours","childSessionId":"not-yours"}))
            if current == DUPLICATE_FIELDS:
                return Completion('{"intent":"question","intent":"task","confidence":"clear","action":"revise"}')
            if current == INTENT_TIMEOUT:
                # Keep the real localhost response pending past the production
                # AbortSignal.timeout(12000); do not replace its clock or fetch.
                sleep(14)
                return Completion('{"intent":"task","confidence":"clear","action":"revise"}')
            if current == UNAVAILABLE:
                raise RuntimeError("fixture classifier unavailable")
            return Completion('{"intent":"clarify","confidence":"uncertain","action":"none"}')
        if content in {TASK_SYNC_PROBE, UNRELATED_SYNC_PROBE}:
            self.scope_observations[content] = self.sync_id in json.dumps(messages, ensure_ascii=False)
            return Completion("已核对当前会话范围。")
        if last["role"] == "tool":
            identifier = last.get("tool_call_id", "")
            if identifier == "private-denied-path":
                assert "within its workspace" in content, content
                return tool("private-rework-write", "write", path=TASKS[0][1], content=REWORK_CONTENT)
            if identifier == "private-rework-write":
                assert "Successfully wrote" in content or "写入" in content, content
                return Completion(PRIVATE_REPLY)
            if identifier.startswith("write-channel-"):
                index = int(identifier.rsplit("-", 1)[-1])
                assert "Successfully wrote" in content or "写入" in content, content
                return Completion(TASKS[index][2])
            if identifier == "child-channel-0":
                return self.child_tool(tool, 1)
            if identifier in {"child-channel-1", "child-channel-2"}:
                request = next(
                    (match[1] for row in reversed(messages)
                     if (match := re.search(r"requestId=([a-f0-9]{32})", text(row)))),
                    None,
                )
                assert request, messages[-4:]
                return tool(f"reply-channel-{request}", "umeko_desktop", operation="agent_bus.reply",
                            arguments={"requestId": request, "status": "completed", "result": "子任务已完成并交接。"})
            return Completion("报告已记录。")

        if content == HELD_TASK and self.hold_marker is not None:
            self.hold_marker.write_text("native model entered", encoding="utf-8")
            Event().wait(90)
            return Completion("不应到达的退出测试回复。")
        if content == PRIVATE:
            names = {row.get("name") or row.get("function", {}).get("name") for row in tools}
            assert not names.intersection({"write", "edit"}), names
            return Completion(QUESTION_REPLY)
        if content == ASSIGNMENT:
            self.task_started.set()
            if not self.task_release.wait(15):
                raise AssertionError("Did not release the accepted task")
            return tool("private-denied-path", "write", path="../channel-must-not-write.txt", content="outside fixture")
        if content in (BOARD_A, BOARD_B) and self.target:
            group = "A" if content == BOARD_A else "B"
            return tool("dispatch-channel-" + group, "umeko_desktop", operation="agent_bus.dispatch",
                        arguments={"targetId": self.target, "text": DELEGATION[content]})
        if "Widget update from " in content and "sent the task in structured data.task" in content:
            if DELEGATION[BOARD_A] in content:
                return self.child_tool(tool, 0)
            if DELEGATION[BOARD_B] in content:
                return self.child_tool(tool, 2)

        for index, (title, filename, finish) in enumerate(TASKS):
            if "请执行子任务：" + title in content:
                return tool(f"write-channel-{index}", "write", path=filename,
                            content=f"# {title}\n\n{finish}。这是合成验收数据。\n")
        return Completion("已接收本地测试结果。")

    def events(self, model, messages, tools, max_tokens, parameters):
        from app.gateway import openai_response

        last = messages[-1]
        if self.recovery and last.get("role") == "tool" and last.get("tool_call_id") == "private-rework-write":
            self.rework_streams += 1
            if self.rework_streams == 1:
                # The real restored child already executed its write. Interrupt
                # the actual SSE response after a draft token, then let native
                # Pi recover from its persisted tool result, not replay tools.
                yield {"choices": [{"index": 0, "delta": {"role": "assistant", "content": "本地断流验收草稿"},
                                      "finish_reason": None}]}
                raise RuntimeError("Network error: stream interrupted (local restored child fixture)")
        yield openai_response(self.complete(model, messages, tools, max_tokens), model)

    @staticmethod
    def child_tool(tool, index):
        title = TASKS[index][0]
        # Two tasks intentionally use identical native role types.
        return tool(f"child-channel-{index}", "subagent", prompt="请执行子任务：" + title,
                    description=title, subagent_type="general-purpose", run_in_background=False)


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def seed(base):
    from app.storage import Store

    workspace = base / "workspace"
    workspace.mkdir()
    store = Store(base / "profile")
    store.data.update(workspace=str(workspace), selectedProvider="internal", selectedModel="fixture", providers=[{
        "id": "internal", "name": "本地合成模型", "api": "internal", "baseUrl": "", "key": "",
        "models": [{"upstream": "fixture", "alias": "fixture"}],
    }])
    store.data["agent"].update(agentDir=str(base / "agent"), toolPermissionMode="auto")
    store.data["desktop"]["teamCollaborationEnabled"] = True
    store.save()
    settings = base / "profile/desktop-plugins/settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"config": {"desktop-pet": {"visible": False}}}), encoding="utf-8")


def run(base, screenshots, reboot=False, native_only=False, crash_phase="", recovery=False):
    os.environ.update(UMEKO_DATA_DIR=str(base / "profile"), PI_CODING_AGENT_DIR=str(base / "agent"),
                      UMEKO_LANGUAGE="zh", QT_QUICK_BACKEND="software", PI_OFFLINE="1")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QObject, Qt
    from PySide6.QtTest import QTest
    from main import create_application

    if not reboot:
        seed(base)
    app, engine, backend = create_application()
    window = engine.rootObjects()[0]
    window.resize(1510, 940)
    warnings = []
    engine.warnings.connect(lambda values: warnings.extend(value.toString() for value in values))
    local = LocalScript()
    local.recovery = recovery
    if crash_phase == "hold":
        local.hold_marker = base / "native-model-hold"
    backend.adapter = backend.gateway.adapter = local
    bus = backend.desktopPlugins.global_agents

    def find(name):
        pending = [window.contentItem()]
        while pending:
            item = pending.pop()
            if item.objectName() == name:
                return item
            if item.objectName() not in ("webSurfaceLoader", "htmlPreviewBrowser"):
                pending.extend(item.childItems())
        return window.findChild(QObject, name)

    def wait(predicate, label, seconds=20):
        deadline = monotonic() + seconds
        while monotonic() < deadline:
            QTest.qWait(25)
            if result := predicate():
                return result
        raise AssertionError(f"{label}\nRequests: {list(bus.requests.values())}\n"
                             f"Recent scripted calls: {local.calls[-5:]}\n{chr(10).join(warnings)}")

    def click(name):
        item = wait(lambda: (candidate := find(name)) and candidate.isVisible() and candidate.isEnabled()
                    and candidate.width() > 0 and candidate.height() > 0 and candidate, f"Not clickable: {name}")
        window.grabWindow()  # Complete layout before testing hit geometry.
        if name.startswith(("channelExecution_", "channelArtifact_")):
            scroll = find("channelBoardScroll")
            relative = item.mapToItem(scroll, item.boundingRect().center()).y()
            if not 0 < relative < scroll.height():
                maximum = max(0, scroll.property("contentHeight") - scroll.height())
                scroll.setProperty("contentY", max(0, min(maximum,
                    scroll.property("contentY") + relative - scroll.height() / 2)))
                QTest.qWait(50)
                item = find(name)
        point = item.mapToScene(item.boundingRect().center()).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)

    def screen(name):
        if screenshots:
            screenshots.mkdir(parents=True, exist_ok=True)
            QTest.qWait(60)  # Wait for the actual UI frame after layout changes.
            assert window.grabWindow().save(str(screenshots / name))

    try:
        if not reboot:
            target = backend._view
            assert backend._command_pi("prompt", target, text="准备一个已授权的本地执行会话。")
            wait(lambda: target.id and target.file and not target.busy, "Native target session was not established")
            coordinator = bus.handle("create", {"name": COORDINATOR})["id"]
            bus.handle("setBridge", {"id": bus.identifier(target), "agentId": coordinator, "enabled": True})
            local.target = bus.identifier(target)
            request_ids, channel_ids = [], []
            assert backend.desktopPlugins.openPage("global-agents")
            member = wait(lambda: (agent_list := find("globalAgentsList")) and agent_list.isVisible()
                          and agent_list.property("currentItem"), "Coordinator not visible in Widget")
            point = member.mapToScene(member.boundingRect().center()).toPoint()
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
            wait(lambda: (obj := find("globalAgentInput")) and obj.isVisible(),
                 "Direct coordinator composer did not open")

            def coordinator_send(message):
                click("globalAgentInput")
                find("globalAgentInput").setProperty("text", message)
                QTest.keyClick(window, Qt.Key_Return)
                wait(lambda: not find("globalAgentInput").property("text"), "Coordinator did not accept prompt")

            assert not backend.channels.channelRows
            coordinator_send("请解释统计口径的含义。")
            wait(lambda: not bus.ensure(coordinator).busy, "Non-delegating prompt did not settle")
            assert not backend.channels.channelRows
            for label, objective in zip(("B", "A"), (BOARD_B, BOARD_A)):
                coordinator_send(objective)
                request = wait(lambda: next((row for row in bus.requests.values()
                                             if row["text"] == DELEGATION[objective] and row["status"] == "completed"), None),
                               f"Actual Pi request {label} did not finish", 65)
                request_ids.append(request["id"])
                assert request.get("channelTaskId"), "Host did not attach the accepted delegation to a task"
                channel_ids.append(request["channelTaskId"])
                wait(lambda: not target.busy and not bus.ensure(coordinator).busy and not bus.outbox,
                     f"Request {label} gateway did not settle")
            assert target.id and target.file
            entries = read_jsonl(target.file)
            notices = [row for row in entries if row.get("customType") == "umeko-widget-update"]
            assert [r["details"]["requestId"] for r in notices] == request_ids, notices
            assert all(r["type"] == "custom_message" and r["details"]["widgetId"] == "global-agents"
                       and r["details"]["data"]["target"] == "session:" + target.id for r in notices)
            native = {}
            for row in entries:
                if row.get("customType") != "umeko-subagent":
                    continue
                item = row["data"]["tool"]["subagent"]
                if item["status"] == "completed":
                    native[item["id"]] = item
            assert len(native) == 3, native
            assert len({row["type"] for row in native.values()}) == 1
            assert len({row["outputFile"] for row in native.values()}) == 3
            assert all(Path(row["outputFile"]).is_file() for row in native.values()), native
            for title, filename, finish in TASKS:
                candidates = [row for row in native.values() if title in row["task"]]
                assert len(candidates) == 1, native
                parsed = read_jsonl(candidates[0]["outputFile"])
                assert finish in json.dumps(parsed, ensure_ascii=False)
                assert (base / "workspace" / filename).is_file()
            bus.save()
            (base / "fixture.json").write_text(json.dumps({"requests": request_ids, "channels": channel_ids[::-1],
                "parent": target.id, "transcript": target.file, "native": native}, ensure_ascii=False), encoding="utf-8")
            print("CHANNEL_NATIVE_OK: one global coordinator, two real requests in one native session, "
                  "three native children with identical roles and separate native transcripts", flush=True)
            if native_only:
                return

        if crash_phase:
            exercise_abrupt_exit(backend, base, find, wait, click, local, reboot)
        else:
            exercise_qml(backend, window, base, find, wait, click, screen, reboot, local)
        assert not [warning for warning in warnings if "ChannelPage.qml" in warning], warnings
    finally:
        backend.close()
        window.close()
        app.processEvents()


def exercise_qml(backend, window, base, find, wait, click, screen, reboot, local):
    fixture = json.loads((base / "fixture.json").read_text(encoding="utf-8"))
    first, second = fixture["channels"]
    channels = backend.channels
    bus = backend.desktopPlugins.global_agents

    def select(identifier, count):
        if channels.channel.get("id") != identifier:
            click("channelSelect_" + identifier)
        wait(lambda: channels.channel.get("id") == identifier and not channels.loading
             and len(channels.channel["tasks"]) == count, f"Channel {identifier} did not load")

    def task(title):
        return next(row for row in channels.channel["tasks"] if title in row["title"])

    def inspect(index):
        title, filename, finish = TASKS[index]
        current = task(title)
        native_id = current["id"].split(":", 1)[1]
        assert current["ready"] and current["status"] == "completed", current
        assert current["artifacts"][0]["name"] == filename
        native = read_jsonl(fixture["native"][native_id]["outputFile"])[0]["id"]
        click("channelExecution_" + current["id"])
        wait(lambda: channels.execution.get("sessionId") == native and not channels.executionLoading
             and len(channels.transcript) >= 2
             and (panel := find("channelExecutionConversation")) and panel.property("count") >= 2,
             "The clicked message did not render its exact native execution")
        displayed = json.dumps(channels.transcript, ensure_ascii=False)
        assert finish in displayed, displayed
        assert all(other[2] not in displayed for other in TASKS if other[2] != finish), displayed
        assert find("channelExecutionPane").isVisible()
        return current

    click("channelSidebarButton")
    wait(lambda: find("channelPage") and find("channelPage").isVisible()
         and find("channelBoard").isVisible(), "Independent Channel entry did not open")
    assert {row["id"] for row in channels.channelRows} == {first, second}
    assert not find("channelExecutionPane").isVisible()
    if not reboot:
        select(first, 2)
        wait(lambda: channels.channel["canSend"], "Live exact coordinator token was not retained")
        followup = "请补充这一季度报告任务的交接说明。"
        find("channelMessageDraft").setProperty("text", followup)
        with patch.object(backend._pool, "write", wraps=backend._pool.write) as native_write:
            click("channelSendButton")
            wait(lambda: any(role == "user" and content == followup for role, content in local.calls),
                 "Channel-originated follow-up did not reach Pi")
            wait(lambda: channels.channel["status"] == "review" and channels.channel["canSend"],
                 "Follow-up coordinator did not finish")
            expected = next(row for row in bus.records.values() if row.title == COORDINATOR)
            assert any(args[0] is expected and args[1].get("type") == "prompt"
                       and args[1].get("text") == followup for args, _ in native_write.call_args_list)
            assert all(args[1].get("type") != "steer" for args, _ in native_write.call_args_list)
        assert any(note["role"] == "user" and note["text"] == followup for note in channels.channel["notes"])
        assert not find("channelMessageDraft").property("text")
        select(second, 1)
        find("channelMessageDraft").setProperty("text", "旧任务草稿不得送进新任务")
        assert not find("channelSendButton").isEnabled(), "An old Channel can send into the newer task"
        assert not channels.sendToCoordinator(second, find("channelMessageDraft").property("text"))
    select(first, 2)
    assert channels.channel["title"] == BOARD_A and channels.channel["coordinator"] == COORDINATOR
    assert len({row["role"] for row in channels.channel["tasks"]}) == 1
    assert channels.channel["status"] == ("closed" if reboot else "review")
    if not reboot:
        draft = "仍在本任务中起草"
        find("channelMessageDraft").setProperty("text", draft)
        assert find("channelSendButton").isEnabled(), "Exact active Channel unexpectedly lost its route"
    model_calls = len(local.calls)
    with patch.object(backend, "_command_pi", wraps=backend._command_pi) as start_pi, \
            patch.object(backend, "openChatboxPath", return_value=True) as open_path:
        board_width = find("channelBoard").width()
        def visible_message(item):
            if not item or not item.isVisible():
                return False
            viewport = find("channelBoardScroll")
            y = item.mapToItem(viewport, item.boundingRect().center()).y()
            return 0 < y < viewport.height()
        if not reboot:
            kickoff = wait(lambda: (message := find("channelKickoffMessage")) and visible_message(message) and message,
                           "Host-recorded user kickoff is not visible in the full-width chat")
            messages = channels.channel["messages"]
            assert messages[0]["role"] == "user" and messages[0]["text"] == BOARD_A and messages[0]["time"]
            assert visible_message(find("channelCoordinatorMessage")), "Coordinator message not visible"
            for title, _, _ in TASKS[:2]:
                worker_message = task(title)
                assert visible_message(find("channelTask_" + worker_message["id"])), "Worker message not visible"
                assert visible_message(find("channelArtifact_" + worker_message["artifacts"][0]["id"])), "Inline artifact not visible"
            assert kickoff
            screen("channel-chat-zh.png")
        first_task = task(TASKS[0][0])
        artifact_id = first_task["artifacts"][0]["id"]
        click("channelArtifact_" + artifact_id)
        open_path.assert_called_once_with(str(base / "workspace" / TASKS[0][1]), False)
        original_scroll = find("channelBoardScroll").property("contentY")
        inspect(0)
        assert find("channelBoard").width() < board_width
        assert not find("channelMessageDraft").isVisible(), "The right-side channel still exposes an input"
        assert not find("channelAcceptButton").isVisible()
        assert find("channelCloseExecution").isVisible()
        if not reboot:
            assert find("channelChildDraft").isVisible()
            assert find("channelMessageDraft").property("text") == draft
            coordinator_record = next(row for row in bus.records.values() if row.title == COORDINATOR)
            old_coordinator_file = coordinator_record.file
            worker_id = first_task["id"].split(":", 1)[1]
            target_child = fixture["native"][worker_id]["outputFile"]
            sibling = next(row["outputFile"] for key, row in fixture["native"].items()
                           if key != worker_id and TASKS[1][0] in row["task"])
            sibling_before = Path(sibling).read_bytes()
            wait(lambda: channels.execution.get("canSend"), "Exact child route not available")
            original_right = json.dumps(channels.channel["messages"], ensure_ascii=False)
            coordinator_bytes = Path(old_coordinator_file).read_bytes()
            output = base / "workspace" / TASKS[0][1]
            original_output = output.read_bytes()
            find("channelChildDraft").setProperty("text", PRIVATE)
            for removed in ("channelChildTaskMode", "channelChildQuestionMode", "channelTaskConsent", "channelChildShareSummary"):
                assert find(removed) is None, removed
            with patch.object(backend._pool, "write", wraps=backend._pool.write) as native_write:
                click("channelChildSend")
                assert not channels.accept(first), "Pending private question did not block acceptance"
                assert not channels.sendToChild(first, first_task["id"], PRIVATE)
                wait(lambda: (not channels.execution.get("pending") and QUESTION_REPLY in
                              json.dumps(channels.transcript, ensure_ascii=False)),
                     "Native private question did not finish")
                types = [args[1]["type"] for args, _ in native_write.call_args_list]
                assert types.count("channel-child") == 1 and "channel-sync" not in types, types
                assert not {"prompt", "steer", "follow-up"} & set(types), types
            assert Path(old_coordinator_file).read_bytes() == coordinator_bytes
            assert json.dumps(channels.channel["messages"], ensure_ascii=False) == original_right
            assert output.read_bytes() == original_output
            assert all(any(row["role"] == role and row["time"] > 0 for row in channels.transcript)
                       for role in ("user", "assistant")), channels.transcript
            screen("channel-v6-question-private-zh.png")

            unclear_messages = [AMBIGUOUS, FORGED, DUPLICATE_FIELDS, UNAVAILABLE]
            if local.recovery:
                unclear_messages.append(INTENT_TIMEOUT)
            for unclear in unclear_messages:
                child_before = Path(target_child).read_bytes()
                find("channelChildDraft").setProperty("text", unclear)
                with patch.object(backend._pool, "write", wraps=backend._pool.write) as native_write:
                    started_at = monotonic()
                    click("channelChildSend")
                    wait(lambda: not channels.execution.get("pending") and "不确定" in channels.executionError,
                         "Ambiguous/forged decision did not clarify privately")
                    if unclear == INTENT_TIMEOUT:
                        elapsed = monotonic() - started_at
                        assert 11.5 <= elapsed < 18, elapsed
                        assert local.classifications.count(INTENT_TIMEOUT) == 1
                        print(f"CHANNEL_INTENT_TIMEOUT_OK: real localhost response aborted after {elapsed:.3f}s; "
                              "zero child execution, zero sync, retained private draft", flush=True)
                        screen("channel-intent-timeout-zh.png")
                    assert channels.execution["draft"] == unclear
                    assert [args[1]["type"] for args, _ in native_write.call_args_list].count("channel-sync") == 0
                assert Path(target_child).read_bytes() == child_before
                assert Path(old_coordinator_file).read_bytes() == coordinator_bytes
                assert json.dumps(channels.channel["messages"], ensure_ascii=False) == original_right
                assert output.read_bytes() == original_output

            find("channelChildDraft").setProperty("text", ASSIGNMENT)
            local.task_release.clear()
            with patch.object(backend._pool, "write", wraps=backend._pool.write) as native_write:
                try:
                    click("channelChildSend")
                    wait(lambda: local.task_started.is_set() and any(r.get("mentionId") and r["status"] == "accepted"
                         for r in channels.channel["messages"]), "Did not notify exact coordinator on acceptance")
                    assert channels.execution["pending"] and not channels.accept(first)
                    assert output.read_bytes() == original_output, "Task output existed before its held work was released"
                    accepted = [r["details"] for r in read_jsonl(old_coordinator_file) if r.get("customType") == "umeko-channel-sync"]
                    assert len(accepted) == 1 and accepted[0]["status"] == "accepted", accepted
                    from PySide6.QtCore import QMetaObject
                    QMetaObject.invokeMethod(find("channelBoardScroll"), "positionViewAtEnd")
                    screen("channel-v6-auto-task-mention-zh.png")
                finally:
                    local.task_release.set()
                wait(lambda: (not channels.execution.get("pending") and PRIVATE_REPLY in
                              json.dumps(channels.transcript, ensure_ascii=False)),
                     "Native assignment did not finish after acceptance")
                types = [args[1]["type"] for args, _ in native_write.call_args_list]
                assert types.count("channel-child") == 1 and types.count("channel-sync") == 1, types
                assert not {"prompt", "steer", "follow-up"} & set(types), types
            child_text = Path(target_child).read_text(encoding="utf-8")
            assert all(x in child_text for x in (PRIVATE, QUESTION_REPLY, ASSIGNMENT, PRIVATE_REPLY))
            assert Path(sibling).read_bytes() == sibling_before
            assert output.read_text(encoding="utf-8") == REWORK_CONTENT
            assert not (base / "channel-must-not-write.txt").exists()
            sync_entries = [r for r in read_jsonl(old_coordinator_file) if r.get("customType") == "umeko-channel-sync"]
            assert len(sync_entries) == 1
            sync = sync_entries[0]["details"]
            assert sync["channelId"] == first and sync["childExecutionId"] == channels.execution["sessionId"]
            assert sync["status"] == "accepted" and sync["artifacts"] == [], sync
            assert sync["taskId"] == first_task["id"] and sync["summary"] == SHARE_SUMMARY
            stable_coordinator_id = "agent:" + coordinator_record.global_agent
            assert sync["mention"] == {"coordinatorId": stable_coordinator_id, "sessionId": coordinator_record.id}
            mentions = [r for r in channels.channel["messages"] if r.get("mentionId")]
            assert len(mentions) == 1 and mentions[0]["mentionId"] == stable_coordinator_id
            assert mentions[0]["actor"] == first_task["id"] and mentions[0]["text"] == SHARE_SUMMARY
            assert mentions[0]["status"] == "completed" and mentions[0]["artifactCount"] == 1
            assert local.classifications == [PRIVATE, *unclear_messages, ASSIGNMENT]
            if local.recovery:
                entries = read_jsonl(target_child)
                writes = [row for row in entries if row.get("type") == "message"
                          and row.get("message", {}).get("role") == "toolResult"
                          and row["message"].get("toolCallId") == "private-rework-write"]
                assert local.rework_streams == 2, local.rework_streams
                assert len(writes) == 1, writes
                assert child_text.count('"toolCallId":"private-rework-write"') == 1
                assert len(mentions) == len(sync_entries) == 1
                print("CHANNEL_RESTORED_RETRY_OK: real child SSE partial draft then interruption, "
                      "native retry succeeded; write executed once, one @, one passive sync", flush=True)
                screen("channel-restored-retry-zh.png")
            assert not any(sync["updateId"] in content for _, content in local.calls), "Passive sync woke the coordinator"
            local.sync_id = sync["updateId"]
            channel_text = json.dumps(channels.channel, ensure_ascii=False)
            coordinator_text = Path(old_coordinator_file).read_text(encoding="utf-8")
            assert not any(x in channel_text or x in coordinator_text for x in (PRIVATE, QUESTION_REPLY, ASSIGNMENT, PRIVATE_REPLY))
            assert channels.channel["status"] == "review"
            model_calls = len(local.calls)
            feed = find("channelBoardScroll")
            from PySide6.QtCore import QMetaObject
            QMetaObject.invokeMethod(feed, "positionViewAtEnd")
            screen("channel-v6-task-completed-zh.png")
            bridge_args = {"id": "session:" + fixture["parent"], "agentId": coordinator_record.global_agent}
            bus.handle("setBridge", {**bridge_args, "enabled": False})
            blocked_draft = "撤回授权后不发送这条私聊。"
            find("channelChildDraft").setProperty("text", blocked_draft)
            assert not channels.sendToChild(first, first_task["id"], blocked_draft)
            assert channels.execution["draft"] == blocked_draft
            bus.handle("setBridge", {**bridge_args, "enabled": True})
        click("channelCloseExecution")
        wait(lambda: not channels.execution
             and abs(find("channelBoardScroll").property("contentY") - original_scroll) < 1,
             "Closing execution did not restore the task chat scroll")
        inspect(1)
        click("channelCloseExecution")
        select(second, 1)
        inspect(2)
        assert not channels.openArtifact(first_task["id"], artifact_id), "Cross-channel artifact accepted"
        click("channelCloseExecution")
        select(first, 2)
        if not reboot:
            assert find("channelMessageDraft").property("text") == draft
            assert len(local.calls) == model_calls, "Read-only navigation called a model"
            find("channelMessageDraft").setProperty("text", TASK_SYNC_PROBE)
            click("channelSendButton")
            wait(lambda: TASK_SYNC_PROBE in local.scope_observations and channels.channel["status"] == "review",
                 "Coordinator did not actually consume the task-scoped sync")
            assert local.scope_observations[TASK_SYNC_PROBE], "Scoped coordinator model did not receive its update"
            model_calls = len(local.calls)
            click("channelAcceptButton")
            wait(lambda: find("channelAcceptDialog").property("opened"), "Explicit acceptance dialog did not open")
            click("channelConfirmAccept")
            wait(lambda: channels.channel["status"] == "closed", "Acceptance did not close the task")
            assert not channels.accept(first)
            assert not find("channelMessageDraft").isVisible()
            inspect(0)
            assert not find("channelChildDraft").isVisible()
            assert not channels.sendToChild(first, first_task["id"], "归档不得重发")
            click("channelCloseExecution")
            screen("channel-accepted-zh.png")
        assert start_pi.call_count == (0 if reboot else 1), start_pi.call_args_list
        assert len(local.calls) == model_calls, "Viewing or accepting Channel triggered a model call"
    if not reboot:
        bus.handle("send", {"id": coordinator_record.global_agent, "text": UNRELATED_SYNC_PROBE})
        wait(lambda: UNRELATED_SYNC_PROBE in local.scope_observations and not coordinator_record.busy,
             "Coordinator's unrelated conversation did not finish")
        assert not local.scope_observations[UNRELATED_SYNC_PROBE], "Private task sync leaked into an unrelated run"
    print("CHANNEL_QT_OK:", "restart retained closed Channel, views and checked artifacts" if reboot
          else "exact-child direct chat/rework, verified output, passive and scoped sync, privacy, drafts and review", flush=True)



def exercise_abrupt_exit(backend, base, find, wait, click, local, reboot):
    fixture = json.loads((base / "fixture.json").read_text(encoding="utf-8"))
    identifier = fixture["channels"][0]
    channels = backend.channels
    click("channelSidebarButton")
    wait(lambda: channels.channel.get("id"), "Channel did not open")
    if channels.channel["id"] != identifier:
        click("channelSelect_" + identifier)
    wait(lambda: channels.channel["id"] == identifier and not channels.loading
         and len(channels.channel["tasks"]) == 2, "Target Channel did not restore")
    task = next(row for row in channels.channel["tasks"] if TASKS[0][0] in row["title"])
    if reboot:
        assert channels.channel["status"] == "interrupted", channels.channel
        notices = [row for row in channels.channel["messages"] if row.get("mentionId")]
        assert len(notices) == 1 and notices[0]["status"] == "interrupted", notices
        with patch.object(backend._pool, "write", wraps=backend._pool.write) as native_write:
            click("channelExecution_" + task["id"])
            wait(lambda: channels.execution.get("id") == task["id"] and not channels.executionLoading,
                 "Interrupted original child record did not restore")
            assert channels.execution["draft"] == HELD_TASK
            assert not channels.execution["pending"] and not channels.execution["canSend"]
            from PySide6.QtTest import QTest
            QTest.qWait(750)
            assert not local.calls, "Model was called after restart"
            assert not any(args[1]["type"] in ("channel-child", "channel-sync") for args, _ in native_write.call_args_list)
        coordinator = Path((base / "coordinator-path").read_text(encoding="utf-8"))
        assert coordinator.read_bytes() == (base / "coordinator-accepted").read_bytes()
        assert len([r for r in read_jsonl(coordinator) if r.get("customType") == "umeko-channel-sync"]) == 1
        print("CHANNEL_HARD_EXIT_OK: interrupted, retained draft and child, no replay or duplicate acceptance", flush=True)
        return

    click("channelExecution_" + task["id"])
    wait(lambda: channels.execution.get("canSend"), "Exact held child not available")
    coordinator = next(row for row in backend.desktopPlugins.global_agents.records.values() if row.title == COORDINATOR)
    coordinator_file = Path(coordinator.file)
    (base / "coordinator-path").write_text(str(coordinator_file), encoding="utf-8")
    (base / "coordinator-before").write_bytes(coordinator_file.read_bytes())
    find("channelChildDraft").setProperty("text", HELD_TASK)
    click("channelChildSend")
    wait(lambda: local.hold_marker.exists() and any(r.get("mentionId") and r["status"] == "accepted"
         for r in channels.channel["messages"]), "Native child did not enter the held, accepted model request")
    persisted = json.loads((base / "profile/settings.json").read_text(encoding="utf-8"))
    pending = next(row for row in persisted["taskChannels"] if row["id"] == identifier)
    assert pending["reworkPending"] and pending["childDrafts"][task["id"]] == HELD_TASK
    assert coordinator_file.read_bytes() != (base / "coordinator-before").read_bytes()
    (base / "coordinator-accepted").write_bytes(coordinator_file.read_bytes())
    (base / "ready-for-hard-exit").write_text(identifier, encoding="utf-8")
    wait(lambda: False, "Expected hard exit from supervising test process", 60)


def hard_exit_test(directory):
    if os.name != "posix":
        raise RuntimeError("The hard-exit process-group test requires POSIX")
    with TemporaryDirectory(prefix="umeko-channel-hard-exit-", dir=directory) as raw:
        base = Path(raw)
        process = subprocess.Popen([sys.executable, __file__, "--hold-inflight", raw], start_new_session=True)
        try:
            deadline = monotonic() + 85
            while monotonic() < deadline:
                if (base / "ready-for-hard-exit").exists():
                    break
                if process.poll() is not None:
                    raise RuntimeError(f"Native fixture exited before its held request: {process.returncode}")
                sleep(0.05)
            else:
                raise RuntimeError("Native request never reached the persisted held state")
        finally:
            # Only kill the isolated fixture's process group, including its Pi
            # descendants. The historical app must have no chance to save/redo.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=10)
        assert process.returncode == -signal.SIGKILL, process.returncode
        subprocess.run([sys.executable, __file__, "--verify-inflight", raw], check=True, timeout=60)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshots", type=Path)
    parser.add_argument("--recovery", action="store_true", help="Exercise real intent timeout and restored-child SSE retry")
    parser.add_argument("--native-only", type=Path, metavar="FIXTURE_DIR")
    parser.add_argument("--profile", type=Path, help="Used only by the restart subprocess")
    parser.add_argument("--hard-exit", type=Path, metavar="DIRECTORY", help="Exercise a real abrupt process exit")
    parser.add_argument("--hold-inflight", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--verify-inflight", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.hard_exit is not None:
        hard_exit_test(args.hard_exit)
    elif args.hold_inflight is not None:
        run(args.hold_inflight, None, crash_phase="hold")
    elif args.verify_inflight is not None:
        run(args.verify_inflight, None, reboot=True, crash_phase="verify")
    elif args.native_only is not None:
        args.native_only.mkdir(parents=True)
        run(args.native_only.resolve(), None, native_only=True)
    elif args.profile is not None:
        run(args.profile, None, reboot=True)
    else:
        with TemporaryDirectory(prefix="umeko-channel-ui-") as profile:
            run(Path(profile), args.screenshots, recovery=args.recovery)
            subprocess.run([sys.executable, __file__, "--profile", profile], check=True, timeout=100)


if __name__ == "__main__":
    main()
