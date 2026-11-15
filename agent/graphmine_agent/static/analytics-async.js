/* Shared cancellation, stale-read protection and retry timing. */
(() => {
  "use strict";
  const abortError = () => new DOMException("The workspace changed.", "AbortError");
  /** @param {number} milliseconds @param {AbortSignal | null | undefined} signal */
  function delay(milliseconds, signal) {
    return new Promise((resolve, reject) => {
      if (signal?.aborted) { reject(abortError()); return; }
      const cancel = () => { clearTimeout(timer); reject(abortError()); };
      const timer = setTimeout(() => { signal?.removeEventListener("abort", cancel); resolve(undefined); }, milliseconds);
      signal?.addEventListener("abort", cancel, {once: true});
    });
  }
  /** @param {string | null} value */
  function retryAfter(value) {
    if (!value) return 0;
    const seconds = Number(value);
    const milliseconds = Number.isFinite(seconds) ? seconds * 1000 : Date.parse(value) - Date.now();
    return Number.isFinite(milliseconds) ? Math.min(300000, Math.max(0, milliseconds)) : 0;
  }
  /** @param {number} failures @param {number} requested @param {number} base */
  const backoff = (failures, requested = 0, base = 1000) => Math.max(Math.min(base * 2 ** Math.min(failures, 5), 30000), Math.min(Math.max(requested, 0), 300000));
  /** @param {{api: (path: string, options?: RequestInit, retries?: number) => Promise<any>, signal: AbortSignal, current: () => boolean}} options */
  function readScope({api, signal, current: valid}) {
    const current = () => valid() && !signal.aborted;
    return {current,
      /** @param {string} path @param {number} retries */
      async get(path, retries = 0) {
      if (!current()) throw abortError();
      try {
        const value = await api(path, {signal}, retries);
        if (current()) return value;
      } catch (error) { if (current()) throw error; }
      throw abortError();
    }};
  }
  window.GraphMineAsync = Object.freeze({delay, retryAfter, backoff, readScope});
})();
