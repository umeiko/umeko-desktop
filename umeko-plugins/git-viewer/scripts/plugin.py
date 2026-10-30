from pathlib import Path
import re,shutil,json,uuid
from umeko_plugin_sdk import Plugin, PluginError

def preview(text, truncated=False):
    text=text.replace('\r\n','\n').replace('\r','\n')
    truncated=truncated or len(text)>48000
    text=text[:48000];lines=text.split('\n');truncated=truncated or len(lines)>1000 or any(len(x)>2000 for x in lines)
    return {'text':'\n'.join(x[:2000] for x in lines[:1000]),'truncated':truncated}

def graph_entries(entries):
    lanes=[]
    for entry in entries:
        incoming=entry['id'] in lanes
        if not incoming:lanes.append(entry['id'])
        before=lanes[:];column=lanes.index(entry['id']);lanes.pop(column)
        for offset,parent in enumerate(entry['parents']):
            if parent not in lanes:lanes.insert(min(column+offset,len(lanes)),parent)
        edges=[{'from':index,'to':lanes.index(commit),'node':False}
               for index,commit in enumerate(before) if commit!=entry['id'] and commit in lanes]
        edges.extend({'from':column,'to':lanes.index(parent),'node':True} for parent in entry['parents'])
        entry['graph']={'column':column,'columns':max(len(before),len(lanes),1),'incoming':incoming,'edges':edges}
    return entries

