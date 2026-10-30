from umeko_plugin_sdk import Plugin, PluginError

class Example(Plugin):
    def __init__(self, context):
        super().__init__(context)
        self.pending = {}

    def handle(self, method, arguments):
        if not hasattr(self.context,'request_host') or 'pi.status' not in self.context.host_capabilities.get('operations',{}):
            raise PluginError('请升级到支持 Widget Host API v1 的版本')
        if method != 'inventory':
            raise PluginError('Unknown example method')
        if len(self.pending) >= 8:
            raise PluginError('Wait for existing host requests')
        target = self.context.capture_session()
        identifier = self.context.request_host('pi.status', {'limit':20}, session=target)
        self.pending[identifier] = (self.context.request_id, target)
        return {'status': 'accepted', 'hostRequestId': identifier}

    def on_event(self, name, data):
        if name != 'host.response':
            return
        owner = self.pending.pop(data.get('requestId'), None)
        if owner:
            request, target = owner
            if data.get('result'):
                value=data['result']
                data={**data,'result':{**{k:value[k] for k in ('total','contextCurrent')},
                    'extensions':[{k:str(row.get(k,''))[:160] for k in ('id','name','scope','enabled')} for row in value['extensions']]}}
            self.context.notify_agent('Pi inventory result', data=data,
                request_id=request, session=target, wake=False)

def create_plugin(context):
    return Example(context)
