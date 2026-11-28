"use strict";
window.GraphMineDataLayout = ({node, host, panes, controls, onChange, onResize}) => {
  const media = matchMedia("(max-width: 800px)"), names = ["query", "preview"];
  const tabs = node("div", {class: "data-steps", role: "tablist", "aria-label": "Query workspace views"});
  let selected = "query", active = true;
  const buttons = names.map((name, i) => {
    const button = node("button", {id: `data-step-${name}`, type: "button", role: "tab", "aria-controls": panes[i].id}, i ? "Graph preview" : "Query");
    button.onclick = () => select(name, true); tabs.append(button); return button;
  });
  controls.append(tabs);
  function render() {
    controls.hidden = !active || !media.matches; host.dataset.step = selected;
    panes.forEach((pane, i) => {
      pane.hidden = media.matches && names[i] !== selected;
      pane.setAttribute("role", media.matches ? "tabpanel" : "region");
      pane.setAttribute("aria-labelledby", media.matches ? buttons[i].id : pane.dataset.heading);
      buttons[i].setAttribute("aria-selected", String(names[i] === selected)); buttons[i].tabIndex = names[i] === selected ? 0 : -1;
    });
    if (active) requestAnimationFrame(onResize);
  }
  function select(name, focus = false) {
    selected = name === "preview" ? "preview" : "query";
    render(); onChange(selected); if (focus && media.matches) buttons[names.indexOf(selected)].focus();
  }
  tabs.onkeydown = event => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault(); select(event.key === "Home" ? "query" : event.key === "End" ? "preview" : selected === "query" ? "preview" : "query", true);
  };
  const resize = () => {
    const focused = panes.findIndex(pane => pane.contains(document.activeElement));
    if (media.matches && focused >= 0 && active) select(names[focused]); else render();
  };
  media.addEventListener("change", resize);
  const observer = new ResizeObserver(() => { if (active) onResize(); }); observer.observe(host); render();
  return {select, current: () => selected, mode() {}, datasetPicker() {}, ready() {}, active(value) { active = value; render(); },
    destroy() { media.removeEventListener("change", resize); observer.disconnect(); }};
};
