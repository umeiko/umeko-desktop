// One visible retry budget; the provider SDK must not add hidden attempts.
export const NETWORK_RETRY = Object.freeze({ enabled: true, maxRetries: 5, baseDelayMs: 2000, maxAgentDelayMs: 30000 });

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
  return /ECONNRESET|ECONNREFUSED|ETIMEDOUT|ENOTFOUND|EAI_AGAIN|UND_ERR_(?:SOCKET|CONNECT_TIMEOUT|HEADERS_TIMEOUT|BODY_TIMEOUT)|network.?error|fetch failed|connection (?:reset|lost|closed|refused)|socket (?:hang up|closed)|timed? out|timeout|terminated|incomplete.?read|premature|stream (?:interrupted|ended|failed)|overloaded|rate.?limit|server_busy|temporarily unavailable|供应商流已中断|连接.*(?:中断|重置|超时)|网络.*(?:中断|超时)/i.test(detail);
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
