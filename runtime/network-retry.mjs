// One visible retry budget; the provider SDK must not add hidden attempts.
export const NETWORK_RETRY = Object.freeze({ enabled: true, maxRetries: 5, baseDelayMs: 2000, maxAgentDelayMs: 30000 });

export function transientFailure(error, http = []) {
  const text = typeof error === 'string' ? error : JSON.stringify(error, Object.getOwnPropertyNames(error || {}));
  const responses = http.map(item => item.response).filter(Boolean);
  const detail = text + ' ' + JSON.stringify(responses.map(r => r.body));
  if (/insufficient_quota|quota exceeded|out of budget|billing|usage limit reached|invalid.?api.?key|unauthorized|authentication|certificate|CERT_|self.signed|额度不足|余额不足/i.test(detail)) return false;
  const status = Number(responses.findLast(r => r.status)?.status);
  if (status >= 400 && status < 500 && ![408, 425, 429].includes(status)) return false;
  if ([408, 425, 429].includes(status) || status >= 500) return true;
  return /ECONNRESET|ECONNREFUSED|ETIMEDOUT|ENOTFOUND|EAI_AGAIN|UND_ERR_(?:SOCKET|CONNECT_TIMEOUT|HEADERS_TIMEOUT|BODY_TIMEOUT)|network.?error|fetch failed|connection (?:reset|lost|closed|refused)|socket (?:hang up|closed)|timed? out|timeout|terminated|incomplete.?read|premature|stream (?:interrupted|ended|failed)|overloaded|rate.?limit|server_busy|temporarily unavailable|供应商流已中断|连接.*(?:中断|重置|超时)|网络.*(?:中断|超时)/i.test(detail);
}

export function upstreamFailure(error) {
  const retryable = error?.retryable === true;
  return { type: 'upstream_error', code: retryable ? 'umeko_stream_interrupted' : 'umeko_request_failed', retryable,
    message: (retryable ? 'Network error: stream interrupted. ' : '') + (error?.reportId ? error.message : 'Provider request failed; check request details') };
}

export function retryOmissions(branch) {
  const edits = new Map(branch.filter(e => e.type === 'context_edit').map(e => [e.targetId, e.replacement]));
  return new Set(branch.filter(e => e.type === 'message' && e.message.role === 'assistant' && e.message.stopReason === 'error' && edits.has(e.id) && edits.get(e.id) === null).map(e => e.id));
}
