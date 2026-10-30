"""Small persisted appearance and provider transport settings."""
import math
import urllib.parse
from PySide6.QtCore import Slot
from .gateway import validate_base_url
from umeko_provider_sdk.network import validate_ca_file


class PreferencesMixin:
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
