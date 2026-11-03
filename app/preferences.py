"""Persisted desktop presentation, appearance and provider transport settings."""
import math
import json
import urllib.parse
from pathlib import Path
from PySide6.QtCore import Slot, QUrl
from PySide6.QtGui import QDesktopServices
from .gateway import validate_base_url
from umeko_provider_sdk.network import validate_ca_file


class PreferencesMixin:
    @Slot(str, result=bool)
    def saveMultimodalSettings(self, raw):
        from .multimodal_settings import normalize, validate
        old = self.store.data['multimodal']
        try:
            if self._models_busy():
                raise ValueError('请等待当前任务结束后修改多模态设置')
            patch = validate(json.loads(raw))
            value = normalize({kind: {**row, **patch.get(kind, {})} for kind, row in old.items()})
            for kind, row in value.items():
                if not row['providerId']:
                    row['model'] = ''
                    continue
                provider = self.gateway.provider(row['providerId'])
                if not provider or (provider['api'] != 'openai' and
                                    kind not in provider.get('generationCapabilities', [])):
                    raise ValueError('请选择支持该生成功能的供应商')
                if not row['model']:
                    raise ValueError('请输入模型 ID')
                if kind == 'speech' and not row['voice']:
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
            value = normalize({**old, **validate_patch(json.loads(raw))})
            if value == old: return True
            self.store.data['desktop'] = value
            self.store.save()
        except (ValueError, OSError, RuntimeError) as error:
            self.store.data['desktop'] = old
            self.toast.emit(str(error)); return False
        self.documentPreview.refreshWebPolicy()
        pool = getattr(self, '_pool', None)
        if pool:
            for record in tuple(pool.records.values()):
                if record.process:
                    pool.write(record, {'type':'desktop_settings', 'webview':configuration(value)})
        self.changed.emit()
        self.desktopSettingsChanged.emit()
        if value['webDisplay'] == 'embedded' and configuration().get('disabled'):
            self.toast.emit('重启 Umeko 后可使用内置网页预览')
        return True

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
            provider['proxy'] = {'mode': mode, 'url': url, **({'caFile': ca_file} if ca_file else {})}
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
