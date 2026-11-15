/* One lossless HTTP transport for workspace modules. */
(() => {
  "use strict";
  /** @typedef {{error?: {message?: string, code?: string, details?: unknown}, detail?: string | {message?: string}}} ErrorPayload */
  /** @typedef {RequestInit & {asBlob?: boolean}} RequestOptions */
  class APIError extends Error {
    /** @param {string} message @param {number} status @param {string | undefined} code @param {unknown} details @param {number} retryAfter */
    constructor(message, status, code, details, retryAfter) {
      super(message); this.name = "APIError";
      this.status = status; this.code = code; this.details = details; this.retryAfter = retryAfter;
    }
  }
  /** @param {{state: {base: string, token: string}, W: {parse: (text: string) => any}}} dependencies */
  function create({state, W}) {
    /** @param {string} path @param {RequestOptions} options @param {number} busyRetries */
    async function api(path, options = {}, busyRetries = 0) {
      const {asBlob, ...requestOptions} = options;
      const headers = new Headers(options.headers);
      if (state.token && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${state.token}`);
      if (!(options.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
      const response = await fetch(state.base + path, {...requestOptions, headers});
      if (response.status === 204) return null;
      if (response.ok && asBlob) return response.blob();
      const retryAfter = window.GraphMineAsync.retryAfter(response.headers.get("Retry-After"));
      const text = await response.text();
      let result;
      try { result = W.parse(text); }
      catch { throw new APIError("The server did not return a readable response.", response.status, "invalid_response", undefined, retryAfter); }
      const detail = /** @type {ErrorPayload} */ (result && typeof result === "object" ? result : {});
      if (busyRetries > 0 && ["GET", "HEAD"].includes((options.method || "GET").toUpperCase()) && response.status === 429 && detail.error?.code === "concurrency_limit") {
        await window.GraphMineAsync.delay(Math.max(1000, retryAfter), options.signal);
        return api(path, options, busyRetries - 1);
      }
      if (!response.ok) {
        const message = detail.error?.message || (typeof detail.detail === "string" ? detail.detail : detail.detail?.message) || `Request failed (${response.status}).`;
        throw new APIError(message, response.status, detail.error?.code, detail.error?.details, retryAfter);
      }
      return result;
    }
    return api;
  }
  window.GraphMineTransport = Object.assign(create, {APIError});
})();
