import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import test from 'node:test';

const bridge = new URL('../runtime/releases/coding-1.5.2/bridge.mjs', import.meta.url);

test('Pi sends workspace reads, writes, edits and commands through SSH', {skip: process.platform === 'win32', timeout: 25000}, async t => {
  const profile = mkdtempSync(join(tmpdir(), 'umeko-ssh-pi-test-'));
  const remote = join(profile, "Remote 'directory'");
  const local = join(profile, 'ssh-workspaces', 'local-anchor');
  mkdirSync(remote);
  mkdirSync(local, {recursive:true});
  writeFileSync(join(local, 'remote.txt'), 'LOCAL_WORKSPACE_MARKER');
  const fixture = join(profile, 'ssh-fixture');
  writeFileSync(fixture, '#!/bin/sh\nfor arg do command=$arg; done\nexec /bin/sh -c "$command"\n', {mode:0o700});
  const config = process.env.UMEKO_TEST_SSH_CONFIG;
  const args = config ? ['-F', config, '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '--', 'umeko-loopback'] : [];
  const requests = [];
  const tools = [
    ['write', {path:'remote.txt', content:'remote original'}],
    ['edit', {path:'remote.txt', edits:[{oldText:'original', newText:'revised'}]}],
    ['read', {path:'remote.txt'}],
    ['bash', {command:'pwd -P; cat remote.txt'}],
  ];
  const server = createServer(async (request, response) => {
    let input = '';
    for await (const chunk of request) input += chunk;
    const body = JSON.parse(input);
    const index = requests.push(body) - 1;
    const out = (delta, finish_reason = null) => `data: ${JSON.stringify({id:'test',object:'chat.completion.chunk',created:1,model:'fake',
      choices:[{index:0,delta,finish_reason}]})}\n\n`;
    response.writeHead(200, {'Content-Type':'text/event-stream'});
    response.write(out({role:'assistant'}));
    if (tools[index]) {
      const [name, params] = tools[index];
      response.write(out({tool_calls:[{index:0,id:`ssh-${index}`,type:'function',function:{name,arguments:JSON.stringify(params)}}]}));
    } else response.write(out({content:'REMOTE_TEST_COMPLETE'}));
    response.end(out({}, tools[index] ? 'tool_calls' : 'stop') + 'data: [DONE]\n\n');
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const child = spawn(process.execPath, [bridge.pathname], {stdio:['pipe','pipe','pipe']});
  let stderr = '';
  child.stderr.on('data', chunk => { stderr += chunk; });
  t.after(async () => {
    if (child.exitCode === null && child.signalCode === null) {
      const exiting = once(child, 'exit');
      child.kill();
      await exiting;
    }
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
    rmSync(profile, {recursive:true, force:true});
  });
  child.stdin.write(JSON.stringify({
    type:'prompt', text:'Modify the remote test file.', gateway:`http://127.0.0.1:${server.address().port}/`, token:'fixture',
    dataDir:profile, workspace:local, defaultCwd:local, agentDir:join(profile,'agent'), sessionDir:join(profile,'sessions'),
    model:'fake', models:[{id:'fake'}], agent:{},
    sshWorkspace:{host:'umeko-loopback', path:remote, executable:config ? '/usr/bin/ssh' : fixture,args},
  }) + '\n');
  let finished = false;
  for await (const line of createInterface({input:child.stdout})) {
    if (!line.startsWith('{')) continue;
    const event = JSON.parse(line);
    assert.notEqual(event.type, 'error', JSON.stringify(event) + stderr);
    if (event.type === 'done' && event.action === 'prompt') {
      finished = true;
      break;
    }
  }
  assert.ok(finished, stderr);
  assert.equal(requests.length, 5);
  assert.deepEqual(requests[0].tools.map(tool => tool.function.name).sort(), ['bash','edit','read','write']);
  assert.match(JSON.stringify(requests[0].messages), /SSH workspace/);
  const outputs = requests[4].messages.filter(message => message.role === 'tool').map(message => message.content);
  assert.match(outputs[2], /remote revised/);
  assert.match(outputs[3], /Remote 'directory'\nremote revised/);
  assert.ok(existsSync(join(remote, 'remote.txt')));
  assert.equal(readFileSync(join(local, 'remote.txt'), 'utf8'), 'LOCAL_WORKSPACE_MARKER');
});
