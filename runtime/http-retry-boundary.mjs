// AgentSession's public autoRetryEnabled/setAutoRetryEnabled API controls only
// the completed HTTP attempt's outer retry boundary. Restore it after Pi emits
// its public agent_settled event; connection failures keep their normal policy.
const MANAGED_HTTP_FINAL = /(?:^|[^A-Za-z0-9_])umeko_http_retry_finished(?:$|[^A-Za-z0-9_])/;

export function bindHttpRetryBoundary(session) {
  let previous, pending = false, closed = false;
  const restore = () => {
    if (!pending) return;
    pending = false;
    session.setAutoRetryEnabled(previous);
  };
  return {
    observe(event) {
      if (closed) return;
      if (event.type === 'agent_settled') {
        restore();
        return;
      }
      const message = event.message;
      if (event.type !== 'message_end' || message?.role !== 'assistant' ||
          message.stopReason !== 'error' || typeof message.errorMessage !== 'string' ||
          !MANAGED_HTTP_FINAL.test(message.errorMessage) || pending) return;
      previous = session.autoRetryEnabled;
      // A session with retry already disabled needs no temporary change.
      if (!previous) return;
      pending = true;
      session.setAutoRetryEnabled(false);
    },
    close() {
      if (closed) return;
      closed = true;
      restore();
    },
  };
}
