"""Keep background model discovery out of live turns and upstream chat streams."""
from collections import Counter
from contextlib import contextmanager
from threading import Condition


class ReasoningActivity:
    def __init__(self):
        self.condition = Condition()
        self.busy, self.probes = set(), set()
        self.chats, self.waiting = Counter(), Counter()
        self.closed = False

    def set_busy(self, keys):
        with self.condition:
            self.busy = set(keys)
            self.condition.notify_all()

    @contextmanager
    def chat(self, key):
        # Chats remain concurrent with each other. A chat arriving during one
        # tiny probe takes priority over the next probe, on the network thread.
        with self.condition:
            self.waiting[key] += 1
            self.condition.notify_all()
            try:
                self.condition.wait_for(lambda: key not in self.probes)
                self.chats[key] += 1
            finally:
                self.waiting[key] -= 1
        try:
            yield
        finally:
            with self.condition:
                self.chats[key] -= 1
                self.condition.notify_all()

    @contextmanager
    def probe(self, keys):
        keys = set(keys)
        with self.condition:
            self.condition.wait_for(lambda: self.closed or (
                not keys.intersection(self.busy | self.probes)
                and not any(self.chats[key] or self.waiting[key] for key in keys)))
            if self.closed:
                raise RuntimeError('Reasoning discovery closed')
            self.probes.update(keys)
        try:
            yield
        finally:
            with self.condition:
                self.probes.difference_update(keys)
                self.condition.notify_all()

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
