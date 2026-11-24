import { Type } from "typebox";
import { createRemoteCommands } from "./remote-command.mjs";
import { createRemoteFiles } from "./remote-files.mjs";
import { RemoteConnection } from "./remote-transport.mjs";

const select = (...values) => Type.Union(values.map(value => Type.Literal(value)));
const name = Type.String({ minLength: 1, maxLength: 64 });
const pathname = Type.String({ minLength: 1, maxLength: 4096 });

const commandArgs = Type.Object({
  action: select("run", "read", "write", "kill"),
  environment: name,
  command: Type.Optional(Type.String({ minLength: 1, maxLength: 65536 })),
  cwd: Type.Optional(pathname),
  yieldMs: Type.Optional(Type.Integer({ minimum: 0, maximum: 30000 })),
  maxOutputBytes: Type.Optional(Type.Integer({ minimum: 1, maximum: 256 * 1024 })),
  sessionId: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })),
  input: Type.Optional(Type.String({ minLength: 1, maxLength: 65536 })),
}, { additionalProperties: false });

const fileArgs = Type.Object({
  action: select("read", "write", "list", "search", "upload", "download"),
  environment: name,
  path: pathname,
  cwd: Type.Optional(pathname),
  localPath: Type.Optional(pathname),
  content: Type.Optional(Type.String({ maxLength: 512 * 1024 })),
  query: Type.Optional(Type.String({ minLength: 1, maxLength: 1024 })),
  offset: Type.Optional(Type.Integer({ minimum: 0 })),
  maxBytes: Type.Optional(Type.Integer({ minimum: 1, maximum: 8 * 1024 * 1024 })),
  maxEntries: Type.Optional(Type.Integer({ minimum: 1, maximum: 10000 })),
  maxMatches: Type.Optional(Type.Integer({ minimum: 1, maximum: 2000 })),
  encoding: Type.Optional(select("utf8", "base64")),
  recursive: Type.Optional(Type.Boolean()),
  caseSensitive: Type.Optional(Type.Boolean()),
}, { additionalProperties: false });

function response(result) {
  return { content: [{ type: "text", text: JSON.stringify(result) }], details: result, isError: result.ok === false };
}

function connectionProgress(name, status) {
  if (status.state !== "reconnecting" && !(status.state === "connected" && status.recovered)) return;
  const result = { ok: true, operation: "remote-environments.reconnect", environment: name, state: status.state,
    message: status.state === "reconnecting" ? "正在重新连接" : "连接已恢复" };
  for (const key of ["attempt", "retryAfterMs", "nextRetryAt", "outageStartedAt", "recovered", "resumed"]) {
    if (status[key] !== undefined) result[key] = status[key];
  }
  return response(result);
}

function connectionErrorDetails(error) {
  return Object.fromEntries(["code", "sshClient", "sshError", "state", "attempt", "retryAfterMs", "nextRetryAt", "outageStartedAt"]
    .filter(key => error[key] !== undefined).map(key => [key, error[key]]));
}

