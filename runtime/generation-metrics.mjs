// Per-response output speed. Estimated counts are always marked explicitly.
export function createGenerationMeter(publish, { now = () => performance.now(), intervalMs = 200 } = {}) {
  let active = false, firstAt = null, units = 0, reported = 0, timer, lastPublished = -Infinity;
  const snapshot = () => {
    const elapsedMs = firstAt === null ? 0 : Math.max(0, now() - firstAt);
    const tokens = reported || Math.ceil(units);
    return { active, estimated: !reported, tokens, elapsedMs,
      tokensPerSecond: tokens > 0 && elapsedMs >= intervalMs ? tokens / (elapsedMs / 1000) : null };
  };
  const tick = (force = false) => {
    if (!force && now() - lastPublished < intervalMs) return;
    lastPublished = now();
    publish(snapshot());
  };
  const stop = () => {
    if (timer) clearInterval(timer);
    timer = undefined;
    if (!active) return;
    active = false;
    tick(true);
  };
  return {
    start() {
      if (timer) clearInterval(timer);
      active = true; firstAt = null; units = 0; reported = 0; lastPublished = -Infinity;
      tick(true);
      timer = setInterval(() => tick(), intervalMs);
      timer.unref?.();
    },
    update(event) {
      if (!active) return;
      if (event.type?.endsWith('_delta') && typeof event.delta === 'string' && event.delta.length) {
        if (firstAt === null) firstAt = now();
        // A bounded estimate for mixed Chinese/English, independent of chunk boundaries.
        for (const char of event.delta) units += /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/u.test(char) ? 1 : Buffer.byteLength(char, 'utf8') / 4;
      }
      const output = event.partial?.usage?.output;
      if (Number.isFinite(output) && output > 0) reported = output;
      tick();
    },
    finish(message) {
      const output = message.usage?.output;
      if (Number.isFinite(output) && output > 0) reported = output;
      stop();
    },
    stop,
    tick: () => { if (active) tick(); },
  };
}
