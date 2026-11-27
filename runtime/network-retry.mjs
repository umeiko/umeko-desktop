// One visible retry budget; the provider SDK must not add hidden attempts.
// Align retry count (5) with Codex CLI / DSH and backoff with Pi's exponential schedule.
export const NETWORK_RETRY = Object.freeze({ enabled: true, maxRetries: 5, baseDelayMs: 2000, maxAgentDelayMs: 30000 });
export const GATEWAY_CONTINUATION_DELAYS = Object.freeze([5000, 10000, 30000]);
export const GATEWAY_TIMEOUT_MARKER = '[Umeko:gateway_timeout]';
export const MAX_STREAM_MAX_RETRIES = 100;
// Disable Pi's own loopback HTTP idle timeout so the local gateway's per-provider
// streamIdleTimeoutMs (default 300s) is the single source of truth.
export const GATEWAY_HTTP_IDLE_TIMEOUT_MS = 0;

export function normalizeStreamMaxRetries(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return NETWORK_RETRY.maxRetries;
  const rounded = Math.round(value);
  return rounded >= 0 && rounded <= MAX_STREAM_MAX_RETRIES ? rounded : NETWORK_RETRY.maxRetries;
}

// Error.cause and AggregateError.errors are often non-enumerable. A JSON
// replacer based on the outer error's keys loses codes in nested failures.
export function describeFailure(error, seen = new Set()) {
  if (!error || typeof error !== 'object') return String(error);
  if (seen.has(error)) return '[Circular error]';
  seen.add(error);
  return {name: error.name, message: error.message, code: error.code, stack: error.stack,
    ...(error.cause ? {cause: describeFailure(error.cause, seen)} : {}),
    ...(error.errors ? {errors: Array.from(error.errors, item => describeFailure(item, seen))} : {})};
}

function failureText(error, seen = new Set()) {
  if (!error || typeof error !== 'object') return String(error);
  if (seen.has(error)) return '';
  seen.add(error);
  // Stack paths are not evidence of a network or certificate failure.
  return [error.message, error.code, error.cause && failureText(error.cause, seen),
    ...(error.errors || []).map(item => failureText(item, seen))].filter(Boolean).join(' ');
}

export function certificateFailure(error) {
  const pending = [error], seen = new Set(), codes = [];
  while (pending.length) {
    const current = pending.pop();
    if (!current || typeof current !== 'object' || seen.has(current)) continue;
    seen.add(current);
    // Error messages and stacks can contain filenames or provider content.
    // Certificate recovery must depend on the transport's structured code.
    for (const value of [current.code, current.tlsCode]) {
      if (typeof value === 'string' && /^(?:ERR_TLS_CERT_[A-Z_]+|UMEKO_CA_[A-Z_]+|CERT_[A-Z_]+|CERTIFICATE_VERIFY_FAILED|SELF_SIGNED_CERT_IN_CHAIN|DEPTH_ZERO_SELF_SIGNED_CERT|UNABLE_TO_VERIFY_LEAF_SIGNATURE|UNABLE_TO_GET_ISSUER_CERT(?:_LOCALLY)?)$/i.test(value)) codes.push(value.toUpperCase());
    }
    pending.push(current.cause, ...(current.errors || []));
  }
  const trustCode = code => /^(?:SELF_SIGNED_CERT_IN_CHAIN|DEPTH_ZERO_SELF_SIGNED_CERT|UNABLE_TO_VERIFY_LEAF_SIGNATURE|UNABLE_TO_GET_ISSUER_CERT(?:_LOCALLY)?|CERT_UNTRUSTED)$/.test(code);
  const fatal = codes.find(code => !trustCode(code));
  const code = fatal || codes[0];
  return code ? {code, recoverable: !fatal} : null;
}

export function transientFailure(error, http = []) {
  if (certificateFailure(error)) return false;
  const text = failureText(error);
  const responses = http.map(item => item.response).filter(Boolean);
  const detail = text + ' ' + JSON.stringify(responses.filter(r => Number(r.status) >= 400).map(r => r.body));
  if (/insufficient_quota|quota exceeded|out of budget|billing|usage limit reached|invalid.?api.?key|unauthorized|authentication|额度不足|余额不足/i.test(detail)) return false;
  const status = Number(responses.findLast(r => r.status)?.status);
  if (status >= 400 && status < 500 && ![408, 425, 429].includes(status)) return false;
  if ([408, 425, 429].includes(status) || status >= 500) return true;
  return /ECONNRESET|ECONNREFUSED|ETIMEDOUT|ENOTFOUND|EAI_AGAIN|UND_ERR_(?:SOCKET|CONNECT_TIMEOUT|HEADERS_TIMEOUT|BODY_TIMEOUT)|network.?error|fetch failed|connection (?:reset|lost|closed|refused)|socket (?:hang up|closed)|timed? out|timeout|terminated|incomplete.?read|premature|stream (?:interrupted|ended|failed)|overloaded|rate.?limit|server_busy|temporarily unavailable|供应商流已中断|供应商请求超时|等待模型输出超时|发出请求后等待响应头超时|收到响应头后等待首条模型输出超时|流式输出中途长时间未收到数据而超时|接收模型输出时连接中断|接收模型输出时未收到正常结束标记即断流|请求超时|连接.*(?:中断|重置|超时)|网络.*(?:中断|超时)/i.test(detail);
}

