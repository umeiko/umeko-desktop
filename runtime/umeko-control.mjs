// One desktop tool; detailed instructions are loaded from the bundled docs on demand.
import { Type } from 'typebox';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { prepareDocumentation } from './umeko-documents.mjs';

export const UMEKO_TOOL = 'umeko_desktop';
let instanceDocs;
export const umekoDocs = () => instanceDocs?.docsRoot || fileURLToPath(new URL('./umeko-docs/', import.meta.url));
export const umekoHelp = () => ({...(instanceDocs || { docsRoot: umekoDocs(), entry: fileURLToPath(new URL('./umeko-docs/README.md', import.meta.url)) }),
  topics:{plugins:'plugins.md',provider:'provider-plugins.md',widget:'widget-plugins.md'}});
export function configureUmekoDocs(options) { instanceDocs = prepareDocumentation(options); }
export const UMEKO_PROMPT = 'Umeko owns providers, credentials, themes, desktop settings, projects and chats; Pi provider configuration does not apply. Umeko plugins have two types: Provider plugins (plugins.*) and desktop Widget plugins (widgets.*). First call umeko_desktop operation help; arguments.topic provider or widget locates the relevant guide. For active Widgets call widgets.list with activeOnly true, then widgets.docs for their documented public methods and communication. Use widgets.call and widgets.result for asynchronous Widget RPC; Widget pushes arrive as attributed custom messages and remain queryable through widgets.messages. Use umeko_desktop to apply changes to the running desktop. Do not edit its settings files behind the UI.';

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
        description: 'Inspect and configure this running Umeko desktop. Provider plugins use plugins.*; desktop Widget plugins use widgets.* for management, public-method calls, results and messages. Use help with arguments.topic provider or widget to find documentation; widgets.list and widgets.docs describe active Widgets. Queued or accepted operations are not completed.',
        parameters: Type.Object({ operation: Type.String({ minLength: 1, maxLength: 80 }), arguments: Type.Optional(Type.Record(Type.String(), Type.Unknown())) }),
        execute: async (_id, params, signal) => {
          const result = await this.request(params.operation, params.arguments || {}, signal);
          return { content: [{ type: 'text', text: JSON.stringify(result) }], isError: result.ok === false };
        },
      });
    },
  };
}
