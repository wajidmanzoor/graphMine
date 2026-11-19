/* Shared DOM rendering primitives and the domain chooser. */
"use strict";
/** @param {import('../../frontend/types/workspace').RenderingDependencies} dependencies */
window.GraphMineRendering = ({state, $, onDomain}) => {
  /** @type {import('../../frontend/types/workspace').NodeFactory} */
  const node = (tag, attributes = {}, text) => {
    const element = document.createElement(tag);
    for (const [key, value] of Object.entries(attributes)) {
      if (key === "class") element.className = String(value);
      else if (key === "hidden") element.hidden = Boolean(value);
      else element.setAttribute(key, String(value));
    }
    if (text !== undefined) element.textContent = String(text);
    return element;
  };
  /** @param {string} message @param {boolean} error */
  function notice(message, error = false) {
    clearTimeout(state.noticeTimer);
    const dialog = document.querySelector("dialog[open]");
    if (dialog && error && message) {
      let feedback = dialog.querySelector(".dialog-notice");
      if (!feedback) { feedback = node("p", {class: "dialog-notice", role: "alert"}); dialog.prepend(feedback); }
      feedback.textContent = message; feedback.scrollIntoView({block: "nearest"});
    }
    $("notice").textContent = message; $("notice").className = `notice${error ? " error" : ""}`; $("notice").hidden = !message;
    if (message && !error) state.noticeTimer = setTimeout(() => { $("notice").hidden = true; }, 5000);
  }
  notice.clearError = () => {
    if ($("notice").classList.contains("error")) notice("");
    document.querySelectorAll(".dialog-notice").forEach(el => el.remove());
  };
  function renderDomains() {
    const glyphs = ["◇", "↗", "◎", "⌘", "◈", "⟷", "◉", "✧"];
    $("domain-grid").replaceChildren();
    state.domains.forEach((domain, index) => {
      const button = node("button", {class: "domain-card", "data-domain": domain.id, hidden: index >= 6});
      button.append(node("span", {class: "domain-icon", "aria-hidden": "true"}, glyphs[index % glyphs.length]), node("strong", {}, domain.name), node("span", {}, domain.description));
      button.addEventListener("click", () => onDomain(domain));
      $("domain-grid").append(button);
    });
    $("show-all-domains").hidden = state.domains.length <= 6;
    $("show-all-domains").textContent = "Explore all domains ↓";
    $("show-all-domains").setAttribute("aria-expanded", "false");
  }
  return {node, notice, renderDomains};
};
