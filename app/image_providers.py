"""Key-only image accounts and small, explicit protocol adapters.

Image accounts share the existing encrypted provider store, but have no chat
model mappings. Public presets contain only connection and capability metadata.
"""
from __future__ import annotations

import copy
import json
import re
import uuid

from PySide6.QtCore import Slot

from .multimodal_settings import DEFAULTS, model_ids, provider_models


ARK_MODELS = [
    {'id': identifier, 'name': name, 'maxCount': count, 'formats': formats,
     'sizeTiers': sizes, 'minPixels': minimum, 'maxPixels': maximum, 'maxRatio': 16}
    for identifier, name, count, formats, sizes, minimum, maximum in (
        ('doubao-seedream-5-5-261028', 'Seedream 5.5', 1, ['png', 'jpeg'], ['1K', '1.5K', '2K'], 921600, 4624220),
        ('doubao-seedream-5-0-pro-260628', 'Seedream 5.0 Pro', 1, ['png', 'jpeg'], ['1K', '1.5K', '2K'], 921600, 4624220),
        ('doubao-seedream-5-0-flash-260915', 'Seedream 5.0 Flash', 1, ['png', 'jpeg'], ['1K', '1.5K', '2K'], 921600, 4624220),
        ('doubao-seedream-5-0-lite-260128', 'Seedream 5.0 Lite', 10, ['png', 'jpeg'], ['2K', '3K', '4K'], 3686400, 16777216),
        ('doubao-seedream-4-5-251128', 'Seedream 4.5', 10, ['jpeg'], ['2K', '4K'], 3686400, 16777216),
        ('doubao-seedream-4-0-250828', 'Seedream 4.0', 10, ['jpeg'], ['1K', '2K', '4K'], 921600, 16777216),
    )
]
QWEN_MODELS = [
    {'id': identifier, 'name': name, 'maxCount': 6, 'formats': ['png'],
     'sizeTiers': [], 'minPixels': 262144, 'maxPixels': 4194304, 'maxRatio': 8}
    for identifier, name in (
        ('qwen-image-3.0-pro', 'Qwen Image 3.0 Pro'), ('qwen-image-3.0', 'Qwen Image 3.0'),
        ('qwen-image-2.1-pro', 'Qwen Image 2.1 Pro'), ('qwen-image-2.1-turbo', 'Qwen Image 2.1 Turbo'),
    )
]
PRESETS = (
    {'id': 'volcengine-image', 'name': '火山方舟', 'label': '火山方舟', 'icon': 'volcengine.svg',
     'baseUrl': 'https://ark.cn-beijing.volces.com/api/v3', 'protocol': 'ark',
     'keyUrl': 'https://ark.volcengine.com/region:cn-beijing/apiKey',
     'models': [m['id'] for m in ARK_MODELS], 'modelDetails': ARK_MODELS},
    {'id': 'qwen-image', 'name': '阿里云百炼', 'label': '阿里云百炼', 'icon': 'bailian.svg',
     'baseUrl': 'https://dashscope.aliyuncs.com/api/v1', 'protocol': 'dashscope',
     'keyUrl': 'https://bailian.console.aliyun.com/cn-beijing/model/settings/api-key',
     'models': [m['id'] for m in QWEN_MODELS], 'modelDetails': QWEN_MODELS},
)
CUSTOM_PRESET = {'id': 'openai-image', 'name': '自定义（OpenAI 兼容）', 'label': '自定义（OpenAI 兼容）',
                 'protocol': 'openai', 'icon': '', 'keyUrl': '', 'custom': True,
                 'maxCount': 10, 'formats': ['png', 'jpeg', 'webp']}
SPEECH_CUSTOM_PRESET = {'id': 'openai-speech', 'name': '自定义（OpenAI 兼容）', 'label': '自定义（OpenAI 兼容）',
                        'protocol': 'openai', 'icon': '', 'keyUrl': '', 'custom': True}
VIDEO_CUSTOM_PRESET = {'id': 'openai-video', 'name': '自定义（OpenAI 兼容）', 'label': '自定义（OpenAI 兼容）',
                       'protocol': 'openai', 'icon': '', 'keyUrl': '', 'custom': True}
MULTIMODAL_APIS = ('image', 'speech', 'video')
MULTIMODAL_CUSTOM_PRESETS = {'image': CUSTOM_PRESET, 'speech': SPEECH_CUSTOM_PRESET, 'video': VIDEO_CUSTOM_PRESET}
MULTIMODAL_SAVED_TOAST = {'image': '图片供应商已保存', 'speech': '语音供应商已保存', 'video': '视频供应商已保存'}


