import { StdioTransport } from '@earendil-works/pi-mcp';

// Keep Pi's MCP client lifecycle, including its initialize/discovery handshake
// and its prohibition on retrying tool calls which may already have run.
export function createWindowsSandboxMcp({ createExtension, createTransport, prepareTransport, loadConfig, platform = process.platform }) {
  const transports = new Set();
  const localServers = new Set();
  let context, command, reconnecting = Promise.resolve(), revision = 0;

  function deferredTransport(server, work, auth) {
    if (platform !== 'win32' || 'url' in server.config) return createTransport(server, work, auth);
    localServers.add(server.name);
    const listeners = { Message: new Set(), Error: new Set(), Close: new Set() };
    const shutdown = new AbortController();
    let inner, opening, closing, closed = false;
    const disposers = [];
    // Pi uses instanceof StdioTransport when collecting a failed server's stderr.
    // This placeholder never starts a process. Its methods wait for the prepared
    // transport below, while preserving that native diagnostic path.
    const wrapper = Object.assign(new StdioTransport({ command: '' }), {
      start() {
        opening ??= (async () => {
          inner = await prepareTransport(server, work, auth, shutdown.signal);
          if (closed) {
            await inner.close();
            return;
          }
          for (const kind of Object.keys(listeners)) {
            disposers.push(inner[`on${kind}`]((value) => {
              for (const listener of listeners[kind]) listener(value);
            }));
          }
          await inner.start();
        })();
        return opening;
      },
      async send(message, options) {
        await opening;
        if (closed) throw new Error('The MCP connection is changing its Windows sandbox policy.');
        return inner.send(message, options);
      },
      close() {
        if (closing) return closing;
        closed = true;
        shutdown.abort();
        transports.delete(wrapper);
        // Mark Pi's old client closed synchronously. The native reconnect waits
        // for process cleanup before it starts a fresh initialize handshake.
        for (const listener of listeners.Close) listener();
        for (const dispose of disposers) dispose();
        closing = (async () => {
          await inner?.close();
          await opening?.catch(() => {});
        })();
        return closing;
      },
      setProtocolVersion(version) { inner?.setProtocolVersion?.(version); },
    });
    Object.defineProperties(wrapper, {
      stderr: { get: () => inner?.stderr || '' },
      pid: { get: () => inner?.pid },
    });
    for (const kind of Object.keys(listeners)) {
      wrapper[`on${kind}`] = listener => {
        listeners[kind].add(listener);
        return () => listeners[kind].delete(listener);
      };
    }
    transports.add(wrapper);
    return wrapper;
  }

  const extension = pi => {
    pi.on('session_start', (_event, ctx) => { context = ctx; });
    pi.on('session_shutdown', () => { context = undefined; revision++; localServers.clear(); });
    pi.on('tool_call', async event => {
      if (event.toolName.startsWith('mcp__') || ['codemode', 'tool_search',
        'list_mcp_resources', 'list_mcp_resource_templates', 'read_mcp_resource'].includes(event.toolName)) {
        // A second policy update may queue while the first reconnect finishes.
        let waiting;
        do { waiting = reconnecting; await waiting; } while (waiting !== reconnecting);
      }
    });
    createExtension({ createTransport: deferredTransport, loadConfig })({
      ...pi,
      registerCommand(name, definition) {
        if (name === 'mcp') command = definition.handler;
        return pi.registerCommand(name, definition);
      },
    });
  };

  function invalidate() {
    const current = ++revision;
    const ctx = context;
    const closing = Promise.all([...transports].map(transport => transport.close()));
    reconnecting = reconnecting.catch(() => {}).then(async () => {
      await closing;
      if (!ctx || context !== ctx || current !== revision || !command) return;
      // Native MCP owns pending discovery, initialized clients and tool
      // registration. Invoke its command directly without a synthetic prompt.
      await Promise.all([...localServers].map(name => command(`reconnect ${name}`, ctx)));
    });
    return reconnecting;
  }

  return { extension, invalidate };
}
