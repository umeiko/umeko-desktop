import tempfile
import unittest

from PySide6.QtCore import QCoreApplication

from app.gateway import _quota_exhausted
from app.global_agents import GlobalAgents
from app.model_groups import GROUP_MODEL, GROUP_PROVIDER
from tests.test_global_agents import Backend, Manager


class ModelRoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.backend = Backend(self.directory.name)
        self.backend.gateway.models = lambda: [
            {"id": "test", "providerID": "provider"},
            {"id": "replacement", "providerID": "provider", "reasoningLevels": ["low"]},
        ]
        self.backend.gateway.model_group_descriptor = lambda: {"id": GROUP_MODEL}
        self.manager = Manager(self.backend)
        self.service = GlobalAgents(self.manager)
        self.service.start()
        self.service.allow_automatic_creation = True
        self.addCleanup(self.service.close)

    def test_create_inherits_a_model_group_and_validates_an_explicit_model(self):
        caller = self.backend._view
        caller.model, caller.provider = GROUP_MODEL, GROUP_PROVIDER
        for key, args, expected in [
            ("group", {}, GROUP_MODEL),
            ("chosen", {"model": "replacement"}, "replacement"),
        ]:
            created = self.service.execute("agent_bus.create", {"requestKey": key, **args}, caller)
            self.assertEqual(created["model"], expected)
            self.assertEqual(self.service.ensure(created["id"]).model, expected)
        with self.assertRaises(ValueError):
            self.service.execute("agent_bus.create", {"requestKey": "invalid", "model": "missing"}, caller)

    def test_quota_pause_preserves_the_record_and_resumes_the_same_conversation(self):
        caller = self.backend._view
        created = self.service.execute("agent_bus.create", {"requestKey": "member"}, caller)
        member = self.service.ensure(created["id"])
        member.messages = [{"role": "user", "text": "Earlier work"}]
        self.service.observe(member, {"type": "message", "quotaExhausted": True})
        self.service.observe(member, {"type": "done"})
        self.assertEqual(self.service.activity(member.global_agent)["state"], "quota_paused")
        self.backend._command_pi.assert_not_called()
        with self.assertRaises(ValueError):
            self.service.execute("agent_bus.set_model", {"targetId": created["targetId"],
                                 "model": "replacement", "reasoningEffort": "high"}, caller)
        self.service.execute("agent_bus.set_model", {"targetId": created["targetId"],
                             "model": "replacement", "reasoningEffort": "low"}, caller)
        self.service.tick()
        self.backend._command_pi.assert_called_once_with("resume-model", member)
        self.assertIs(self.service.ensure(member.global_agent), member)
        self.assertEqual((member.model, member.reasoning_effort), ("replacement", "low"))
        self.assertEqual(member.messages[0]["text"], "Earlier work")

    def test_rate_limit_and_quota_exhaustion_are_distinct(self):
        self.assertFalse(_quota_exhausted("too many requests", {"status": 429}))
        self.assertTrue(_quota_exhausted("insufficient_quota", {"status": 429}))
        self.assertTrue(_quota_exhausted("", {"status": 402}))
