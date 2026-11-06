"""Timer-driven native session tasks, with no front-chat notifications."""
import copy
import json
import threading
import uuid
from umeko_plugin_sdk import Plugin, PluginError


class SessionTaskService(Plugin):
    def __init__(self, context):
        super().__init__(context)
        self.lock = threading.Lock()
        self.latest = {'status': 'idle'}
        self.thread = threading.Thread(target=self.run_tasks, daemon=True)
        self.thread.start()

    def set_latest(self, value):
        with self.lock:self.latest = copy.deepcopy(value)
        # The task result belongs to the service, not to the foreground composer.
        (self.context.state_dir / 'latest-task.json').write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

    def handle(self, method, arguments):
        if method != 'status':raise PluginError('Unknown service operation')
        with self.lock:return copy.deepcopy(self.latest)

    def run_tasks(self):
        config = dict(self.context.config)
        while not self.context.cancelled.is_set():
            handle = None
            try:
                external_key = config['externalKey'] or 'task-' + uuid.uuid4().hex
                acquired = self.context.sessions.acquire(external_key, profile=config['profile'])
                handle = acquired['handle']
                self.context.sessions.subscribe(handle)
                submitted = self.context.sessions.submit(handle, uuid.uuid4().hex, config['content'])
                self.set_latest({'status': submitted['disposition'], 'externalKey': external_key,
                    'sessionId': acquired['sessionId'], 'runId': submitted['runId'], 'created': acquired['created']})
                terminal = self.context.sessions.wait(handle, submitted['runId'])
                self.set_latest({'externalKey': external_key, 'sessionId': acquired['sessionId'], **terminal})
            except Exception as error:
                if not self.context.cancelled.is_set():
                    self.set_latest({'status': 'failed', 'error': str(error)[:1000]})
            finally:
                if handle and not self.context.cancelled.is_set():
                    try:self.context.sessions.release(handle)
                    except PluginError:pass
            if config['oneShot'] or self.context.cancelled.wait(config['intervalSeconds']):break

    def close(self):
        # Context.close wakes any pending helper wait. The host owns native-run cleanup.
        super().close()
        self.thread.join(timeout=2)


def create_plugin(context):return SessionTaskService(context)
