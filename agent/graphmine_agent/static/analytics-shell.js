/* Navigation and disclosure behavior; analysis state stays in analytics-ui.js. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const mobile = window.matchMedia("(max-width: 900px)");
  const sidebar = $("app-sidebar"), backdrop = $("panel-backdrop");
  const panels = {activity: $("activity-sidebar"), navigation: sidebar};
  const triggers = {activity: [$("toggle-activity")], navigation: [$("toggle-sidebar")]};
  let currentPanel = null, returnFocus = null, collapsed = false;
  const inertSiblings = new Set();
  function restoreBackground() {
    for (const element of inertSiblings) element.inert = false;
    inertSiblings.clear();
  }
  function isolatePanel(panel) {
    // Preserve any pre-existing inert state; native dialogs manage their own scope.
    for (let branch = panel; branch && branch !== document.body; branch = branch.parentElement) {
      for (const sibling of branch.parentElement.children) {
        if (sibling === branch || sibling === backdrop || !(sibling instanceof HTMLElement)
          || sibling.matches("script, style, dialog") || sibling.inert) continue;
        sibling.inert = true;
        inertSiblings.add(sibling);
      }
    }
  }
  try { collapsed = localStorage.getItem("graphmine.sidebarCollapsed") === "true"; } catch { /* Private browsing. */ }

  function closePanel(restoreFocus = true) {
    if (!currentPanel) return;
    const panel = panels[currentPanel];
    restoreBackground();
    panel.hidden = true;
    panel.removeAttribute("role");
    panel.removeAttribute("aria-modal");
    panel.classList.remove("mobile-open");
    triggers[currentPanel].forEach(button => button.setAttribute("aria-expanded", "false"));
    backdrop.hidden = true;
    delete document.body.dataset.overlay;
    delete document.body.dataset.panel;
    currentPanel = null;
    if (restoreFocus && returnFocus?.isConnected && returnFocus.getClientRects().length) returnFocus.focus();
    returnFocus = null;
  }

  function setPanel(name, open, trigger = document.activeElement) {
    if (!panels[name]) return;
    if (!open) { if (currentPanel === name) closePanel(); return; }
    closePanel(false);
    currentPanel = name;
    returnFocus = trigger;
    const panel = panels[name];
    panel.hidden = false;
    triggers[name].forEach(button => button.setAttribute("aria-expanded", "true"));
    renderPanel();
    (panel.querySelector("[data-close-panel], #collapse-sidebar") || panel).focus();
  }

  function renderPanel() {
    if (!currentPanel) return;
    const panel = panels[currentPanel], modal = mobile.matches || currentPanel === "navigation";
    restoreBackground();
    if (modal) isolatePanel(panel);
    panel.setAttribute("role", modal ? "dialog" : "complementary");
    if (modal) panel.setAttribute("aria-modal", "true");
    else panel.removeAttribute("aria-modal");
    panel.classList.toggle("mobile-open", modal);
    backdrop.hidden = !modal;
    delete document.body.dataset.overlay;
    delete document.body.dataset.panel;
    document.body.dataset[modal ? "overlay" : "panel"] = currentPanel;
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
  mobile.addEventListener("change", () => { renderSidebar(); renderPanel(); });
  backdrop.addEventListener("click", () => closePanel());
  document.querySelectorAll("[data-close-panel]").forEach(button => button.addEventListener("click", () => closePanel()));
  $("toggle-activity").addEventListener("click", () => setPanel("activity", currentPanel !== "activity"));
  for (const id of ["composer-data", "welcome-data"]) $(id).addEventListener("click", () => document.dispatchEvent(new CustomEvent($(id).dataset.action === "projection" ? "graphmine:project-table" : "graphmine:open-data-source")));
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
  document.addEventListener("click", event => {
    for (const menu of document.querySelectorAll(".compute-settings[open], .session-menu[open]")) {
      if (!menu.contains(event.target)) menu.open = false;
    }
  });
  function positionCompute() {
    if (!$("compute-settings").open) return;
    const popover = document.querySelector(".compute-popover");
    popover.style.transform = "";
    const rect = popover.getBoundingClientRect();
    const shift = rect.left < 12 ? 12 - rect.left : rect.right > innerWidth - 12 ? innerWidth - 12 - rect.right : 0;
    if (shift) popover.style.transform = `translateX(${shift}px)`;
  }
  $("compute-settings").addEventListener("toggle", positionCompute);
  window.addEventListener("resize", positionCompute);
  document.addEventListener("keydown", event => {
    // Native dialogs manage their own Escape and focus behavior.
    if (document.querySelector("dialog[open]")) return;
    if (event.key === "Escape") {
      const menu = document.querySelector(".compute-settings[open], .session-menu[open]");
      if (menu) { event.preventDefault(); menu.open = false; menu.querySelector("summary").focus(); return; }
    }
    if (event.key === "Escape" && currentPanel) { event.preventDefault(); closePanel(); return; }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k" && !$("recent-section").hidden) {
      event.preventDefault();
      if (mobile.matches) setPanel("navigation", true);
      else if (collapsed) toggleSidebar();
      $("session-search").focus();
      return;
    }
    if (event.key !== "Tab" || !currentPanel || !document.body.dataset.overlay) return;
    const panel = panels[currentPanel];
    const closedSections = [...panel.querySelectorAll("details:not([open])")];
    const focusable = [...panel.querySelectorAll('a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex="0"]')].filter(element => element.getClientRects().length && !closedSections.some(details => details.contains(element) && details.querySelector(":scope > summary") !== element));
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
      skip.href = page === "domains" ? "#domain-heading" : page === "results" ? "#results-view" : page === "data" ? "#data-workspace-view" : "#chat-content";
      skip.textContent = page === "domains" ? "Skip to workspace" : page === "results" ? "Skip to results" : page === "data" ? "Skip to data workspace" : "Skip to conversation";
      $("nav-new-chat").setAttribute("aria-current", page === "domains" ? "page" : "false");
      $("nav-database")?.setAttribute("aria-current", page === "data" ? "page" : "false");
    },
  };
  renderSidebar();
  (window.GraphMineAccount?.ready || Promise.resolve(false)).then(enabled => { $("nav-projects").hidden = !enabled; }).catch(() => {});
})();
