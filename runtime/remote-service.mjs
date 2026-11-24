// Desktop-level persistent remote environment service (JSONL over stdio).
// Serves the WorkspacePicker dialog, Settings add/test actions, and the plugin
// WorkspaceExecutor even when no Pi bridge session is active.
import { createInterface } from "node:readline";
import { createRemoteEnvironments } from "./remote-environments.mjs";

const emit = payload => process.stdout.write(JSON.stringify(payload) + "\n");

let configuredEnvironments = [];
let serviceConfig = {};
const inflight = new Map();

const remote = createRemoteEnvironments({
  request: async operation => {
    if (operation === "remote-environments.list") {
      return { ok: true, environments: configuredEnvironments };
    }
    return { ok: false, error: `Unsupported operation: ${operation}` };
  },
  emit: event => emit(event),
  getConfig: () => serviceConfig,
});

function updateEnvironments(list) {
  if (Array.isArray(list)) {
    configuredEnvironments = list.filter(row => row && typeof row.name === "string" && typeof row.host === "string" && typeof row.platform === "string");
  }
}

async function handle(message) {
  if (!message || typeof message !== "object") return;
  if (message.type === "cancel" && message.id) {
    inflight.get(message.id)?.abort();
    return;
  }
  const { id, method, params = {} } = message;
  if (Array.isArray(params.environments)) updateEnvironments(params.environments);
  if (params.remoteTestSshCommand !== undefined) {
    serviceConfig = { ...serviceConfig, remoteTestSshCommand: params.remoteTestSshCommand };
  }

  const controller = new AbortController();
  if (id !== undefined) inflight.set(id, controller);

  try {
    let result;
    if (method === "setConfig") {
      updateEnvironments(params.environments);
      if (params.remoteTestSshCommand !== undefined) {
        serviceConfig = { ...serviceConfig, remoteTestSshCommand: params.remoteTestSshCommand };
      }
      result = { ok: true };
    } else if (method === "sshHosts") {
      result = remote.sshHosts(params.file ? { file: params.file } : {});
    } else if (method === "detectPlatform") {
      result = await remote.detectPlatform(params.host, controller.signal);
    } else if (method === "test") {
      result = await remote.test({ name: params.name }, controller.signal);
    } else if (method === "home") {
      result = await remote.home({ name: params.name }, controller.signal);
    } else if (method === "browse") {
      result = await remote.browse({ name: params.name, path: params.path, includeFiles: params.includeFiles === true }, controller.signal);
    } else if (method === "mkdir") {
      result = await remote.mkdir({ name: params.name, path: params.path }, controller.signal);
    } else if (method === "workspaceOp") {
      result = await remote.workspaceOp(params, controller.signal);
    } else if (method === "close") {
      remote.close(params.name);
      result = { ok: true };
    } else if (method === "shutdown") {
      remote.dispose();
      if (id !== undefined) emit({ type: "response", id, result: { ok: true } });
      process.exit(0);
    } else {
      result = { ok: false, error: `Unknown method: ${method}` };
    }
    if (id !== undefined) emit({ type: "response", id, result });
  } catch (error) {
    if (id !== undefined) {
      emit({ type: "response", id, result: { ok: false, error: error?.message || String(error), aborted: error?.name === "AbortError" } });
    }
  } finally {
    if (id !== undefined) inflight.delete(id);
  }
}

const rl = createInterface({ input: process.stdin });
rl.on("line", line => {
  if (!line.trim()) return;
  try {
    void handle(JSON.parse(line));
  } catch (error) {
    emit({ type: "error", message: error.message });
  }
});
rl.on("close", () => {
  for (const controller of inflight.values()) controller.abort();
  inflight.clear();
  remote.dispose();
});

emit({ type: "ready" });
