"""Real Qt/SQLite dashboard, with labelled synthetic data and no model calls."""
import argparse
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(profile, output):
    os.environ.update(UMEKO_DATA_DIR=str(profile), PI_CODING_AGENT_DIR=str(profile / "pi"),
                      UMEKO_LANGUAGE="zh", QT_QUICK_BACKEND="software")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QObject, Qt
    from PySide6.QtQml import QQmlEngine, QQmlExpression
    from PySide6.QtTest import QTest
    from app.pi_runtime import RELEASE_NAME, verify_runtime
    from app.storage import Store
    from main import create_application

    verify_runtime(ROOT / "runtime/releases" / RELEASE_NAME, ROOT / "runtime/bridge.mjs")
    store = Store(profile)
    store.data.update(selectedProvider="internal", selectedModel="fixture", providers=[{
        "id": "internal", "name": "Local fixture", "api": "internal", "baseUrl": "", "key": "",
        "models": [{"upstream": "fixture", "alias": "fixture"}],
    }])
    store.data["agent"]["agentDir"] = str(profile / "pi")
    store.save()
    settings = profile / "desktop-plugins/settings.json"
    settings.parent.mkdir(exist_ok=True)
    settings.write_text(json.dumps({"config": {"desktop-pet": {"visible": False}}}), encoding="utf-8")
    app, engine, backend = create_application()
    window = engine.rootObjects()[0]
    window.resize(1440, 1130)
    warnings = []
    engine.warnings.connect(lambda values: warnings.extend(value.toString() for value in values))
    requests = []

    class NoModel:
        ready = True

        def complete(self, *args, **kwargs):
            requests.append(args)
            raise AssertionError("Board reads must not run a model")

    backend.adapter = backend.gateway.adapter = NoModel()

    def find(name):
        pending = [window.contentItem()]
        while pending:
            item = pending.pop()
            if item.objectName() == name:
                return item
            if item.objectName() not in ("webSurfaceLoader", "htmlPreviewBrowser"):
                pending.extend(item.childItems())
        return window.findChild(QObject, name)

    def wait(check, label):
        deadline = monotonic() + 8
        while monotonic() < deadline:
            QTest.qWait(20)
            if check():
                return
        raise AssertionError(label + "\n" + "\n".join(warnings))

    def click(name):
        wait(lambda: (item := find(name)) and item.isVisible() and item.isEnabled(), "Unavailable: " + name)
        item = find(name)
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, item.mapToScene(item.boundingRect().center()).toPoint())

    def evaluate(item, js):
        script = QQmlExpression(QQmlEngine.contextForObject(item), item, js)
        result, _ = script.evaluate()
        assert not script.hasError(), script.error().toString()
        return result

    def prop(name, key):
        item = find(name)
        if item is None:
            return None
        value = item.property(key)
        return value.toVariant() if hasattr(value, "toVariant") else value

    board_name = "globalTeamBoard"
    status = "globalTeamBoardStatus"

    def rows():
        return prop(board_name, "rows") or []

    def ready():
        return prop(board_name, "detailReady") and not prop(board_name, "loading")

    def save(filename):
        if output:
            output.mkdir(parents=True, exist_ok=True)
            QTest.qWait(180)
            image = window.grabWindow()
            assert not image.isNull() and image.save(str(output / filename))

    enabled = json.dumps({"teamCollaborationEnabled": True})
    disabled = json.dumps({"teamCollaborationEnabled": False})
    try:
        assert backend.desktopPlugins.openPage("global-agents")
        wait(lambda: prop("globalAgentsPage", "section") == "agents", "Global Agents did not load")
        wait(lambda: find("webPane") and find("webPane").property("live"), "Widget transition did not settle")
        click("teamBoardTabButton")
        wait(lambda: prop(board_name, "active") and find(status).isVisible()
             and "开启团队协作" in prop(status, "text"), "Disabled-state guidance absent")
        assert backend.saveDesktopSettings(enabled)
        wait(lambda: "还没有团队" in (prop(status, "text") or ""), "Empty-state guidance absent")

        service = backend.desktopPlugins.global_agents
        storage = service.team_board.storage()
        authors = ("lead", "build", "qa")
        agents = {name: service.handle("create", {"name": name})["id"] for name in authors}
        service.agents[agents["lead"]]["sessionId"] = "fixture-idle-session"
        # Only the isolated session record is marked busy, never a fake metric.
        # The real host API computes status from this record; no process starts.
        test_record = service.ensure(agents["build"])
        test_record.busy = True
        coordinator, developer, qa = [
            {"targetId": "agent:" + agents[name], "name": name,
             "role": "coordinator" if name == "lead" else "member", "groups": []}
            for name in authors
        ]
        release = storage.create_team("桌面发布 · 演示团队", [coordinator, developer, qa])
        other = storage.create_team("文档校对 · 演示团队", [coordinator, qa])

        def add(kind, actor, *, team=release, **fields):
            return storage.post_team_event(team, actor, kind, fields, [])["task"]

        package = add("task", coordinator, title="验证桌面安装包", text="核对安装、首次启动与设置保留。", blockedBy=[])
        add("claim", developer, taskId=package["id"], expectedVersion=1, text="")
        add("handoff", developer, taskId=package["id"], expectedVersion=2, text="安装已通过，交给 QA 检查升级路径。", to="qa")
        add("result", qa, taskId=package["id"], expectedVersion=3, text="安装、升级和设置保留均通过。")
        keyboard = add("task", coordinator, title="回归快捷键与输入法", text="复核窄栏、键盘焦点及中文输入。", blockedBy=[])
        add("claim", developer, taskId=keyboard["id"], expectedVersion=1, text="")
        add("progress", developer, taskId=keyboard["id"], expectedVersion=2, text="已完成基础交互，正在核对输入法。")
        add("task", coordinator, title="整理发布验收记录", text="汇总两个平台的验证记录与已知限制。", blockedBy=[])
        for n in range(12):
            add("message", qa, text=f"演示记录 {n + 1}：检查结果已归档。")
        add("message", developer, text="这是第二页的演示交接。")
        add("message", qa, text="\n".join(f"详细验收：第 {step} 步" for step in range(1, 12)))
        add("message", qa, team=other, text="独立文档团队演示记录。")
        original_records = tuple(service.records)

        click("globalTeamBoardReload")
        wait(lambda: ready() and len(prop(board_name, "teams")) == 2, "Board did not load seeded teams")
        item = find(board_name)
        evaluate(item, f"selectTeam({json.dumps(release['id'])})")
        wait(lambda: ready() and len(prop(board_name, "events")) == 20, "First cursor page not read")
        assert [r["status"] for r in rows() if r["type"] == "member"] == ["等待点名", "运行中", "尚未启动"]
        assert {r["status"] for r in rows() if r["type"] == "task"} == {"已完成", "执行中", "待认领"}
        assert any(r.get("meta") == "build → qa" and "交接任务" in r["title"] for r in rows())
        for name, value in (("teamMetricMembers", 3), ("teamMetricRunning", 1), ("teamMetricWaiting", 1)):
            assert prop(name, "value") == value, (name, prop(name, "value"))
        assert prop("teamMetricDone", "text") == "1 / 3"
        segment = find("teamProgressCompletedSegment")
        assert abs(segment.width() / segment.parentItem().width() - 1/3) < 0.01
        wait(lambda: "3" in prop("globalSubagentsTabButton", "text"), "Widget agent count not populated")
        backend.setTheme("white")
        wait(lambda: not prop(board_name, "colors")["dark"], "Light theme not active")
        save("team-dashboard-light.png")

        backend.setTheme("dark")
        wait(lambda: prop(board_name, "colors")["dark"], "Dark theme not active")
        save("team-dashboard-dark.png")
        pane = find("webPane")
        old_width = window.property("webPreferredWidth")
        window.setProperty("webPreferredWidth", 320)
        evaluate(pane, "snapWidth()")
        wait(lambda: ready() and abs(pane.width() - 320) < 2 and 270 <= find(board_name).width() <= 305,
             "Supported minimum-width layout not active")
        assert find("teamDashboardOverview").width() > 0
        assert all(find(name).width() > 50 for name in ("teamMetricMembers", "teamMetricRunning", "teamMetricWaiting"))
        assert find("teamMetricDone").isVisible()
        assert find("teamBoardTabButton").isVisible()
        save("team-dashboard-narrow.png")
        window.setProperty("webPreferredWidth", old_width)
        evaluate(pane, "snapWidth()")
        wait(lambda: ready() and find(board_name).width() >= 400, "Wide layout not restored")

        first = prop(board_name, "events")[0]["sequence"]
        click("globalTeamBoardNext")
        wait(lambda: ready() and len(prop(board_name, "events")) == 2, "Next page not read")
        assert prop(board_name, "events")[0]["sequence"] == first + 20
        assert prop("teamMetricDone", "text") == "1 / 3"
        last = prop(board_name, "events")[-1]["sequence"]
        entry = f"teamBoardRow_event-{last}"
        toggle = f"teamBoardExpand_event-{last}"
        listing = find("globalTeamBoardRows")
        evaluate(listing, "positionViewAtEnd()")
        wait(lambda: find(entry) and find(toggle) and find(toggle).isVisible(), "Expand action not visible")
        height = prop(entry, "height")
        click(toggle)
        wait(lambda: prop(toggle, "text") == "收起团队记录" and prop(entry, "height") > height, "Entry did not expand")
        evaluate(listing, "positionViewAtEnd()")
        click(toggle)
        wait(lambda: prop(entry, "height") == height, "Entry did not collapse")
        click("globalTeamBoardPrevious")
        wait(lambda: ready() and len(prop(board_name, "events")) == 20, "Previous page not restored")
        assert prop(board_name, "events")[0]["sequence"] == first

        evaluate(item, f"selectTeam({json.dumps(other['id'])}); selectTeam({json.dumps(release['id'])})")
        wait(lambda: ready() and len(prop(board_name, "events")) == 20, "Rapid team switching lost results")
        assert all(r.get("body") != "独立文档团队演示记录。" for r in rows())
        click("globalTeamBoardPicker")
        wait(lambda: evaluate(find("globalTeamBoardPicker"), "popup.opened"), "Team picker not open")
        # Teams can share a creation timestamp; the backend then sorts by ID.
        target_index = next(i for i, row in enumerate(prop(board_name, "teams")) if row["id"] == other["id"])
        QTest.keyClick(window, Qt.Key_Home if target_index == 0 else Qt.Key_End)
        QTest.keyClick(window, Qt.Key_Return)
        wait(lambda: ready() and any(r.get("body") == "独立文档团队演示记录。" for r in rows()), "Team picker did not switch")
        assert prop("teamMetricDone", "text") == "0 / 0"
        original_storage = service.team_board.storage

        def unavailable():
            raise OSError("Synthetic storage failure")

        service.team_board.storage = unavailable
        click("globalTeamBoardReload")
        wait(lambda: "读取失败" in (prop(status, "text") or ""), "Failure state not visible")
        assert any(r.get("body") == "独立文档团队演示记录。" for r in rows())
        service.team_board.storage = original_storage
        click("globalTeamBoardReload")
        wait(lambda: ready() and not prop(status, "text"), "Retry did not clear error")
        backend.setLanguage("en")
        wait(lambda: prop("teamBoardTabButton", "text") == "Team board"
             and any(r.get("title") == "Activity timeline" for r in rows()), "English strings not refreshed")
        assert backend.saveDesktopSettings(disabled)
        wait(lambda: "Enable Team collaboration" in (prop(status, "text") or "") and not rows(), "Disabled view retained data")
        assert not requests and tuple(service.records) == original_records and not test_record.process
        assert len(storage.team_board(release["id"], 0, 50)["events"]) == 22
        assert not [warning for warning in warnings if "TeamBoard.qml" in warning], warnings
        print("GLOBAL_TEAM_DASHBOARD_UI_OK: real Qt/SQLite, 3/1/1 metrics, 1/3 progress bar, light/dark/narrow, "
              "two teams, pagination, expanded activity, stale response, error/retry, English/Chinese, no model calls")
        test_record.busy = False
    finally:
        backend.close()
        window.close()
        app.processEvents()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="umeko-team-dashboard-") as directory:
        run(Path(directory) / "profile", args.screenshots)
