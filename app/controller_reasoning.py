"""Run per-model level and thinking-format discovery outside the GUI thread."""
import copy
import queue
import threading

from PySide6.QtCore import QObject, Signal, Slot

from .model_capabilities import normalize_model
from .model_reasoning import normalize_reasoning
from .provider_models import fetch_model_windows
from .thinking_formats import FORMAT_OPTIONS, valid_format


class ReasoningDiscovery(QObject):
    finished = Signal(object)
    rejected = Signal(str, str, str, object)

    def __init__(self, controller):
        super().__init__(controller)
        self.c, self.closed = controller, False
        self.jobs, self.pending, self.sequence = {}, {}, 0
        self.busy_keys = set()
        self.tasks = queue.Queue()
        self.finished.connect(self._finished)
        self.rejected.connect(self._rejected)
        self.c.gateway.reasoning_rejected = self.rejected.emit
        for provider in self.c.store.data['providers']:
            for row in provider['models']:
                row.update(normalize_reasoning(row))
                for key in ('reasoningDetection', 'reasoningFormatDetection'):
                    if row[key]['state'] == 'probing':
                        row[key]['state'] = 'unknown'
                # Acceptance-only caches get one background effect measurement.
                cached = row['reasoningFormatDetection']
                if row['reasoningFormatAuto'] and cached['state'] == 'known' and cached.get('evidenceVersion') != 1:
                    cached['state'] = 'unknown'
                levels = row['reasoningDetection']
                if row['reasoningLevelsAuto'] and levels['state'] == 'known' and levels.get('evidenceVersion') != 1:
                    levels['state'] = 'unknown'
        for _ in range(2):
            threading.Thread(target=self._worker, daemon=True).start()
        self.c.changed.connect(self.sync_active)
        self.c.chatChanged.connect(self.sync_active)

    def _worker(self):
        while True:
            task = self.tasks.get()
            if task is None:
                return
            if self.closed:
                continue
            kind, snapshot, upstream, alias, token = task
            try:
                if kind == 'catalog':
                    keys = {(snapshot['id'], upstream) for upstream in snapshot['_reasoning_targets']}
                    with self.c.gateway.reasoning_activity.probe(keys):
                        result = {'windows': fetch_model_windows(snapshot)}
                else:
                    result = self.c.gateway.detect_reasoning(alias, snapshot['id'],
                              advertised_levels=next((row.get('reasoningDetection', {}).get('levels')
                                  for row in snapshot['models'] if row['upstream'] == upstream
                                  and row.get('reasoningDetection', {}).get('source') == 'metadata'), None))
            except Exception as error:
                message = str(error).replace(snapshot.get('key') or '\0', '[redacted]')[:500]
                failure = {'state': 'failed', 'error': message, 'verified': False}
                result = {'levels': {**failure, 'levels': []}, 'format': failure}
            if not self.closed:
                self.finished.emit((kind, snapshot, upstream, token, result))

    @staticmethod
    def connection(provider):
        return {key: provider.get(key) for key in ('api', 'baseUrl', 'key', 'wireApi', 'proxy', 'pluginId', 'pluginVersion')}

    def model(self, provider_id, alias):
        provider = self.c.gateway.provider(provider_id)
        return next((row for row in provider['models'] if row['alias'] == alias), None) if provider else None

    def current(self):
        return self.model(self.c.store.data['selectedProvider'], self.c.store.data['selectedModel'])

    @staticmethod
    def state(row, kind):
        prefix = 'reasoningLevels' if kind == 'levels' else 'reasoningFormat'
        cache = 'reasoningDetection' if kind == 'levels' else 'reasoningFormatDetection'
        return 'manual' if row.get(prefix + 'Auto') is False else row.get(cache, {}).get('state', 'unknown')

    def states(self, row=None):
        row = self.current() if row is None else row
        return {kind: self.state(row or {}, kind) for kind in ('levels', 'format')}

    def notify(self, save=False):
        reconciled = []
        for record in self.c._pool.records.values():
            previous = record.reasoning_effort
            self.c._reconcile_reasoning(record)
            if record.reasoning_effort != previous:
                reconciled.append(record)
        if save:
            self.c.store.save()
        for record in reconciled:
            self.send(record)
        self.c.reasoningDetectionChanged.emit()
        self.c.reasoningChanged.emit()

    def update_activity(self):
        busy = set()
        for record in self.c._pool.records.values():
            if not record.busy:
                continue
            provider = record.provider or self.c.store.data['selectedProvider']
            alias = record.model or self.c.store.data['selectedModel']
            row = self.model(provider, alias)
            if row:
                busy.add((provider, row['upstream']))
        previous, self.busy_keys = self.busy_keys, busy
        self.c.gateway.reasoning_activity.set_busy(busy)
        return previous - busy

    def _busy(self, kind, provider, upstream):
        if kind == 'catalog':
            targets = self.jobs.get((kind, provider, upstream), (None, set()))[1]
            return any((provider, target) in self.busy_keys for target in targets)
        return (provider, upstream) in self.busy_keys

    def _snapshot(self, provider, key):
        snapshot = copy.deepcopy(provider)
        if key[0] == 'catalog':
            snapshot['_reasoning_targets'] = list(self.jobs[key][1])
        return snapshot

    def sync_active(self):
        if self.closed or self.c._closing:
            return
        if self.update_activity():
            for key, task in list(self.pending.items()):
                if not self._busy(*key):
                    self.pending.pop(key)
                    kind, snapshot, upstream, alias, token = task
                    provider = self.c.gateway.provider(snapshot['id'])
                    row = next((row for row in provider['models'] if row['upstream'] == upstream), None) if provider else None
                    if not provider or (kind == 'probe' and row is None):
                        self.jobs.pop(key, None)
                        continue
                    self.tasks.put((kind, self._snapshot(provider, key), upstream,
                                    row['alias'] if row else alias, token))
        self.c.reasoningDetectionChanged.emit()

    def ensure(self, provider_id, alias):
        row = self.model(provider_id, alias)
        if row is None:
            return False
        if 'unknown' in self.states(row).values():
            return self.refresh(provider_id, only=row['upstream'], force=False)
        return True

    def _submit(self, kind, provider, upstream='', alias='', targets=None):
        key = (kind, provider['id'], upstream)
        if key in self.jobs:
            if targets:
                self.jobs[key][1].update(targets)
            if key in self.pending:
                old = self.pending[key]
                self.pending[key] = (kind, self._snapshot(provider, key), upstream, alias, old[-1])
            return False
        self.update_activity()
        self.sequence += 1
        self.jobs[key] = (self.sequence, set(targets or []))
        task = (kind, self._snapshot(provider, key), upstream, alias, self.sequence)
        if self._busy(*key):
            self.pending[key] = task
        else:
            self.tasks.put(task)
        return True

    def refresh(self, provider_id, only=None, force=True):
        provider = self.c.gateway.provider(provider_id)
        if self.closed or not provider:
            return False
        for row in provider['models']:
            row.update(normalize_reasoning(row))
        catalog = provider['api'] in ('openai', 'anthropic')
        rows = [row for row in provider['models'] if (only is None or row['upstream'] == only)
                and ((force and catalog) or any(state != 'manual' and (force or state == 'unknown')
                                               for state in self.states(row).values()))]
        if not rows:
            return True
        if catalog and (force or any(self.state(row, 'levels') == 'unknown' for row in rows)):
            self._submit('catalog', provider, targets=[row['upstream'] for row in rows])
            for row in rows:
                self._mark_probing(row)
            self.notify(save=True)
        else:
            for row in rows:
                self.probe(provider, row)
        return True

    def _mark_probing(self, row):
        for kind, field in (('levels', 'reasoningDetection'), ('format', 'reasoningFormatDetection')):
            if self.state(row, kind) != 'manual':
                row[field] = {**row.get(field, {}), 'state': 'probing'}

    def probe(self, provider, row):
        if self._submit('probe', provider, row['upstream'], row['alias']):
            self._mark_probing(row)
            self.notify(save=True)

    @Slot(object)
    def _finished(self, payload):
        kind, snapshot, upstream, token, result = payload
        provider = self.c.gateway.provider(snapshot['id'])
        key = (kind, snapshot['id'], upstream)
        job = self.jobs.get(key)
        if self.closed or not job or job[0] != token:
            return
        self.jobs.pop(key)
        if not provider:
            return
        if self.connection(provider) != self.connection(snapshot):
            for row in provider['models']:
                for field in ('reasoningDetection', 'reasoningFormatDetection'):
                    if row.get(field, {}).get('state') == 'probing':
                        row[field]['state'] = 'unknown'
            self.notify(save=True)
            self.refresh(provider['id'], force=False)
            return
        if kind == 'catalog':
            windows = result.get('windows', {})
            levels = getattr(windows, 'reasoning', {})
            context_changed = False
            for row in provider['models']:
                if row['upstream'] not in job[1]:
                    continue
                row.update(normalize_reasoning(row))
                old_context = (row.get('contextWindow'), row.get('providerContextWindow'))
                if row['upstream'] in windows:
                    row.pop('providerContextWindow', None)
                    if windows[row['upstream']] is not None:
                        row['providerContextWindow'] = windows[row['upstream']]
                row.update(normalize_model(row))
                context_changed |= old_context != (row.get('contextWindow'), row.get('providerContextWindow'))
                if row['upstream'] in levels:
                    found = levels[row['upstream']]
                    row['reasoningDetection'] = {'state': 'known', 'source': 'metadata',
                                                 'levels': list(found), 'verified': False}
                    if row['reasoningLevelsAuto']:
                        row['reasoningLevels'] = list(found)
                if row.get('reasoningFormatAuto', True) or (row['reasoningLevelsAuto'] and row['upstream'] not in levels):
                    self.probe(provider, row)
            self.notify(save=True)
            if context_changed:
                self.c._restart_pi()
                self.c.changed.emit()
            return
        for row in provider['models']:
            if row['upstream'] != upstream:
                continue
            rejected = row.get('reasoningDetection', {}).get('rejected', [])
            levels = dict(result.get('levels', {}))
            if levels.get('source') != 'manual':
                levels['rejected'] = rejected
                if levels.get('state') == 'known':
                    levels['levels'] = [level for level in levels['levels'] if level not in rejected]
                    if row['reasoningLevelsAuto']:
                        row['reasoningLevels'] = list(levels['levels'])
                row['reasoningDetection'] = levels
            format_result = result.get('format', {})
            if format_result.get('source') != 'manual':
                row['reasoningFormatDetection'] = dict(format_result)
                if row.get('reasoningFormatAuto', True) and format_result.get('state') == 'known':
                    row['reasoningFormat'] = format_result['format']
        for record in self.c._pool.records.values():
            if record.provider == provider['id']:
                self.c._reconcile_reasoning(record)
                self.send(record)
        self.notify(save=True)

    @Slot(str, str, str, object)
    def _rejected(self, provider_id, upstream, effort, allowed):
        provider = self.c.gateway.provider(provider_id)
        if self.closed or not provider:
            return
        rows = [row for row in provider['models'] if row['upstream'] == upstream]
        if effort == 'off':
            for row in rows:
                row['reasoningFormatDetection'] = {**row.get('reasoningFormatDetection', {}),
                    'state': 'unknown', 'offVerified': False, 'offSupported': None,
                    'offFormat': None, 'status': 'unknown'}
            if rows:
                self.probe(provider, rows[0])
            self.notify(save=True)
            return
        for row in rows:
            old = row.get('reasoningDetection', {})
            rejected = list(dict.fromkeys([*old.get('rejected', []), effort]))
            levels = allowed if allowed is not None and row['reasoningLevelsAuto'] else row.get('reasoningLevels', [])
            row['reasoningLevels'] = [level for level in levels if level not in rejected]
            row['reasoningDetection'] = {**old, 'state': 'unknown', 'source': 'error',
                'levels': list(row['reasoningLevels']), 'rejected': rejected}
        if rows:
            self.probe(provider, rows[0])
        self.notify(save=True)

    def send(self, record):
        self.c._write_pi({'type': 'reasoning_effort', 'value': record.reasoning_effort}, record)

    def settings(self, provider_id, alias):
        row = self.model(provider_id, alias)
        return {**normalize_reasoning(row), 'states': self.states(row)} if row is not None else {}

    def set_levels(self, provider_id, alias, levels, automatic):
        row = self.model(provider_id, alias)
        if row is None or type(automatic) is not bool:
            return False
        change = normalize_reasoning({**row, 'reasoningLevels': levels, 'reasoningLevelsAuto': automatic})
        row.update(change)
        if automatic:
            cached = row['reasoningDetection']
            if cached['state'] == 'known':
                row['reasoningLevels'] = list(cached.get('levels', []))
            else:
                cached['state'] = 'unknown'
                row.pop('reasoningLevels', None)
        self.notify(save=True)
        self.c.changed.emit()
        if automatic:
            self.ensure(provider_id, alias)
        return True

    def set_format(self, provider_id, alias, value, automatic):
        row = self.model(provider_id, alias)
        if row is None or type(automatic) is not bool or not valid_format(value):
            return False
        row['reasoningFormat'], row['reasoningFormatAuto'] = value, automatic
        if automatic:
            cached = row['reasoningFormatDetection']
            if cached['state'] == 'known':
                row['reasoningFormat'] = cached['format']
            else:
                cached['state'] = 'unknown'
        self.notify(save=True)
        self.c.changed.emit()
        if automatic:
            self.ensure(provider_id, alias)
        return True

    def close(self):
        self.closed = True
        self.c.gateway.reasoning_rejected = None
        self.c.gateway.reasoning_activity.close()
        self.jobs.clear()
        self.pending.clear()
        for _ in range(2):
            self.tasks.put(None)
