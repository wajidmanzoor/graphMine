/* Authorized conversation history, searched and paged by the server. */
(() => {
  "use strict";
  /** @param {import('../../frontend/types/workspace').HistoryDependencies} dependencies */
  window.GraphMineSessionHistory = ({state, api, node, notice, onAction}) => {
    /** @param {string} id */
    const $ = id => {
      const element = document.getElementById(id);
      if (!element) throw new Error(`Missing workspace element: ${id}`);
      return element;
    };
    /** @param {string} id */
    const input = id => {
      const element = $(id);
      if (!(element instanceof HTMLInputElement)) throw new Error(`Expected input: ${id}`);
      return element;
    };
    const more = $("load-more-sessions");
    if (!(more instanceof HTMLButtonElement)) throw new Error("Conversation controls are unavailable.");
    const controls = {more};
    const request = window.GraphMineClient(api, {stringify: JSON.stringify}), PAGE = 50;
    let generation = 0, loading = false;
    /** @type {AbortController | null} */ let controller = null;
    /** @type {number | undefined} */ let timer;
    let hasMore = false, nextOffset = 0, lastFilter = "", failure = "";
    // Untitled conversations nobody has used yet are not history.
    const filters = () => ({q: input("session-search").value.trim(), include_archived: input("show-archived").checked, hide_empty: true});

    function render() {
      const scroll = $("recent-sessions").scrollTop;
      $("recent-section").hidden = false;
      const sessions = state.sessions || [];
      $("recent-sessions").replaceChildren();
      for (const session of sessions) {
        const name = session.title || "New conversation";
        const link = node("a", {class: "recent-session", href: `#workspace/${encodeURIComponent(session.id)}/chat`, "aria-current": session.id === state.session?.id ? "page" : "false", title: name});
        const domain = state.domains.find(row => row.id === session.domain_id);
        link.append(node("strong", {}, name + (session.archived ? " (archived)" : "")), node("span", {}, domain?.name || session.domain_id), node("span", {"aria-hidden": "true"}, "→"));
        const row = node("div", {class: "session-row"}), menu = node("details", {class: "session-menu"});
        menu.append(node("summary", {"aria-label": `Actions for ${name}`}, "⋯"));
        const actions = node("div", {class: "session-menu-actions"});
        for (const [action, label] of [["rename", "Rename"], ["archive", session.archived ? "Unarchive" : "Archive"], ["delete", "Delete"]]) {
          const button = node("button", {type: "button", class: action === "delete" ? "quiet danger" : "quiet", "data-session-action": action}, label);
          button.addEventListener("click", () => { menu.open = false; onAction(session, action).catch(error => notice(error.message, true)); }); actions.append(button);
        }
        menu.append(actions); row.append(link, menu); $("recent-sessions").append(row);
      }
      if (!sessions.length && !loading && !failure) $("recent-sessions").append(node("p", {class: "muted"}, input("session-search").value.trim() ? "No conversations match these filters." : "No active conversations. Your questions will appear here."));
      $("recent-sessions").scrollTop = scroll;
      $("recent-sessions").setAttribute("aria-busy", String(loading));
      $("session-history-status").textContent = failure || (loading ? "Searching conversations…" : `${sessions.length} conversation${sessions.length === 1 ? "" : "s"} shown${hasMore ? " · more available" : ""}`);
      $("load-more-sessions").hidden = !hasMore;
      controls.more.disabled = loading;

    }

    async function load(append = false) {
      clearTimeout(timer); controller?.abort(); controller = new AbortController();
      const signal = controller.signal, generationId = ++generation, filter = filters(), key = JSON.stringify(filter);
      append = append && key === lastFilter;
      const offset = append ? nextOffset : 0;
      loading = true; failure = "";
      if (!append && key !== lastFilter) state.sessions = [];
      render();
      try {
        const rows = await request("get", "/api/sessions", {query: {...filter, limit: PAGE + 1, offset}, signal});
        if (generationId !== generation || signal.aborted) return;
        const page = rows.slice(0, PAGE).map(row => {
          if (!row.id) throw new Error("A conversation is missing its identifier.");
          return {...row, id: row.id};
        });
        state.sessions = append ? [...new Map([...(state.sessions || []), ...page].map(row => [row.id, row])).values()] : page;
        nextOffset = offset + page.length; hasMore = rows.length > PAGE; lastFilter = key;
      } catch (error) {
        if (generationId !== generation || signal.aborted) return;
        failure = "Could not load conversations. Use Refresh to try again.";
        throw error;
      } finally {
        if (generationId === generation) { loading = false; render(); }
      }
    }

    function search() {
      generation++; controller?.abort(); clearTimeout(timer);
      state.sessions = []; hasMore = false; loading = true; failure = "";
      $("recent-sessions").scrollTop = 0; render();
      timer = setTimeout(() => load().catch(error => notice(error.message, true)), 200);
    }
    $("session-search").addEventListener("input", search);
    $("show-archived").addEventListener("change", search);
    $("load-more-sessions").addEventListener("click", () => load(true).catch(error => notice(error.message, true)));
    return {load, render};
  };
})();