class GitViewer(Plugin):
    def reference(self,value):
        if value=='HEAD' or re.fullmatch('[a-fA-F0-9]{7,40}',value):
            result=self.git('rev-parse','--verify',value+'^{commit}')['text'].strip()
            return result
        if not value.startswith(('refs/heads/','refs/remotes/','refs/tags/')):raise PluginError('请选择有效的分支、标签或提交')
        self.git('show-ref','--verify',value)
        return value
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
        if method=='showDiff':
            result=self.handle('diff',args)
            self.context.publish('git.diff',{'path':args['path'],'group':args.get('group','changes'),**result})
            return {'published':True,'path':args['path'],'truncated':result.get('truncated',False)}
        if method=='status':
            probe=self.context.run_executable('git',['rev-parse','--show-toplevel'])
            if probe['code']:
                return {'repository':False,'branch':'','entries':[],'truncated':False}
            root=probe['text'].strip()
            # Keep operations in the selected session directory, including subdirectories of a repository.
            branch_result=self.context.run_executable('git',['symbolic-ref','--short','-q','HEAD'])
            branch=branch_result['text'].strip() if branch_result['code']==0 else self.git('rev-parse','--short','HEAD')['text'].strip()
            data=self.git('status','--porcelain=v1','-z','--untracked-files=all',limit=512*1024)
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
            return {'repository':True,'branch':branch,'root':root,'entries':rows,'truncated':data['truncated'] or len(rows)>=2000}
        if method=='history':
            flags=['--all'] if args.get('all',True) else []
            result=self.context.run_executable('git',['--no-pager','log',*flags,'--date-order','--date=short','--format=%H%x1f%h%x1f%ad%x1f%an%x1f%s%x1f%D%x1f%P','-n',str(self.context.config.get('historyLimit',30))])
            if result['code']:return {'entries':[],'truncated':False}
            entries=[]
            for line in result['text'].split('\n'):
                fields=line.rstrip('\r').split('\x1f')
                if len(fields)!=7:continue
                entry=dict(zip(('id','hash','date','author','subject','refs','parents'),fields))
                entry['parents']=entry['parents'].split();entry['refs']=[x.strip() for x in entry['refs'].split(',') if x.strip()]
                entries.append(entry)
            return {'entries':graph_entries(entries),'truncated':result['truncated']}
        if method=='branches':
            result=self.git('for-each-ref','--sort=-committerdate','--count=300','--format=%(refname)%1f%(refname:short)%1f%(objectname:short)%1f%(committerdate:unix)%1f%(authorname)%1f%(subject)','refs/heads','refs/remotes','refs/tags')
            entries=[]
            for line in result['text'].split('\n'):
                fields=line.rstrip('\r').split('\x1f')
                if len(fields)!=6 or fields[0].endswith('/HEAD'):continue
                entry=dict(zip(('ref','name','hash','timestamp','author','subject'),fields))
                entry['kind']='branch' if entry['ref'].startswith('refs/heads/') else 'remote' if entry['ref'].startswith('refs/remotes/') else 'tag'
                if entry['kind']=='branch':entry['name']=entry['ref'][11:]
                elif entry['kind']=='remote':entry['name']=entry['ref'][13:]
                else:entry['name']=entry['ref'][10:]
                entries.append(entry)
            entries.sort(key=lambda e:({'branch':0,'remote':1,'tag':2}[e['kind']],-int(e['timestamp'] or 0)))
            return {'entries':entries,'truncated':result['truncated'] or len(entries)>=300}
        if method in ('checkout','createBranch'):
            self.context.require('git.write')
            if method=='createBranch':
                name=args.get('name','').strip()
                if not name or len(name)>200 or name.startswith('-') or '@{' in name:raise PluginError('分支名称无效')
                self.git('check-ref-format','--branch',name)
                source=self.reference(args.get('ref','HEAD'))
                self.git('-c','core.hooksPath=NUL' if __import__('os').name=='nt' else 'core.hooksPath=/dev/null','switch','-c',name,source)
            else:
                ref=self.reference(args.get('ref',''))
                flags=['--detach'] if args.get('detached') or ref.startswith('refs/tags/') or not ref.startswith('refs/') else ['--track'] if ref.startswith('refs/remotes/') else []
                target=ref[11:] if ref.startswith('refs/heads/') and not flags else ref
                if flags==['--track']:
                    local=ref[13:].split('/',1)[-1]
                    upstream=self.context.run_executable('git',['rev-parse','--abbrev-ref','--symbolic-full-name',local+'@{upstream}'])
                    if upstream['code']==0 and upstream['text'].strip()==ref[13:]:flags=[];target=local
                self.git('-c','core.hooksPath=NUL' if __import__('os').name=='nt' else 'core.hooksPath=/dev/null','switch',*flags,'--',target)
            return {'changed':True}
        if method=='headFile':
            path=self.relative(args['path']);prefix=self.git('rev-parse','--show-prefix')['text'].strip()
            result=self.git('show','HEAD:'+prefix+path,limit=128*1024)
            return preview('二进制文件' if '\0' in result['text'] else result['text'],result['truncated'])
        if method in ('discard','ignore'):
            self.context.require('git.write');relative=self.relative(args['path']);path=self.context.resolve_workspace(relative)
            if method=='ignore':
                target=self.context.resolve_workspace('.gitignore')
                if target.exists() and target.stat().st_size>1024*1024:raise PluginError('.gitignore 过大，请手动编辑')
                pattern='/'+re.sub(r'([\\*?\[\]!#])',r'\\\1',relative)
                text=target.read_text(encoding='utf-8',errors='replace') if target.exists() else ''
                if pattern not in text.splitlines():
                    with target.open('a',encoding='utf-8') as stream:stream.write(('\n' if text and not text.endswith('\n') else '')+pattern+'\n')
            else:
                backup=self.context.state_dir/'discarded'/uuid.uuid4().hex
                if path.is_file():
                    backup.mkdir(parents=True);shutil.copy2(path,backup/path.name)
                    (backup/'location.json').write_text(json.dumps({'workspace':str(self.context.workspace),'path':relative},ensure_ascii=False),encoding='utf-8')
                if args.get('group')=='untracked':
                    if not path.is_file():raise PluginError('该文件不存在')
                    path.unlink()
                else:self.git('restore','--worktree','--',relative)
                self.context.notify('已放弃更改；恢复副本：'+str(backup))
            return {'changed':True}
        if method=='commitDiff':
            identifier=args.get('hash','')
            if not re.fullmatch('[a-fA-F0-9]{7,40}',identifier):raise PluginError('提交标识无效')
            result=self.git('show','--no-ext-diff','--no-textconv','--format=medium',identifier,'--','.',limit=256*1024)
            return preview(result['text'],result['truncated'])
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
        if method in ('stage','unstage','commit','stageAll','unstageAll','init'):
            self.context.require('git.write')
            if method=='init':self.git('init')
            elif method=='stageAll':self.git('add','--','.')
            elif method=='stage':self.git('add','--',self.relative(args['path']))
            elif method in ('unstage','unstageAll'):
                path=self.relative(args['path']) if method=='unstage' else '.'
                head=self.context.run_executable('git',['rev-parse','--verify','HEAD'])
                self.git(*(['restore','--staged','--',path] if head['code']==0 else ['rm','--cached','--',path]))
            else:
                message=args.get('message','').strip()
                if not message or len(message)>4000:raise PluginError('请输入提交说明（最多 4000 字符）')
                self.git('-c','core.hooksPath=/dev/null' if __import__('os').name!='nt' else 'core.hooksPath=NUL','commit','--no-gpg-sign','-m',message)
            return {'changed':True}
        if method=='attach':self.context.attach_file(args['path']);return {'attached':True}
        if method=='reveal':self.context.reveal_file(args['path']);return {'revealed':True}
        if method=='explorer':self.context.reveal_in_explorer(args['path']);return {'revealed':True}
        raise PluginError('未知版本管理操作')
def create_plugin(context):return GitViewer(context)
