"""Offline C2C adapter seam. No network client, credentials, or automatic tasks."""
import hashlib
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass
from umeko_plugin_sdk import Plugin, PluginError


def digest(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()


@dataclass(frozen=True)
class Envelope:
    account: str
    sender: str
    message_id: str
    text: str

    @classmethod
    def from_sdk(cls, account, message):
        """Accept the public qqbot-nodejs 1.0.5 normalized C2C shape only.

        account is trusted transport configuration, never taken from the event.
        Raw gateway frames, groups, attachments and bot echoes are not supported.
        """
        if not isinstance(message, dict):
            raise ValueError('Invalid message')
        target = message.get('replyTarget')
        if (message.get('kind') != 'c2c' or not isinstance(target, dict)
                or target.get('scope') != 'c2c' or message.get('senderIsBot')
                or message.get('attachments') or message.get('msgElements')):
            raise ValueError('Only plain C2C text is supported')
        sender, message_id, text = (message.get(k) for k in ('senderId', 'messageId', 'content'))
        if any(not isinstance(v, str) or not v or len(v) > 256 for v in (account, sender, message_id)):
            raise ValueError('Invalid identity')
        if target.get('targetId') != sender or target.get('msgId') != message_id:
            raise ValueError('Reply identity mismatch')
        # Leave room for the host request envelope under the 16 KiB limit.
        if not isinstance(text, str) or not text.strip() or len(json.dumps(text).encode()) > 12000:
            raise ValueError('Invalid text size')
        return cls(account, sender, message_id, text)

    @property
    def target(self):
        return {'scope': 'c2c', 'targetId': self.sender, 'msgId': self.message_id}


class Adapter:
    """Inject sessions + transport.send_text(target, text) from a trusted caller.

    receive() is blocking: call only on a dedicated background worker, never the
    SDK event reader / UI thread. Calls are serialized, including across peers;
    use bounded admission outside this first-slice core. stop() blocks new work
    and suppresses late replies. Host/Context.close owns native task cleanup.
    """
    def __init__(self, sessions, transport, *, account, profile, allowed_senders=(), capacity=256):
        if not isinstance(account, str) or not account or len(account) > 256:
            raise ValueError('Invalid account')
        if not isinstance(profile, str) or not profile:
            raise ValueError('A pre-approved profile is required')
        if not isinstance(capacity, int) or isinstance(capacity, bool) or not 1 <= capacity <= 4096:
            raise ValueError('Invalid dedup capacity')
        self.sessions, self.transport = sessions, transport
        self.account, self.profile = account, profile
        self.allowed_senders = frozenset(allowed_senders)
        self.capacity = capacity
        self.seen = OrderedDict()
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.delivery_lock = threading.RLock()

    def stop(self):
        # Let an already-entered send finish; no send can start after stop returns.
        with self.delivery_lock:
            self.stopped.set()

    def receive(self, message):
        envelope = Envelope.from_sdk(self.account, message)
        # Empty allowlist denies all. No event may change profile or tools.
        if envelope.sender not in self.allowed_senders:
            return {'status': 'denied'}
        with self.lock:
            if self.stopped.is_set():
                return {'status': 'stopped'}
            key = digest(envelope.account, 'c2c', envelope.sender, envelope.message_id)
            if key in self.seen:
                return {'status': 'duplicate'}
            # Mark before ANY host side effect. On ambiguous failure never retry
            # automatically; retained IDs are process-local, not an exactly-once ledger.
            self.seen[key] = True
            if len(self.seen) > self.capacity:
                self.seen.popitem(last=False)
            handle = None
            try:
                acquired = self.sessions.acquire(digest('c2c', envelope.sender),
                    namespace='qq-' + digest(envelope.account), profile=self.profile)
                handle = acquired['handle']
                if self.stopped.is_set():
                    return {'status': 'stopped'}
                submitted = self.sessions.submit(handle, key, envelope.text)
                run_id = submitted['runId']
                terminal = self.sessions.wait(handle, run_id)
                if terminal.get('runId') != run_id:
                    raise ValueError('Terminal run identity mismatch')
                status = terminal.get('status')
                if status not in ('completed', 'failed', 'cancelled'):
                    raise ValueError('Expected a terminal status')
                if self.stopped.is_set():
                    return {'status': 'stopped', 'runId': run_id}
                if status != 'completed':
                    return {'status': status, 'runId': run_id}
                messages = terminal.get('assistantMessages')
                if not isinstance(messages, list) or any(not isinstance(x, str) for x in messages):
                    raise ValueError('Invalid assistant messages')
                text = '\n\n'.join(messages)
                if text:
                    # Exactly one attempt to the captured reply target. No fallback
                    # to current peer / proactive send / automatic retry on ambiguity.
                    with self.delivery_lock:
                        if self.stopped.is_set():
                            return {'status': 'stopped', 'runId': run_id}
                        self.transport.send_text(envelope.target, text)
                return {'status': 'completed', 'runId': run_id, 'replied': bool(text)}
            finally:
                if handle is not None:
                    try:
                        self.sessions.release(handle)
                    except PluginError:
                        # Context shutdown wakes waiters; host owns their cleanup.
                        if not self.stopped.is_set():
                            raise


class OfflineExample(Plugin):
    def handle(self, method, arguments):
        if method != 'status':
            raise PluginError('Unknown operation')
        return {'mode': 'offline', 'connected': False, 'acceptsMessages': False}


def create_plugin(context):
    # Deliberately inert: no live transport and no public message-injection API.
    return OfflineExample(context)
