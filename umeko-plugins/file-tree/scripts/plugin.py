import os
from umeko_plugin_sdk import Plugin, PluginError

class Explorer(Plugin):
    def handle(self, method, args):
        if method=='list':
            path=self.context.resolve_workspace(args.get('path','.'))
            if not path.is_dir():raise PluginError('该目录不存在或不可访问')
            show=args.get('showHidden',self.context.config.get('showHidden',False))
            limit=self.context.config.get('directoryLimit',1000);rows=[];truncated=False
            with os.scandir(path) as entries:
                for entry in entries:
                    if self.context.cancelled.is_set():break
                    if entry.name=='.git' or not show and entry.name.startswith('.'):continue
                    if len(rows)>=limit:truncated=True;break
                    try:
                        symlink=entry.is_symlink();directory=entry.is_dir(follow_symlinks=False)
                        relative=os.path.relpath(entry.path,self.context.workspace).replace('\\','/')
                        rows.append({'name':entry.name,'path':relative,'directory':directory,'symlink':symlink,'extension':entry.name.rsplit('.',1)[-1].lower() if '.' in entry.name else ''})
                    except OSError:continue
            rows.sort(key=lambda row:(not row['directory'],row['name'].casefold()))
            return {'path':args.get('path','.'),'entries':rows,'truncated':truncated,'root':self.context.workspace.name}
        if method=='preview':self.context.preview_file(args['path']);return {'opened':True}
        if method=='attach':self.context.attach_file(args['path']);return {'attached':True}
        if method=='copyPath':return {'path':str(self.context.resolve_workspace(args['path']))}
        raise PluginError('未知文件树操作')
def create_plugin(context):return Explorer(context)
