// Only the community package loader resolves this facade. Keep its native
// session lifecycle and retry implementation, with Umeko's in-memory policy.
export * from "./node_modules/@earendil-works/pi-coding-agent/dist/index.js";
import { SettingsManager as NativeSettingsManager } from "./node_modules/@earendil-works/pi-coding-agent/dist/index.js";
import { createAgentSession as nativeCreateAgentSession } from "./node_modules/@earendil-works/pi-coding-agent/dist/index.js";
import { DefaultResourceLoader as NativeResourceLoader } from "./node_modules/@earendil-works/pi-coding-agent/dist/index.js";
import { NETWORK_RETRY } from "./network-retry.mjs";
import { SUBAGENT_COMPLETION_HINT } from "./resources.mjs";
import { backgroundJobsExtension } from "./background-jobs.mjs";
import { createToolPermissionExtension } from "./tool-permissions.mjs";

const permissionHost = () => globalThis[Symbol.for("umeko:tool-permission-host")];

export class DefaultResourceLoader extends NativeResourceLoader {
  constructor(options = {}) {
    const factories = options.extensionFactories || [];
    super({ ...options, extensionFactories: [
      ...factories,
      ...(factories.some(item => item.name === "background-jobs") ? [] :
        [{ name: "background-jobs", builtin: true, replaceable: false, factory: backgroundJobsExtension }]),
      { name: "tool-permissions", hidden: true, replaceable: false,
        factory: createToolPermissionExtension({ getPolicy: () => permissionHost()?.getPolicy() || { mode: "auto" } }) },
    ] });
  }
  getAppendSystemPrompt() {
    const append = super.getAppendSystemPrompt();
    return this.getSystemPrompt()?.includes(SUBAGENT_COMPLETION_HINT) || append.some(text=>text.includes(SUBAGENT_COMPLETION_HINT))
      ? append : [...append, SUBAGENT_COMPLETION_HINT];
  }
}

// Observe public native session events without patching the community package.
// Jiti and ESM can load separate module instances; the process-local symbol is
// the narrow handoff between its SDK facade and the desktop extension.
export async function createAgentSession(options) {
  const result = await nativeCreateAgentSession(options);
  // The community package binds children with {}. Relay supported confirmations
  // through the desktop while leaving genuinely headless contexts headless.
  const bind = result.session.bindExtensions.bind(result.session);
  result.session.bindExtensions = (options = {}) => {
    const host = permissionHost();
    return bind(host?.ui ? { ...options, uiContext: host.ui, mode: "rpc" } : options);
  };
  globalThis[Symbol.for("umeko:subagent-session")]?.(result.session, options);
  return result;
}

export class SettingsManager extends NativeSettingsManager {
  static create(...args) {
    const settings = NativeSettingsManager.create(...args);
    const applyRetry = () => {
      const retry = settings.getSettings().retry;
      settings.applyOverrides({ retry: { ...retry, ...NETWORK_RETRY,
        provider: { ...retry?.provider, maxRetries: 0 } } });
    };
    applyRetry();
    // The child's DefaultResourceLoader reloads these settings before creating
    // its session. Reapply only this instance's policy after that native read.
    const reload = settings.reload.bind(settings);
    settings.reload = async (...options) => { await reload(...options); applyRetry(); };
    return settings;
  }
}
