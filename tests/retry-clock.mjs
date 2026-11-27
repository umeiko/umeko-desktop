// Integration tests still exercise Pi's actual policy/events, without sleeping a minute.
const original = globalThis.setTimeout;
globalThis.setTimeout = (callback, ms, ...args) => original(callback,
  callback.name === "finish" && [5000,10000,30000].includes(ms) ? 100
    : [2000,4000,8000,16000,30000].includes(ms) ? 5 : ms, ...args);
