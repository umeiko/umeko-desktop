"""Background per-account/model effort discovery and controller-facing settings."""
from __future__ import annotations

import copy
import queue
import threading

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from .model_capabilities import normalize_model
from .provider_models import fetch_model_windows
from .reasoning_levels import clamp_effort, normalize_levels, normalize_reasoning


class ReasoningModels(QObject):
    finished = Signal(object)
    rejected = Signal(str, str, str, object)

    def __init__(self, controller):
        super().__init__(controller)
        self.c = controller
        self.closed = False
        self.jobs = {}
        self.generation = 0
        self.tasks = queue.Queue()
        self.finished.connect(self._finished)
        self.rejected.connect(self._rejected)
        self.c.gateway.reasoning_rejected = self.rejected.emit
        for provider in self.c.store.data['providers']:
            for model in provider['models']:
                model.update(normalize_reasoning(model))
                if model['reasoningDetection']['state'] == 'probing':
                    model['reasoningDetection']['state'] = 'unknown'
        # Two daemon workers bound discovery concurrency without waiting on the GUI.
        for _ in range(2):
            threading.Thread(target=self._worker, daemon=True).start()
        self.c.changed.connect(self.sync_active)
        QTimer.singleShot(0, self.sync_active)

    def _worker(self):
        while True:
            task = self.tasks.get()
            if task is None:
                return
            if self.closed:
                continue
            kind, provider_id, upstream, token, snapshot, alias = task
            try:
                if kind == 'catalog':
                    result = {'windows': fetch_model_windows(snapshot)}
                else:
                    result = self.c.gateway.detect_reasoning_levels(alias, provider_id)
            except Exception as error:
                message = str(error).replace(snapshot.get('key', '') or '\0', '[redacted]')[:500]
                result = {'state': 'failed', 'source': 'probe', 'levels': [], 'error': message}
            if not self.closed:
                self.finished.emit((kind, provider_id, upstream, token, snapshot, result))

    @staticmethod
    def connection(provider):
        return {key: provider.get(key) for key in ('api', 'baseUrl', 'key', 'wireApi', 'proxy', 'pluginId', 'pluginVersion')}

    def model(self, provider_id, alias):
        provider = self.c.gateway.provider(provider_id)
        return next((row for row in provider['models'] if row['alias'] == alias), None) if provider else None

    def for_record(self, record=None):
        record = record or self.c._view
        provider, alias = record.provider, record.model
        if record is self.c._view and not record.busy:
            provider, alias = self.c.store.data['selectedProvider'], self.c.store.data['selectedModel']
        return self.model(provider, alias)

    def levels(self, record=None):
        row = self.for_record(record)
        return normalize_reasoning(row)['reasoningLevels'] if row else []

    def state(self, row=None):
        row = row if row is not None else self.for_record()
        settings = normalize_reasoning(row or {})
        return 'manual' if not settings['reasoningLevelsAuto'] else settings['reasoningDetection']['state']

    def _notify(self, save=False):
        if save:
            self.c.store.save()
        self.c.reasoningLevelsChanged.emit()
        self.c.reasoningChanged.emit()

    def clamp(self, record=None, persist=True):
        record = record or self.c._view
        value = clamp_effort(record.reasoning_effort, self.levels(record))
        if value == record.reasoning_effort:
            return False
        record.reasoning_effort = value
        if record.id:
            self.c.store.data['sessionMeta'].setdefault(record.id, {})['reasoningEffort'] = value
        if record is self.c._view:
            self.c.store.data['ui']['reasoningEffort'] = value
        self.send_levels(record)
        self._notify(save=persist)
        return True

    def send_levels(self, record=None):
        record = record or self.c._view
        self.c._write_pi({'type': 'reasoning_effort', 'value': record.reasoning_effort,
                          'model': record.model, 'provider': record.provider,
                          'reasoningLevels': self.levels(record)}, record)

    def sync_active(self):
        if self.closed or self.c._closing:
            return
        self.clamp()
        row = self.for_record()
        if row and self.state(row) == 'unknown':
            provider_id = self.c.store.data['selectedProvider']
            provider = self.c.gateway.provider(provider_id)
            if provider and provider['api'] in ('openai', 'anthropic', 'plugin', 'internal'):
                self.refresh(provider_id, force=False, only=row['upstream'])
        self.c.reasoningLevelsChanged.emit()

    def _submit(self, kind, provider, upstream='', alias='', targets=None):
        job = (kind, provider['id'], upstream)
        if job in self.jobs:
            return False
        self.generation += 1
        snapshot = copy.deepcopy(provider)
        self.jobs[job] = (self.generation, targets)
        self.tasks.put((kind, provider['id'], upstream, self.generation, snapshot, alias))
        return True

    def refresh(self, provider_id, force=True, only=None):
        provider = self.c.gateway.provider(provider_id)
        if self.closed or not provider:
            return False
        targets = [row for row in provider['models']
                   if (only is None or row['upstream'] == only)
                   and (force or (normalize_reasoning(row)['reasoningLevelsAuto'] and self.state(row) == 'unknown'))]
        if not targets:
            return True
        if provider['api'] in ('openai', 'anthropic'):
            submitted = self._submit('catalog', provider, targets=[row['upstream'] for row in targets])
            if not submitted:
                pending = self.jobs.get(('catalog', provider_id, ''))
                if pending:
                    pending[1].extend(row['upstream'] for row in targets if row['upstream'] not in pending[1])
                    for row in targets:
                        if normalize_reasoning(row)['reasoningLevelsAuto']:
                            row.update(normalize_reasoning(row))
                            row['reasoningDetection']['state'] = 'probing'
                return True
            for row in targets:
                row.update(normalize_reasoning(row))
                if row['reasoningLevelsAuto']:
                    row['reasoningDetection'] = {**row['reasoningDetection'], 'state': 'probing'}
            self._notify()
        else:
            for row in targets:
                if not (self.state(row) == 'known' and row.get('reasoningDetection', {}).get('source') == 'metadata'):
                    self.probe(provider, row, include_manual=force)
        return True

    def probe(self, provider, row, include_manual=False):
        if not include_manual and not normalize_reasoning(row)['reasoningLevelsAuto']:
            return
        if self._submit('probe', provider, row['upstream'], row['alias']):
            row.update(normalize_reasoning(row))
            row['reasoningDetection'] = {**row['reasoningDetection'], 'state': 'probing'}
            self._notify()

    @Slot(object)
    def _finished(self, payload):
        kind, provider_id, upstream, token, snapshot, result = payload
        saved = self.jobs.pop((kind, provider_id, upstream), None)
        provider = self.c.gateway.provider(provider_id)
        if self.closed or not saved or saved[0] != token or not provider:
            return
        if self.connection(provider) != self.connection(snapshot):
            for row in provider['models']:
                if self.state(row) == 'probing':
                    row['reasoningDetection']['state'] = 'unknown'
            self.sync_active()
            return
        if kind == 'catalog':
            windows = result.get('windows', {})
            metadata = getattr(windows, 'reasoning', {})
            for row in provider['models']:
                if row['upstream'] not in (saved[1] or []):
                    continue
                if row['upstream'] in windows:
                    row.pop('providerContextWindow', None)
                    if windows[row['upstream']] is not None:
                        row['providerContextWindow'] = windows[row['upstream']]
                row.update(normalize_model(row))
                if row['upstream'] in metadata:
                    levels = metadata[row['upstream']]
                    rejected = row['reasoningDetection'].get('rejected', [])
                    discovered = [level for level in levels if level not in rejected]
                    if row['reasoningLevelsAuto']:
                        row['reasoningLevels'] = discovered
                    row['reasoningDetection'] = {'state': 'known', 'source': 'metadata',
                        'levels': discovered, 'rejected': rejected}
                    if not levels:
                        row['reasoningDetection']['noParameter'] = True
                else:
                    self.probe(provider, row, include_manual=True)
        else:
            row = next((row for row in provider['models'] if row['upstream'] == upstream), None)
            if row is None:
                return
            rejected = row.get('reasoningDetection', {}).get('rejected', [])
            result = {**result, 'rejected': rejected}
            if result['state'] == 'known':
                result['levels'] = [level for level in result['levels'] if level not in rejected]
                if normalize_reasoning(row)['reasoningLevelsAuto']:
                    row['reasoningLevels'] = list(result['levels'])
            row['reasoningDetection'] = result
        for record in self.c._pool.records.values():
            if record.provider == provider_id or record is self.c._view:
                self.clamp(record, persist=False)
                self.send_levels(record)
        self._notify(save=True)
        self.c.changed.emit()

    @Slot(str, str, str, object)
    def _rejected(self, provider_id, upstream, effort, allowed):
        provider = self.c.gateway.provider(provider_id)
        row = next((row for row in provider['models'] if row['upstream'] == upstream), None) if provider else None
        if self.closed or row is None:
            return
        row.update(normalize_reasoning(row))
        detection = row['reasoningDetection']
        rejected = list(dict.fromkeys([*detection.get('rejected', []), effort]))
        available = allowed if allowed is not None and row['reasoningLevelsAuto'] else row['reasoningLevels']
        row['reasoningLevels'] = [level for level in available if level not in rejected]
        row['reasoningDetection'] = {**detection, 'state': 'unknown', 'source': 'error',
            'levels': list(row['reasoningLevels']), 'rejected': rejected}
        # A manual list remains manual; a rejected entry is removed immediately.
        self.probe(provider, row, include_manual=True)
        for record in self.c._pool.records.values():
            if record.provider == provider_id and record.model == row['alias']:
                self.clamp(record, persist=False)
                self.send_levels(record)
        self._notify(save=True)

    def settings(self, provider_id, alias):
        row = self.model(provider_id, alias)
        if row is None:
            return {}
        return {**normalize_reasoning(row), 'state': self.state(row)}

    def set_manual(self, provider_id, alias, levels, automatic):
        row = self.model(provider_id, alias)
        if row is None or type(automatic) is not bool:
            return False
        levels = normalize_levels(levels)
        row.update(normalize_reasoning(row))
        row['reasoningLevelsAuto'] = automatic
        if automatic:
            detection = row['reasoningDetection']
            row['reasoningLevels'] = list(detection.get('levels', [])) if detection['state'] == 'known' else []
            if detection['state'] != 'known':
                detection['state'] = 'unknown'
        else:
            row['reasoningLevels'] = levels
        self.clamp(persist=False)
        self._notify(save=True)
        self.c.changed.emit()
        if automatic and self.state(row) == 'unknown':
            self.refresh(provider_id, force=False, only=row['upstream'])
        return True

    def close(self):
        self.closed = True
        self.c.gateway.reasoning_rejected = None
        self.jobs.clear()
        for _ in range(2):
            self.tasks.put(None)
