import { createHash } from "node:crypto";

export function sessionAffinityHeaders(sessionId) {
  return typeof sessionId === "string" && sessionId
    ? { "x-session-affinity": createHash("sha256").update(sessionId, "utf8").digest("hex").slice(0, 32) }
    : {};
}

// Capture the owning session, including children and restored sessions, rather
// than the selected desktop session or Pi's temporary summary routing IDs.
export function attachSessionAffinity(session) {
  const stream = session.agent.streamFunction;
  session.agent.streamFunction = (model, context, options) => stream(model, context, {
    ...options,
    headers: { ...options?.headers, ...sessionAffinityHeaders(session.sessionManager.getSessionId()) },
  });
}
