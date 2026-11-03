"""Widget market jobs; installation remains owned by DesktopPlugins.importZip."""
from __future__ import annotations

import uuid
from PySide6.QtCore import QObject, QUrl, Slot

from .widget_market import MarketCatalog, is_newer


class MarketJobs(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host, self.m, self.b = host, host.m, host.b
        self.catalog = MarketCatalog(self.b.store.directory, root=self.b.root)
        self.prepared = {}
        self.active = None
        self.imports = {}
        self.b.jobDone.connect(self._finished)
        self.m.managed.connect(self._imported)

    def _tr(self, zh, en):
        return en if getattr(self.b, 'language', 'zh').startswith('en') else zh

    def _owned(self, request, token):
        item = self.prepared.get(token)
        if not item or item['worker'] is not request['worker'] or item['session'] != request['session']['token']:
            raise ValueError('Download confirmation expired; select the Widget again')
        return item

    def confirmation(self, request):
        operation, args = request['operation'], request['arguments']
        if operation == 'market.install':
            item = self._owned(request, args['token'])
            manifest = item['package']['manifest']
            verified = item['package']['digestVerified']
            digest = self._tr('GitHub SHA-256 已匹配。', 'GitHub SHA-256 matched.') if verified else self._tr(
                'GitHub 未提供附件摘要，无法核对下载摘要。', 'GitHub provides no asset digest; download digest verification is unavailable.')
            permissions = ', '.join(manifest.get('permissions', [])) or self._tr('无', 'None')
            return {'title': self._tr('导入 Widget ZIP', 'Import Widget ZIP'), 'detail': '\n\n'.join((
                manifest['name'] + ' · ' + manifest['version'], manifest.get('description', ''),
                self._tr('权限：', 'Permissions: ') + permissions, digest,
                self._tr('此插件可执行 Python 和 QML，请仅安装你信任的插件。',
                         'This plugin can execute Python and QML. Install only plugins you trust.'),
                self._tr('使用现有 ZIP 导入流程。用户配置会保留；新安装的 Widget 默认停用，请在插件管理中明确启用。',
                         'Uses ZIP import. User configuration is preserved. New Widgets stay disabled until you explicitly enable them in Plugin Management.')))}
        identifier = args['id']
        entry = self.m.entries.get(identifier, {})
        if not entry or entry.get('builtin'):
            raise ValueError('Only an installed external Widget can be uninstalled')
        return {'title': self._tr('卸载插件', 'Uninstall plugin'), 'detail': entry['name'] + ' · ' + entry['version']}

    def discard(self, request):
        token = request['arguments']['token']
        item = self._owned(request, token)
        self.prepared.pop(token)
        self.catalog.cleanup(item['package'])

    def declined(self, request):
        if request['operation'] == 'market.install':
            token = request['arguments'].get('token')
            try:
                item = self._owned(request, token)
            except ValueError:
                return
            self.prepared.pop(token)
            self.catalog.cleanup(item['package'])

    def stop(self, identifier):
        for token, item in list(self.prepared.items()):
            if item['widget'] == identifier:
                self.prepared.pop(token)
                self.catalog.cleanup(item['package'])

    def start(self, request):
        operation, args = request['operation'], request['arguments']
        if operation == 'market.discard':
            self.discard(request)
            self.host._reply(request, {'ok': True})
            return
        if operation == 'market.install':
            if self.m.busy:
                raise ValueError('Plugin management is busy; please retry')
            item = self._owned(request, args['token'])
            key = self.m.importZip(QUrl.fromLocalFile(str(item['package']['path'])).toString())
            if not key:
                self.declined(request)
                raise ValueError(self.m.status or 'Could not start ZIP import')
            self.prepared.pop(args['token'])
            self.imports[key] = (request, item['package'])
            return
        if operation == 'market.uninstall':
            self.confirmation(request)
            if not self.m.uninstall(args['id']):
                raise ValueError(self.m.status or 'Could not uninstall Widget')
            self.host._reply(request, {'ok': True, 'result': {'uninstalled': args['id']}})
            return
        if self.active:
            raise ValueError('The market is busy; please retry')
        # Only a visible, enabled market Widget may initiate a GET job.
        name = 'widget-market:' + uuid.uuid4().hex
        self.active = (name, request)
        def work():
            try:
                result = self.catalog.refresh(force=args.get('force', False)) if operation == 'market.list' else self.catalog.prepare(args['id'])
            except (ValueError, OSError) as error:
                # Keep English failures useful even when an existing ZIP validator
                # reports Chinese; preserve its original reason in Chinese UI.
                messages = {
                    'digest': 'The asset digest is invalid or the SHA-256 does not match. Installation was refused.',
                    'identity': 'The ZIP manifest ID or version does not match its release asset name.',
                    'archive': 'The ZIP failed the existing import validation (manifest, paths or size).',
                    'source': 'Only assets from the official Widget repository are allowed.',
                    'missing': 'The Widget is no longer in the cached catalog. Refresh the list.',
                    'rate-limit': 'GitHub is rate limiting requests. Retry later or import a local ZIP.',
                    'response': 'GitHub could not provide the asset. Retry or import a local ZIP.',
                    'network': 'GitHub is unreachable. Retry or import a local ZIP.',
                }
                code = getattr(error, 'code', 'archive')
                return {'marketError': self._tr(str(error), messages.get(code, messages['archive']))}
            if self.m.closed and operation == 'market.prepare':
                self.catalog.cleanup(result)
                return None
            return result
        self.b._job(name, work)

    @Slot(str, object)
    def _finished(self, name, result):
        if not self.active or self.active[0] != name:
            return
        _, request = self.active
        self.active = None
        value = result.get('value')
        try:
            self.host._owner(request)
            if not result.get('ok'):
                raise ValueError(str(value))
            if value and 'marketError' in value:
                raise ValueError(value['marketError'])
            if request['operation'] == 'market.prepare':
                token = uuid.uuid4().hex
                self.prepared[token] = {'package': value, 'widget': request['widget'],
                                        'worker': request['worker'], 'session': request['session']['token']}
                value = {'token': token}
            else:
                value = dict(value)
                rows = []
                for row in value['rows']:
                    entry = self.m.entries.get(row['id'], {})
                    installed = entry.get('version', '')
                    newer = bool(installed and is_newer(row['version'], installed))
                    rows.append({**row, 'installedVersion': installed,
                                 'state': 'update-available' if newer else 'installed' if installed else 'not-installed',
                                 'builtin': bool(entry.get('builtin'))})
                value['rows'] = rows
            self.host._reply(request, {'ok': True, 'result': value})
        except (ValueError, TypeError, KeyError) as error:
            if request['operation'] == 'market.prepare' and result.get('ok') and result.get('value') and 'path' in result['value']:
                self.catalog.cleanup(result['value'])
            self.host._reply(request, {'ok': False, 'error': str(error)})

    def _imported(self, key, result):
        pending = self.imports.pop(key, None)
        if not pending:
            return
        request, package = pending
        self.catalog.cleanup(package)
        value = {'ok': True, 'result': {'installed': package['manifest']['id']}} if result.get('ok') else result
        self.host._reply(request, value)
