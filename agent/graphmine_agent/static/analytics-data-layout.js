"use strict";
window.GraphMineDataLayout = ({node, host, panes, controls, footer, queryAction, onChange, onResize}) => {
  const media = matchMedia("(max-width: 1100px)"), names = ["connection", "query", "preview"];
  const labels = ["Connection", "Query", "Preview"];
  const tabs = node("div", {class: "data-steps", role: "tablist", "aria-label": "Data workspace steps"});
  const buttons = names.map((name, index) => {
    const button = node("button", {id: `data-step-${name}`, type: "button", role: "tab", "aria-controls": panes[index].id});
    button.append(node("span", {"aria-hidden": "true"}, String(index + 1)), node("span", {}, labels[index]));
    button.onclick = () => select(name, true);
    tabs.append(button); return button;
  });
  controls.append(tabs);
  const previous = node("button", {id: "data-step-back", type: "button", class: "quiet"}, "Back");
  const next = node("button", {id: "data-step-next", type: "button", class: "secondary"}, "Continue to query");
  const hint = node("span", {class: "data-step-hint", role: "status"});
  const actions = node("div", {class: "data-step-actions"}); actions.append(previous, hint, next); footer.prepend(actions);
  let selected = "connection", available = false, active = true, mode = "query", datasetPicker = false;
  function render() {
    const current = names.indexOf(selected);
    controls.hidden = !active || !media.matches;
    actions.hidden = !active || !media.matches;
    host.dataset.step = selected;
    for (const [index, pane] of panes.entries()) {
      pane.hidden = media.matches && current !== index;
      pane.setAttribute("role", media.matches ? "tabpanel" : "region");
      pane.setAttribute("aria-labelledby", media.matches ? buttons[index].id : pane.dataset.heading);
      buttons[index].setAttribute("aria-selected", String(index === current));
      buttons[index].tabIndex = index === current ? 0 : -1;
    }
    previous.hidden = current === 0;
    next.hidden = current === 2;
    next.textContent = current === 0 ? mode === "import" ? "Continue to import" : "Continue to query" : "View preview";
    buttons[1].lastElementChild.textContent = mode === "import" ? "Import" : "Query";
    buttons[0].lastElementChild.textContent = datasetPicker ? "Dataset" : "Connection";
    next.disabled = current === 0 && !available;
    hint.textContent = current === 0 && !available ? "Choose a ready dataset to continue." : "";
    queryAction.hidden = media.matches && selected === "connection";
    if (active) requestAnimationFrame(onResize);
  }
  function select(name, focus = false) {
    selected = names.includes(name) ? name : "connection";
    render(); onChange(selected);
    if (focus && media.matches) buttons[names.indexOf(selected)].focus();
  }
  previous.onclick = () => select(names[Math.max(0, names.indexOf(selected) - 1)], true);
  next.onclick = () => select(names[Math.min(2, names.indexOf(selected) + 1)], true);
  tabs.onkeydown = event => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const index = buttons.indexOf(document.activeElement), target = event.key === "Home" ? 0 : event.key === "End" ? 2 : (index + (event.key === "ArrowLeft" ? 2 : 1)) % 3;
    select(names[target], true);
  };
  const resize = () => {
    const previous = selected;
    if (media.matches) {
      const focused = panes.findIndex(pane => pane.contains(document.activeElement));
      if (focused >= 0) selected = names[focused];
    }
    render();
    if (active && previous !== selected) onChange(selected);
  };
  media.addEventListener("change", resize);
  const observer = new ResizeObserver(() => { if (active) onResize(); }); observer.observe(host);
  render();
  return {select, current: () => selected,
    mode(value) { mode = value; render(); },
    datasetPicker(value) { datasetPicker = value; render(); },
    ready(value) { available = value; render(); },
    active(value) { active = value; render(); },
    destroy() { media.removeEventListener("change", resize); observer.disconnect(); }};
};
