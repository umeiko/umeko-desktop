from pathlib import Path
from umeko_plugin_sdk import Plugin, PluginError

def preview(text, truncated=False):
    text=text.replace('\r\n','\n').replace('\r','\n')
    truncated=truncated or len(text)>48000
    text=text[:48000];lines=text.split('\n');truncated=truncated or len(lines)>1000 or any(len(x)>2000 for x in lines)
    return {'text':'\n'.join(x[:2000] for x in lines[:1000]),'truncated':truncated}

class GitViewer(Plugin):
    def git(self,*args,limit=512*1024):
        result=self.context.run_executable('git',['--no-pager','-c','core.quotepath=false',*args],limit=limit)
        if result['code'] and not result['truncated']:raise PluginError(result['text'].strip()[:800] or 'Git 操作失败')
        return result
    def relative(self,value):
        path=self.context.resolve_workspace(value)
        if path==self.context.workspace.resolve():raise PluginError('请选择单个仓库文件')
        return path.relative_to(self.context.workspace.resolve()).as_posix()
    def handle(self,method,args):
        self.context.require('git.read')
        if method=='status':
            root=self.git('rev-parse','--show-toplevel')['text'].strip()
            # Keep operations in the selected session directory, including subdirectories of a repository.
            branch_result=self.context.run_executable('git',['symbolic-ref','--short','-q','HEAD'])
            branch=branch_result['text'].strip() if branch_result['code']==0 else 'HEAD'
            data=self.git('status','--porcelain=v1','-z','--untracked-files=normal',limit=512*1024)
            parts=data['text'].split('\0');rows=[];index=0
            while index<len(parts) and len(rows)<2000:
                line=parts[index];index+=1
                if len(line)<4:continue
                x,y,path=line[0],line[1],line[3:]
                old=''
                if x in ('R','C') or y in ('R','C'):
                    old=parts[index] if index<len(parts) else '';index+=1
                # git status paths are relative to repository root, not the current subdirectory.
                absolute=Path(root)/path
                try:local=absolute.relative_to(self.context.workspace.resolve()).as_posix()
                except ValueError:continue
                if x=='?' and not self.context.config.get('showUntracked',True):continue
                common={'path':local,'name':Path(path).name,'directory':str(Path(path).parent),'oldPath':old}
                if x not in (' ','?'):rows.append({**common,'group':'staged','status':x})
                if y!=' ' or x=='?':rows.append({**common,'group':'untracked' if x=='?' else 'changes','status':'U' if x=='?' else y})
            return {'branch':branch,'root':root,'entries':rows,'truncated':data['truncated'] or len(rows)>=2000}
        if method=='history':
            result=self.context.run_executable('git',['--no-pager','log','--date=short','--format=%h%x09%ad%x09%s','-n',str(self.context.config.get('historyLimit',30))])
            if result['code']:return {'entries':[],'truncated':False}
            return {'entries':[dict(zip(('hash','date','subject'),line.split('\t',2))) for line in result['text'].splitlines() if line.count('\t')>=2],'truncated':result['truncated']}
        if method=='diff':
            path=self.relative(args['path'])
            if args.get('group')=='untracked':
                source=self.context.resolve_workspace(path)
                with source.open('rb') as stream:raw=stream.read(128*1024+1)
                if b'\0' in raw:return {'text':'二进制文件','truncated':False}
                return preview('新文件：'+path+'\n\n'+raw[:128*1024].decode('utf-8','replace'),len(raw)>128*1024)
            flags=['--cached'] if args.get('group')=='staged' else []
            result=self.git('diff','--no-ext-diff','--no-textconv','--unified=3',*flags,'--',path,limit=256*1024)
            return preview(result['text'] or '没有文本差异',result['truncated'])
        if method in ('stage','unstage','commit'):
            self.context.require('git.write')
            if method=='stage':self.git('add','--',self.relative(args['path']))
            elif method=='unstage':
                path=self.relative(args['path'])
                head=self.context.run_executable('git',['rev-parse','--verify','HEAD'])
                self.git(*(['restore','--staged','--',path] if head['code']==0 else ['rm','--cached','--',path]))
            else:
                message=args.get('message','').strip()
                if not message or len(message)>4000:raise PluginError('请输入提交说明（最多 4000 字符）')
                self.git('-c','core.hooksPath=/dev/null' if __import__('os').name!='nt' else 'core.hooksPath=NUL','commit','--no-gpg-sign','-m',message)
            return {'changed':True}
        if method=='attach':self.context.attach_file(args['path']);return {'attached':True}
        raise PluginError('未知 Git 查看器操作')
def create_plugin(context):return GitViewer(context)