export function upstreamFailure(error) {
  const retryable = error?.retryable === true;
  return { type: 'upstream_error', code: error?.tlsCode ? 'umeko_tls_certificate' : retryable ? 'umeko_stream_interrupted' : 'umeko_request_failed', retryable,
    ...(error?.tlsCode ? {tlsCode: error.tlsCode} : {}),
    message: (retryable ? 'Network error: stream interrupted. ' : '') + (error?.reportId ? error.message : 'Provider request failed; check request details') };
}

export function retryOmissions(branch) {
  const edits = new Map(branch.filter(e => e.type === 'context_edit').map(e => [e.targetId, e.replacement]));
  return new Set(branch.filter(e => e.type === 'message' && e.message.role === 'assistant' && e.message.stopReason === 'error' && edits.has(e.id) && edits.get(e.id) === null).map(e => e.id));
}

function summarizeToolTarget(args) {
  if (!args || typeof args !== 'object') return '';
  for (const key of ['path', 'file_path', 'filePath', 'command', 'url']) {
    const value = args[key];
    if (typeof value === 'string' && value.trim()) {
      const compact = value.replace(/\s+/g, ' ').trim();
      return compact.length > 80 ? compact.slice(0, 77) + '...' : compact;
    }
  }
  return '';
}

function assistantTextOf(content) {
  if (typeof content === 'string') return content.trim();
  if (!Array.isArray(content)) return '';
  return content.filter(block => block?.type === 'text' && typeof block.text === 'string').map(block => block.text).join('\n').trim();
}

export function buildStagedContinuation(branch = []) {
  const omitted = retryOmissions(branch);
  let start = 0;
  for (let i = branch.length - 1; i >= 0; i--) {
    if (branch[i]?.type === 'message' && branch[i]?.message?.role === 'user') {
      start = i;
      break;
    }
  }
  const slice = branch.slice(start).filter(entry => entry && !omitted.has(entry.id));
  const results = new Map();
  for (const entry of slice) {
    if (entry.type === 'message' && entry.message?.role === 'toolResult' && entry.message.toolCallId) {
      results.set(entry.message.toolCallId, entry.message);
    }
  }
  const confirmedTools = [];
  const failedTools = [];
  const unconfirmedTools = [];
  let partialOutput = '';
  for (const entry of slice) {
    if (entry.type !== 'message' || entry.message?.role !== 'assistant') continue;
    const message = entry.message;
    const content = Array.isArray(message.content) ? message.content : [];
    for (const block of content) {
      if (block?.type !== 'toolCall' || !block.id) continue;
      const target = summarizeToolTarget(block.arguments);
      const label = target ? `${block.name}(${target})` : String(block.name || 'tool');
      const result = results.get(block.id);
      if (result) {
        if (result.isError) failedTools.push(label);
        else confirmedTools.push(label);
      } else {
        unconfirmedTools.push(label);
      }
    }
    if (message.stopReason === 'error') {
      const text = assistantTextOf(message.content);
      if (text) partialOutput = text;
    }
  }
  const lines = [
    'The previous model response timed out or was interrupted. Continue the same task in small, incremental stages from the last confirmed milestone.',
  ];
  if (partialOutput) {
    const excerpt = partialOutput.length > 400 ? partialOutput.slice(0, 397) + '...' : partialOutput;
    lines.push('Partial output preserved as incomplete: the preceding interrupted assistant reply is NOT complete. Do not treat it as finished, and do not blindly repeat what was already delivered. Interrupted excerpt: ' + JSON.stringify(excerpt));
  }
  if (confirmedTools.length) {
    lines.push('Already confirmed tool results (DO NOT re-execute or repeat these completed writes/operations): ' + confirmedTools.slice(-12).join(', ') + '.');
  } else {
    lines.push('Do not repeat any tool calls or file writes that already succeeded earlier in this conversation.');
  }
  if (unconfirmedTools.length) {
    lines.push('Operations with uncertain execution state (VERIFY actual current state first before modifying anything): ' + unconfirmedTools.slice(-8).join(', ') + '.');
  } else {
    lines.push('For any write, command, or side-effecting step whose completion status is uncertain, verify the current state on disk or in the workspace before acting.');
  }
  if (failedTools.length) {
    lines.push('Previously failed tool calls to take into account: ' + failedTools.slice(-6).join(', ') + '.');
  }
  lines.push('Break the remaining work into short, self-contained stages (smaller responses or smaller writes per turn) so each stage finishes well within the timeout and the user can stop between stages at any time. Stop as soon as the original task is complete.');
  return {
    content: lines.join('\n'),
    details: {
      version: 1,
      hasPartialOutput: Boolean(partialOutput),
      confirmedTools: confirmedTools.slice(-12),
      unconfirmedTools: unconfirmedTools.slice(-8),
    },
  };
}