def _text(value, limit, label):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(label + '无效 / Invalid image provider field')
    return value.strip()


def profile(provider, model=None):
    if provider.get('api') != 'image':
        return None
    if provider.get('presetId') == CUSTOM_PRESET['id'] and provider.get('imageProtocol') == 'openai':
        if model is not None:
            _text(model, 200, '模型 ID')
        return CUSTOM_PRESET
    preset = next((row for row in PRESETS if row['id'] == provider.get('presetId')), None)
    if not preset or provider.get('imageProtocol') != preset['protocol']:
        raise ValueError('图片供应商协议无效 / Invalid image provider protocol')
    if model is not None and model not in preset['models']:
        raise ValueError('请选择该供应商支持的生图模型 / Select a supported image model')
    if model is None:
        return preset
    return {**preset, **next(row for row in preset['modelDetails'] if row['id'] == model)}


def parameters(provider, model, options):
    """Validate capabilities before a request is sent, including saved options."""
    preset = profile(provider, model)
    count = options.get('count', 1)
    if type(count) is not int or not 1 <= count <= preset['maxCount']:
        raise ValueError(f"{preset['name']}：图片数量应为 1–{preset['maxCount']} / Image count outside supported range")
    if preset['protocol'] == 'openai':
        return {'count': count, 'format': options.get('format', ''), 'size': options.get('size', '')}
    if options.get('quality'):
        raise ValueError('此生图模型不支持 quality 参数 / This image model does not support quality')
    format = options.get('format', '')
    if format and format not in preset['formats']:
        raise ValueError('此生图模型不支持所选图片格式 / Unsupported output format for this image model')
    size = options.get('size', '')
    if not isinstance(size, str):
        raise ValueError('图片尺寸无效 / Invalid image size')
    size = size.strip()
    if size in ('', 'auto'):
        size = ''
    elif size in preset['sizeTiers']:
        pass
    else:
        match = re.fullmatch(r'([1-9][0-9]{0,4})[x*]([1-9][0-9]{0,4})', size)
        if not match:
            raise ValueError('图片尺寸应为 宽x高 / Image size must be WIDTHxHEIGHT')
        width, height = map(int, match.groups())
        pixels = width * height
        valid = preset['minPixels'] <= pixels <= preset['maxPixels'] and 1 / preset['maxRatio'] <= width / height <= preset['maxRatio']
        if not valid:
            raise ValueError('图片尺寸超出该模型支持范围 / Image size outside this model’s supported range')
        size = f'{width}{"*" if preset["protocol"] == "dashscope" else "x"}{height}'
    return {'count': count, 'format': format, 'size': size}


def request(provider, model, prompt, options):
    values = parameters(provider, model, options)
    if provider['imageProtocol'] == 'openai':
        payload = {'model': model, 'prompt': prompt, 'n': values['count']}
        payload.update({k: options[k] for k in ('size', 'quality') if options.get(k)})
        if values['format']:
            payload['output_format'] = values['format']
        return '/images/generations', payload
    if provider['imageProtocol'] == 'dashscope':
        settings = {'n': values['count']}
        if values['size']:
            settings['size'] = values['size']
        return '/services/aigc/multimodal-generation/generation', {
            'model': model, 'input': {'messages': [{'role': 'user', 'content': [{'text': prompt}]}]},
            'parameters': settings}
    payload = {'model': model, 'prompt': prompt, 'response_format': 'url'}
    if values['count'] > 1:
        payload.update(sequential_image_generation='auto', sequential_image_generation_options={'max_images': values['count']})
    if values['size']:
        payload['size'] = values['size']
    if values['format'] and model not in ('doubao-seedream-4-5-251128', 'doubao-seedream-4-0-250828'):
        payload['output_format'] = values['format']
    return '/images/generations', payload


def response(provider, result):
    if provider.get('api') == 'image' and isinstance(result, dict) and result.get('code') not in (None, '', 200, '200'):
        raise ValueError(f"{result['code']}: {result.get('message', '图片生成失败 / Image generation failed')}")
    if provider.get('api') != 'image' or provider.get('imageProtocol') != 'dashscope':
        return result.get('data') if isinstance(result, dict) else None
    choices = result.get('output', {}).get('choices') if isinstance(result, dict) and isinstance(result.get('output'), dict) else None
    if not isinstance(choices, list):
        return None
    values = []
    for choice in choices:
        message = choice.get('message') if isinstance(choice, dict) else None
        content = message.get('content') if isinstance(message, dict) else None
        if not isinstance(content, list):
            return None
        for part in content:
            if isinstance(part, dict) and 'image' in part:
                values.append({'url': part['image']})
    return values


