"""Exercise the task panel and real Pi bridge in a disposable profile."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QObject, Qt, QUrl, QMetaObject, Q_ARG
from PySide6.QtTest import QTest
from app.integration import Completion
from main import create_application


class Fixture:
    ready = True

    def __init__(self):
        self.calls = 0
        self.partial = False
        self.release = None
        self.waiting = False

    def complete(self, model, messages, tools, max_tokens):
        self.calls += 1
        if messages[-1]["role"] == "tool":
            if self.release:
                self.waiting = True
                self.release.wait(20)
            return Completion("Report submitted.")
        items = [{"path": "report.txt"}]
        if self.partial:
            items.append({"path": "missing.txt"})
        return Completion(tool_calls=[{
            "id": f"report-{self.calls}", "name": "submit_to_chatbox",
            "arguments": {"items": items},
        }])


def until(predicate, description):
    for _ in range(400):
        if predicate():
            return
        QTest.qWait(50)
    raise AssertionError(description)


with tempfile.TemporaryDirectory(prefix="umeko-task-records-ui-") as temp:
    profile = Path(temp)
    os.environ.update(HOME=temp, UMEKO_DATA_DIR=str(profile / "data"))
    fixture = Fixture()
    with patch("app.controller.load_adapter", return_value=fixture):
        app, engine, backend = create_application()
    if os.environ.get('UMEKO_TEST_FONT'):
        from PySide6.QtGui import QFont, QFontDatabase
        assert QFontDatabase.addApplicationFont(os.environ['UMEKO_TEST_FONT']) >= 0
        app.setFont(QFont('Noto Sans CJK SC',10))
    window = engine.rootObjects()[0]
    window.setWidth(1440)
    window.setHeight(960)
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))

    def find(name):
        pending = [window.contentItem()]
        while pending:
            item = pending.pop()
            if item.objectName() == name:
                return item
            pending.extend(item.childItems())
        return window.findChild(QObject, name)

    def control(name):
        item = find(name)
        assert item is not None, name
        return item

    def click(name):
        item = control(name)
        assert item.property("enabled"), name
        item.clicked.emit()

    manager = backend.desktopPlugins
    ledger = backend._task_records
    assert not manager.enabled('task-records')
    assert 'task-records' not in {row['id'] for row in manager.sessionPlugins}
    assert ledger.store is None
    manager.setEnabled('task-records', True)

    def open_widget():
        menu = control("desktopPluginSessionMenu")
        until(lambda: not menu.property("animating"), "Previous Widget menu animation did not settle")
        click("desktopPluginMenuButton")
        until(lambda: menu.property("desiredOpen") and not menu.property("animating"), "Widget menu did not open")
        until(lambda: find("openDesktopPlugin_task-records") is not None, "Task Widget menu entry missing")
        entry = control("openDesktopPlugin_task-records")
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, entry.mapToScene(entry.boundingRect().center()).toPoint())
        until(lambda: find("taskRecordsWidget") is not None, "Task Widget did not open")
        panel = control("taskRecordsWidget")
        until(lambda: manager.page.get("id") == "task-records" and not manager.page["loading"]
              and panel.property("loaded") and not panel.property("request"), "Task Widget did not load its records")
        return panel

    def select_task(panel, task_id):
        until(lambda: find("openTask_" + task_id) is not None, "Task row not rendered")
        click("openTask_" + task_id)
        until(lambda: panel.property("view") == "task" and not panel.property("request"), "Task details did not load")

    workspace = profile / "project"
    workspace.mkdir()
    report = workspace / "report.txt"
    report.write_text("Fixture deliverable", encoding="utf-8")
    input_file = workspace / "input.txt"
    input_file.write_text("Fixture input", encoding="utf-8")
    backend.store.data.update(selectedProvider="internal", selectedModel="umeko-default",
        providers=[{"id": "internal", "name": "Fixture", "api": "internal", "baseUrl": "", "key": "",
                    "models": [{"upstream": "default", "alias": "umeko-default"}]}])
    backend.setWorkspace(QUrl.fromLocalFile(str(workspace)).toString())
    assert backend.addAttachments(json.dumps([QUrl.fromLocalFile(str(input_file)).toString()]))
    view = backend._view
    view.draft = "Existing unsent draft"
    attachments = list(view.attachments)
    try:
        assert window.findChild(QObject, "taskRecordsButton") is None
        panel = open_widget()
        click("newTaskRecord")
        control("taskObjective").setProperty("text", "生成项目验收报告" if os.environ.get("UMEKO_LANGUAGE")=="zh" else "Deliver the review report")
        control("taskScope").setProperty("text", "读取本项目参考资料，生成验收报告，不修改原始文件。" if os.environ.get("UMEKO_LANGUAGE")=="zh" else "Read input.txt and submit report.txt in this project.")
        click("saveTaskRecord")
        until(lambda: panel.property("view") == "task" and not panel.property("request"), "Task was not created")
        task_id = ledger.store.tasks()[0]["id"]
        assert backend._view is view and view.draft == "Existing unsent draft"
        assert view.attachments == attachments and view.process is None and fixture.calls == 0

        until(lambda: not panel.property("request") and view.prepared_task == task_id, "Task was not linked")
        assert fixture.calls == 0 and view.draft == "Existing unsent draft"
        if len(sys.argv)>1:
            QTest.qWait(300)
            assert window.grabWindow().save(str(Path(sys.argv[1]).with_stem('task-pending')))
        click("cancelPreparedTask")
        until(lambda: not panel.property("request") and not view.prepared_task, "Preparation was not cancelled")
        assert view.attachments == attachments and view.draft == "Existing unsent draft" and fixture.calls == 0
        click("prepareNewTask")
        until(lambda: not panel.property("request") and view.prepared_task == task_id, "Task was not prepared again")
        click("goToTaskChat")
        until(lambda: manager.page.get("id") != "task-records" and not control("webPane").property("opened") and control("promptInput").property("activeFocus"), "Chat entry did not focus the input")
        assert view.draft == "Existing unsent draft" and view.attachments == attachments and fixture.calls == 0
        assert backend.send("Submit the report")
        until(lambda: ledger.store.tasks()[0]["state"] != "running", "Pi did not finish")
        assert ledger.store.tasks()[0]["state"] == "finished", warnings
        first = ledger.store.attempts(task_id)[0]
        result = ledger.store.details(task_id, first["id"])
        assert result["session_id"] == view.id and result["session_state"] == "available", result
        assert any(row["kind"] == "message" for row in result["steps"]), result
        assert [(row["source"], row["state"]) for row in result["files"]] == [
            ("input", "available"), ("submitted", "available")], result
        panel = open_widget()
        select_task(panel, task_id)
        until(lambda: control("verifyTaskArtifacts").property("enabled"), "Verification action did not load")
        click("verifyTaskArtifacts")
        until(lambda: control("acceptTaskAttempt").property("enabled"), "Acceptance action did not load")
        assert ledger.store.details(task_id, first["id"])["files"][-1]["check_result"] == "available"
        assert "1" in control("taskCheckResult").property("text")
        file_id=ledger.store.details(task_id,first["id"])["files"][-1]["id"]
        click("viewTaskFile_"+str(file_id))
        until(lambda: control("webPane").property("mode")=="document", "File preview did not open")
        click("backDocumentPreviewButton")
        until(lambda: control("webPane").property("mode")=="plugin" and panel.property("sdk").property("active") and not panel.property("request"), "Could not return to task record")
        click("acceptTaskAttempt")
        assert ledger.store.tasks()[0]["state"] == "finished"
        click("confirmTaskAcceptance")
        until(lambda: ledger.store.tasks()[0]["state"] == "accepted", "Acceptance was not stored")
        manager.closePage()

        backend.newSession()
        assert backend._view is not view
        panel = open_widget()
        select_task(panel, task_id)
        click("prepareTaskAttempt")
        until(lambda: not panel.property("request") and backend._view.prepared_task == task_id, "Retry was not linked")
        manager.closePage()
        report.write_text("Revised fixture deliverable", encoding="utf-8")
        fixture.partial = True
        assert backend.send("Submit the revised report")
        until(lambda: ledger.store.tasks()[0]["state"] != "running", "Retry did not finish")
        attempts = ledger.store.attempts(task_id)
        assert len(attempts) == 2 and attempts[0]["session_id"] != attempts[1]["session_id"], attempts
        assert attempts[1]["accepted"] and attempts[0]["state"] == "failed", attempts
        revised = ledger.store.details(task_id, attempts[0]["id"])
        assert revised["files"][0]["state"] == "available" and any(
            step["kind"] == "delivery_error" for step in revised["steps"]), revised
        assert ledger.store.details(task_id, first["id"])["files"][-1]["state"] == "changed"

        before = fixture.calls
        panel = open_widget()
        select_task(panel, task_id)
        control("taskAttemptSelector").activated.emit(1)
        until(lambda: not panel.property("request"), "Earlier attempt not rendered")
        assert "report.txt" in control("taskAttemptDetails").property("text")
        assert panel.property("nodes").toVariant()
        assert control("taskTimelineRail").property("visible")
        assert fixture.calls == before
        assert not [line for line in warnings if "task-records/qml" in line or "taskRecords" in line], warnings
        if len(sys.argv) > 1:
            QTest.qWait(300)
            assert window.grabWindow().save(sys.argv[1])
        # Verify preview navigation uses the actual rendered page.
        click("showTaskProcess")
        until(lambda:not panel.property("request"),"History not loaded")
        panel.setProperty("navigationOpen",True)
        QTest.qWait(100)
        assert control("taskTimelinePreview").property("visible")
        assert QMetaObject.invokeMethod(panel,"jump",Qt.DirectConnection,Q_ARG("QVariant",2))
        assert panel.property("selectedNode")==2
        panel.setProperty("navigationOpen",True)
        if len(sys.argv)>1:
            QTest.qWait(100)
            assert window.grabWindow().save(str(Path(sys.argv[1]).with_stem('task-timeline')))
        manager.closePage()
        for label,state in [('整理客户素材','running'),('生成产品文案','pending'),('检查测试结果','failed'),('归档项目资料','finished'),('准备发布说明','draft')]:
            other=ledger.store.create(label,'仅处理当前项目资料',str(workspace))
            if state!='draft':
                attempt_id=ledger.store.begin(other,str(workspace),'','',[])
                if state!='running':ledger.store.finish(attempt_id,state,'')
        panel=open_widget()
        if len(sys.argv)>1:
            QTest.qWait(200)
            assert window.grabWindow().save(str(Path(sys.argv[1]).with_stem('task-list')))
        manager.closePage()

        # Read a real large Pi history, retaining draft and attachments while browsing 10k steps.
        history=profile/'large.jsonl'
        with history.open('w',encoding='utf-8') as output:
            output.write(json.dumps({'type':'session','id':'large-history','cwd':str(workspace)})+'\n')
            for index in range(2002):
                output.write(json.dumps({'type':'message','id':str(index),'parentId':str(index-1) if index else None,
                    'message':{'role':'user' if index%2==0 else 'assistant','content':'Large history message '+str(index)}})+'\n')
        backend._sessions.append({'id':'large-history','file':str(history),'title':'Large history','workspace':str(workspace)})
        backend.openSession('large-history')
        until(lambda:backend._view.id=='large-history' and backend.messageCount>=2002,'Large chat did not load')
        large=backend._view
        large.draft='Retained large-history draft'
        backend.editorText.emit(large.draft)
        assert backend.addAttachments(json.dumps([QUrl.fromLocalFile(str(input_file)).toString()]))
        large_attachments=list(large.attachments)
        with ledger.store.connection() as db:
            db.executemany("INSERT INTO steps (attempt_id,kind,key,detail,observed,updated) VALUES (?,'tool',?,'read · done',NULL,NULL)",
                ((first['id'],'large-step-'+str(index)) for index in range(10000)))
        elapsed=[]
        for repeat in range(3):
            start=time.perf_counter()
            panel=open_widget();select_task(panel,task_id);click('showTaskProcess')
            until(lambda:not panel.property('request'),'Large detail page did not load')
            elapsed.append(round((time.perf_counter()-start)*1000,1))
            assert len(panel.property('nodes').toVariant())<=20
            assert QMetaObject.invokeMethod(panel,'showAttempt',Qt.DirectConnection,Q_ARG('QVariant',1),Q_ARG('QVariant',9992),Q_ARG('QVariant',False),Q_ARG('QVariant',False))
            until(lambda:not panel.property('request') and panel.property('edgeReady'),'Late history page did not load')
            assert len(panel.property('nodes').toVariant())<=20
            assert QMetaObject.invokeMethod(panel,'edgePage',Qt.DirectConnection,Q_ARG('QVariant',-1))
            until(lambda:not panel.property('request') and panel.property('edgeReady'),'Reverse pagination did not finish')
            assert panel.property('detailOffset')==9984
            timeline=control('taskTimeline')
            timeline.setProperty('contentY', min(100, max(0, timeline.property('contentHeight')-timeline.property('height'))))
            QTest.qWait(100)
            scroll_before=timeline.property('contentY')
            ledger.changed.emit()
            until(lambda:not panel.property('request') and panel.property('edgeReady'),'Live refresh did not settle')
            QTest.qWait(100)
            assert abs(timeline.property('contentY')-scroll_before)<2, (scroll_before,timeline.property('contentY'))
            assert large.draft=='Retained large-history draft' and large.attachments==large_attachments and fixture.calls==before
            manager.closePage()
        print('LARGE_TASK_RECORDS_UI_OK',json.dumps({'messages':2002,'steps':10000,'offscreen_open_and_select_ms':elapsed,'max_nodes':20}))
        # Keep the actual Pi turn running after delivery; the open Widget must
        # receive the new file before completion or any manual refresh.
        backend.newSession()
        backend.store.data['desktop']['autoOpenSubmissions']=False
        fixture.partial=False
        fixture.release=threading.Event()
        live_task=ledger.create('Live delivery fixture','Only this isolated project')
        assert ledger.prepare(live_task)
        panel=open_widget()
        select_task(panel,live_task)
        assert backend.send('Submit the report and wait')
        until(lambda:fixture.waiting,'Pi did not reach the paused final response')
        until(lambda:any(row.get('file') for row in panel.property('nodes').toVariant()),'Running Widget did not refresh its delivery')
        assert backend._view.busy and backend._view.task_attempt
        assert ledger.store.tasks()[0]['state']=='running'
        fixture.release.set()
        until(lambda:not backend._view.busy,'Live fixture did not finish')
        manager.closePage()
        print('LIVE_TASK_RECORDS_UI_OK: new delivery visible before the Pi turn ended; scroll retained on refresh')
        print("TASK_RECORDS_UI_OK: isolated browsing, real Pi delivery, retry, partial failure, and changed artifact")
    except AssertionError:
        panel = find("taskRecordsWidget")
        if panel:
            print({key: panel.property(key) for key in ("view", "request", "loaded", "error")}, warnings, file=sys.stderr)
        raise
    finally:
        if fixture.release:
            fixture.release.set()
        backend.close()
        window.hide()
        import shiboken6
        shiboken6.delete(engine)
