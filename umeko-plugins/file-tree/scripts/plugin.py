import ntpath, os, posixpath, shutil
from pathlib import Path
from umeko_plugin_sdk import Plugin, PluginError

class Explorer(Plugin):
    def _remote_rel(self, value, *, allow_root=False):
        self.context.require('workspace.read')
        raw = str(value or '.').replace('\\', '/').strip()
        if not raw or raw == '.':
            if allow_root: return '.'
            raise PluginError('请选择工作目录中的文件或子目录')
        norm = posixpath.normpath(raw)
        if norm == '.':
            if allow_root: return '.'
            raise PluginError('不能操作工作目录之外或工作目录本身')
        if norm == '..' or norm.startswith('../') or norm.startswith('/'):
            raise PluginError('不能操作工作目录之外或工作目录本身')
        return norm

    def _remote_root_label(self):
        remote = self.context.remote_workspace or {}
        path = str(remote.get('remotePath') or '').rstrip('/\\')
        base = path.replace('\\', '/').rsplit('/', 1)[-1] or path or 'workspace'
        host = remote.get('host') or ''
        return f'{host}:{base}' if host else base

    def _remote_full_path(self, rel):
        remote = self.context.remote_workspace or {}
        root = str(remote.get('remotePath') or '')
        if not rel or rel == '.': return root
        if remote.get('platform') == 'windows':
            return ntpath.normpath(ntpath.join(root, rel.replace('/', '\\')))
        return posixpath.normpath(posixpath.join(root, rel))

    def entry_path(self,value):
        self.context.require('workspace.read')
        root=self.context.resolve_workspace();candidate=root/value
        if candidate.name in ('','.', '..'):raise PluginError('请选择工作目录中的文件或子目录')
        path=candidate.parent.resolve()/candidate.name
        if not path.is_relative_to(root) or path==root:raise PluginError('不能操作工作目录之外或工作目录本身')
        return path

    def handle(self, method, args):
        if self.context.is_remote:
            return self._handle_remote(method, args)
        if method=='focus':
            path=self.context.resolve_workspace(args['path'])
            if not path.exists():raise PluginError('该文件或目录不存在')
            relative=path.relative_to(self.context.workspace.resolve()).as_posix()
            self.context.publish('file.select',{'path':relative});return {'path':relative,'published':True}
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
        if method=='openWith':self.context.open_with(args['path']);return {'opened':True}
        if method=='openDefault':self.context.open_file(args['path']);return {'opened':True}
        if method=='reveal':self.context.reveal_file(args['path']);return {'revealed':True}
        if method in ('copy','cut'):
            if method=='cut':self.context.require('workspace.write')
            self.context.copy_files([args['path']],cut=method=='cut');return {'copied':True}
        if method in ('rename','delete'):
            self.context.require('workspace.write');path=self.entry_path(args['path'])
            if method=='rename':
                name=args.get('name','').strip()
                if not name or name in ('.','..') or len(name)>255 or any(char in name for char in '/\\\0'):raise PluginError('请输入有效的文件名称')
                target=self.entry_path(str(Path(args['path']).parent/name))
                if target.exists() or target.is_symlink():raise PluginError('同名文件或文件夹已存在')
                path.rename(target);return {'changed':True,'path':target.relative_to(self.context.workspace.resolve()).as_posix()}
            if path.is_symlink() or path.is_file():path.unlink()
            elif path.is_dir():
                resolved=path.resolve();root=self.context.workspace.resolve()
                if resolved==root or not resolved.is_relative_to(root):raise PluginError('目录超出工作区范围')
                shutil.rmtree(path)
            else:raise PluginError('文件已不存在')
            return {'changed':True,'path':path.parent.relative_to(self.context.workspace.resolve()).as_posix()}
        raise PluginError('未知文件树操作')

    def _handle_remote(self, method, args):
        if method == 'focus':
            rel = self._remote_rel(args.get('path', ''))
            stat = self.context.workspace_stat(rel)
            if not stat.get('exists'): raise PluginError('该文件或目录不存在')
            self.context.publish('file.select', {'path': rel})
            return {'path': rel, 'published': True}
        if method == 'list':
            rel = self._remote_rel(args.get('path', '.'), allow_root=True)
            res = self.context.workspace_read_dir(rel, with_metadata=True)
            show = args.get('showHidden', self.context.config.get('showHidden', False))
            limit = self.context.config.get('directoryLimit', 1000)
            rows = []; truncated = False
            for entry in res.get('entries', []):
                name = entry.get('name', '')
                if not name or name == '.git' or (not show and name.startswith('.')): continue
                if len(rows) >= limit: truncated = True; break
                child_rel = name if rel == '.' else f'{rel}/{name}'
                rows.append({
                    'name': name, 'path': child_rel,
                    'directory': bool(entry.get('isDirectory')),
                    'symlink': bool(entry.get('isSymlink')),
                    'extension': name.rsplit('.', 1)[-1].lower() if '.' in name else '',
                })
            rows.sort(key=lambda row: (not row['directory'], row['name'].casefold()))
            return {'path': args.get('path', '.'), 'entries': rows, 'truncated': truncated, 'root': self._remote_root_label()}
        if method in ('preview', 'openDefault', 'openWith'):
            rel = self._remote_rel(args['path'])
            res = self.context.workspace_preview_file(rel)
            self.context.emit({'event': 'preview.file', 'arguments': {'path': res['localPath'], 'session': self.context.capture_session()}})
            return {'opened': True}
        if method == 'attach':
            rel = self._remote_rel(args['path'])
            res = self.context.workspace_preview_file(rel)
            self.context.emit({'event': 'session.attach', 'arguments': {'path': res['localPath'], 'session': self.context.capture_session()}})
            return {'attached': True}
        if method == 'copyPath':
            rel = self._remote_rel(args['path'])
            return {'path': self._remote_full_path(rel)}
        if method == 'reveal':
            rel = self._remote_rel(args['path'])
            self.context.notify('远程路径：' + self._remote_full_path(rel))
            return {'revealed': True}
        if method in ('copy', 'cut'):
            raise PluginError('远程目录暂不支持本机系统剪贴板复制文件，请使用复制路径或下载预览')
        if method in ('rename', 'delete'):
            self.context.require('workspace.write')
            rel = self._remote_rel(args['path'])
            parent = posixpath.dirname(rel)
            if method == 'rename':
                name = args.get('name', '').strip()
                if not name or name in ('.', '..') or len(name) > 255 or any(char in name for char in '/\\\0'):
                    raise PluginError('请输入有效的文件名称')
                dest = f'{parent}/{name}' if parent else name
                if self.context.workspace_stat(dest).get('exists'):
                    raise PluginError('同名文件或文件夹已存在')
                self.context.workspace_rename(rel, dest)
                return {'changed': True, 'path': dest}
            self.context.workspace_remove(rel, recursive=True, force=True)
            return {'changed': True, 'path': parent or '.'}
        raise PluginError('未知文件树操作')

def create_plugin(context):return Explorer(context)
