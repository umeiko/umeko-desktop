// Only the community package loader resolves this facade. Keep its native
// session lifecycle and retry implementation, with Umeko's in-memory policy.
export * from "./node_modules/@earendil-works/pi-coding-agent/dist/index.js";
import { SettingsManager as NativeSettingsManager } from "./node_modules/@earendil-works/pi-coding-agent/dist/index.js";
import { NETWORK_RETRY } from "./network-retry.mjs";

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
