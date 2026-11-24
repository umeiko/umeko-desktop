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

export function createRemoteEnvironments({ request, emit, getConfig = () => ({}) }) {
  const live = new Map();

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
    const status = {};
    const connection = new RemoteConnection({ host, platform }, {
      sshCommand: getConfig()?.remoteTestSshCommand,
      onState(state, detail = {}) {
        for (const key of ["message", "sshError", "attempt", "retryAfterMs"]) delete status[key];
        for (const key of ["sshClient", "message", "sshError", "attempt", "retryAfterMs"]) {
          if (detail[key] !== undefined) status[key] = detail[key];
        }
        emit({ type: "remote_environment_state", name, host, platform, state, ...status });
      },
    });
    const entry = { host, platform, connection, status, commands: createRemoteCommands(connection), files: createRemoteFiles(connection) };
    live.set(name, entry);
    return entry;
  }

  return {
    async test(args, signal) {
      if (!args || typeof args !== "object" || Object.keys(args).length !== 1 || typeof args.name !== "string" || !args.name) {
        return { ok: false, error: "Provide the name of a configured remote environment." };
      }
      let entry;
      const diagnostics = () => Object.fromEntries(["sshClient", "sshError"]
        .filter(key => entry?.status[key]).map(key => [key, entry.status[key]]));
      try {
        entry = await environment(args.name, signal);
        const info = await entry.connection.ready({ signal });
        return { ok: true, operation: "remote-environments.test", name: args.name, state: "connected", platform: entry.platform, cwd: info.cwd, ...diagnostics() };
      } catch (error) {
        return { ok: false, error: error.message, ...diagnostics() };
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
        async execute(_id, args, signal, _onUpdate, ctx) {
          const entry = await environment(args.environment, signal);
          return response(await entry.commands.execute(args, { signal, cwd: ctx.cwd }));
        },
      });
      pi.registerTool({
        name: "remote_files", label: "Remote files", parameters: fileArgs,
        description: "Read or write a file, list a directory, search file contents, or upload/download a file or directory in a named SSH environment. path and cwd are remote. localPath is a local workspace path for transfers. Reconnecting resumes in-progress file transfers.",
        annotations: { readOnlyHint: false, destructiveHint: true },
        async execute(_id, args, signal, onUpdate, ctx) {
          const entry = await environment(args.environment, signal);
          return response(await entry.files.execute(args, {
            signal, cwd: ctx.cwd,
            onUpdate: value => onUpdate?.(response(value)),
          }));
        },
      });
    },
  };
}
