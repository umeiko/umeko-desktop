import unittest
from uuid import uuid4
from app.subagent_admission import SubagentAdmission


class SubagentAdmissionTests(unittest.TestCase):
    def test_desktop_fifo_survives_cancel_lower_and_worker_exit(self):
        delivered = []

        def send(owner, reply):
            delivered.append((owner, reply['ticket'], reply['state']))
            return True

        broker = SubagentAdmission(send, limit=2)
        a, b, c = object(), object(), object()

        def issue(owner, action='acquire', ticket=None):
            ticket = ticket or str(uuid4())
            broker.event(owner, {'ticket': ticket, 'action': action})
            return ticket

        a1, a2 = issue(a), issue(a)
        b1, c1 = issue(b), issue(c)
        broker.set_limit(1)
        self.assertEqual(broker.active, {(a, a1), (a, a2)})
        issue(b, 'cancel', b1)
        issue(a, 'release', a1)
        self.assertIn((c, c1), broker.waiting)
        broker.owner_exited(a)
        self.assertEqual(broker.active, {(c, c1)})
        self.assertEqual(delivered[-1], (c, c1, 'granted'))
        self.assertNotIn((b, b1, 'granted'), delivered)
        issue(c, 'release', c1)
        self.assertFalse(broker.active or broker.waiting)
