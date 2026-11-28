"""Desktop-owned admission of native Pi subagent runs (one FIFO across workers)."""
from collections import OrderedDict
from uuid import UUID

DEFAULT_SUBAGENT_LIMIT = 10
MAX_WAITERS = 256


def valid_subagent_limit(value):
    return type(value) is int and 1 <= value <= 20


class SubagentAdmission:
    def __init__(self, send, limit=DEFAULT_SUBAGENT_LIMIT):
        self._send = send
        self.limit = limit if valid_subagent_limit(limit) else DEFAULT_SUBAGENT_LIMIT
        self.waiting = OrderedDict()
        self.active = set()
        self.closed = False

    @staticmethod
    def _valid_ticket(value):
        if not isinstance(value, str) or len(value) != 36:
            return False
        try:
            ident = UUID(value)
        except ValueError:
            return False
        return ident.version == 4 and str(ident) == value

    def _reply(self, owner, ticket, state):
        return self._send(owner, {"type": "subagent-admission-reply", "ticket": ticket, "state": state})

    def set_limit(self, limit):
        if not valid_subagent_limit(limit):
            raise ValueError("Subagent concurrency must be an integer from 1 to 20")
        self.limit = limit
        self._drain()

    def _drain(self):
        while not self.closed and self.waiting and len(self.active) < self.limit:
            (owner, ticket), _ = self.waiting.popitem(last=False)
            if self._reply(owner, ticket, "granted"):
                self.active.add((owner, ticket))

    def event(self, owner, message):
        ticket = message.get("ticket")
        if not self._valid_ticket(ticket):
            return
        key = owner, ticket
        action = message.get("action")
        if action == "acquire":
            if key in self.waiting or key in self.active:
                return
            if self.closed or len(self.waiting) >= MAX_WAITERS:
                self._reply(owner, ticket, "rejected")
                return
            self.waiting[key] = None
            self._drain()
            if key in self.waiting and not self._reply(owner, ticket, "waiting"):
                self.waiting.pop(key, None)
        elif action in ("cancel", "release"):
            # Bridge cancels before observing a grant, while started work
            # returns its slot only from the settled finally block.
            self.waiting.pop(key, None)
            self.active.discard(key)
            self._drain()

    def remove_waiters(self, owner, *, notify=True):
        for entry in list(self.waiting):
            if entry[0] is owner:
                self.waiting.pop(entry, None)
                if notify:
                    self._reply(*entry, "rejected")

    def owner_exited(self, owner):
        self.remove_waiters(owner)
        self.active = {key for key in self.active if key[0] is not owner}
        self._drain()

    def close(self):
        self.closed = True
        for entry in list(self.waiting):
            self._reply(*entry, "rejected")
        self.waiting.clear()
        self.active.clear()
