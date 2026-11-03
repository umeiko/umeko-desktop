"""Optional image interpretation through an explicitly selected desktop model."""
import json
from PySide6.QtCore import Slot
from .model_capabilities import normalize_vision

DEFAULTS = {'providerId': '', 'model': '', 'autoAnalyze': True, 'toolEnabled': True}


def normalize(value):
    if not isinstance(value, dict) or value.keys() - DEFAULTS.keys():
        raise ValueError('辅助视觉设置无效')
    result = {**DEFAULTS, **value}
    for key in ('providerId', 'model'):
        if not isinstance(result[key], str) or len(result[key]) > 256:
            raise ValueError('辅助视觉模型无效')
    for key in ('autoAnalyze', 'toolEnabled'):
        if type(result[key]) is not bool:
            raise ValueError('辅助视觉开关必须为 true 或 false')
    if bool(result['providerId']) != bool(result['model']):
        raise ValueError('请同时选择辅助视觉供应商和模型')
    return result


class AuxiliaryVisionMixin:
    def _auxiliaryVisionModels(self):
        return [{'providerId': p['id'], 'model': m['alias'], 'modelName': m.get('upstream') or m['alias'],
                 'providerName': p['name'], 'label': p['name'] + ' / ' + m['alias']}
                for p in self.store.data['providers'] for m in p['models'] if normalize_vision(m)['vision']]

    def _auxiliary_vision(self):
        config = self.store.data['auxiliaryVision']
        model = next((m for m in self.auxiliaryVisionModels
                      if (m['providerId'], m['model']) == (config['providerId'], config['model'])), None)
        return {**config, **model} if model else {**config, 'model': '', 'providerId': ''}

    def _can_analyze_attachments(self, model, provider):
        config = self._auxiliary_vision()
        return bool(config['model'] and config['autoAnalyze'] and not self.gateway.supports_vision(model, provider))

    @Slot(str, result=bool)
    def saveAuxiliaryVision(self, raw):
        previous = self.store.data['auxiliaryVision']
        try:
            value = normalize({**self.store.data['auxiliaryVision'], **json.loads(raw)})
            if value['model'] and not any((m['providerId'], m['model']) == (value['providerId'], value['model'])
                                         for m in self.auxiliaryVisionModels):
                raise ValueError('请选择已配置且支持图片的辅助模型')
            self.store.data['auxiliaryVision'] = value
            self.store.save()
            self._restart_pi()
            self.changed.emit()
            return True
        except (ValueError, TypeError, OSError, RuntimeError) as error:
            self.store.data['auxiliaryVision'] = previous
            self.toast.emit(str(error))
            return False
