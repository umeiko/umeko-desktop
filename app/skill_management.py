"""Widget-only native skill jobs, scoped to the requesting chat and workspace."""
from __future__ import annotations

import copy
import json
import subprocess
import uuid
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QDesktopServices

from .npm_config import npm_environment
from .pi_runtime import CREATE_NO_WINDOW, node_executable
from .pi_install import remove_package


def skill_command(release, cwd, agent_dir, agent, **action):
    environment = npm_environment(agent)
    environment['PI_OFFLINE'] = '1'
    environment.pop('NODE_OPTIONS', None)
    environment.pop('NODE_PATH', None)
    result = subprocess.run([node_executable(), str(release / 'skills.mjs')],
        input=json.dumps({'cwd': str(cwd), 'agentDir': str(agent_dir), 'agent': agent, **action}),
        capture_output=True, text=True, encoding='utf-8', timeout=45,
        env=environment, creationflags=CREATE_NO_WINDOW)
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        raise RuntimeError('Skill discovery failed') from None
    if result.returncode or not payload.get('ok'):
        raise RuntimeError(payload.get('error', 'Skill operation failed'))
    return payload


class SkillJobs(QObject):
    """No approval entrypoint: WidgetHost starts writes only after host confirmation."""

    def __init__(self, host):
        super().__init__(host)
        self.host, self.b = host, host.b
        self.jobs = OrderedDict()
        self.catalog = {}
        self.previews = {}
        self.b.jobDone.connect(self._finished)

    def idle(self):
        if self.b.busy or self.b.kernelBusy or self.b.piManagement.busy or any(
                row['status'] == 'running' for row in self.jobs.values()):
            raise ValueError('Pi is busy; retry when the chat and management jobs are idle')

    def _context(self, request):
        self.host._owner(request)
        record = self.b._view
        if record.key != request['session']['token'] or record.workspace != request['session']['workspace']:
            raise ValueError('The target chat or workspace changed')
        return record

    def get(self, request, identifier):
        row = self.jobs.get(identifier)
        owner = row and row['owner']
        if not owner or owner['widget'] != request['widget'] or owner['worker'] is not request['worker'] or any(
                owner['session'].get(k) != request['session'].get(k) for k in ('token', 'workspace')):
            raise ValueError('Host job does not belong to this Widget instance and chat')
        return {'ok': True, 'jobs': [{key: row[key] for key in ('id', 'status', 'result')}]}

    def preview_for(self, request, identifier):
        preview = self.previews.get(identifier)
        owner = preview and preview['owner']
        if not owner or owner['widget'] != request['widget'] or owner['worker'] is not request['worker'] or any(
                owner['session'].get(k) != request['session'].get(k) for k in ('token', 'workspace')):
            raise ValueError('Import preview does not belong to this Widget and chat')
        if preview['value'].get('errors'):
            raise ValueError('Resolve import validation errors first')
        return preview

    def start(self, request):
        record = self._context(request)
        self.idle()
        operation, args = request['operation'], request['arguments']
        release, cwd, agent_dir, agent = self.b.piManagement._context()
        key = (record.key, record.workspace)
        rows = self.catalog.get(key, [])
        row = next((row for row in rows if row['id'] == args.get('id')), None)
        if operation not in ('skills.list', 'skills.importPreview', 'skills.import') and not row:
            raise ValueError('Refresh the current skill catalog first')
        if operation == 'skills.default' and not row.get('defaultMutable'):
            raise ValueError(row.get('defaultReason') or 'This source has no global default switch')
        if operation == 'skills.remove' and not row.get('removable'):
            raise ValueError('Only a registered Pi package can be removed')
        loaded = copy.deepcopy(list(record.known_skills.values()))
        for item in record.resources.get('skills', []):
            if item.get('filePath') or item.get('path'):
                loaded.append(copy.deepcopy(item))
        options = dict(sessionSkills=copy.deepcopy(record.skill_modes), loadedSkills=loaded)
        preview = self.preview_for(request, args['id']) if operation == 'skills.import' else None
        destination = (Path(cwd) / '.pi/skills' if args.get('project') else Path(agent_dir) / 'skills') if operation == 'skills.importPreview' else None
        if operation == 'skills.importPreview' and args.get('project') and not record.workspace:
            raise ValueError('Choose a project before importing project skills')
        def run():
            if operation == 'skills.importPreview':
                from .skill_import import preview_import
                source = QUrl(args['source']).toLocalFile() if args['source'].startswith('file:') else args['source']
                def validate(documents):
                    return skill_command(release, cwd, agent_dir, agent, action='validateText', documents=documents)['documents']
                return {'ok': True, 'preview': preview_import(source, destination, rows, validate)}
            if operation == 'skills.import':
                from .skill_import import commit_import
                return {'ok': True, **commit_import(preview['value'], args.get('decisions', {}), preview['destination'])}
            if operation == 'skills.attach':
                return {'ok': True, 'path': row['path'], 'enabled': args['enabled']}
            if operation == 'skills.reveal':
                return {'ok': True, 'directory': str(Path(row['path']).parent)}
            if operation == 'skills.remove':
                source = row['packageSource']
                if source.startswith(('./', '../')):
                    base = Path(cwd) / '.pi' if row.get('scope') == 'project' else Path(agent_dir)
                    source = str((base / source).resolve())
                remove_package(release, cwd, agent_dir, source, row.get('scope') == 'project', npm_config=agent)
                return {'ok': True}
            action = {'skills.list': 'list', 'skills.details': 'details', 'skills.default': 'default'}[operation]
            return skill_command(release, cwd, agent_dir, agent, action=action, **args, **options)
        identifier = uuid.uuid4().hex
        self.jobs[identifier] = {'id': identifier, 'status': 'running', 'result': {},
            'owner': request, 'record': record, 'operation': operation, 'context': (str(release), str(cwd), str(agent_dir), agent),
            'destination': destination, 'project': args.get('project', False)}
        while len(self.jobs) > 128:
            completed = next((key for key, value in self.jobs.items() if value['status'] != 'running'), None)
            if completed is None: break
            self.jobs.pop(completed)
        self.b._job('widget-skills:' + identifier, run)
        return {'ok': True, 'accepted': True, 'jobId': identifier}

    def _finished(self, name, result):
        if not name.startswith('widget-skills:'): return
        job = self.jobs.get(name.split(':', 1)[1])
        if not job: return
        try:
            self._context(job['owner'])
            if not result['ok']: raise ValueError(str(result['value']))
            value, record, operation = result['value'], job['record'], job['operation']
            if operation == 'skills.attach':
                if record.busy or self.b.kernelBusy or self.b.piManagement.busy:
                    raise ValueError('The chat became busy; no chat change was applied')
                old = dict(record.skill_modes)
                record.skill_modes[value['path']] = value['enabled']
                try:
                    if record.id:
                        self.b.store.data['sessionMeta'].setdefault(record.id, {})['skillModes'] = dict(record.skill_modes)
                        self.b.store.save()
                except (OSError, RuntimeError):
                    record.skill_modes = old
                    self.b.store.data['sessionMeta'].setdefault(record.id, {})['skillModes'] = old
                    raise
                record.stale = True
                if record.process and not record.busy and not record.subagents_active:
                    self.b._pool.retire(record)
                self.b.changed.emit()
                self.b.chatChanged.emit()
            elif operation == 'skills.importPreview':
                preview = value['preview']
                identifier = preview['planId']
                self.previews[identifier] = {'owner': job['owner'], 'value': preview,
                    'destination': job['destination'], 'project': job['project']}
                value = {'ok': True, 'preview': {'id': identifier, 'skills': preview['skills'],
                    'errors': preview['errors'], 'project': job['project'], 'sourceName': Path(preview['source']).name}}
            elif operation == 'skills.list':
                self.catalog[(record.key, record.workspace)] = value['skills']
                for item in record.resources.get('skills', []):
                    path = item.get('filePath') or item.get('path')
                    if path: record.known_skills[path] = copy.deepcopy(item)
            elif operation == 'skills.reveal':
                if not QDesktopServices.openUrl(QUrl.fromLocalFile(value['directory'])):
                    raise ValueError('Could not open the containing folder')
            elif operation in ('skills.default', 'skills.remove', 'skills.import'):
                # Native settings changed. Preserve all chat overrides.
                self.b._restart_pi()
                if operation == 'skills.import': self.previews.pop(job['owner']['arguments']['id'], None)
            job['result'], job['status'] = value, 'completed'
        except (ValueError, TypeError, KeyError, OSError, RuntimeError) as error:
            job['result'], job['status'] = {'ok': False, 'error': str(error)[:800]}, 'failed'

    def stop(self, widget):
        if self.previews:
            from .skill_import import discard_import
            for key in [key for key, value in self.previews.items() if value['owner']['widget'] == widget]:
                discard_import(self.previews.pop(key)['value'])
        for key in [key for key, value in self.jobs.items() if value['owner']['widget'] == widget]:
            self.jobs.pop(key)
