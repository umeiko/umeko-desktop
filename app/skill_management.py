"""Widget-only native skill jobs, scoped to the requesting chat and workspace."""
from __future__ import annotations

import copy
import json
import subprocess
import uuid
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication

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
    if isinstance(payload.get('skills'), list):
        from .bundled_skills import describe_bundled
        describe_bundled(payload['skills'], agent_dir)
    return payload


class SkillJobs(QObject):
    """Scoped host jobs; direct additions never replace existing Skill folders."""

    def __init__(self, host):
        super().__init__(host)
        self.host, self.b = host, host.b
        self.jobs = OrderedDict()
        self.catalog = {}
        self.previews = {}
        self.folders = {}
        self.catalog_owners = {}
        self.b.jobDone.connect(self._finished)

    def idle(self):
        if self.b.busy or self.b.kernelBusy or self.b.piManagement.busy or any(
                row['status'] == 'running' and row['operation'] != 'skills.preview' for row in self.jobs.values()):
            raise ValueError('Pi is busy; retry when the chat and management jobs are idle')

    def _context(self, request):
        self.host._owner(request)
        record = self.b._view
        if record.key != request['session']['token'] or record.workspace != request['session']['workspace']:
            raise ValueError('The target chat or workspace changed')
        return record

    def get(self, request, identifier, offset=0, limit=100):
        row = self.jobs.get(identifier)
        owner = row and row['owner']
        if not owner or owner['widget'] != request['widget'] or owner['worker'] is not request['worker'] or any(
                owner['session'].get(k) != request['session'].get(k) for k in ('token', 'workspace')):
            raise ValueError('Host job does not belong to this Widget instance and chat')
        result = row['result']
        # Page the completed job's immutable snapshot, never rerun discovery for
        # a next page. The byte budget also covers long paths and UTF-8 metadata.
        field = 'skills' if isinstance(result.get('skills'), list) else 'preview.skills'
        values = result.get('skills') if field == 'skills' else result.get('preview', {}).get('skills')
        if isinstance(values, list):
            if offset > len(values):
                raise ValueError('Skill page offset exceeds the snapshot size')
            result = dict(result)
            container = result
            if field == 'preview.skills':
                result['preview'] = dict(result['preview'])
                container = result['preview']
            container['skills'] = page = []
            result['skillsPage'] = info = {'offset': offset, 'total': len(values), 'nextOffset': None, 'field': field}
            budget = 192 * 1024 - len(json.dumps(result, ensure_ascii=False).encode('utf-8'))
            used = 0
            for value in values[offset:offset + limit]:
                size = len(json.dumps(value, ensure_ascii=False).encode('utf-8')) + 2
                if used + size > budget:
                    if not page:
                        raise ValueError('A skill entry exceeds the host page size')
                    break
                page.append(value)
                used += size
            end = offset + len(page)
            info['nextOffset'] = end if end < len(values) else None
        return {'ok': True, 'jobs': [{'id': row['id'], 'status': row['status'], 'result': result}]}

    def preview_for(self, request, identifier):
        preview = self.previews.get(identifier)
        owner = preview and preview['owner']
        if not owner or owner['widget'] != request['widget'] or owner['worker'] is not request['worker'] or any(
                owner['session'].get(k) != request['session'].get(k) for k in ('token', 'workspace')):
            raise ValueError('Import preview does not belong to this Widget and chat')
        if preview['value'].get('errors'):
            raise ValueError('Resolve import validation errors first')
        return preview

    def folder_for(self, request, identifier):
        record = self._context(request)
        folder = self.folders.get((record.key, record.workspace), {}).get(identifier)
        if not folder:
            raise ValueError('请刷新当前工作区和全局 Skill 目录后重试')
        _, cwd, agent_dir, _ = self.b.piManagement._context()
        current_root = Path(agent_dir).resolve() / 'skills' if folder['scope'] == 'global' else Path(cwd).resolve() / '.pi/skills'
        if current_root != folder['root'] or folder['scope'] == 'project' and not record.workspace:
            raise ValueError('Skill 目录配置已变化，请刷新后重试')
        return folder

    def start(self, request):
        record = self._context(request)
        operation, args = request['operation'], request['arguments']
        direct_import = operation in ('skills.paste', 'skills.importLocal')
        folder_reads = ('skills.browse', 'skills.preview', 'skills.open', 'skills.copy', 'skills.insert')
        if operation not in folder_reads:
            self.idle()
        elif any(row['status'] == 'running' and row['operation'] != 'skills.preview' for row in self.jobs.values()):
            raise ValueError('Skill manager is busy; retry shortly')
        release, cwd, agent_dir, agent = self.b.piManagement._context()
        key = (record.key, record.workspace)
        rows = self.catalog.get(key, [])
        row = next((row for row in rows if row['id'] == args.get('id')), None)
        if operation not in ('skills.list', 'skills.browse', 'skills.paste', 'skills.importLocal', 'skills.importPreview', 'skills.import') and not row:
            raise ValueError('Refresh the current skill catalog first')
        if operation == 'skills.default' and not row.get('defaultMutable'):
            raise ValueError(row.get('defaultReason') or 'This source has no global default switch')
        if operation == 'skills.remove' and not row.get('removable'):
            raise ValueError('Only a registered Pi package can be removed')
        loaded = copy.deepcopy(list(record.known_skills.values()))
        for item in record.resources.get('skills', []):
            if item.get('filePath') or item.get('path'):
                loaded.append(copy.deepcopy(item))
        options = dict(sessionSkills=copy.deepcopy(record.skill_modes), loadedSkills=loaded,
                       skillsEnabled=self.host.m.skills_enabled(record))
        preview = self.preview_for(request, args['id']) if operation == 'skills.import' else None
        destination = (Path(cwd) / '.pi/skills' if args.get('project') else Path(agent_dir) / 'skills') if operation == 'skills.importPreview' or direct_import else None
        folder_import = key in self.folders
        import_rows = rows
        if destination is not None and (folder_import or direct_import):
            import_rows = [row for row in rows if Path(row['path']).parent.is_relative_to(destination.resolve())]
        if destination is not None and args.get('project') and not record.workspace:
            raise ValueError('Choose a project before importing project skills')
        folder_ops = ('skills.preview', 'skills.open', 'skills.copy', 'skills.insert', 'skills.rename', 'skills.delete')
        folder = self.folder_for(request, args['id']) if operation in folder_ops else None
        clipboard_source = ''
        if operation == 'skills.paste':
            data = QGuiApplication.clipboard().mimeData()
            urls = data.urls() if data and data.hasUrls() else []
            if len(urls) != 1 or not urls[0].isLocalFile():
                raise ValueError('请先复制一个本地 Skill 文件夹或压缩包')
            clipboard_source = urls[0].toLocalFile()
        def run():
            if operation == 'skills.browse':
                from .skill_folders import folder_snapshots
                roots = {'global': Path(agent_dir).resolve() / 'skills'}
                if record.workspace:
                    roots['project'] = Path(cwd).resolve() / '.pi/skills'
                value = skill_command(release, Path(cwd).resolve(), Path(agent_dir).resolve(), agent,
                                      action='browse', includeProject=bool(record.workspace))
                value['roots'] = {scope: str(path) for scope, path in roots.items()}
                value['_folderApprovals'] = folder_snapshots(value, roots)
                return value
            if operation in folder_ops:
                from .skill_folders import checked_folder, rename_folder, delete_folder
                directory = checked_folder(folder)
                if operation == 'skills.preview':
                    from .skill_folders import preview_folder
                    return {'ok': True, 'details': {'id': args['id'], **preview_folder(folder)}}
                if operation == 'skills.rename':
                    directory = rename_folder(folder, args['name'])
                elif operation == 'skills.delete':
                    delete_folder(folder)
                return {'ok': True, 'directory': str(directory)}
            if operation == 'skills.importPreview' or direct_import:
                from .skill_import import preview_import
                source = clipboard_source if operation == 'skills.paste' else args['source']
                url = QUrl(source)
                if url.scheme() == 'file':
                    if not url.isLocalFile() or url.host() not in ('', 'localhost'):
                        raise ValueError('请选择本地 Skill 文件夹或压缩包')
                    source = url.toLocalFile()
                def validate(documents):
                    return skill_command(release, cwd, agent_dir, agent, action='validateText', documents=documents)['documents']
                if direct_import:
                    from .skill_import import import_local
                    value = import_local(source, destination, import_rows, validate)
                    return {'ok': not bool(value['errors']), **value,
                            'error': '\n'.join(row['name'] + ': ' + row['error'] for row in value['errors'][:8])}
                return {'ok': True, 'preview': preview_import(source, destination, import_rows, validate,
                                                             preserve_folder_names=folder_import)}
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
            elif operation in ('skills.list', 'skills.browse'):
                self.catalog_owners[(record.key, record.workspace)] = job['owner']
                if operation == 'skills.browse':
                    self.folders[(record.key, record.workspace)] = value.pop('_folderApprovals')
                self.catalog[(record.key, record.workspace)] = value['skills']
                for item in record.resources.get('skills', []):
                    path = item.get('filePath') or item.get('path')
                    if path: record.known_skills[path] = copy.deepcopy(item)
            elif operation == 'skills.reveal':
                if not QDesktopServices.openUrl(QUrl.fromLocalFile(value['directory'])):
                    raise ValueError('Could not open the containing folder')
            elif operation in ('skills.open', 'skills.copy', 'skills.insert'):
                from .skill_folders import checked_folder
                directory = checked_folder(self.folder_for(job['owner'], job['owner']['arguments']['id']))
                args = job['owner']['arguments']
                if operation == 'skills.insert':
                    self.b.attachChatboxFile(str(directory))
                elif operation == 'skills.copy':
                    if args['kind'] == 'path':
                        QGuiApplication.clipboard().setText(str(directory))
                    else:
                        from .plugin_file_actions import copy_files
                        copy_files([directory])
                elif args['mode'] == 'preview':
                    self.b.widgetDocumentRequested.emit(str(directory / 'SKILL.md'), directory.name, 'file', job['owner']['widget'])
                elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory if args['mode'] == 'reveal' else directory / 'SKILL.md'))):
                    raise ValueError('无法打开文件，请检查系统文件关联')
            elif operation in ('skills.default', 'skills.remove', 'skills.import', 'skills.paste', 'skills.importLocal', 'skills.rename', 'skills.delete'):
                # Native settings changed. Preserve all chat overrides.
                self.b._restart_pi()
                if operation == 'skills.import': self.previews.pop(job['owner']['arguments']['id'], None)
            job['result'], job['status'] = value, 'completed'
        except (ValueError, TypeError, KeyError, OSError, RuntimeError) as error:
            job['result'], job['status'] = {'ok': False, 'error': str(error)[:800]}, 'failed'

    def stop(self, widget):
        for key in [key for key, owner in self.catalog_owners.items() if owner['widget'] == widget]:
            self.catalog_owners.pop(key)
            self.catalog.pop(key, None)
            self.folders.pop(key, None)
        if self.previews:
            from .skill_import import discard_import
            for key in [key for key, value in self.previews.items() if value['owner']['widget'] == widget]:
                discard_import(self.previews.pop(key)['value'])
        for key in [key for key, value in self.jobs.items() if value['owner']['widget'] == widget]:
            self.jobs.pop(key)
