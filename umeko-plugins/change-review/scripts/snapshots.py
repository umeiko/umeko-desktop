"""Bounded, read-only worktree snapshots. All object/index/diff work belongs to Git."""
from pathlib import Path, PurePosixPath
import json, os, shutil, stat, subprocess, tempfile, threading, time

MAX_FILES = 4000
MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 32 * 1024 * 1024
MAX_OUTPUT = 512 * 1024
SNAPSHOT_SECONDS = 5

class SnapshotError(RuntimeError): pass

class Snapshot:
    def __init__(self, workspace, state, cancelled=None):
        self.workspace = Path(workspace).resolve()
        if not self.workspace.is_dir(): raise SnapshotError('请先选择存在的会话工作目录')
        self.git = shutil.which('git')
        if not self.git: raise SnapshotError('未找到 Git，请安装 Git 后重新开始一轮任务')
        self.folder = Path(tempfile.mkdtemp(prefix='review-', dir=state))
        self.repo = self.folder / 'objects.git'
        self.cancelled = cancelled or threading.Event()
        self.deadline = time.monotonic() + SNAPSHOT_SECONDS
        self.base = self.end = None
        self.closed = False
        try:
            self.run(['init', '--bare', '--template=', str(self.repo)])
        except Exception:
            self.close(); raise

    def run(self, args, *, cwd=None, data=None, limit=MAX_OUTPUT, private=False, allow=(0,)):
        if self.cancelled.is_set(): raise SnapshotError('审查已取消')
        remaining = self.deadline - time.monotonic()
        if remaining <= 0: raise SnapshotError('采集超过 5 秒，已停止；本轮审查不可用')
        env = {k:v for k,v in os.environ.items() if not k.upper().startswith('GIT_')}
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0')
        command = [self.git, '--no-pager', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath='+os.devnull]
        if private: command += ['--git-dir='+str(self.repo),'--work-tree='+str(self.workspace)]
        command += args
        with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as output:
            if data: source.write(data)
            source.seek(0)
            process = subprocess.Popen(command, cwd=cwd or self.workspace, env=env, stdin=source,
                stdout=output, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                while process.poll() is None:
                    if self.cancelled.is_set() or time.monotonic() >= self.deadline or output.tell() > limit:
                        process.kill(); process.wait()
                        raise SnapshotError('采集已取消、超时或 Git 输出超过限制；未改动项目')
                    time.sleep(.01)
                if output.tell() > limit: raise SnapshotError('Git 输出超过预览限制')
                if process.returncode not in allow: raise SnapshotError('Git 无法读取本轮快照，请刷新或重新开始任务')
                output.seek(0)
                return output.read(limit)
            finally:
                if process.poll() is None: process.kill(); process.wait()

    def capture(self):
        self.deadline = time.monotonic() + SNAPSHOT_SECONDS
        # Use the project's index ONLY for enumeration; never update it. No Git
        # filters, hooks, textconv or user-defined diff drivers are executed.
        probe = self.run(['rev-parse','--is-inside-work-tree'],allow=(0,128))
        repository = probe.strip() == b'true'
        raw = self.run(['ls-files', '--cached', '--others', '--exclude-standard', '-z', '--', '.'], private=not repository)
        names = sorted(set(raw.split(b'\0')) - {b''})
        limited = len(names) > MAX_FILES
        names = names[:MAX_FILES]
        files = {}; copied = []; total = 0
        with tempfile.TemporaryDirectory(prefix='files-', dir=self.folder) as temporary:
            staging = Path(temporary)
            for encoded in names:
                if time.monotonic() >= self.deadline or self.cancelled.is_set(): raise SnapshotError('采集超时或已取消；本轮审查不可用')
                try:relative = encoded.decode('utf-8')
                except UnicodeDecodeError:limited=True;continue
                if len(relative)>4096:limited=True;continue
                # Never descend into repository metadata, submodules or links.
                parts = PurePosixPath(relative).parts
                if not parts or any(p in ('.git','..') for p in parts) or PurePosixPath(relative).is_absolute(): continue
                source = self.workspace.joinpath(*parts)
                try:
                    if not source.resolve().is_relative_to(self.workspace) or source.resolve().is_relative_to(self.folder.parent): continue
                    info = source.lstat()
                    if not stat.S_ISREG(info.st_mode): continue
                    record = {'size':info.st_size,'stamp':[info.st_mtime_ns,info.st_ctime_ns], 'mode':'100755' if info.st_mode & 0o111 else '100644'}
                    files[relative] = record
                    if info.st_size > MAX_FILE or total + info.st_size > MAX_TOTAL:
                        record['omitted'] = True; limited = True; continue
                    # O_NOFOLLOW and fstat guard replacements with links/special files.
                    descriptor = os.open(source, os.O_RDONLY | getattr(os,'O_NOFOLLOW',0) | getattr(os,'O_NONBLOCK',0))
                    with os.fdopen(descriptor,'rb') as stream:
                        before = os.fstat(stream.fileno())
                        if not stat.S_ISREG(before.st_mode): record['omitted']=True; limited=True; continue
                        content = stream.read(MAX_FILE + 1)
                        after = os.fstat(stream.fileno())
                    if len(content)>MAX_FILE or (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):
                        record['omitted']=True; limited=True; continue
                    if total+len(content)>MAX_TOTAL:record['omitted']=True;limited=True;continue
                    total += len(content)
                    destination = staging.joinpath(*parts); destination.parent.mkdir(parents=True,exist_ok=True)
                    destination.write_bytes(content)
                    record['binary'] = b'\0' in content
                    copied.append(relative)
                except FileNotFoundError:
                    # ls-files includes tracked files already deleted before the
                    # loop. Absence is a valid baseline, not an incomplete scan.
                    if relative in files:files[relative]['omitted']=True;limited=True
                except (OSError,ValueError):
                    if relative in files: files[relative]['omitted']=True
                    limited=True
            paths = ''.join(json.dumps(str(staging.joinpath(*PurePosixPath(p).parts)),ensure_ascii=False)+'\n' for p in copied).encode('utf-8', 'surrogateescape')
            hashes = self.run(['hash-object','-w','--no-filters','--stdin-paths'],data=paths,private=True).splitlines() if copied else []
            if len(hashes)!=len(copied):raise SnapshotError('快照不完整，请重新开始任务')
            self.run(['read-tree','--empty'],private=True)
            entries=[]
            for relative,blob in zip(copied,hashes):
                files[relative]['blob']=blob.decode('ascii')
                entries.append(files[relative]['mode'].encode()+b' '+blob+b'\t'+os.fsencode(relative)+b'\0')
            if entries:self.run(['update-index','-z','--index-info'],private=True,data=b''.join(entries))
            tree=self.run(['write-tree'],private=True).decode().strip()
        return {'files':files,'tree':tree,'limited':limited,'repository':repository,'captured':time.time()}

    def begin(self):
        self.base=self.capture()
        self.run(['update-ref','refs/review/base',self.base['tree']],private=True)

    def finish(self):
        if self.base is None:raise SnapshotError('未取得本轮开始前的基线，请开启后重新开始一轮任务')
        started=time.monotonic()
        self.end=self.capture()
        self.deadline=started+SNAPSHOT_SECONDS
        a,b=self.base['files'],self.end['files'];rows=[]
        for path in sorted(a.keys()|b.keys()):
            left,right=a.get(path),b.get(path)
            if not right and self.end['limited'] and (self.workspace/path).exists():continue
            baseline_missing=not left and self.base['limited']
            omitted=bool((left or {}).get('omitted') or (right or {}).get('omitted'))
            if left and right:
                if omitted:
                    if (left['size'],left['stamp'],left['mode'])==(right['size'],right['stamp'],right['mode']):continue
                elif (left.get('blob'),left['mode'])==(right.get('blob'),right['mode']):continue
            binary=bool((left or {}).get('binary') or (right or {}).get('binary'))
            rows.append({'path':path,'status':'?' if baseline_missing else 'A' if not left else 'D' if not right else 'M',
                'binary':binary,'omitted':omitted or baseline_missing,'added':-1,'removed':-1})
        # Git supplies the statistics; rename detection is intentionally off so
        # large workspaces cannot trigger quadratic similarity searches.
        stats=self.run(['diff-tree','--no-commit-id','--numstat','-r','-z','--no-renames','--no-ext-diff','--no-textconv',self.base['tree'],self.end['tree']],private=True)
        counts={}
        for line in stats.split(b'\0'):
            parts=line.split(b'\t',2)
            if len(parts)==3:counts[os.fsdecode(parts[2])]=parts[:2]
        for row in rows:
            if row['omitted'] or row['binary']:continue
            count=counts.get(row['path'])
            if count and all(x.isdigit() for x in count):row.update(added=int(count[0]),removed=int(count[1]))
        # Keep only the two trees required by this review. Refresh must not
        # accumulate old versions as unreachable loose objects. These refs and
        # pruning are confined to the private repository.
        self.run(['update-ref','refs/review/end',self.end['tree']],private=True)
        self.run(['prune','--expire=now'],private=True)
        return {'entries':rows,'limited':self.base['limited'] or self.end['limited'], 'repository':self.base['repository'],
            'started':self.base['captured'],'ended':self.end['captured']}

    def diff(self,path):
        if not self.base or not self.end:raise SnapshotError('尚无已完成的快照')
        left=self.base['files'].get(path);right=self.end['files'].get(path)
        if not left and not right:raise SnapshotError('该文件不在本轮快照中')
        if (left or {}).get('omitted') or (right or {}).get('omitted'):return {'text':'文件超过采集限制或在采集时发生变化，仅显示状态。','truncated':True}
        if (left or {}).get('binary') or (right or {}).get('binary'):return {'text':'二进制文件，仅显示变更状态。','truncated':False}
        self.deadline=time.monotonic()+SNAPSHOT_SECONDS
        # Per-file size is bounded; cap the UI further, without constructing rich text.
        raw=self.run(['diff-tree','-p','--no-commit-id','-r','--no-renames','--no-ext-diff','--no-textconv',
            '--unified=3',self.base['tree'],self.end['tree'],'--',':(literal)'+path],private=True,limit=12*MAX_FILE)
        text=raw[:48000].decode('utf-8','replace');lines=text.splitlines();truncated=len(raw)>48000 or len(lines)>1000 or any(len(x)>2000 for x in lines)
        return {'text':'\n'.join(x[:2000] for x in lines[:1000]),'truncated':truncated}

    def close(self):
        if not self.closed:shutil.rmtree(self.folder,ignore_errors=True);self.closed=True
