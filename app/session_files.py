"""User-visible session lifecycle; all transcript filesystem work is off-thread."""
import json
import os
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import QObject, Property, QProcess, QTimer, QUrl, Signal, Slot
import shiboken6

from .pi_runtime import node_executable, CREATE_NO_WINDOW


class SessionFiles(QObject):
    changed = Signal()
    failureChanged = Signal()

    def __init__(self, backend):
        super().__init__(backend)
        self.b = backend
        self.pending = set()
        self.deleted = set()
        self._busy = False
        self._failure = {}
        self._job = None

    @Property(bool, notify=changed)
    def busy(self): return self._busy

    @Property('QVariantMap', notify=failureChanged)
    def failure(self): return self._failure

    @Slot()
    def dismissFailure(self):
        self._failure = {}
        self.failureChanged.emit()

    def fail(self, title, errors):
        self._failure = {'title': title, 'details': '\n\n'.join(
            (str(row.get('name', '')) + '\n' + str(row.get('error', '操作失败'))).strip()
            for row in errors[:20])}
        self.failureChanged.emit()

    def _workspace(self, value):
        return self.b._project_workspace_key(value) if value else ''

    def _sessions(self, project):
        key = self._workspace(project['path'])
        return [dict(row) for row in self.b._sessions if self._workspace(row.get('workspace')) == key]

    @Slot(str, result='QVariantMap')
    def projectSummary(self, identifier):
        project = next((p for p in self.b.store.data['projects'] if p['id'] == identifier), None)
        if not project: return {}
        key = self._workspace(project['path'])
        running = any(self.b._pool.protected(record) for record in self.b._pool.records.values()
                      if self._workspace(record.workspace) == key)
        return {'count': len(self._sessions(project)), 'busy': running or self.busy}

    def _execute(self, payload):
        result = subprocess.run([node_executable(), str(self.b.root/'runtime/session-files.mjs')],
            input=json.dumps(payload), capture_output=True, text=True, encoding='utf-8',
            timeout=180, creationflags=CREATE_NO_WINDOW)
        value = json.loads(result.stdout)
        if result.returncode or not value.get('ok'): raise RuntimeError(value.get('error', '会话文件操作失败'))
        return value

    def _start(self, payload, context):
        self._busy = True
        self._job = (payload, context)
        self.changed.emit()
        self.b._job('session-files', lambda: self._execute(payload))

    @Slot(str, str)
    def importFiles(self, raw, project_id=''):
        if self.busy:
            self.b.toast.emit('请等待当前会话文件操作完成'); return
        project = next((p for p in self.b.store.data['projects'] if p['id'] == project_id), None)
        if project_id and project is None: return
        sources = []
        try:
            for value in json.loads(raw):
                url = QUrl(value)
                if not url.isLocalFile(): raise ValueError('仅支持本地 JSONL 会话文件')
                sources.append(url.toLocalFile())
            if not 1 <= len(sources) <= 20: raise ValueError('每次可导入 1–20 个会话文件')
        except (ValueError, TypeError) as error:
            self.fail('无法导入会话', [{'error': str(error)}]); return
        workspace = project['path'] if project else ''
        self._start({'operation': 'import', 'sources': sources,
            'profile': str(self.b.store.directory),
            'sessionDir': str(self.b.store.directory/'pi/sessions'),
            'cwd': workspace or str(self.b.store.directory/'workspace')}, {'workspace': workspace, 'project': project_id})

    @Slot(str)
    def deleteSession(self, identifier):
        session = next((dict(s) for s in self.b._sessions if s['id'] == identifier), None)
        if session: self._delete([session], '')

    @Slot(str)
    def deleteProject(self, identifier):
        project = next((p for p in self.b.store.data['projects'] if p['id'] == identifier), None)
        if project: self._delete(self._sessions(project), identifier)

    def _delete(self, sessions, project_id):
        if self.busy:
            self.b.toast.emit('请等待当前会话文件操作完成'); return
        b = self.b
        ids = {s['id'] for s in sessions}
        project = next((p for p in b.store.data['projects'] if p['id'] == project_id), None)
        key = self._workspace(project['path']) if project else None
        records = [r for r in b._pool.records.values() if r.id in ids or
                   key is not None and self._workspace(r.workspace) == key]
        if any(b._pool.protected(r) for r in records) or ids & b._management_jobs:
            b.toast.emit('此会话或项目仍有任务运行，请先停止任务'); return
        self._busy = True
        self.pending = ids | {record.id for record in records}
        self.changed.emit()
        processes = [r.process for r in records if r.process]
        # Close search/index writers before purging their plaintext projections.
        b._session_preview.cancel()
        b._chat_search.clear()
        search = b._chat_search.retire()
        if search: processes.append(search)
        b._subagents.forget(records)
        for record in records: b._pool.retire(record)
        writers = tuple(b._dsh_history.pending)
        payload = {'operation': 'delete', 'profile': str(b.store.directory), 'sessions': sessions}
        if project: payload['workspace'] = project['path']
        self._job = (payload, {'project': project_id, 'records': records})
        started = time.monotonic()
        def drained():
            alive = [p for p in processes if shiboken6.isValid(p) and p.state() != QProcess.NotRunning]
            if alive and time.monotonic() - started < 15:
                QTimer.singleShot(30, drained); return
            if alive:
                self.complete({'ok': False, 'value': '会话进程尚未退出，未删除会话数据'}); return
            if search and shiboken6.isValid(search): search.deleteLater()
            def work():
                # A pending large-history index must finish before its database
                # is removed, otherwise it could recreate the deleted cache.
                for future in writers: future.result(timeout=15)
                for session in sessions:
                    if session.get('file'): b.transcripts.discard(session['file'])
                result = self._execute(payload)
                if (b.store.directory/'tasks.sqlite3').is_file():
                    from .task_records import TaskStore
                    TaskStore(b.store.directory/'tasks.sqlite3').erase_sessions({row['id'] for row in result['deleted']})
                return result
            b._job('session-files', work)
        drained()

    def complete(self, result):
        if not self._job: return
        payload, context = self._job
        self._job = None
        b = self.b
        self._busy = False
        self.pending.clear()
        self.changed.emit()
        if not result['ok']:
            self.fail('无法导入会话' if payload['operation'] == 'import' else '会话未能完全删除', [{'error': str(result['value'])}]); return
        value = result['value']
        if payload['operation'] == 'import':
            for session in value['sessions']:
                session['workspace'] = context['workspace']
                b._sessions.insert(0, session)
                project = next((p for p in b.store.data['projects'] if p['id'] == context['project']), None)
                if project and project.get('archived'):
                    b.store.data['sessionMeta'][session['id']] = {'archived': True}
            if value['sessions']:
                b.store.save()
                b.store.save_sessions(b._sessions)
                b.toast.emit('会话导入成功')
        else:
            ids = {row['id'] for row in value['deleted']}
            clear_current = b._view.id in ids or bool(context['project'] and not value['errors'] and b.store.data['activeProject'] == context['project'])
            self.deleted.update(ids)
            b._desktop_plugins.global_agents.forget_sessions(ids, [record.key for record in context['records']])
            b._sessions = [row for row in b._sessions if row['id'] not in ids]
            for identifier in ids: b.store.data['sessionMeta'].pop(identifier, None)
            for record in context['records']:
                if record.id in ids or not record.id and not value['errors']:
                    b._conversation_views.discard(record.key)
                    b._pool._clear_body(record)
                    record.messages, record.history, record.tree = [], [], []
                    record.attachments, record.queue, record.subagents = [], [], {}
                    record.draft, record.transcript = '', None
                    record.loaded, record.body_bytes = False, 0
                    b._pool.records.pop(record.key, None)
                    for workspace, draft in list(b._project_drafts.items()):
                        if draft is record: b._project_drafts.pop(workspace, None)
            project_id = context['project']
            if project_id and not value['errors']:
                b.store.data['projects'] = [p for p in b.store.data['projects'] if p['id'] != project_id]
                if project_id not in b.store.data['removedProjects']: b.store.data['removedProjects'].append(project_id)
            if clear_current:
                if b._view.id in ids: b._view.id = ''
                if project_id: b.store.data.update(activeProject='', workspace='')
                b._clear_current()
            b.store.save()
            b.store.save_sessions(b._sessions)
            b._task_records.changed.emit()
            if not value['errors']: b.toast.emit('项目及会话数据已删除' if project_id else '会话及数据已删除')
        if value['errors']:
            self.fail('无法导入会话' if payload['operation'] == 'import' else '会话未能完全删除', value['errors'])
        b.changed.emit()
        b.chatChanged.emit()
