"""Curated Key-only accounts; user names never change upstream model IDs."""
import copy
import json
import re
import uuid
from PySide6.QtCore import Property, Slot


class CommonProvidersMixin:
    @Property('QVariantList', constant=True)
    def commonProviders(self):
        return json.loads((self.root / 'app/provider-presets.json').read_text(encoding='utf-8'))

    @Slot(str, str, str, result=bool)
    @Slot(str, str, str, str, result=bool)
    def addCommonProvider(self, preset_id, key, alias, region='cn'):
        try:
            preset = next((p for p in self.commonProviders if p['id'] == preset_id), None)
            if not preset:
                raise ValueError('请选择常见供应商')
            if region not in ('cn', 'international'):
                raise ValueError('请选择有效的供应商站点')
            if region == 'international':
                if not preset.get('international'):
                    raise ValueError('该供应商没有国际站配置')
                preset = {**preset, **preset['international']}
            key, alias = key.strip(), alias.strip()
            if not key:
                raise ValueError('请输入 API Key')
            if len(alias) > 60 or re.search(r'[\x00-\x1f\x7f]', alias):
                raise ValueError('别名最多 60 个字符，不能包含换行或控制字符')
            providers = self.store.data['providers']
            names = {p['name'] for p in providers}
            count = sum(p.get('presetId') == preset_id and p.get('presetRegion', 'cn') == region for p in providers)
            name = preset['name'] + ('(' + alias + ')' if alias else '')
            if alias and name in names:
                raise ValueError('该供应商别名已存在，请换一个别名')
            number = max(2, count + 1)
            if not alias and (count or name in names):
                name = preset['name'] + '(' + str(number) + ')'
                while name in names:
                    number += 1
                    name = preset['name'] + '(' + str(number) + ')'
            taken = {m['alias'] for p in providers for m in p['models']}
            models = copy.deepcopy(preset['models'])
            for model in models:
                model['alias'] = model['upstream']
                index = 2
                while model['alias'] in taken:
                    model['alias'] = model['upstream'] + '-' + str(index)
                    index += 1
                taken.add(model['alias'])
            identifier = uuid.uuid4().hex[:12]
            if not self.saveProvider(identifier, name, preset['api'], preset['baseUrl'], key, json.dumps(models)):
                return False
            provider = self.gateway.provider(identifier)
            provider.update(presetId=preset_id, presetRegion=region, accountAlias=alias)
            if preset.get('wireApi'): provider['wireApi'] = preset['wireApi']
            self.store.save()
            self.changed.emit()
            if not self.busy: self.selectModel(identifier, models[0]['alias'])
            return True
        except (ValueError, OSError, KeyError) as error:
            self.toast.emit(str(error))
            return False
