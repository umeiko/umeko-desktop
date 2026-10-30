"""Observable config_umeko job completion without network or child processes."""
import copy
import unittest
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication, QObject, Signal

from app.umeko_control import UmekoControl, redacted

ROOT = Path(__file__).resolve().parents[1]
APP = QCoreApplication.instance() or QCoreApplication([])


class Pool(QObject):
    event = Signal(object, object)

    def __init__(self, record):
        super().__init__()
        self.records = {record.key: record}

    def find(self, identifier):
        return next((r for r in self.records.values() if r.id == identifier), None)


class Plugins(QObject):
    finished = Signal(str, object)

    def __init__(self):
        super().__init__()
        self.busy = set()


class Manager(QObject):
    operationFinished = Signal(str, object)

    def __init__(self, backend):
        super().__init__()
        self.backend, self.busy = backend, False

    def scan(self):
        self.busy = True
        self.backend.jobStarted.emit('pi-admin:scan')


class Updater(QObject):
    changed = Signal(object)


class Backend(QObject):
    jobStarted = Signal(str)
    jobDone = Signal(str, object)
    piCommandStarted = Signal(object, str)
    toast = Signal(str)

    def __init__(self):
        super().__init__()
        self.root, self._closing, self.kernelBusy = ROOT, False, False
        self._sessions, self._management_jobs = [], set()
        self._view = SimpleNamespace(key='view', id='view', busy=False, failed=False, cancelled=False)
        self._pool = Pool(self._view)
        self.providerPlugins, self.piManagement = Plugins(), Manager(self)
        self.appAbout = SimpleNamespace(updater=Updater())
        self.config = {'providers': []}
        self.store = SimpleNamespace(data={'projects': [], 'sessionMeta': {}})

    def checkKernel(self):
        self.kernelBusy = True
        self.jobStarted.emit('check')

    def updateKernel(self):
        self.toast.emit('当前 Pi 内核已是最新版本')

    def refreshAgent(self):
        self._view.busy = True
        self.piCommandStarted.emit(self._view, 'inspect')
        return True

    def _models_busy(self, *args):
        return False


