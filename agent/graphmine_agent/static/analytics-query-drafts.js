/* Browser drafts are isolated by API identity, conversation/input, and source. */
(() => {
  "use strict";
  const memory = new Map(), volatile = new Set(), VERSION = 1;
  window.GraphMineQueryDrafts = async ({base = "", token = "", userId = "", conversationId = "new", inputId = "", backendId = "local"} = {}) => {
    if (!["local", "iu-remote"].includes(backendId)) throw new Error("Unknown database backend");
    const endpoint = new URL(base || location.origin, location.href);
    const identity = userId && endpoint.origin === location.origin ? ["account", userId] : ["token", token];
    const context = JSON.stringify([endpoint.href.replace(/\/$/, ""), ...identity]);
    let namespace = null;
    try {
      const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(context));
      namespace = [...new Uint8Array(hash)].map(byte => byte.toString(16).padStart(2, "0")).join("");
    } catch { /* An insecure browser context retains drafts only in memory. */ }
    const prefix = `graphmine.queryDraft.v${VERSION}.${namespace}.`;
    // Existing keys belong to local. Keep them intact and give IU a new scope.
    const scope = backendId === "local" ? [conversationId, inputId] : [conversationId, inputId, backendId];
    const key = (type, source = "", dataset = "") => JSON.stringify([type, ...scope, source, dataset]);
    function read(key) {
      // A failed persistent write must still restore the newest edit in this tab.
      if (memory.has(context + key)) return memory.get(context + key);
      if (namespace) {
        try {
          const value = JSON.parse(localStorage.getItem(prefix + key) || "null");
          if (value?.version === VERSION && (!value.backend_id || value.backend_id === backendId)) return {...value, backend_id: backendId};
        } catch { /* Corrupt or unavailable browser storage must not block editing. */ }
      }
      return memory.get(context + key) || null;
    }
    function write(key, value) {
      value = {...value, backend_id: backendId, version: VERSION, updatedAt: new Date().toISOString()};
      memory.set(context + key, value);
      volatile.add(context + key);
      if (namespace) {
        try {
          const serialized = JSON.stringify(value);
          if (new TextEncoder().encode(serialized).length > 512 * 1024) return false;
          localStorage.setItem(prefix + key, serialized); volatile.delete(context + key); return true;
        } catch { /* Quota/private-mode failures are reported in the draft status. */ }
      }
      return false;
    }
    return {
      selection(source = "") { const value = read(key("selection", source)); return typeof value?.source === "string" && typeof value?.dataset === "string" ? value : null; },
      select(source, dataset) { write(key("selection", source), {source, dataset}); return write(key("selection"), {source, dataset}); },
      get(source, dataset) {
        const draftKey = key("draft", source, dataset), value = read(draftKey);
        return typeof value?.query === "string" && typeof value?.parameters === "string" && ["directed", "undirected"].includes(value.direction) && ["elements", "rows"].includes(value.projection) ? {...value, persisted: Boolean(namespace) && !volatile.has(context + draftKey)} : null;
      },
      put(source, dataset, value) { return write(key("draft", source, dataset), value); },
      discard(source, dataset) {
        const draftKey = key("draft", source, dataset);
        memory.delete(context + draftKey);
        volatile.delete(context + draftKey);
        if (namespace) { try { localStorage.removeItem(prefix + draftKey); return true; } catch { /* Keep the editor usable. */ } }
        return false;
      },
    };
  };
})();
