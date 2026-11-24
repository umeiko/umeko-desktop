import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {createServer} from 'node:http';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {createInterface} from 'node:readline';
import {once} from 'node:events';
import {setTimeout as delay} from 'node:timers/promises';
import {fileURLToPath} from 'node:url';
import test from 'node:test';

const bridge = fileURLToPath(new URL('../runtime/releases/coding-1.5.2/bridge.mjs', import.meta.url));

test('real Pi bridge declares and runs apply_patch only on enabled models', {timeout: 45000}, async () => {
  const dir = mkdtempSync(join(tmpdir(), 'umeko-patch-bridge-'));
  const workspace = join(dir, 'workspace'), events = [], requests = [];
  mkdirSync(workspace);
  writeFileSync(join(workspace, 'one.txt'), 'old\r\n');
  const patch = '*** Begin Patch\n*** Update File: one.txt\n@@\n-old\n+new\n*** End Patch';
  const server = createServer(async (request, response) => {
    let raw = '';
    for await (const chunk of request) raw += chunk;
    const body = JSON.parse(raw);
    requests.push(body);
    const toolCall = body.model === 'enabled' && !body.messages.some(message => message.role === 'tool');
    const delta = toolCall ? {role: 'assistant', tool_calls: [{index: 0, id: 'patch-test', type: 'function',
      function: {name: 'apply_patch', arguments: JSON.stringify({patch})}}]} : {role: 'assistant', content: 'Done'};
    const common = {id: 'patch-test', object: 'chat.completion.chunk', created: 1, model: body.model};
    response.writeHead(200, {'Content-Type': 'text/event-stream'});
    for (const [content, finish] of [[delta, null], [{}, toolCall ? 'tool_calls' : 'stop']]) {
      response.write('data: ' + JSON.stringify({...common, choices: [{index: 0, delta: content, finish_reason: finish}]}) + '\n\n');
    }
    response.end('data: [DONE]\n\n');
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const environment = {...process.env, PI_SKIP_VERSION_CHECK:'1', PI_CODING_AGENT_DIR: join(dir, 'agent')};
  const child = spawn(process.execPath, [bridge], {env: environment, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe']});
  let stderr = '';
  child.stderr.on('data', data => { stderr += data; });
  createInterface({input: child.stdout}).on('line', line => events.push(JSON.parse(line)));
  const closed = once(child, 'close');

  async function request(data) {
    const from = events.length;
    child.stdin.write(JSON.stringify(data) + '\n');
    const deadline = Date.now() + 15000;
    while (!events.slice(from).some(event => event.type === 'done')) {
      if (Date.now() > deadline || child.exitCode !== null) throw new Error(stderr + JSON.stringify(events.slice(from)));
      await delay(25);
    }
    assert.equal(events.slice(from).find(event => event.type === 'error'), undefined);
  }

  try {
    await request({type: 'prompt', text: 'Apply a patch', workspace, defaultCwd: workspace,
      agentDir: join(dir, 'agent'), sessionDir: join(dir, 'sessions'), model: 'enabled',
      models: [{id: 'enabled', applyPatch: true}, {id: 'disabled'}], agent: {safeMode: true},
      gateway: 'http://127.0.0.1:' + server.address().port + '/', token: 'local'});
    const finish = events.find(event => event.type === 'tool' && event.name === 'apply_patch' && event.state !== 'running');
    assert.deepEqual(finish?.patchFiles, [{path: 'one.txt', kind: 'modified'}], JSON.stringify(finish));
    const completed = events.findLast(event => event.type === 'state').messages
      .flatMap(message => message.tools || []).find(tool => tool.name === 'apply_patch');
    assert.deepEqual(completed?.patchFiles, ['one.txt']);
    assert.equal(readFileSync(join(workspace, 'one.txt'), 'utf8'), 'new\r\n');
    await request({type: 'prompt', text: 'Inspect available tools', model: 'disabled'});
    const off = requests.find(row => row.model === 'disabled').tools.map(tool => tool.function.name);
    assert.ok(off.includes('edit'));
    assert.ok(!off.includes('apply_patch'));
  } finally {
    child.stdin.end();
    const timer = setTimeout(() => child.kill(), 3000);
    await closed;
    clearTimeout(timer);
    server.close();
    rmSync(dir, {recursive: true, force: true});
  }
});