export function createRemoteEnvironments({ request, emit, getConfig = () => ({}), getSshEnvironment }) {
  const live = new Map();

  async function withProgress(name, entry, onUpdate, operation) {
    let reconnection;
    const update = status => {
      const progress = connectionProgress(name, status);
      if (!progress) return;
      if (status.recovered) reconnection = progress.details;
      onUpdate?.(progress);
    };
    entry.listeners.add(update);
    try {
      if (entry.status.state === "reconnecting" ||
          entry.status.recovered && entry.lastReportedRecovery !== entry.status.outageStartedAt) update(entry.status);
      const result = await operation();
      if (!reconnection) return result;
      entry.lastReportedRecovery = reconnection.outageStartedAt;
      return { ...result, reconnection };
    }
    finally { entry.listeners.delete(update); }
  }

  async function toolResult(name, entry, onUpdate, operation) {
    try { return response(await withProgress(name, entry, onUpdate, operation)); }
    catch (error) {
      if (error.code !== "REMOTE_RECONNECT_TIMEOUT") throw error;
      return response({ ok: false, error: error.message, ...connectionErrorDetails(error) });
    }
  }

  function close(name) {
    const entry = live.get(name);
    if (!entry) return;
    live.delete(name);
    entry.connection.close();
  }

  async function environment(name, signal) {
    const result = await request("remote-environments.list", {}, signal);
    if (!result.ok) throw new Error(result.error || "Unable to load remote environments.");
    const settings = result.environments.find(row => row.name === name);
    if (!settings) {
      close(name);
      throw new Error(`Unknown remote environment "${name}". Add it with umeko_desktop first.`);
    }
    const current = live.get(name);
    if (current && current.host === settings.host && current.platform === settings.platform) return current;
    close(name);
    const { host, platform } = settings;
    const status = {}, listeners = new Set();
    const connection = new RemoteConnection({ host, platform }, {
      sshWrapper: getConfig()?.remoteTestSshCommand,
      getSshEnvironment,
      onState(state, detail = {}) {
        for (const key of Object.keys(status)) if (key !== "sshClient") delete status[key];
        status.state = state;
        for (const key of ["sshClient", "message", "sshError", "attempt", "retryAfterMs", "nextRetryAt", "outageStartedAt", "outageNoticeAt", "recovered", "resumed"]) {
          if (detail[key] !== undefined) status[key] = detail[key];
        }
        emit({ type: "remote_environment_state", name, host, platform, state, ...status });
        for (const listener of listeners) listener(status);
      },
    });
    const entry = { host, platform, connection, status, listeners, commands: createRemoteCommands(connection), files: createRemoteFiles(connection) };
    live.set(name, entry);
    return entry;
  }

  return {
    async test(args, signal, onUpdate) {
      if (!args || typeof args !== "object" || Object.keys(args).length !== 1 || typeof args.name !== "string" || !args.name) {
        return { ok: false, error: "Provide the name of a configured remote environment." };
      }
      let entry;
      const diagnostics = () => Object.fromEntries(["sshClient", "sshError"]
        .filter(key => entry?.status[key]).map(key => [key, entry.status[key]]));
      try {
        entry = await environment(args.name, signal);
        const info = await withProgress(args.name, entry, onUpdate, () => entry.connection.waitForReady(signal));
        return { ok: true, operation: "remote-environments.test", name: args.name, state: "connected", platform: entry.platform,
          cwd: info.cwd, ...(info.reconnection ? { reconnection: info.reconnection } : {}), ...diagnostics() };
      } catch (error) {
        return { ok: false, error: error.message, ...diagnostics(), ...connectionErrorDetails(error) };
      }
    },
    close,
    dispose() {
      for (const name of live.keys()) close(name);
    },
    extension(pi) {
      pi.registerTool({
        name: "remote_command", label: "Remote command", parameters: commandArgs,
        description: "Run shell commands in a named SSH environment. Run returns output and a sessionId; if running, read it to get new output, write input including its newline, or kill that session. Use umeko_desktop remote-environments.list to find configured environments. The session can survive a network interruption.",
        annotations: { readOnlyHint: false, destructiveHint: true },
        async execute(_id, args, signal, onUpdate, ctx) {
          const entry = await environment(args.environment, signal);
          return toolResult(args.environment, entry, onUpdate,
            () => entry.commands.execute(args, { signal, cwd: ctx.cwd }));
        },
      });
      pi.registerTool({
        name: "remote_files", label: "Remote files", parameters: fileArgs,
        description: "Read or write a file, list a directory, search file contents, or upload/download a file or directory in a named SSH environment. path and cwd are remote. localPath is a local workspace path for transfers. Reconnecting resumes in-progress file transfers.",
        annotations: { readOnlyHint: false, destructiveHint: true },
        async execute(_id, args, signal, onUpdate, ctx) {
          const entry = await environment(args.environment, signal);
          return toolResult(args.environment, entry, onUpdate, () => entry.files.execute(args, {
            signal, cwd: ctx.cwd,
            onUpdate: value => onUpdate?.(response(value)),
          }));
        },
      });
    },
  };
}
