// One desktop tool; detailed instructions are loaded from the bundled docs on demand.
import { Type } from 'typebox';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import { prepareDocumentation } from './umeko-documents.mjs';
import { CORE_TOOLS } from './session-capabilities.mjs';

export const UMEKO_TOOL = 'umeko_desktop';
export const SEND_TO_USER = 'send_to_user';
export const REMINDER = 'reminder';
export const coordinatorNativeTools = value => Array.isArray(value)
  ? [...new Set(value.filter(name => CORE_TOOLS.includes(name)))] : [];
let instanceDocs;
export const umekoDocs = () => instanceDocs?.docsRoot || fileURLToPath(new URL('./umeko-docs/', import.meta.url));
export const umekoHelp = () => ({...(instanceDocs || { docsRoot: umekoDocs(), entry: fileURLToPath(new URL('./umeko-docs/README.md', import.meta.url)) }),
  topics:{plugins:'plugins.md',provider:'provider-plugins.md',widget:'widget-plugins.md',agents:'global-agents.md'}});
export function configureUmekoDocs(options) { instanceDocs = prepareDocumentation(options); }
export const UMEKO_PROMPT = 'umeko-desk 的临时文件存放在 ./.umeko 目录下。 Umeko owns providers, credentials, themes, desktop settings, projects and chats; Pi provider configuration does not apply. First call umeko_desktop operation help to discover its documentation. Discover enabled Widgets with widgets.list (activeOnly true) and read widgets.docs before using them. Apply desktop changes through umeko_desktop, not by editing its settings files.';

export function createUmekoControl({ emit, timeoutMs = 90000, getPetAssistantBinding = () => '', getPetReminderBinding = () => '', waitForSpeech = (ms, signal) => delay(ms, undefined, {signal}) }) {
  const pending = new Map();
  let speechTail = Promise.resolve(), speechLife = new AbortController();
  function cancellable(promise, signal) {
    if (signal.aborted) return Promise.reject(signal.reason);
    return new Promise((resolve, reject) => {
      const abort = () => {signal.removeEventListener('abort', abort);reject(signal.reason);};
      signal.addEventListener('abort', abort, {once:true});
      promise.then(value => {signal.removeEventListener('abort', abort);resolve(value);}, error => {signal.removeEventListener('abort', abort);reject(error);});
    });
  }
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
    clear() { for (const id of [...pending.keys()]) finish(id, 'Umeko connection closed');speechLife.abort();speechLife=new AbortController();speechTail=Promise.resolve(); },
    extension(pi) {
      if (getPetAssistantBinding()) pi.registerTool({
        name: SEND_TO_USER, label: '告诉用户', exposure: 'direct',
        description: 'Speak through your bound desktop pet. For pet input, task briefs and notifications, reply here without repeating it in ordinary chat. Direct questions in the agent chat may use ordinary chat. Prefer 10–30 visible characters per call, at most 80. Longer replies may use multiple calls; each returns after a reading pause and concurrent calls are displayed in order. Stop on unavailable or binding_changed.',
        parameters: Type.Object({ text: Type.String({minLength: 1, maxLength: 1024}) }),
        execute: async (_id, params, signal) => {
          const text = typeof params.text === 'string' ? params.text.trim().replace(/\s+/gu, ' ') : '';
          if (!text || [...new Intl.Segmenter(undefined, {granularity:'grapheme'}).segment(text)].length > 80)
            return {content:[{type:'text',text:'Use 1–80 visible characters in one short sentence.'}],isError:true};
          const speechSignal = signal ? AbortSignal.any([signal,speechLife.signal]) : speechLife.signal;
          const run = speechTail.then(async () => {
            speechSignal.throwIfAborted();
            const result = await this.request('desktop_pet.send_to_user', {text, binding:getPetAssistantBinding()}, speechSignal);
            if (result.ok !== false && result.status === 'shown') {
              const duration = Number.isFinite(result.reading_ms) ? Math.max(1800,Math.min(14000,result.reading_ms)) : 1800;
              await waitForSpeech(duration,speechSignal);
            }
            return {content:[{type:'text',text:JSON.stringify(result)}],isError:result.ok === false};
          });
          speechTail = run.catch(() => {});
          return cancellable(run,speechSignal);
        },
      });
      if (getPetReminderBinding()) pi.registerTool({
        name: REMINDER, label: '提醒事项', exposure: 'direct',
        description: 'Manage the reminders shared with your desktop-pet reminder window. List/get/create/update/complete/delete only reminders associated with yourself. repeat is once or daily; daily uses dueAt with an explicit UTC offset plus an IANA timeZone, keeping the same local clock time. Completing a daily reminder stops its future repeats. With action complete, completed:false restores it to open; an overdue restore does not replay missed alerts. User unread badges are cleared only when the user views them.',
        parameters: Type.Object({
          action:Type.Union(['list','get','create','update','complete','delete'].map(value=>Type.Literal(value))),
          completed:Type.Optional(Type.Boolean()),
          id:Type.Optional(Type.String()),status:Type.Optional(Type.Union(['open','completed','all'].map(value=>Type.Literal(value)))),
          title:Type.Optional(Type.String({minLength:1,maxLength:200})),notes:Type.Optional(Type.String({maxLength:2000})),
          dueAt:Type.Optional(Type.Union([Type.String(),Type.Null()])),clearDueAt:Type.Optional(Type.Boolean()),
          repeat:Type.Optional(Type.Union([Type.Literal('once'),Type.Literal('daily')])),timeZone:Type.Optional(Type.String({maxLength:128})),
          offset:Type.Optional(Type.Integer({minimum:0,maximum:10000})),limit:Type.Optional(Type.Integer({minimum:1,maximum:100}))
        }),
        execute:async(_id,params,signal)=>{
          const result=await this.request('desktop_pet.reminder',{...params,binding:getPetReminderBinding()},signal);
          return {content:[{type:'text',text:JSON.stringify(result)}],isError:result.ok===false};
        }
      });
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
export function coordinatorToolGate(event, {petAssistant = false, reminderAssistant = false, skillReader = false, nativeTools = []} = {}) {
  if (coordinatorNativeTools(nativeTools).includes(event.toolName)) return;
  if (petAssistant && event.toolName === SEND_TO_USER) return;
  if (reminderAssistant && event.toolName === REMINDER) return;
  if (skillReader && event.toolName === 'read') return;
  if (petAssistant && event.toolName === UMEKO_TOOL &&
      (['widgets.docs','widgets.call'].includes(event.input?.operation) && event.input?.arguments?.id === 'scheduled-tasks' ||
       event.input?.operation === 'widgets.result')) return;
  if (event.toolName === UMEKO_TOOL && event.input?.operation === 'agent_bus.create')
    return { block: true, reason: 'Only ordinary session Agents may create global subagents. Global subagents cannot create other global subagents.' };
  if (event.toolName !== UMEKO_TOOL || !['agent_bus.overview','agent_bus.dispatch','agent_bus.requests','agent_bus.reply','agent_bus.connections','agent_bus.set_connection','help','models.list'].includes(event.input?.operation))
    return { block: true, reason: 'Global coordinators use the opt-in agent_bus.* API; delegate workspace work to a bridged session.' };
}
export function coordinatorExtension(pi, options = {}) { pi.on('tool_call', event => coordinatorToolGate(event, options)); }
