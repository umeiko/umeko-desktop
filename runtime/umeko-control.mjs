// One desktop tool; detailed instructions are loaded from the bundled docs on demand.
import { Type } from 'typebox';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { prepareDocumentation } from './umeko-documents.mjs';

export const UMEKO_TOOL = 'umeko_desktop';
let instanceDocs;
export const umekoDocs = () => instanceDocs?.docsRoot || fileURLToPath(new URL('./umeko-docs/', import.meta.url));
export const umekoHelp = () => ({...(instanceDocs || { docsRoot: umekoDocs(), entry: fileURLToPath(new URL('./umeko-docs/README.md', import.meta.url)) }),
  topics:{plugins:'plugins.md',provider:'provider-plugins.md',widget:'widget-plugins.md',agents:'global-agents.md'}});
export function configureUmekoDocs(options) { instanceDocs = prepareDocumentation(options); }
export const UMEKO_PROMPT = 'Umeko owns providers, credentials, themes, desktop settings, projects and chats; Pi provider configuration does not apply. First call umeko_desktop operation help to discover its documentation. Discover enabled Widgets with widgets.list (activeOnly true) and read widgets.docs before using them. Apply desktop changes through umeko_desktop, not by editing its settings files.';

export function createUmekoControl({ emit, timeoutMs = 90000 }) {
  const pending = new Map();
  function finish(id, error, result) {
    const item = pending.get(id);
    if (!item) return;
    pending.delete(id); clearTimeout(item.timer);
    item.signal?.removeEventListener('abort', item.abort);
    if (error) item.reject(new Error(error)); else item.resolve(result);
  }
  return {
    request(operation, args = {}, signal) {
      if (signal?.aborted) return Promise.reject(new Error('Umeko operation cancelled'));
      if (operation === 'help' && !args.topic) return Promise.resolve({ ok: true, ...umekoHelp() });
      const id = randomUUID();
      return new Promise((resolve, reject) => {
        const abort = () => finish(id, 'Umeko operation cancelled; an already accepted desktop change may still finish');
        const timer = setTimeout(() => finish(id, 'Umeko desktop did not acknowledge the operation; check current state before retrying'), timeoutMs);
        pending.set(id, { resolve, reject, timer, signal, abort });
        signal?.addEventListener('abort', abort, { once: true });
        emit({ type: 'umeko_request', id, operation, arguments: args });
      });
    },
    response(event) { finish(event.id, null, event.result); },
    clear() { for (const id of [...pending.keys()]) finish(id, 'Umeko connection closed'); },
    extension(pi) {
      pi.registerCommand('help', { description: 'Umeko documentation directory', handler: async (_args, ctx) => ctx.ui.notify(umekoDocs(), 'info') });
      pi.registerTool({ name: UMEKO_TOOL, label: '管理 Umeko', exposure: 'direct',
        description: 'Inspect and configure this running Umeko desktop. Start with help for documentation; widgets.list and widgets.docs discover enabled Widgets and their interfaces. Queued or accepted operations are not completed.',
        parameters: Type.Object({ operation: Type.String({ minLength: 1, maxLength: 80 }), arguments: Type.Optional(Type.Record(Type.String(), Type.Unknown())) }),
        execute: async (_id, params, signal) => {
          const result = await this.request(params.operation, params.arguments || {}, signal);
          return { content: [{ type: 'text', text: JSON.stringify(result) }], isError: result.ok === false };
        },
      });
    },
  };
}

// Mandatory coordinator boundary, independent of user extension/tool filters.
export function coordinatorToolGate(event) {
  if (event.toolName === UMEKO_TOOL && event.input?.operation === 'agent_bus.create')
    return { block: true, reason: 'Only ordinary session Agents may create global subagents. Global subagents cannot create other global subagents.' };
  if (event.toolName !== UMEKO_TOOL || !['agent_bus.overview','agent_bus.dispatch','agent_bus.requests','agent_bus.reply','agent_bus.connections','agent_bus.set_connection','help','models.list'].includes(event.input?.operation))
    return { block: true, reason: 'Global coordinators use the opt-in agent_bus.* API; delegate workspace work to a bridged session.' };
}
export function coordinatorExtension(pi) { pi.on('tool_call', coordinatorToolGate); }
