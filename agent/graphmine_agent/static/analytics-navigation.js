/* Workspace routes and page selection; conversation loading is injected. */
"use strict";
window.GraphMineNavigation = ({state, $, openSession, openWorkflow, renderGraph, getHome, getDatabase, isSessionLoading, getWorkflowTarget}) => {
  let routeGeneration = 0, dataReturnRoute = "#";
  function route(page = "chat", workflow = "") {
    return state.session ? `#workspace/${encodeURIComponent(state.session.id)}/${page}${workflow ? `/${encodeURIComponent(workflow)}` : ""}` : page === "data" ? `#data${workflow ? `/${encodeURIComponent(workflow)}` : ""}` : "#";
  }
  function showPage(page) {
    state.view = page;
    getHome()?.setActive(page === "domains");
    document.title = `GraphMine · ${page === "data" ? "Data workspace" : page === "results" ? "Results" : "Chat workspace"}`;
    window.GraphMineShell.setView(page);
    $("domain-view").hidden = page !== "domains";
    $("workspace-view").hidden = page !== "chat";
    $("results-view").hidden = page !== "results";
    $("data-workspace-view").hidden = page !== "data";
    $("workspace-nav").hidden = page === "domains" || page === "data" && !state.session;
    $("chat-page-link").href = route("chat");
    $("results-page-link").href = route("results", state.record?.id || "");
    $("data-page-link").href = route("data");
    $("data-page-link").setAttribute("aria-current", page === "data" ? "page" : "false");
    $("chat-page-link").setAttribute("aria-current", page === "chat" ? "page" : "false");
    $("results-page-link").setAttribute("aria-current", page === "results" ? "page" : "false");
    if (page === "results") requestAnimationFrame(() => { renderGraph(state.graph); state.cy?.resize(); });
  }
  function go(page, workflow = "") {
    const next = route(page, workflow);
    if (location.hash === next) showPage(page); else location.hash = next;
  }
  async function applyRoute() {
    const match = /^#workspace\/([^/]+)(?:\/(chat|results|data)(?:\/([^/]+))?)?$/.exec(location.hash);
    const standaloneData = /^#data(?:\/(files|connection|query|preview))?$/.exec(location.hash);
    const isData = Boolean(standaloneData || match?.[2] === "data");
    const dataPart = standaloneData?.[1] || (isData ? match?.[3] : null) || "connection";
    const id = match ? decodeURIComponent(match[1]) : "";
    if (state.busy && !isSessionLoading() && id !== (state.session?.id || "")) { history.replaceState(null, "", route(state.view)); return; }
    const generation = ++routeGeneration, workflowId = !isData && match?.[3] ? decodeURIComponent(match[3]) : null;
    try {
      if (!isData || id !== (state.session?.id || "")) getDatabase()?.close();
      if (standaloneData) {
        if (state.session || isSessionLoading()) await openSession("");
        if (generation !== routeGeneration) return;
        if (state.view !== "data") dataReturnRoute = "#";
        showPage("data"); await getDatabase().mount(dataPart); return;
      }
      // A pending conversation has no state.session yet, but must still be
      // invalidated when the user goes home.
      if (!match) { await openSession(""); return; }
      if (id !== state.session?.id || isSessionLoading()) {
        if (!await openSession(id, workflowId)) return;
      }
      if (generation !== routeGeneration) return;
      if (isData) {
        if (state.view !== "data") dataReturnRoute = state.view === "results" ? route("results", state.record?.id || "") : route("chat");
        showPage("data"); await getDatabase().mount(dataPart); return;
      }
      if (workflowId && (workflowId !== state.record?.id || getWorkflowTarget() && getWorkflowTarget() !== workflowId)) {
        const workflow = state.workflows.find(row => row.id === workflowId);
        if (!workflow) throw new Error("This analysis is not part of the selected conversation.");
        if (!await openWorkflow(workflow.id)) return;
      }
      if (generation === routeGeneration) showPage(match[2] || "chat");
    } catch (error) {
      if (generation === routeGeneration && error.name !== "AbortError") throw error;
    }
  }
  return {route, showPage, go, applyRoute,
    get returnRoute() { return dataReturnRoute; }};
};
