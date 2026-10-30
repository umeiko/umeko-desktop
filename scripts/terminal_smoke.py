"""Exercise the packaged Widget worker and its real PTY without a system Node."""
import json
import queue
import subprocess
import threading
import time


def verify_terminal_worker(command, resources, environment, report_dir):
    workspace=report_dir/'terminal-workspace';workspace.mkdir(parents=True,exist_ok=True)
    package=resources/'umeko-plugins/terminal'
    config=json.loads((package/'config.json').read_text(encoding='utf-8'));config['useShellProfile']=False
    target={'token':'packaged-terminal-fixture','id':'packaged-fixture','workspace':str(workspace.resolve())}
    responses=queue.Queue();serial=0
    log_path=report_dir/'terminal-worker.log'
    with log_path.open('wb') as errors, subprocess.Popen(command,
            env=dict(environment,UMEKO_SMOKE_FIXTURE='TERMINAL_PACKAGED_OK'),
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errors,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)) as process:
        def consume():
            for line in process.stdout:
                try:responses.put(json.loads(line))
                except ValueError:responses.put({'invalidOutput':line[:200].decode('utf-8','replace')})
            responses.put({'eof':True})
        reader=threading.Thread(target=consume,daemon=True);reader.start()
        def request(operation,args):
            nonlocal serial
            serial+=1;identifier='smoke-'+str(serial)
            process.stdin.write((json.dumps({'id':identifier,'operation':operation,'arguments':args})+'\n').encode('ascii'));process.stdin.flush()
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                try:result=responses.get(timeout=max(.01,deadline-time.monotonic()))
                except queue.Empty:break
                if result.get('eof') or 'invalidOutput' in result:raise RuntimeError('Terminal worker protocol failed: '+str(result))
                if result.get('id')==identifier:
                    if not result.get('ok'):raise RuntimeError('Terminal worker rejected request: '+str(result))
                    return result['result']
            raise RuntimeError('Packaged terminal worker timed out; see terminal-worker.log')
        def call(method,args=None):return request('call',{'method':method,'arguments':args or {},'session':target})
        try:
            request('initialize',{'path':str(package.resolve()),'stateDir':str((report_dir/'terminal-state').resolve()),'config':config,'session':target})
            terminal=call('list',{'ensure':True})['terminals'][0];identifier=terminal['id']
            if terminal['profile']=='powershell':command="Write-Output ('UMEKO_'+$env:UMEKO_SMOKE_FIXTURE)"
            elif terminal['profile']=='cmd':command='echo UMEKO_%UMEKO_SMOKE_FIXTURE%'
            else:command="printf 'UMEKO_%s\\n' \"$UMEKO_SMOKE_FIXTURE\""
            call('run',{'terminalId':identifier,'command':command})
            deadline=time.monotonic()+12
            while True:
                output=call('read',{'terminalId':identifier})
                if 'UMEKO_TERMINAL_PACKAGED_OK' in output.get('text',''):break
                if time.monotonic()>deadline:raise RuntimeError('Packaged shell did not execute the shared-terminal command')
                time.sleep(.05)
            call('attach',{'terminalId':identifier})
            result=request('agentCall',{'method':'read','arguments':{'terminalId':identifier},'session':target})
            assert result['pid']==terminal['pid'] and 'UMEKO_TERMINAL_PACKAGED_OK' in result['text']
            frame=call('view',{'ids':[identifier]})['frames'][0];assert frame['screen'] and frame['terminalId']==identifier
            call('kill',{'terminalId':identifier});assert not call('list')['terminals']
        finally:
            process.stdin.close()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
            reader.join(timeout=1)
            process.stdout.close()
        if process.returncode:raise RuntimeError('Packaged terminal worker failed: '+log_path.read_text(encoding='utf-8',errors='replace')[-1500:])
    print('Packaged terminal PTY, Agent access and cleanup verified')
