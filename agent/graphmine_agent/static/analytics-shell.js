/* Navigation and disclosure behavior; analysis state stays in analytics-ui.js. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const mobile = window.matchMedia("(max-width: 900px)");
  const sidebar = $("app-sidebar"), backdrop = $("panel-backdrop");
  const panels = {data: $("data-sidebar"), activity: $("activity-sidebar"), navigation: sidebar};
  const triggers = {data: [$("toggle-data"), $("composer-data")], activity: [$("toggle-activity")], navigation: [$("toggle-sidebar")]};
  let currentPanel = null, returnFocus = null, collapsed = false;
  try { collapsed = localStorage.getItem("graphmine.sidebarCollapsed") === "true"; } catch { /* Private browsing. */ }

  function closePanel(restoreFocus = true) {
    if (!currentPanel) return;
    const panel = panels[currentPanel];
    panel.hidden = true;
    panel.removeAttribute("role");
    panel.removeAttribute("aria-modal");
    panel.classList.remove("mobile-open");
    triggers[currentPanel].forEach(button => button.setAttribute("aria-expanded", "false"));
    backdrop.hidden = true;
    delete document.body.dataset.overlay;
    currentPanel = null;
    if (restoreFocus && returnFocus?.isConnected && returnFocus.getClientRects().length) returnFocus.focus();
    returnFocus = null;
  }

  function setPanel(name, open, trigger = document.activeElement) {
    if (!open) { if (currentPanel === name) closePanel(); return; }
    closePanel(false);
    currentPanel = name;
    returnFocus = trigger;
    const panel = panels[name];
    panel.hidden = false;
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");
    panel.classList.add("mobile-open");
    triggers[name].forEach(button => button.setAttribute("aria-expanded", "true"));
    document.body.dataset.overlay = name;
    backdrop.hidden = false;
    (panel.querySelector("[data-close-panel], #collapse-sidebar") || panel).focus();
  }

  function renderSidebar() {
    if (currentPanel === "navigation") closePanel(false);
    document.body.classList.toggle("sidebar-collapsed", collapsed && !mobile.matches);
    sidebar.hidden = mobile.matches || collapsed;
    $("toggle-sidebar").setAttribute("aria-expanded", String(!sidebar.hidden));
    $("toggle-sidebar").setAttribute("aria-label", "Open sidebar");
  }
  function toggleSidebar() {
    if (mobile.matches) { setPanel("navigation", currentPanel !== "navigation"); return; }
    collapsed = !collapsed;
    try { localStorage.setItem("graphmine.sidebarCollapsed", String(collapsed)); } catch { /* Private browsing. */ }
    renderSidebar();
    (collapsed ? $("toggle-sidebar") : $("collapse-sidebar")).focus();
  }
  $("toggle-sidebar").addEventListener("click", toggleSidebar);
  $("collapse-sidebar").addEventListener("click", () => mobile.matches ? closePanel() : toggleSidebar());
  mobile.addEventListener("change", renderSidebar);
  backdrop.addEventListener("click", () => closePanel());
  document.querySelectorAll("[data-close-panel]").forEach(button => button.addEventListener("click", () => closePanel()));
  $("toggle-activity").addEventListener("click", () => setPanel("activity", currentPanel !== "activity"));
  for (const id of ["composer-data", "welcome-data"]) $(id).addEventListener("click", () => setPanel("data", currentPanel !== "data"));
  $("welcome-sample").addEventListener("click", () => $("sample-data").click());
  document.querySelector(".skip-link").addEventListener("click", event => {
    event.preventDefault();
    const target = document.querySelector(event.currentTarget.getAttribute("href"));
    target.focus();
    target.scrollIntoView({block: "nearest"});
  });

  const question = $("question");
  function resizeComposer() {
    question.style.height = "auto";
    question.style.height = `${Math.max(72, Math.min(question.scrollHeight, 200))}px`;
  }
  question.addEventListener("input", resizeComposer);
  document.querySelectorAll("[data-prompt]").forEach(button => button.addEventListener("click", () => {
    question.value = button.dataset.prompt;
    resizeComposer();
    question.focus();
  }));
  document.addEventListener("keydown", event => {
    // Native dialogs manage their own Escape and focus behavior.
    if (document.querySelector("dialog[open]")) return;
    if (event.key === "Escape" && currentPanel) { event.preventDefault(); closePanel(); return; }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k" && !$("recent-section").hidden) {
      event.preventDefault();
      if (mobile.matches) setPanel("navigation", true);
      else if (collapsed) toggleSidebar();
      $("session-search").focus();
      return;
    }
    if (event.key !== "Tab" || !currentPanel) return;
    const panel = panels[currentPanel];
    const focusable = [...panel.querySelectorAll('a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex="0"]')].filter(element => element.getClientRects().length);
    const first = focusable[0], last = focusable.at(-1);
    if (!first) { event.preventDefault(); panel.focus(); return; }
    if (event.shiftKey && (document.activeElement === first || !panel.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && (document.activeElement === last || !panel.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
  });

  window.GraphMineShell = {
    setPanel,
    resizeComposer,
    setView(page) {
      closePanel(false);
      document.body.dataset.page = page;
      const skip = document.querySelector(".skip-link");
      skip.href = page === "domains" ? "#domain-heading" : page === "results" ? "#results-view" : "#chat-content";
      skip.textContent = page === "domains" ? "Skip to workspace" : page === "results" ? "Skip to results" : "Skip to conversation";
      $("nav-new-chat").setAttribute("aria-current", page === "domains" ? "page" : "false");
    },
  };
  renderSidebar();
  (window.GraphMineAccount?.ready || Promise.resolve(false)).then(enabled => { $("nav-projects").hidden = !enabled; }).catch(() => {});
})();
