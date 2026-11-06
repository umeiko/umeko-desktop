// Deterministic local ACP peer; no model, network, credentials or user state.
import { createInterface } from 'node:readline';
const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
const send = message => process.stdout.write(JSON.stringify({ jsonrpc: '2.0', ...message }) + '\n');
let sessionId = 'fake-session', currentValue = 'opaque:model:first', pendingPrompt, permissionPrompt;
let permissionMode = 'auto';
process.on('message', message => {
  if (message?.type !== 'umeko_tool_permission_mode') return;
  permissionMode = message.value;
  process.send?.({ type: 'umeko_tool_permission_mode_applied', id: message.id, mode: permissionMode,
    ...(process.env.FAKE_ACP_PERMISSION_FAILURE ? { error: 'fixture_permission_failure' } : {}) });
});
process.channel?.unref();
const options = () => [{ id: 'model', name: 'Model', type: 'select', currentValue, options: [{ name: 'First', value: 'opaque:model:first' }, { name: 'Second', value: 'opaque:model:second' }] }];
const update = data => send({ method: 'session/update', params: { sessionId, update: data } });
const result = (id, data) => send({ id, result: data });
lines.on('line', line => {
  const message = JSON.parse(line), params = message.params ?? {};
  if (message.id === 'permission-1' && !message.method) {
    update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: `permission:${message.result.outcome.optionId ?? message.result.outcome.outcome}` } });
    result(permissionPrompt, { stopReason: 'end_turn' });
    permissionPrompt = undefined;
    return;
  }
  switch (message.method) {
    case 'initialize':
      if (process.env.FAKE_ACP_INITIALIZE_FAILURE) {
        send({ id: message.id, error: { code: -32603, message: 'isolated fixture initialization failure' } });
        break;
      }
      setTimeout(() => result(message.id, { protocolVersion: 1, agentInfo: { name: 'fake-dsh', version: '1' }, agentCapabilities: { sessionCapabilities: { resume: {}, close: {}, list: {} } }, authMethods: [] }), Number(process.env.FAKE_ACP_INITIALIZE_DELAY ?? 0));
      break;
    case 'session/new': result(message.id, { sessionId, configOptions: options() }); break;
    case 'session/resume': sessionId = params.sessionId; result(message.id, { configOptions: options() }); break;
    case 'session/set_config_option': currentValue = params.value; result(message.id, { configOptions: options() }); break;
    case 'session/prompt': {
      if (params.prompt.at(-1).text === 'permission-mode') {
        update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: permissionMode } });
        result(message.id, { stopReason: 'end_turn' });
        break;
      }
      if (params.prompt.at(-1).text === 'prompt-blocks') {
        update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: JSON.stringify(params.prompt) } });
        result(message.id, { stopReason: 'end_turn' });
        break;
      }
      const text = params.prompt[0].text;
      if (text === 'crash') { process.exit(3); }
      if (text === 'wait') { pendingPrompt = message.id; break; }
      if (text === 'permission') {
        permissionPrompt = message.id;
        send({ id: 'permission-1', method: 'session/request_permission', params: { sessionId, toolCall: { toolCallId: 'tool-permission', title: 'Write file', rawInput: { path: 'test.txt' } }, options: [{ optionId: 'once', name: 'Allow once', kind: 'allow_once' }, { optionId: 'deny', name: 'Reject once', kind: 'reject_once' }] } });
        break;
      }
      update({ sessionUpdate: 'agent_thought_chunk', content: { type: 'text', text: 'thinking' } });
      update({ sessionUpdate: 'tool_call', toolCallId: 'read-1', title: 'read', status: 'in_progress', rawInput: { path: 'input.txt' } });
      update({ sessionUpdate: 'tool_call_update', toolCallId: 'read-1', status: 'completed', content: [{ type: 'content', content: { type: 'text', text: 'file content' } }] });
      update({ sessionUpdate: 'usage_update', used: 25, size: 100 });
      update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: text === 'model-state' ? currentValue : text } });
      result(message.id, { stopReason: 'end_turn' });
      break;
    }
    case 'session/cancel':
      if (pendingPrompt !== undefined) { result(pendingPrompt, { stopReason: 'cancelled' }); pendingPrompt = undefined; }
      break;
    case 'session/close': result(message.id, {}); break;
    default:
      if (message.id !== undefined) send({ id: message.id, error: { code: -32601, message: 'Method not found' } });
  }
});
