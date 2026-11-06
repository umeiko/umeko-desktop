"""Built-in System Prompt page requests, bound to the current Pi/workspace.

The runtime owns the prompt and workspace overrides. This host only forwards
explicit page actions; neither model tools nor third-party workers can edit it.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer


FIELDS = {
    'systemPrompt.inspect': set(),
    'systemPrompt.toggle': {'id', 'enabled'},
    'systemPrompt.save': {'id', 'text'},
    'systemPrompt.restore': {'id'},
}


class SystemPromptHost(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host, self.b = host, host.b
        self.pending = {}
        self.b._pool.event.connect(self.observe)

    def request(self, request):
        manager = self.host.m
        operation, args = request['operation'], request['arguments']
        if (request['widget'] != 'system-prompt' or not request.get('page')
                or not manager.entries['system-prompt'].get('builtin')
                or manager._page != 'system-prompt'):
            raise ValueError('Open the built-in System Prompt page to use this operation')
        if operation not in FIELDS or set(args) != FIELDS[operation]:
            raise ValueError('Invalid System Prompt arguments')
        action = operation.split('.')[1]
        if action != 'inspect' and (not isinstance(args['id'], str) or not args['id']):
            raise ValueError('Select a prompt source first')
        if action == 'toggle' and type(args['enabled']) is not bool:
            raise ValueError('enabled must be a boolean')
        if action == 'save' and not isinstance(args['text'], str):
            raise ValueError('text must be a string')
        record = self.b._view
        if record.key != request['session']['token'] or record.workspace != request['session']['workspace']:
            raise ValueError('The target chat or workspace changed')
        if record.busy or record.subagents_active or self.b.kernelBusy:
            raise ValueError('Wait for the current task to finish')
        self.pending[request['id']] = (request, record)
        if not self.b._command_pi('system-prompt', record=record,
                requestId=request['id'], promptOperation=action, **args):
            self.pending.pop(request['id'], None)
            raise ValueError('Could not load the current system prompt')
        QTimer.singleShot(45000, self, lambda: self.expire(request['id']))

    def expire(self, identifier):
        pending = self.pending.pop(identifier, None)
        if pending:
            self.host._reply(pending[0], {'ok': False, 'error': 'System prompt request timed out; retry'})

    def observe(self, record, event):
        kind = event.get('type')
        if kind == 'system_prompt':
            pending = self.pending.pop(event.get('requestId'), None)
            if pending and pending[1] is record:
                self.host._reply(pending[0], event.get('result', {}))
        elif kind in ('exit', 'error'):
            for identifier, (request, owner) in list(self.pending.items()):
                if owner is record:
                    self.pending.pop(identifier)
                    self.host._reply(request, {'ok': False, 'error': event.get('message') or 'Pi stopped before returning its prompt'})
