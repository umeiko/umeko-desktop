// Cordis extension for the official DSH ACP profile. The native sandbox and
// approval services retain ownership of confinement and one-shot decisions.
// Public seams: dsh-tools README "Enforce policy on calls" and PreToolDecision.
export const name = 'umeko-tool-permissions';
export const inject = ['tools', 'approval', 'sandboxPolicy', 'permissionPresets'];

const MUTATING_TOOLS = new Set(['write', 'edit', 'apply_patch']);
const SHELL_TOOLS = new Set(['pwsh', 'bash', 'shell']);
const READ_TOOLS = new Set(['read', 'read_image', 'grep', 'glob', 'find', 'ls', 'search', 'list_directory']);
const WIDER_MODES = {
  'read-only': new Set(['workspace-write', 'danger-full-access']),
  'workspace-write': new Set(['danger-full-access']),
};

export function permissionMode(value) {
  if (value !== 'auto' && value !== 'ask') throw new TypeError('Umeko 工具权限模式只能为 auto 或 ask');
  return value;
}

export function needsToolApproval(toolName, definition) {
  if (MUTATING_TOOLS.has(toolName) || SHELL_TOOLS.has(toolName)) return true;
  if (READ_TOOLS.has(toolName)) return false;
  // Only affirmative metadata qualifies an additional tool. Unknown tools are
  // left to their native policies; this does not reproduce Pi's risk classifier.
  const annotations = definition?.annotations;
  return annotations?.readOnlyHint === false || annotations?.destructiveHint === true;
}

export function hasNativeEscalation(exec, standingMode) {
  if (!MUTATING_TOOLS.has(exec.name) && !SHELL_TOOLS.has(exec.name)) return false;
  const args = exec.arguments ?? {};
  return WIDER_MODES[standingMode]?.has(args.sandbox_permissions) === true
    && typeof args.justification === 'string' && args.justification.trim().length > 0;
}

export function toolPermissionDecision(mode, exec, definition, standingMode, previous = { kind: 'allow' }) {
  // A later policy's deny/cancel/ask is never relaxed or replaced.
  if (previous.kind !== 'allow' || mode === 'auto') return previous;
  if (!needsToolApproval(exec.name, definition) || hasNativeEscalation(exec, standingMode)) return previous;
  return {
    kind: 'ask',
    reason: `Umeko 每次询问：执行工具 ${exec.name} 前需要本次授权。`,
    displayReason: {
      en: `Umeko asks for one-time approval before running ${exec.name}.`,
      zh: `Umeko 每次询问：执行工具 ${exec.name} 前需要本次授权。`,
    },
  };
}

export function installPermissionModeChannel(host, getMode, setMode) {
  const onMessage = message => {
    if (message?.type !== 'umeko_tool_permission_mode') return;
    let error;
    try { setMode(permissionMode(message.value)); } catch { error = 'unsupported_permission_mode'; }
    if (typeof host.send !== 'function' || host.connected === false) return;
    try {
      host.send({ type: 'umeko_tool_permission_mode_applied', id: message.id, mode: getMode(), ...(error ? { error } : {}) }, () => {});
    } catch { /* Parent disconnect cannot grant a tool or corrupt ACP stdout. */ }
  };
  host.on('message', onMessage);
  host.channel?.unref();
  return () => host.off('message', onMessage);
}

export function apply(ctx, config = {}) {
  let mode = permissionMode(config.mode ?? 'auto');
  // AgentRegistry.announce awaits serial agent/created handlers. The official
  // preset owner's prepend listener first restores stored facts; this ordinary
  // listener then aligns new and resumed agents before publication completes.
  // The public setter is idempotent and writes no explanatory user message.
  ctx.on('agent/created', ({ agent }) => {
    ctx.permissionPresets.set(agent.session, 'workspace-write');
  });
  ctx.on('tools/pre-execute', async (exec, next) => {
    const previous = await next();
    const definition = ctx.tools.get(exec.name, exec.agent);
    const policy = ctx.sandboxPolicy.resolve(exec.agent ? { session: exec.agent.session } : {});
    return toolPermissionDecision(mode, exec, definition, policy.mode, previous);
  });
  const removeChannel = installPermissionModeChannel(process, () => mode, value => { mode = value; });
  ctx.effect(() => removeChannel);
}
