"""Persisted desktop presentation, appearance and provider transport settings."""
import json
import logging
import math
import sys
import urllib.parse
from pathlib import Path
from PySide6.QtCore import Slot, QUrl
from PySide6.QtGui import QDesktopServices
from .gateway import (
    validate_base_url,
    validate_request_max_retries,
    validate_stream_idle_timeout_seconds,
    validate_stream_max_retries,
)
from umeko_provider_sdk.network import validate_ca_file


class PreferencesMixin:
    @Slot()
    def configureCliPath(self):
        from .cli_path import configure_path, packaged_cli
        try:
            launcher = packaged_cli()
            if launcher is None:
                raise ValueError('packaged CLI launcher unavailable')
            configure_path(launcher)
        except (OSError, ValueError, KeyError) as error:
            logging.getLogger(__name__).warning('Could not configure CLI PATH: %s', error)
            self.toast.emit('无法配置 CLI 到 PATH，请参照 Umeko CLI 与 ACP 文档手动设置。')
        else:
            self.toast.emit('已配置 CLI 到 PATH，请关闭并重新打开终端。')

    @Slot(str, result=bool)
    def saveRequestHeaders(self, raw):
        from .request_headers import validate
        old = self.store.data.get('requestHeaders')
        try:
            value = validate(json.loads(raw))
            if value == old:
                return True
            self.store.data['requestHeaders'] = value
            self.store.save()
        except (ValueError, OSError, RuntimeError) as error:
            if old is None:
                self.store.data.pop('requestHeaders', None)
            else:
                self.store.data['requestHeaders'] = old
            self.toast.emit(str(error))
            return False
        self.changed.emit()
        self.toast.emit('请求头已保存，将用于后续模型请求')
        return True

    @Slot(int, result=bool)
    def setSessionCacheSize(self, size):
        if type(size) is not int or not 0 <= size <= 2147483647:
            return False
        ui = self.store.data['ui']
        previous = ui['sessionCacheSize']
        if previous == size:
            return True
        ui['sessionCacheSize'] = size
        try:
            self.store.save()
        except (OSError, RuntimeError) as error:
            ui['sessionCacheSize'] = previous
            self.toast.emit(str(error))
            return False
        self._pool.limit = size
        self._pool.trim()
        self.changed.emit()
        return True

    @Slot(str, result=bool)
    def saveMultimodalSettings(self, raw):
        from .multimodal_settings import normalize, validate
        from .generation import capabilities
        old = self.store.data['multimodal']
        try:
            if self._models_busy():
                raise ValueError('请等待当前任务结束后修改多模态设置')
            patch = validate(json.loads(raw))
            value = normalize({kind: {**row, **patch.get(kind, {})} for kind, row in old.items()})
            for kind in patch:
                row = value[kind]
                if not row['providerId']:
                    row['model'] = ''
                    continue
                provider = self.gateway.provider(row['providerId'])
                if not provider or kind not in capabilities(provider):
                    raise ValueError('请选择支持该生成功能的供应商')
                if not row['model']:
                    raise ValueError('请输入模型 ID')
                if provider.get('api') == 'image':
                    from .image_providers import parameters
                    parameters(provider, row['model'], row)
                if kind == 'speech' and provider.get('api') != 'plugin' and not row['voice']:
                    raise ValueError('请输入供应商支持的音色 ID')
            if value == old:
                return True
            self.store.data['multimodal'] = value
            self.store.save()
        except (ValueError, OSError, RuntimeError) as error:
            self.store.data['multimodal'] = old
            self.toast.emit(str(error))
            return False
        self._restart_pi()
        self.changed.emit()
        self.toast.emit('多模态设置已保存')
        return True

    @Slot(str, result=bool)
    def saveDesktopSettings(self, raw):
        from .desktop_preferences import validate_patch, normalize
        from .webview import configuration
        old = self.store.data['desktop']
        try:
            patch = validate_patch(json.loads(raw))
            value = normalize({**old, **patch})
            if sys.platform == 'win32' and value['preferGitBash'] and {'preferGitBash', 'gitBashPath'} & patch.keys():
                from .git_for_windows import find_git_bash
                if not find_git_bash(value['gitBashPath']):
                    raise ValueError('找不到 Git for Windows 的 bash.exe。请将 Git Bash 加入 PATH，或填写 bash.exe 的完整路径。')
            if value == old: return True
            self.store.data['desktop'] = value
            self.store.save()
        except (ValueError, OSError, RuntimeError) as error:
            self.store.data['desktop'] = old
            self.toast.emit(str(error)); return False
        if any(value[key] != old[key] for key in ('autoOpenSubmissions', 'webDisplay')):
            self.documentPreview.refreshWebPolicy()
            pool = getattr(self, '_pool', None)
            if pool:
                policy = configuration(value)
                for record in tuple(pool.records.values()):
                    if record.process:
                        pool.write(record, {'type':'desktop_settings', 'webview':policy})
        if old['remoteWorkspaceEnabled'] != value['remoteWorkspaceEnabled']:
            self._remote_workspace_tools_changed()
        if sys.platform == 'win32' and any(value[key] != old[key] for key in ('preferGitBash', 'gitBashPath')):
            self.windowsSandbox.publish()
        if (pool := getattr(self, '_pool', None)):
            limit = self.desktopSettings['subagentConcurrency']
            if pool.subagent_admission.limit != limit:
                pool.subagent_admission.set_limit(limit)
        self.desktopSettingsChanged.emit()
        if old['webDisplay'] != value['webDisplay'] and value['webDisplay'] == 'embedded' and configuration().get('disabled'):
            self.toast.emit('重启 Umeko 后可使用内置网页预览')
        return True

    def _remote_network_settings_changed(self):
        from .remote_environments import network_config
        self.remoteEnvironmentsChanged.emit()
        payload = {'type': 'desktop_settings', 'remoteNetwork': network_config(self.store)}
        self._remote_service.refresh_network()
        for record in tuple(self._pool.records.values()):
            if record.process:
                self._pool.write(record, payload)

    def _save_remote_network_setting(self, name, value):
        old = self.store.data.get(name)
        if old == value:
            return True
        self.store.data[name] = value
        try:
            self.store.save()
        except (OSError, RuntimeError) as error:
            if old is None:
                self.store.data.pop(name, None)
            else:
                self.store.data[name] = old
            self.toast.emit(str(error))
            return False
        self._remote_network_settings_changed()
        return True

    @Slot(bool, result=bool)
    def setRemoteNetworkEnabled(self, enabled):
        return self._save_remote_network_setting('remoteNetworkEnabled', enabled)

    @Slot(str, result=bool)
    def setRemoteNetworkProxy(self, address):
        address = address.strip()
        if address:
            try:
                value = urllib.parse.urlsplit(address)
                valid = (value.scheme in ('http', 'https', 'socks5', 'socks5h') and value.hostname
                         and value.port != 0 and not value.username and not value.password
                         and value.path in ('', '/') and not value.query and not value.fragment)
            except ValueError:
                valid = False
            if not valid:
                self.toast.emit('请输入不含凭据的 HTTP、HTTPS 或 SOCKS5 代理地址')
                return False
        return self._save_remote_network_setting('remoteNetworkProxy', address)

    def _open_browser(self, url):
        try:
            if QDesktopServices.openUrl(url): return True
        except OSError: pass
        self.toast.emit('无法打开系统默认浏览器')
        return False

    @Slot(str, str, result=bool)
    def openWebPreview(self, raw, title):
        url = self.normalizeWebUrl(raw)
        if not url: return False
        if self.store.data['desktop']['webDisplay'] == 'external':
            return self._open_browser(QUrl(url))
        if not self.webviewAvailable:
            self.toast.emit('网页预览组件尚未安装或无法加载'); return False
        self.webRequested.emit(url, title)
        return True

    @Slot(str, result=bool)
    def openExternalHtml(self, raw):
        path = Path(raw)
        if self.store.data['desktop']['webDisplay'] != 'external' or path.suffix.lower() not in ('.html', '.htm'):
            return False
        if path.is_absolute() and path.is_file():
            self._open_browser(QUrl.fromLocalFile(str(path)))
        else:
            self.toast.emit('文件已移动或不存在')
        return True

    @Slot(str)
    def setLanguage(self, language):
        if language not in ('zh', 'en') or language == self.language:
            return
        self.store.data['ui']['language'] = language
        self.store.save()
        # Pi's extension UI language is read in its startup payload.
        self._restart_pi()
        self.appearanceChanged.emit()

    @Slot(float)
    def setFontScale(self, scale):
        if not math.isfinite(scale):
            return
        scale = round(max(.3, min(2., scale)), 2)
        if scale == self.fontScale:
            return
        self.store.data['ui']['fontScale'] = scale
        self.appearanceChanged.emit()
        self._appearance_save.start()

    @Slot(str)
    def setLineSpacing(self, spacing):
        if spacing not in ('compact', 'standard', 'relaxed') or spacing == self.lineSpacing:
            return
        self.store.data['ui']['lineSpacing'] = spacing
        self.appearanceChanged.emit()
        self._appearance_save.start()

    @Slot(str, str, str, result=bool)
    def setProviderProxy(self, identifier, mode, address):
        provider = self.gateway.provider(identifier) or {}
        return self.setProviderNetwork(identifier, mode, address, provider.get('proxy', {}).get('caFile', ''))

    @Slot(str, str, result=bool)
    def setProviderCertificate(self, identifier, ca_file):
        proxy = (self.gateway.provider(identifier) or {}).get('proxy', {})
        return self.setProviderNetwork(identifier, proxy.get('mode', 'system'), proxy.get('url', ''), ca_file)

    @Slot(str, str, str, str, result=bool)
    def setProviderNetwork(self, identifier, mode, address, ca_file):
        return self._save_provider_network(identifier, mode, address, ca_file, update_timeout=False)

    @Slot(str, str, str, str, str, result=bool)
    def setProviderNetworkWithTimeout(self, identifier, mode, address, ca_file, stream_idle_timeout_sec):
        return self._save_provider_network(identifier, mode, address, ca_file,
                                           stream_idle_timeout_sec=stream_idle_timeout_sec, update_timeout=True)

    @Slot(str, str, str, str, str, str, str, result=bool)
    def setProviderNetworkConfig(self, identifier, mode, address, ca_file,
                                 stream_idle_timeout_sec, stream_max_retries, request_max_retries):
        return self._save_provider_network(
            identifier, mode, address, ca_file,
            stream_idle_timeout_sec=stream_idle_timeout_sec,
            stream_max_retries=stream_max_retries,
            request_max_retries=request_max_retries,
            update_timeout=True,
            update_retries=True,
        )

    @Slot(str, str, str, str, result=bool)
    def setProviderTimeouts(self, identifier, stream_idle_timeout_sec, stream_max_retries, request_max_retries):
        proxy = (self.gateway.provider(identifier) or {}).get('proxy', {})
        return self._save_provider_network(
            identifier,
            proxy.get('mode', 'system'),
            proxy.get('url', ''),
            proxy.get('caFile', ''),
            stream_idle_timeout_sec=stream_idle_timeout_sec,
            stream_max_retries=stream_max_retries,
            request_max_retries=request_max_retries,
            update_timeout=True,
            update_retries=True,
        )

    def _save_provider_network(self, identifier, mode, address, ca_file,
                               stream_idle_timeout_sec='', stream_max_retries='', request_max_retries='',
                               *, update_timeout=False, update_retries=False):
        try:
            provider = self.gateway.provider(identifier)
            if not provider or mode not in ('system', 'direct', 'custom'):
                raise ValueError('代理设置无效')
            if self._models_busy(identifier):
                raise ValueError('该供应商仍有任务运行')
            if provider['api'] == 'plugin':
                self._provider_plugins._idle(identifier)
            url = validate_base_url(address) if mode == 'custom' else ''
            if url and urllib.parse.urlsplit(url).path not in ('', '/'):
                raise ValueError('请输入有效的 HTTP / HTTPS 代理地址')
            if url:
                port = urllib.parse.urlsplit(url).port
                if port is not None and not 1 <= port <= 65535:
                    raise ValueError('请输入有效的 HTTP / HTTPS 代理地址')
            ca_file = validate_ca_file(ca_file)
            timeout_ms = validate_stream_idle_timeout_seconds(stream_idle_timeout_sec) if update_timeout else None
            stream_retries = validate_stream_max_retries(stream_max_retries) if update_retries else None
            request_retries = validate_request_max_retries(request_max_retries) if update_retries else None
            provider['proxy'] = {'mode': mode, 'url': url, **({'caFile': ca_file} if ca_file else {})}
            if update_timeout:
                if timeout_ms is None:
                    provider.pop('streamIdleTimeoutMs', None)
                else:
                    provider['streamIdleTimeoutMs'] = timeout_ms
            if update_retries:
                if stream_retries is None:
                    provider.pop('streamMaxRetries', None)
                else:
                    provider['streamMaxRetries'] = stream_retries
                if request_retries is None:
                    provider.pop('requestMaxRetries', None)
                else:
                    provider['requestMaxRetries'] = request_retries
            if provider['api'] == 'plugin':
                self._provider_plugins._invalidate(identifier)
            self.store.save()
            self._restart_pi()
            self.changed.emit()
            return True
        except (ValueError, RuntimeError) as error:
            self.toast.emit(str(error))
            return False

    @Slot(str, result=str)
    def requestReport(self, identifier):
        return self.gateway.diagnostics.read(identifier)

    @Slot(str)
    def showRequestDetails(self, identifier):
        self.requestDetailsRequested.emit(identifier)
