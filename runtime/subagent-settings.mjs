// Reuse the community settings loader and honor explicit user concurrency policy.
// The desktop's default has no four-agent admission cap.
export * from "./node_modules/@gotgenes/pi-subagents/src/settings.ts";
import { SettingsManager as CommunitySettingsManager } from "./node_modules/@gotgenes/pi-subagents/src/settings.ts";
export class SettingsManager extends CommunitySettingsManager {
  load() {
    const values = super.load();
    if (!Object.hasOwn(values, "maxConcurrent")) this.maxConcurrent = Number.MAX_SAFE_INTEGER;
    return values;
  }
}
