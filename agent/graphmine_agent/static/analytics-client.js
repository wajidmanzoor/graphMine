/* Typed route builder over the shared transport and lossless JSON wire format. */
(() => {
  "use strict";
  /** @typedef {string | number | bigint | boolean | null | undefined} QueryValue */
  /** @typedef {{path?: Record<string, string | number | bigint>, query?: Record<string, QueryValue | QueryValue[]>, body?: unknown, signal?: AbortSignal, headers?: HeadersInit, asBlob?: boolean}} Options */
  /** @param {import('../../frontend/types/client').Transport} api @param {{stringify(value: unknown): string}} wire @returns {import('../../frontend/types/client').Client} */
  function create(api, wire) {
    /** @param {string} method @param {string} template @param {Options} options */
    async function request(method, template, options = {}) {
      const path = template.replace(/\{([^}]+)\}/g, (_, key) => {
        const value = options.path?.[key];
        if (value === undefined || value === "" || value === "." || value === "..") throw new TypeError(`Missing or invalid API path parameter: ${key}`);
        return encodeURIComponent(String(value));
      });
      const query = new URLSearchParams();
      for (const [key, value] of Object.entries(options.query || {})) {
        for (const item of Array.isArray(value) ? value : [value]) if (item != null) query.append(key, String(item));
      }
      const parameters = query.toString();
      return api(path + (parameters ? "?" + parameters : ""), {
        method: method.toUpperCase(), signal: options.signal, headers: options.headers, asBlob: options.asBlob,
        ...(options.body === undefined ? {} : {body: wire.stringify(options.body)}),
      });
    }
    return /** @type {import('../../frontend/types/client').Client} */ (request);
  }
  window.GraphMineClient = create;
})();
