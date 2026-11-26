import assert from 'node:assert/strict';
import test from 'node:test';
import { McpServerConnection } from '../runtime/node_modules/@earendil-works/pi-coding-agent/dist/extensions/mcp/runtime.js';
import { createWindowsSandboxMcp } from '../runtime/windows-sandbox-mcp.mjs';

function transport(trace, policy) {
  const listeners = { Message: new Set(), Error: new Set(), Close: new Set() };
  const result = {
    async start() { trace.push(['start', policy]); },
    async send(message) {
      trace.push([message.method, policy]);
      if (message.id === undefined) return;
      const value = message.method === 'initialize'
        ? { protocolVersion: message.params.protocolVersion, capabilities: { tools: {} }, serverInfo: { name: 'fixture', version: '1' } }
        : message.method === 'tools/list' ? { tools: [] }
          : { content: [{ type: 'text', text: policy }] };
      queueMicrotask(() => {
        for (const listener of listeners.Message) listener({ jsonrpc: '2.0', id: message.id, result: value });
      });
    },
    async close() {
      trace.push(['close', policy]);
      for (const listener of listeners.Close) listener();
    },
  };
  for (const kind of Object.keys(listeners)) {
    result[`on${kind}`] = listener => {
      listeners[kind].add(listener);
      return () => listeners[kind].delete(listener);
    };
  }
  return result;
}

test('policy change automatically initializes a new MCP client before the next call without replay', async () => {
  const handlers = new Map(), trace = [];
  const entry = { name: 'local', config: { command: 'fixture' } };
  let policy = 'off', connection, finishPreparation;
  const preparation = new Promise(resolve => { finishPreparation = resolve; });
  const adapter = createWindowsSandboxMcp({
    platform: 'win32',
    createTransport() { throw new Error('Local transport bypassed preparation'); },
    async prepareTransport() {
      if (policy === 'on') await preparation;
      return transport(trace, policy);
    },
    createExtension: options => pi => {
      pi.registerCommand('mcp', { handler: async args => {
        assert.equal(args, 'reconnect local');
        await connection.reconnect();
      } });
      pi.on('session_start', async () => {
        connection = new McpServerConnection({ entry, cwd: process.cwd(), createTransport: options.createTransport,
          credentials: {}, onTools() {} });
        await connection.getClient();
      });
    },
  });
  adapter.extension({
    on(name, handler) { const list = handlers.get(name) || []; list.push(handler); handlers.set(name, list); },
    registerCommand() {},
  });
  async function event(name, data = {}) {
    for (const handler of handlers.get(name) || []) await handler(data, {});
  }
  await event('session_start');
  assert.equal((await connection.callTool('action', {})).content[0].text, 'off');
  policy = 'on';
  const reconnecting = adapter.invalidate();
  let toolStarted = false;
  const called = event('tool_call', { toolName: 'mcp__local__action' }).then(async () => {
    toolStarted = true;
    return connection.callTool('action', {});
  });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(toolStarted, false);
  assert.deepEqual(trace.filter(([method]) => method === 'tools/call'), [['tools/call', 'off']]);
  finishPreparation();
  await reconnecting;
  assert.equal((await called).content[0].text, 'on');
  assert.deepEqual(trace.filter(([method]) => method === 'initialize'), [['initialize', 'off'], ['initialize', 'on']]);
  assert.deepEqual(trace.filter(([method]) => method === 'tools/call'), [['tools/call', 'off'], ['tools/call', 'on']]);
  await connection.close();
});

test('HTTP and non-Windows transports use the original factory directly', () => {
  for (const [platform, config] of [['win32', { url: 'http://localhost/' }], ['linux', { command: 'fixture' }]]) {
    const expected = {};
    let options;
    const adapter = createWindowsSandboxMcp({ platform,
      createTransport() { return expected; },
      prepareTransport() { throw new Error('Unexpected Windows preparation'); },
      createExtension(value) { options = value; return () => {}; },
    });
    adapter.extension({ on() {}, registerCommand() {} });
    assert.equal(options.createTransport({ name: 'fixture', config }, '.', undefined), expected);
  }
});
