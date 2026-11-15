"use strict";

// Append-only events have stable sequence IDs. Index new arrivals once, including
// older history pages; consumers never scan the whole event log for each turn.
window.GraphMineEventIndex = () => {
  let rows = [], seen = new Set(), types = new Map(), turns = new Map(), versions = new Map(), answers = new Map(), chats = [];
  const compare = (a, b) => a.sequence < b.sequence ? -1 : a.sequence > b.sequence ? 1 : 0;
  const append = (map, key, event) => { if (!map.has(key)) map.set(key, []); map.get(key).push(event); };
  function add(events) {
    const added = [], touchedTypes = new Set(), touchedTurns = new Set();
    let older = false;
    for (const event of events) {
      const id = String(event.sequence);
      if (seen.has(id)) continue;
      seen.add(id); older ||= rows.length > 0 && compare(event, rows.at(-1)) < 0;
      rows.push(event); added.push(event); append(types, event.type, event); touchedTypes.add(event.type);
      const turn = event.payload?.turn_id;
      if (turn) { append(turns, turn, event); touchedTurns.add(turn); versions.set(turn, (versions.get(turn) || 0) + 1); }
      if (event.type === "workflow.chat" && !event.payload.evaluation_id) chats.push(event);
      if (event.type === "workflow.answer") {
        const key = JSON.stringify([event.payload.workflow_id, event.payload.revision]), previous = answers.get(key);
        if (!previous || compare(event, previous) > 0) answers.set(key, event);
      }
    }
    if (older) {
      rows.sort(compare); chats.sort(compare);
      for (const type of touchedTypes) types.get(type).sort(compare);
      for (const turn of touchedTurns) turns.get(turn).sort(compare);
    }
    return added;
  }
  function reset(events = []) {
    rows = []; seen = new Set(); types = new Map(); turns = new Map(); versions = new Map(); answers = new Map(); chats = [];
    add(events);
  }
  return {add, reset, all: () => rows, chats: () => chats, type: type => types.get(type) || [],
    turn: turn => turns.get(turn) || [], version: turn => versions.get(turn) || 0,
    answer: record => answers.get(JSON.stringify([record.id, record.revision]))?.payload};
};

// Reuse unchanged DOM nodes and insert only new/changed entries. Reading an
// unrelated update must not detach a focused control or an expanded disclosure.
window.GraphMineKeyedNodes = () => {
  let entries = new Map();
  function item(key, signature, build) {
    const previous = entries.get(key);
    if (previous?.signature === signature) return previous.node;
    const value = build(); value.dataset.renderKey = key;
    if (previous) {
      const expanded = new Map([...previous.node.querySelectorAll("details")].map(detail => [detail.dataset.history || detail.dataset.turn || detail.querySelector("summary")?.textContent, detail.open]));
      for (const detail of value.querySelectorAll("details")) {
        const key = detail.dataset.history || detail.dataset.turn || detail.querySelector("summary")?.textContent;
        if (expanded.has(key)) detail.open = expanded.get(key);
      }
    }
    entries.set(key, {signature, node: value});
    return value;
  }
  function reconcile(container, nodes) {
    const retained = new Set(nodes), keys = new Set(nodes.map(node => node.dataset.renderKey));
    for (const key of entries.keys()) if (!keys.has(key)) entries.delete(key);
    for (const child of [...container.children]) if (!retained.has(child)) child.remove();
    let cursor = container.firstChild;
    for (const value of nodes) {
      if (value === cursor) cursor = cursor.nextSibling;
      else container.insertBefore(value, cursor);
    }
  }
  return {item, reconcile, clear: () => { entries = new Map(); }};
};

// Refresh attributes in place when topology is unchanged. Preserve dragged
// node positions, pan, zoom and subscriptions across result/overlay refreshes.
window.GraphMineGraphView = W => {
  const snapshots = new WeakMap();
  function render(previous, config, scope, layout, positions) {
    const topology = W.stringify(config.elements.map(({data}) => [data.id, data.source ?? null, data.target ?? null, data.original?.id ?? null]).sort((a, b) => a[0].localeCompare(b[0])));
    const coordinates = positions ? W.stringify(positions) : null;
    const saved = previous && snapshots.get(previous);
    const reuse = previous && !previous.destroyed() && saved?.scope === scope && saved.topology === topology;
    let cy;
    if (reuse) {
      cy = previous;
      cy.batch(() => {
        cy.elements().removeStyle();
        for (const {data} of config.elements) cy.getElementById(data.id).data(data);
        cy.style(config.style);
      });
      if (layout === saved.layout && coordinates !== saved.coordinates && coordinates !== null) cy.layout(config.layout).run();
      cy.resize();
    } else {
      previous?.destroy(); config.container.replaceChildren();
      cy = window.cytoscape(config);
    }
    snapshots.set(cy, {scope, topology, layout, coordinates});
    return {cy, reused: Boolean(reuse)};
  }
  return {render};
};
