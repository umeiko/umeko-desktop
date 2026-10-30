"""One app process; every subscription retains its own captured chat identity."""
import threading
from umeko_plugin_sdk import Plugin, PluginError


class FileWatchService(Plugin):
    def __init__(self,context):
        super().__init__(context)
        self.lock=threading.Lock();self.subscriptions={}
        self.thread=threading.Thread(target=self.watch,daemon=True);self.thread.start()

    @staticmethod
    def stamp(path):
        try:
            value=path.stat();return value.st_mtime_ns,value.st_size
        except OSError:return None

    def handle(self,method,arguments):
        target=self.context.capture_session();token=target['token']
        if method=='subscribe':
            path=self.context.resolve_workspace(arguments['path'],session=target)
            if not path.is_file():raise PluginError('请选择工作区中存在的文件')
            with self.lock:
                if token not in self.subscriptions and len(self.subscriptions)>=32:raise PluginError('最多监听 32 个聊天的文件')
                self.subscriptions[token]={'session':target,'path':path,'stamp':self.stamp(path)}
            return {'subscribed':True,'path':arguments['path'],'sessionId':target['id']}
        if method=='unsubscribe':
            with self.lock:self.subscriptions.pop(token,None)
            return {'subscribed':False}
        if method=='status':
            with self.lock:item=self.subscriptions.get(token)
            return {'subscribed':bool(item),'path':str(item['path']) if item else ''}
        raise PluginError('未知服务操作')

    def watch(self):
        while not self.context.cancelled.wait(self.context.config['intervalSeconds']):
            with self.lock:items=list(self.subscriptions.items())
            for token,item in items:
                try:path=self.context.resolve_workspace(str(item['path']),session=item['session'])
                except PluginError:
                    with self.lock:self.subscriptions.pop(token,None)
                    continue
                stamp=self.stamp(path)
                if stamp==item['stamp']:continue
                with self.lock:
                    if self.subscriptions.get(token) is not item:continue
                    item['stamp']=stamp
                self.context.notify_agent('监听的文件发生变化',data={'path':str(path),'exists':stamp is not None},session=item['session'],wake=True)

    def close(self):
        super().close();self.thread.join(timeout=2)


def create_plugin(context):return FileWatchService(context)
