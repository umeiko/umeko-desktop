"""Saved SSH environment names and transient connection state for the desktop."""
import re


_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}')
_HOST = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,252}')
_STATES = {'disconnected', 'connecting', 'connected', 'reconnecting', 'error'}


def network_config(store):
    proxy = store.data.get('remoteNetworkProxy')
    return {'enabled': store.data.get('remoteNetworkEnabled') is not False,
            'proxy': proxy if isinstance(proxy, str) else ''}


class RemoteEnvironments:
    def __init__(self, store, changed):
        self.store = store
        self.changed = changed
        self.connections = {}

    def configured(self):
        saved = self.store.data.get('remoteEnvironments')
        if not isinstance(saved, list):
            return []
        return [item for item in saved if isinstance(item, dict)
                and all(isinstance(item.get(key), str) for key in ('name', 'host', 'platform'))
                and _NAME.fullmatch(item['name']) and _HOST.fullmatch(item['host'])
                and item['platform'] in ('linux', 'windows')]

    def rows(self):
        rows = []
        for item in self.configured():
            identity = (item['name'], item['host'], item['platform'])
            states = list(self.connections.get(identity, {}).values())
            status = next((status for state in ('connected', 'reconnecting', 'connecting', 'error', 'disconnected')
                           for status in reversed(states) if status['state'] == state), {'state': 'disconnected'})
            rows.append({key: item[key] for key in ('name', 'host', 'platform')} | status)
        return rows

    def add(self, name, host, platform):
        if not _NAME.fullmatch(name):
            raise ValueError('Use a unique environment name made of letters, numbers, dots, dashes or underscores.')
        if not _HOST.fullmatch(host):
            raise ValueError('Enter an OpenSSH host alias. Configure credentials, port and jump hosts in OpenSSH.')
        if platform not in ('linux', 'windows'):
            raise ValueError('platform must be linux or windows')
        environments = self.configured()
        existing = next((item for item in environments if item['name'] == name), None)
        item = {'name': name, 'host': host, 'platform': platform}
        if existing and any(existing[key] != value for key, value in item.items()):
            raise ValueError('This environment name already exists.')
        if not existing:
            self.store.data['remoteEnvironments'] = [*environments, item]
            self.store.save()
            self.changed()
        return next(row for row in self.rows() if row['name'] == name)

    def remove(self, name):
        environments = self.configured()
        item = next((item for item in environments if item['name'] == name), None)
        if not item:
            raise ValueError('Unknown remote environment: ' + name)
        self.store.data['remoteEnvironments'] = [item for item in environments if item['name'] != name]
        self.store.save()
        self.connections.pop((item['name'], item['host'], item['platform']), None)
        self.changed()

    def observe(self, source, event):
        identity = tuple(event.get(key) for key in ('name', 'host', 'platform'))
        state = event.get('state')
        if state not in _STATES:
            return
        if not any(identity == (row['name'], row['host'], row['platform']) for row in self.configured()):
            return
        states = self.connections.setdefault(identity, {})
        status = {'state': state}
        for key in ('sshClient', 'message', 'sshError'):
            if isinstance(event.get(key), str) and event[key]:
                status[key] = event[key]
        for key in ('attempt', 'retryAfterMs', 'nextRetryAt', 'outageStartedAt', 'outageNoticeAt'):
            if isinstance(event.get(key), (int, float)) and not isinstance(event[key], bool) and event[key] > 0:
                status[key] = event[key]
        for key in ('recovered', 'resumed'):
            if isinstance(event.get(key), bool):
                status[key] = event[key]
        network = event.get('networkStatus')
        if state == 'connected' and isinstance(network, dict) and network.get('network') in ('local', 'remote'):
            status['networkStatus'] = {key: network[key] for key in ('network', 'message', 'outbound', 'outboundLabel')
                                       if isinstance(network.get(key), str)}
            if type(network.get('port')) is int and 0 < network['port'] <= 65535:
                status['networkStatus']['port'] = network['port']
        if states.get(source) != status:
            states.pop(source, None)
            states[source] = status
            self.changed()

    def disconnect(self, source):
        changed = False
        for states in self.connections.values():
            if source in states:
                del states[source]
                changed = True
        if changed:
            self.changed()
