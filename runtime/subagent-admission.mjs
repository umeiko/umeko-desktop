import { randomUUID } from "node:crypto";

export function createSubagentAdmission(emit) {
  const pending = new Map();
  let closed = false;

  async function run({ signal, onWaiting }, work) {
    if (closed || signal?.aborted) return false;
    const ticket = randomUUID();
    const send = action => emit({type: "subagent_admission", action, ticket});
    const state = await new Promise(resolve => {
      const cancel = () => {
        if (!pending.has(ticket)) return;
        finish("cancelled");
        send("cancel");
      };
      const finish = state => {
        pending.delete(ticket);
        signal?.removeEventListener("abort", cancel);
        resolve(state);
      };
      pending.set(ticket, {finish, onWaiting});
      signal?.addEventListener("abort", cancel, {once:true});
      send("acquire");
    });
    if (state === "rejected") throw new Error("子智能体队列已满或桌面正在关闭 / Subagent queue unavailable");
    if (state !== "granted") return false;
    try {
      if (closed || signal?.aborted) return false;
      await work();
      return true;
    } finally { send("release"); }
  }

  function reply({ ticket, state }) {
    const request = pending.get(ticket);
    if (!request) return;
    if (state === "waiting") request.onWaiting?.();
    else if (state === "granted" || state === "rejected") request.finish(state);
  }

  function close() {
    closed = true;
    for (const request of pending.values()) request.finish("cancelled");
  }
  return {run, reply, close};
}
