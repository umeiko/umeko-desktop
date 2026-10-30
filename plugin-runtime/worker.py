"""JSONL worker; importing packages and managing ZIPs never activates plugin code."""
from __future__ import annotations
import contextlib, copy, hashlib, importlib.util, json, os, signal, sys, threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from umeko_plugin_sdk import Context, Plugin, PluginError
from umeko_plugin_sdk.packages import install, validate, validate_config
OUTPUT=sys.stdout
sys.stdout=sys.stderr
LOCK=threading.Lock()
MAX=2*1024*1024

def emit(value):
    raw=json.dumps(value,ensure_ascii=True,allow_nan=False)
    if len(raw)>MAX:raise PluginError('插件返回内容过大')
    with LOCK:OUTPUT.write(raw+'\n');OUTPUT.flush()

def main():
    plugin=None;context=None
    def shutdown(*_):
        if context:context.close()
        if plugin:
            with contextlib.suppress(Exception):plugin.close()
        raise SystemExit(0)
    signal.signal(signal.SIGTERM,shutdown)
    while True:
        raw=sys.stdin.readline(MAX+1)
        if not raw:break
        request={}
        try:
            if len(raw)>MAX:raise PluginError('插件请求过大')
            request=json.loads(raw);op=request.get('operation');args=request.get('arguments',{})
            if op=='install': result=install(args['archive'],args['destination'],args.get('reserved',[]),args.get('configs'))
            elif op=='config':
                _,_,schema=validate(args['path']);validate_config(args['config'],schema);result={'config':args['config']}
            elif op=='initialize':
                folder=Path(args['path']).resolve();m,defaults,schema=validate(folder)
                config=args.get('config',defaults);validate_config(config,schema)
                session=copy.deepcopy(args['session'])
                if 'session.read' not in m.get('permissions',[]):session.pop('messages',None)
                state=Path(args['stateDir']);state.mkdir(parents=True,exist_ok=True)
                context=Context(folder,state,config,session,m.get('permissions',[]),m.get('executables',{}),
                    lambda event:emit({'type':'event',**event}),lifecycle=m.get('lifecycle','session'),
                    host_capabilities=copy.deepcopy(args.get('hostCapabilities',{})),
                    runtimes=copy.deepcopy(args.get('runtimes',{})))
                vendor=folder/'vendor'
                if vendor.is_dir():sys.path.insert(0,str(vendor))
                entry,_,factory=m['entrypoint'].partition(':')
                namespace='_umeko_desktop_plugin_'+hashlib.sha256(str(folder).encode()).hexdigest()[:20]
                import types
                package=types.ModuleType(namespace);package.__path__=[str((folder/entry).parent)];sys.modules[namespace]=package
                spec=importlib.util.spec_from_file_location(namespace+'.entry',folder/entry)
                module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
                plugin=getattr(module,factory)(context)
                if not isinstance(plugin,Plugin):raise PluginError('插件必须继承 umeko_plugin_sdk.Plugin')
                result={'ready':True}
            elif op in ('call','agentCall'):
                if plugin is None:raise PluginError('插件尚未启动')
                if op=='agentCall':
                    method=m.get('agent',{}).get('methods',{}).get(args['method'])
                    if method is None:raise PluginError('该方法未在 Widget 的 Agent 接口中公开')
                    validate_config(args.get('arguments',{}),method['parameters'])
                context.request_id=str(request.get('id',''));context.call_source='agent' if op=='agentCall' else 'ui'
                context.request_session=copy.deepcopy(args.get('session',context.session))
                if 'session.read' not in context.permissions:context.request_session.pop('messages',None)
                try:result=plugin.handle(args['method'],args.get('arguments',{}))
                finally:context.request_id='';context.call_source='';context.request_session={}
            elif op=='session':
                if context:
                    session=copy.deepcopy(args['session'])
                    if 'session.read' not in context.permissions:session.pop('messages',None)
                    context.session=session
                    plugin.on_event('session.changed',copy.deepcopy(session))
                result={'updated':True}
            elif op=='event':
                if plugin is None:raise PluginError('插件尚未启动')
                plugin.on_event(args['name'],args.get('data',{}));result={'received':True}
            else:raise PluginError('未知插件请求')
            emit({'type':'response','id':request.get('id'),'ok':True,'result':result})
        except Exception as error:
            message=str(error)[:1000] if isinstance(error,(PluginError,ValueError)) else '插件运行失败，请检查插件日志和依赖'
            emit({'type':'response','id':request.get('id'),'ok':False,'error':message})
    if context:context.close()
    if plugin:
        with contextlib.suppress(Exception):plugin.close()

if __name__=='__main__':main()
