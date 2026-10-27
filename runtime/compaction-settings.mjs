// Per-session overrides only. Native/project settings and output limits stay intact.
export function compactionSettings(model, native = {}) {
  const settings = { ...native };
  const threshold = model?.compactionThreshold;
  if (threshold === null || threshold === undefined || threshold === "") return settings;
  const window = model.contextWindow || 128000;
  if (!Number.isInteger(threshold) || threshold < 1024 || threshold > window)
    throw new Error("Compaction threshold must be an integer from 1024 to the context window");
  return { ...settings, reserveTokens: window - threshold,
    keepRecentTokens: Math.min(native.keepRecentTokens ?? 20000, Math.floor(threshold / 2)) };
}
