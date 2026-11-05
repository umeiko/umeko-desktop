"""Deterministic offline scheduling: user chats overlap, discovery never does."""
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.gateway import Gateway
from app.integration import UnconfiguredAdapter
from app.reasoning_activity import ReasoningActivity


class ReasoningSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.activity = ReasoningActivity()
        self.errors, self.threads, self.releases = [], [], []
        self.addCleanup(self.finish_threads)

    def finish_threads(self):
        for release in self.releases:
            release.set()
        self.activity.set_busy(set())
        self.activity.close()
        for thread in self.threads:
            thread.join(4)
            self.assertFalse(thread.is_alive(), 'fixture worker failed to finish')
        self.assertEqual(self.errors, [])

    def start(self, function):
        def guarded():
            try:
                function()
            except Exception as error:
                self.errors.append(error)
        thread = threading.Thread(target=guarded, daemon=True)
        self.threads.append(thread)
        thread.start()
        return thread

    def event(self, *, release=False):
        event = threading.Event()
        if release:
            self.releases.append(event)
        return event

    def wait(self, event):
        self.assertTrue(event.wait(4), 'fixture event deadline exceeded')

    def test_same_model_chats_overlap_but_probe_waits_for_both(self):
        key = ('fixture', 'model')
        entered = [self.event(), self.event()]
        release = [self.event(release=True), self.event(release=True)]
        probe_waiting, probe_entered = self.event(), self.event()
        order = []

        def chat(index):
            with self.activity.chat(key):
                order.append(('chat-start', index))
                entered[index].set()
                self.wait(release[index])
                order.append(('chat-end', index))

        def probe():
            with self.activity.probe({key}):
                order.append(('probe', 0))
                probe_entered.set()

        self.start(lambda: chat(0))
        self.wait(entered[0])
        self.start(lambda: chat(1))
        self.wait(entered[1])
        original_wait = self.activity.condition.wait

        def waiting(*args, **kwargs):
            probe_waiting.set()
            return original_wait(*args, **kwargs)

        with patch.object(self.activity.condition, 'wait', side_effect=waiting):
            worker = self.start(probe)
            self.wait(probe_waiting)
            with self.activity.condition:
                self.assertEqual(self.activity.chats[key], 2)
                self.assertFalse(probe_entered.is_set())
            release[0].set()
            self.threads[0].join(4)
            with self.activity.condition:
                self.assertEqual(self.activity.chats[key], 1)
                self.assertFalse(probe_entered.is_set())
            release[1].set()
            self.wait(probe_entered)
            worker.join(4)
        self.assertGreater(order.index(('probe', 0)), order.index(('chat-end', 0)))
        self.assertGreater(order.index(('probe', 0)), order.index(('chat-end', 1)))

    def test_busy_model_does_not_block_different_model_probe(self):
        busy, other = ('fixture', 'busy'), ('fixture', 'other')
        self.activity.set_busy({busy})
        entered = self.event()

        def probe():
            with self.activity.probe({other}):
                entered.set()

        self.start(probe)
        self.wait(entered)
        self.assertEqual(self.activity.busy, {busy})

    def test_gateway_finishes_current_tiny_probe_then_chat_then_next_probe_after_turn(self):
        with tempfile.TemporaryDirectory() as temp:
            provider = {'id': 'fixture', 'name': 'Fixture', 'api': 'openai',
                        'baseUrl': 'https://fixture.invalid/v1', 'key': '',
                        'models': [{'alias': 'model', 'upstream': 'model'}]}
            store = SimpleNamespace(directory=Path(temp), data={'providers': [provider]})
            gateway = Gateway(store, UnconfiguredAdapter())
            self.activity = gateway.reasoning_activity
            key = ('fixture', 'model')
            probe_entered, probe_release = self.event(), self.event(release=True)
            chat_entered, chat_release = self.event(), self.event(release=True)
            probe_finished, chat_finished, next_probe = self.event(), self.event(), self.event()
            chat_waiting = self.event()
            calls = []

            def events(alias, messages, *args, **kwargs):
                is_probe = messages[0]['content'] == 'Reply OK.'
                if is_probe:
                    count = sum(call == 'probe' for call in calls)
                    calls.append('probe')
                    if count == 0:
                        probe_entered.set()
                        self.wait(probe_release)
                    else:
                        next_probe.set()
                else:
                    calls.append('chat')
                    chat_entered.set()
                    self.wait(chat_release)
                yield {'choices': [{'message': {'content': 'OK'}, 'finish_reason': 'stop'}]}

            def detection(request, **kwargs):
                request('high', 'openai', 1)
                request('off', 'openai', 1)
                probe_finished.set()
                return {'levels': {}, 'format': {}}

            def chat():
                list(gateway.events('model', [{'role': 'user', 'content': 'actual user prompt'}]))
                chat_finished.set()

            original_wait = self.activity.condition.wait

            def waiting(*args, **kwargs):
                if threading.current_thread().name == 'user-chat':
                    chat_waiting.set()
                return original_wait(*args, **kwargs)

            with patch.object(gateway, '_events', side_effect=events), \
                    patch('app.gateway.detect_model', side_effect=detection), \
                    patch.object(self.activity.condition, 'wait', side_effect=waiting):
                self.start(lambda: gateway.detect_reasoning('model', 'fixture'))
                self.wait(probe_entered)
                self.activity.set_busy({key})

                def named_chat():
                    threading.current_thread().name = 'user-chat'
                    chat()

                self.start(named_chat)
                self.wait(chat_waiting)
                with self.activity.condition:
                    self.assertEqual(calls, ['probe'])
                probe_release.set()
                self.wait(chat_entered)
                self.assertEqual(calls, ['probe', 'chat'])
                self.assertFalse(next_probe.is_set())
                chat_release.set()
                self.wait(chat_finished)
                with self.activity.condition:
                    self.assertFalse(next_probe.is_set())
                    self.assertEqual(self.activity.busy, {key})
                self.activity.set_busy(set())
                self.wait(probe_finished)
                self.assertEqual(calls, ['probe', 'chat', 'probe'])


if __name__ == '__main__':
    unittest.main()