class ImageProvidersMixin:
    def _image_provider_rows(self):
        return [{'id': p['id'], 'presetId': p.get('presetId', ''), 'name': p['name'],
                 'hasKey': bool(p.get('key')), 'baseUrl': p.get('baseUrl', ''),
                 'model': (p.get('imageModels') or [''])[0]}
                for p in self.store.data['providers'] if p.get('api') == 'image']

    def _multimodal_provider_rows(self):
        from .generation import capabilities
        settings = self.store.data['multimodal']
        rows = []
        for provider in self.store.data['providers']:
            kinds = capabilities(provider)
            if not kinds:
                continue
            identifier = provider['id']
            models = {kind: list(provider_models(provider, kind)) for kind in kinds}
            for kind in kinds:
                selection = settings[kind]
                if selection['providerId'] == identifier and selection['model'] and selection['model'] not in models[kind]:
                    # Keep manually configured defaults from older profiles selectable.
                    models[kind].append(selection['model'])
            rows.append({'id': identifier, 'api': provider['api'], 'presetId': provider.get('presetId', ''),
                         'name': provider['name'], 'accountLabel': provider.get('accountLabel', ''),
                         'hasKey': bool(provider.get('key')), 'baseUrl': provider.get('baseUrl', ''),
                         'kinds': kinds, 'models': models, 'model': (models[kinds[0]] or [''])[0],
                         'speechVoices': provider.get('speechVoices', {}) if provider['api'] == 'plugin' else {}})
        return rows

    @Slot(str, str, result=bool)
    def saveImageProvider(self, preset_id, key):
        preset = next((p for p in PRESETS if p['id'] == preset_id), None)
        if not preset:
            self.toast.emit('请选择图片供应商 / Select an image provider')
            return False
        existing = next((p for p in self.store.data['providers'] if p.get('api') == 'image' and p.get('presetId') == preset_id), None)
        return self._save_multimodal_account('image', preset, existing, key, preset['name'], preset['baseUrl'], preset['models'])

    @Slot(str, result=bool)
    def saveCustomImageProvider(self, raw):
        return self.saveCustomMultimodalProvider('image', raw)

    @Slot(str, str, result=bool)
    def saveCustomMultimodalProvider(self, kind, raw):
        try:
            if kind not in MULTIMODAL_CUSTOM_PRESETS:
                raise ValueError('多模态供应商类型无效 / Invalid multimodal provider kind')
            preset = MULTIMODAL_CUSTOM_PRESETS[kind]
            value = json.loads(raw)
            if not isinstance(value, dict) or set(value) - {'id', 'name', 'baseUrl', 'key', 'model'}:
                raise ValueError('多模态供应商配置无效 / Invalid multimodal provider settings')
            existing = None
            if value.get('id'):
                existing = next((p for p in self.store.data['providers'] if p.get('api') == kind and p.get('presetId') == preset['id'] and p['id'] == value['id']), None)
                if existing is None:
                    raise ValueError('多模态供应商已不存在 / Multimodal provider no longer exists')
            from .gateway import validate_base_url
            base = validate_base_url(_text(value.get('baseUrl'), 2048, 'Base URL'))
            name = _text(value.get('name'), 60, '供应商名称')
            model = _text(value.get('model'), 200, '模型 ID')
            return self._save_multimodal_account(kind, preset, existing, value.get('key', ''), name, base, [model])
        except (ValueError, TypeError) as error:
            self.toast.emit(str(error))
            return False

    @Slot(str, str, result=bool)
    def saveGenerationProvider(self, kind, raw):
        try:
            value = json.loads(raw)
            if kind not in MULTIMODAL_CUSTOM_PRESETS or not isinstance(value, dict):
                raise ValueError('多模态供应商配置无效 / Invalid multimodal provider settings')
            presets = [MULTIMODAL_CUSTOM_PRESETS[kind], *(PRESETS if kind == 'image' else ())]
            preset = next((row for row in presets if row['id'] == value.get('presetId')), None)
            if not preset:
                raise ValueError('多模态供应商类型无效 / Invalid multimodal provider kind')
            existing = None
            if value.get('id'):
                existing = next((p for p in self.store.data['providers'] if p['id'] == value['id']
                                 and p.get('api') == kind and p.get('presetId') == preset['id']), None)
                if not existing:
                    raise ValueError('多模态供应商已不存在 / Multimodal provider no longer exists')
            models = model_ids(value.get('models'))
            if preset.get('custom'):
                from .gateway import validate_base_url
                base = validate_base_url(_text(value.get('baseUrl'), 2048, 'Base URL'))
                name = _text(value.get('name'), 60, '供应商名称')
            else:
                if any(model not in preset['models'] for model in models):
                    raise ValueError('请选择该供应商支持的生图模型 / Select a supported image model')
                name, base = preset['name'], preset['baseUrl']
            return self._save_multimodal_account(kind, preset, existing, value.get('key', ''), name, base, models,
                                                 select=False)
        except (ValueError, TypeError) as error:
            self.toast.emit(str(error))
            return False

    def _save_multimodal_account(self, kind, preset, existing, key, name, base, models, *, select=True):
        previous_providers = self.store.data['providers']
        previous_settings = self.store.data['multimodal']
        try:
            if not isinstance(key, str):
                raise ValueError('多模态供应商配置无效 / Invalid multimodal provider settings')
            if self._models_busy():
                raise ValueError('请等待当前任务结束后修改多模态设置')
            key = key.strip() or (existing or {}).get('key', '')
            if not key or len(key) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in key):
                raise ValueError('请输入有效的 API Key / Enter a valid API Key')
            # A changed key gets a fresh credential slot. If settings.json
            # cannot be replaced, its old account still resolves the old key.
            identifier = existing['id'] if existing and key == existing.get('key') else uuid.uuid4().hex[:12]
            provider = {**(existing or {}), 'id': identifier,
                        'name': name, 'api': kind, 'baseUrl': base, 'key': key,
                        'models': [], 'presetId': preset['id'],
                        'generationCapabilities': [kind],
                        'proxy': (existing or {}).get('proxy', {'mode': 'system', 'url': ''})}
            if kind == 'image':
                provider['imageModels'] = list(models)
                provider['imageProtocol'] = preset['protocol']
            else:
                provider['generationModels'] = list(models)
            settings = copy.deepcopy(previous_settings)
            if existing and settings[kind]['providerId'] == existing['id']:
                settings[kind]['providerId'] = identifier
                if settings[kind]['model'] not in models:
                    settings[kind].update(model=models[0] if select else '', providerId=identifier if select else '')
            elif select:
                preserved = {'voice': settings[kind]['voice']} if kind == 'speech' and settings[kind].get('voice') else {}
                settings[kind] = {**DEFAULTS[kind], **preserved, 'providerId': provider['id'], 'model': models[0]}
            if existing == provider and settings == previous_settings:
                return True
            self.store.data['providers'] = [p for p in previous_providers if p['id'] != (existing or {}).get('id')] + [provider]
            self.store.data['multimodal'] = settings
            self.store.save()
        except (ValueError, OSError, RuntimeError) as error:
            self.store.data['providers'] = previous_providers
            self.store.data['multimodal'] = previous_settings
            self.toast.emit(str(error))
            return False
        self.gateway.compatibility.clear_provider(provider['id'])
        if existing and existing['id'] != provider['id']:
            self.gateway.compatibility.clear_provider(existing['id'])
        self._restart_pi()
        self.changed.emit()
        self.toast.emit(MULTIMODAL_SAVED_TOAST[kind])
        return True

    @Slot(str, result=bool)
    def removeImageProvider(self, identifier):
        return self.removeMultimodalProvider(identifier)

    @Slot(str, result=bool)
    def removeMultimodalProvider(self, identifier):
        previous_providers = self.store.data['providers']
        previous_settings = self.store.data['multimodal']
        try:
            provider = next((p for p in previous_providers if p.get('api') in MULTIMODAL_APIS and (
                p['id'] == identifier or (p.get('api') == 'image' and p.get('presetId') == identifier and identifier != CUSTOM_PRESET['id']))), None)
            if not provider:
                return True
            if self._models_busy(provider['id']):
                raise ValueError('该供应商仍有会话运行，结束后可移除')
            kind = provider['api']
            self.store.data['providers'] = [p for p in previous_providers if p['id'] != provider['id']]
            settings = copy.deepcopy(previous_settings)
            if settings[kind]['providerId'] == provider['id']:
                settings[kind] = copy.deepcopy(DEFAULTS[kind])
            self.store.data['multimodal'] = settings
            self.store.save()
        except (ValueError, OSError, RuntimeError) as error:
            self.store.data['providers'] = previous_providers
            self.store.data['multimodal'] = previous_settings
            self.toast.emit(str(error))
            return False
        self.gateway.compatibility.clear_provider(provider['id'])
        self._restart_pi()
        self.changed.emit()
        return True
