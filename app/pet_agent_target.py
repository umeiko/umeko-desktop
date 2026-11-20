"""Host-only explicit global-agent target; not a Widget/model API or UI picker.

Only already initialized sessions are supported. No agent, connection or runtime
is created during selection. Responses remain in the target's normal conversation.
"""
from __future__ import annotations

import copy
from uuid import uuid4


class PetAgentTarget:
    def __init__(self, bus, identifier):
        self.bus = bus
        self.identifier = identifier
        self.row = bus.agents.get(identifier)
        self.record = bus.records.get(identifier)
        self.configuration = self._configuration()
        self.identity = self._identity()
        self.consumed = False

    def _configuration(self):
        # Messages/session persistence are runtime output, not permission changes.
        return copy.deepcopy({key: value for key, value in (self.row or {}).items()
                              if key not in ('messages', 'sessionId', 'sessionFile')})

    def _identity(self):
        record = self.record
        return ((record.key, record.id, record.file, record.workspace,
                 record.global_agent, record.model, record.provider) if record else None)

    def _unavailable(self, *, allow_follow_up=False):
        bus = self.bus
        if bus.m.closed or not bus.active or not bus.m.enabled('global-agents'):
            return 'unavailable'
        if (self.row is None or self.record is None
                or bus.agents.get(self.identifier) is not self.row
                or bus.records.get(self.identifier) is not self.record
                or self.record.global_agent != self.identifier
                or self._identity() != self.identity
                or self._configuration() != self.configuration):
            return 'target_changed'
        if self.consumed:
            return 'already_submitted'
        if (self.record.subagents_active or self.record.approval
                or getattr(bus.b, 'kernelBusy', False)):
            return 'busy'
        if self.record.busy:
            return '' if allow_follow_up and self.follow_up_identity() else 'busy'
        if sum(record.busy for record in bus.records.values()) >= 4:
            return 'capacity'
        return ''

    def follow_up_identity(self):
        record = self.record
        if (record and record.id and record.file and record.ready and record.process
                and record.phase == 'running' and record.action in ('prompt', 'widget-notify')
                and not (record.operation or record.cancelled or record.stop_state)
                and record.pet_follow_up_run):
            return (record.process, record.pet_follow_up_run)
        return None

    def submit_follow_up(self, text, run):
        status = self._unavailable(allow_follow_up=True)
        if not status and (not run or self.follow_up_identity() != run):
            status = 'run_changed'
        if not status and (not isinstance(text, str) or not text.strip() or len(text) > 16000):
            status = 'invalid_text'
        if status:
            return {'ok': False, 'status': status}
        request = uuid4().hex
        self.consumed = True
        try:
            self.bus.b._pool.write(self.record, {
                'type': 'follow-up', 'petRunId': run[1], 'messageId': request,
                'text': '(input from pet)\n' + text.strip(), 'images': []})
        except (OSError, RuntimeError, ValueError):
            return {'ok': False, 'status': 'uncertain'}
        return {'ok': True, 'status': 'pending', 'messageId': request}

    def submit(self, text):
        """Submit once to captured idle target, or retain the exact caller draft.

        No fallback, steer, follow-up, permissions grants or UI state changes.
        A fresh explicit selection is required after a submission attempt: uncertain
        failures must not be retried automatically.
        """
        def reject(status):
            return {'ok': False, 'status': status, 'draft': text,
                    'targetId': self.identifier}

        status = self._unavailable()
        if status:
            return reject(status)
        if not isinstance(text, str) or not text.strip() or len(text) > 16000:
            return reject('invalid_text')
        record = self.record
        prompt = '(input from pet)\n' + text.strip()
        previous_messages = list(record.messages)
        previous_optimistic = record.optimistic_user
        record.messages.extend([{'role': 'user', 'text': prompt},
                                {'role': 'assistant', 'text': ''}])
        record.optimistic_user = True
        self.consumed = True
        try:
            accepted = self.bus.b._command_pi('prompt', record, text=prompt)
        except (ValueError, OSError, RuntimeError):
            # Dispatch may have partially happened. Do not replay this handle.
            record.messages[:] = previous_messages
            record.optimistic_user = previous_optimistic
            return reject('uncertain')
        if not accepted:
            record.messages[:] = previous_messages
            record.optimistic_user = previous_optimistic
            return reject('failed')
        self.bus.changed()
        return {'ok': True, 'status': 'accepted', 'targetId': self.identifier,
                'sessionKey': record.key}