class PersonaControlTests(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()
        self.control = UmekoControl(self.backend)
        self.addCleanup(self.control.timer.stop)

    def submit(self, operation, arguments=None):
        return self.control.execute({'operation': operation, 'arguments': arguments or {}})

    def job(self, identifier):
        return self.submit('jobs.get', {'id': identifier})['jobs'][0]

    def test_accepted_and_queued_kernel_report_worker_terminal_results(self):
        direct = self.submit('kernel.check')
        self.assertEqual(direct['status'], 'accepted')
        self.assertEqual(self.job(direct['jobId'])['status'], 'running')
        self.backend.kernelBusy = False
        self.backend.jobDone.emit('check', {'ok': True, 'value': '1.4.0'})
        self.assertEqual(self.job(direct['jobId'])['result'], {'ok': True, 'value': '1.4.0'})
        self.assertEqual(self.job(direct['jobId'])['status'], 'done')
        self.backend._view.busy = True
        queued = self.submit('kernel.check')
        self.assertEqual(queued['status'], 'queued')
        self.backend._view.busy = False
        self.control._drain()
        self.assertEqual(self.job(queued['jobId'])['status'], 'running')
        self.backend.kernelBusy = False
        self.backend.jobDone.emit('check', {'ok': False, 'value': 'npm registry unavailable'})
        row = self.job(queued['jobId'])
        self.assertEqual(row['status'], 'failed')
        self.assertEqual(row['result']['error'], 'npm registry unavailable')
        self.assertEqual(set(self.control.jobs), {direct['jobId'], queued['jobId']})

    def test_queued_refresh_keeps_ids_and_finishes_from_native_events(self):
        self.backend._view.busy = True
        first, second = self.submit('agent.refresh'), self.submit('agent.refresh')
        self.assertNotEqual(first['jobId'], second['jobId'])
        self.backend._view.busy = False
        self.control._drain()
        self.assertEqual(self.job(first['jobId'])['status'], 'running')
        self.assertEqual(self.job(second['jobId'])['status'], 'queued')
        resources = {'tools': [{'name': 'config_umeko'}], 'skills': []}
        self.backend._pool.event.emit(self.backend._view, {'type': 'state', 'resources': resources})
        self.assertEqual(self.job(first['jobId'])['status'], 'running')
        self.backend._view.busy = False
        self.backend._pool.event.emit(self.backend._view, {'type': 'done'})
        self.assertEqual(self.job(first['jobId'])['status'], 'done')
        self.assertEqual(self.job(first['jobId'])['result']['resources'], resources)
        self.control._drain()
        self.assertEqual(self.job(second['jobId'])['status'], 'running')
        self.backend._pool.event.emit(self.backend._view, {'type': 'exit', 'message': 'native process exited'})
        self.assertEqual(self.job(second['jobId'])['status'], 'failed')
        self.assertEqual(self.job(second['jobId'])['result']['error'], 'native process exited')
        self.assertEqual(set(self.control.jobs), {first['jobId'], second['jobId']})

    def test_native_error_is_failed_and_false_start_is_not_accepted(self):
        started = self.submit('agent.refresh')
        self.backend._pool.event.emit(self.backend._view, {'type': 'error', 'message': 'extension load failed'})
        self.assertEqual(self.job(started['jobId'])['result']['error'], 'extension load failed')
        self.backend._view.busy = False
        self.backend.refreshAgent = lambda: False
        rejected = self.submit('agent.refresh')
        self.assertFalse(rejected['ok'])
        self.assertEqual(rejected['status'], 'failed')

    def test_running_jobs_are_retained_and_busy_manager_queues_without_dropping(self):
        running = self.submit('kernel.check')['jobId']
        for _ in range(127):
            identifier = self.control._new_job('fixture', 'done')
            self.control.jobs[identifier]['result'] = {'ok': True}
        self.control._new_job('fixture-next', 'done')
        self.assertIn(running, self.control.jobs)
        self.backend.kernelBusy = False
        self.backend.piManagement.busy = True
        scan = self.submit('extensions.scan')
        self.assertEqual(scan['status'], 'queued')
        self.backend.piManagement.busy = False
        self.control._drain()
        self.assertEqual(self.job(scan['jobId'])['status'], 'running')
        # Raw worker success is insufficient until the management apply completes.
        self.backend.jobDone.emit('pi-admin:scan', {'ok': True, 'value': []})
        self.assertEqual(self.job(scan['jobId'])['status'], 'running')
        self.backend.piManagement.operationFinished.emit('pi-admin:scan', {'ok': False, 'value': 'cannot save config'})
        self.assertEqual(self.job(scan['jobId'])['result']['error'], 'cannot save config')

    def test_noop_async_is_done_and_stored_results_redact_credentials(self):
        noop = self.submit('kernel.update')
        self.assertEqual(self.job(noop['jobId'])['status'], 'done')
        self.assertIn('当前 Pi 内核已是最新版本', self.job(noop['jobId'])['result']['messages'])
        started = self.submit('kernel.check')
        self.backend.jobDone.emit('check', {'ok': True, 'value': {'credentials': {'password': 'fixture-secret'}}})
        row = self.job(started['jobId'])
        self.assertEqual(row['result']['value']['credentials'], '[redacted]')
        self.assertNotIn('arguments', self.control.jobs[started['jobId']])

    def test_install_validation_failure_leaves_no_running_job(self):
        manager = self.backend.piManagement
        manager.installState = 'failed'
        manager.installMessage = '请填写 MCP 命令或 JSON；项目范围需先打开项目，并关闭恢复模式'
        manager.addMcp = lambda text, local: None
        rejected = self.submit('mcp.add', {'text': '', 'project': False})
        self.assertFalse(rejected['ok'])
        self.assertEqual(rejected['error'], manager.installMessage)
        self.assertEqual(len(self.control.jobs), 1)
        row = self.submit('jobs.get')['jobs'][0]
        self.assertEqual(row['status'], 'failed')
        self.assertEqual(row['result']['error'], manager.installMessage)

    def test_auth_descriptors_preserve_keys_and_hide_only_secret_values(self):
        source = {'fields': [
            {'key': 'username', 'type': 'string', 'secret': False, 'value': 'alice', 'label': 'User'},
            {'key': 'password', 'type': 'string', 'secret': True, 'value': 'fixture-private', 'hasValue': True}],
            'credentials': {'username': 'private'}, 'headers': {'Authorization': 'Bearer private'},
            'env': {'EXAMPLE_API_KEY': 'private'}}
        original = copy.deepcopy(source)
        output = redacted(source)
        self.assertEqual(output['fields'][0], source['fields'][0])
        self.assertEqual(output['fields'][1], {**source['fields'][1], 'value': '[redacted]'})
        self.assertEqual(output['credentials'], '[redacted]')
        self.assertEqual(output['headers']['Authorization'], '[redacted]')
        self.assertEqual(output['env']['EXAMPLE_API_KEY'], '[redacted]')
        self.assertEqual(source, original)

    def test_duplicate_mapping_alias_returns_exact_validation_error(self):
        from app.controller import Controller
        self.backend.config['providers'] = [{'id': 'fixture', 'api': 'openai', 'models': [{'upstream': 'a', 'alias': 'a'}, {'upstream': 'b', 'alias': 'b'}]}]
        self.backend.store.data['providers'] = self.backend.config['providers']
        self.backend._validate_model_mappings = lambda *args, **kwargs: Controller._validate_model_mappings(self.backend, *args, **kwargs)
        self.backend.saveMappings = lambda raw: Controller.saveMappings(self.backend, raw)
        result = self.submit('models.mappings', {'models': [
            {'provider': 'fixture', 'upstream': 'a', 'alias': 'duplicate'},
            {'provider': 'fixture', 'upstream': 'b', 'alias': 'duplicate'}]})
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error'], '模型 ID 不能为空；别名不能重复或包含空白')


if __name__ == '__main__':
    unittest.main()
