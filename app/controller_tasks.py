"""Track explicitly linked chat attempts without changing normal chat permissions."""
import sqlite3
import uuid

from PySide6.QtCore import QObject, QLockFile, Signal

from .task_records import TaskStore, versions_of


class TaskRecords(QObject):
    changed = Signal()

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.store = None
        self.lock = QLockFile(str(host.store.directory / "tasks.lock"))
        self.lock.setStaleLockTime(0)

    def _storage(self):
        if self.store is None:
            if not self.lock.tryLock(0):
                self.host.toast.emit("任务记录正在另一个窗口中使用")
                return None
            try:
                store = TaskStore(self.host.store.directory / "tasks.sqlite3")
                store.recover("应用已重启")
                self.store = store
            except (sqlite3.Error, OSError):
                self.lock.unlock()
                self.host.toast.emit("无法打开任务记录")
        return self.store

    def _write(self, operation, *args):
        try:
            return operation(*args)
        except sqlite3.Error:
            self.host.toast.emit("无法保存任务记录")
            return None

    def _cwd(self, record):
        return record.workspace or str(self.host.store.directory / "workspace")

    def _project(self, record):
        return self.host.store.data["workspace"] or self._cwd(record)

    def create(self, objective, scope):
        objective, scope = objective.strip(), scope.strip()
        if not objective or not scope or len(objective) > 1000 or len(scope) > 4000:
            return ""
        store = self._storage()
        if store:
            result = self._write(store.create, objective, scope, self._project(self.host._view))
            if result:
                self.changed.emit()
                return result
        return ""

    def canPrepare(self, task_id):
        record = self.host._view
        if record.busy or record.approval or record.global_agent or not self.store:
            return False
        task = self._write(self.store.task, task_id)
        if not task or task["project"] != self._project(record):
            return False
        return self._write(self.store.running, task_id) is False

    def prepare(self, task_id):
        if not self.canPrepare(task_id):
            return False
        self.host._view.prepared_task = task_id
        self.changed.emit()
        return True

    def clear(self):
        self.host._view.prepared_task = ""
        self.changed.emit()

    def remove(self, task_id):
        if not self.store or not self._write(self.store.delete, task_id):
            return False
        for record in self.host._pool.records.values():
            if record.prepared_task == task_id:
                record.prepared_task = ""
        self.changed.emit()
        return True

    def accept(self, task_id, attempt_id):
        if self.store:
            self.store.accept(task_id, attempt_id)
            self.changed.emit()

    def start(self, record, attachments):
        task_id = record.prepared_task
        if not self.canPrepare(task_id):
            self.host.toast.emit("当前会话无法继续此任务")
            return False
        attempt_id = self._write(self.store.begin, task_id, self._cwd(record),
                                 record.id if record.file else "", record.file, versions_of(attachments))
        if attempt_id is None:
            return False
        record.task_attempt = attempt_id
        record.task_record_error = False
        record.prepared_task = ""
        self.changed.emit()
        return True

    def input_files(self, record, attachments):
        versions = versions_of(attachments)
        if versions:
            self._attempt_write(record, self.store.files, "input", uuid.uuid4().hex, versions)

    def _attempt_write(self, record, operation, *args):
        try:
            operation(record.task_attempt, *args)
        except sqlite3.Error:
            if not record.task_record_error:
                self.host.toast.emit("无法完整保存任务尝试")
            record.task_record_error = True

    def event(self, record, event):
        kind = event["type"]
        if kind in ("ready", "session", "state") and event.get("session"):
            session = event["session"]
            self._attempt_write(record, self.store.session, session["workspace"], session["id"], session.get("file", ""))
        elif kind == "native_entry":
            self._attempt_write(record, self.store.step, "message", record.id + "/" + event["entryId"], event["role"])
        elif kind == "tool" and event.get("taskStep", True):
            self._attempt_write(record, self.store.step, "tool", event["id"], event["name"] + " · " + event["state"])
        elif kind == "task_delivery":
            self._attempt_write(record, self.store.files, event["source"], event["id"],
                                versions_of(event["items"]), event.get("failed", 0))

    def end_turn(self, record, exited):
        if exited:
            self.finish(record, "pending", "Pi 进程已退出")
        elif record.cancelled:
            self.finish(record, "pending", "用户已停止尝试")
        elif record.failed:
            self.finish(record, "failed", "Pi 执行失败")
        elif record.messages and record.messages[-1].get("stopReason") == "length":
            self.finish(record, "pending", "输出达到长度上限")
        else:
            self.finish(record, "finished", "")

    def finish(self, record, state, reason):
        if record.task_record_error:
            state, reason = "pending", "任务记录写入不完整"
        self._write(self.store.finish, record.task_attempt, state, reason)
        record.task_attempt = 0
        self.changed.emit()

    def close(self):
        if self.store:
            self._write(self.store.recover, "应用已退出")
            self.store = None
            self.lock.unlock()
