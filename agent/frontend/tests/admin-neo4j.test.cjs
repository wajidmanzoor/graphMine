const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag, attrs = {}, children = []) { this.tag = tag; this.attrs = attrs; this.children = children.flat(Infinity).filter(v => v != null); this.disabled = attrs.disabled || false; this.checked = attrs.checked || false; }
  append(...children) { this.children.push(...children.flat(Infinity).filter(v => v != null)); }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  setAttribute(key, value) { this.attrs[key] = value; }
  set textContent(value) { this.children = [value]; }
  get textContent() { return this.children.map(v => v instanceof Element ? v.textContent : String(v)).join(" "); }
  all(tag) { return [this, ...this.children.flatMap(v => v instanceof Element ? v.all(tag) : [])].filter(v => v.tag === tag); }
  click() { assert.equal(this.disabled, false); return this.action?.(); }
}

function fixture({running = false, failed = false} = {}) {
  const el = (tag, attrs = {}, ...children) => new Element(tag, attrs, children);
  const f = {mutations: [], active: "local", events: [], intervals: [], dialogs: [], storage: []};
  const counts = {connections: 1, snapshots: 2};
  const status = () => ({active_backend: f.active, switching: false, record_counts: {local: counts, "iu-remote": counts},
    running_jobs: running ? [{id: "job"}] : [], local: {rss_bytes: 1000, units: [{unit: "demo", active: "active", enabled: "enabled", rss_bytes: 1000}]},
    remote: {vpn_reachable: true, is_up: false, started_by_graphmine: false, last_used: null, autowake: true, idle_minutes: 30}});
  const A = {el, api: async path => path === "/api/admin/neo4j" ? status() : {after: f.events.length, events: f.events},
    mutate: (path, body) => { f.mutations.push({path, body}); return new Promise((resolve, reject) => { f.finish = () => failed ? reject(new Error("Target verification failed")) : (f.active = body.target, resolve({})); }); },
    hint: text => el("p", {}, text), badge: text => el("span", {}, text), details: rows => el("dl", {}, rows.flat()),
    bytes: String, stamp: String, n: String,
    button: (label, action) => { const node = el("button", {}, label); node.action = action; return node; },
    dialog: () => { const d = {node: el("dialog"), open() {}, close() { f.closed = true; }}; f.dialogs.push(d); return d; },
    footer: (d, button) => el("footer", {}, button),
    check: label => { const input = el("input", {type: "checkbox"}); return {input, label: el("label", {}, label, input)}; }};
  const context = {window: {GraphMineAdmin: A}, localStorage: {setItem: (...args) => f.storage.push(args)},
    setInterval: fn => (f.intervals.push(fn), f.intervals.length), clearInterval: id => f.intervals[id - 1] = null};
  vm.runInNewContext(fs.readFileSync(require.resolve("../admin-neo4j.js"), "utf8"), context);
  f.mount = context.window.GraphMineNeo4jCard;
  return f;
}

test("admin card confirms scope, disables switches and shows live progress until completion", async () => {
  const f = fixture({running: true}), card = await f.mount();
  assert.equal(card.all("button")[0].disabled, true);
  card.all("button")[1].click();
  const d = f.dialogs[0];
  assert.match(d.node.textContent, /datasets and saved Neo4j work shown will change/);
  assert.match(d.node.textContent, /Uploaded files remain available/);
  d.node.all("input")[0].checked = true;
  const pending = d.node.all("button")[0].click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.closed, true);
  assert.equal(f.mutations.length, 1);
  assert.equal(f.mutations[0].body.force, true);
  assert.equal(f.mutations[0].body.target, "iu-remote");
  assert.ok(card.all("button").every(b => b.disabled));
  f.events = [{type: "database.power", payload: {message: "Starting the database, about 40 seconds…"}}];
  await f.intervals[0]();
  assert.match(card.textContent, /Starting the database, about 40 seconds/);
  f.finish(); await pending;
  assert.match(card.textContent, /Indiana University is active/);
  assert.equal(card.all("button")[0].disabled, false);
  assert.equal(card.all("button")[1].disabled, true);
  assert.ok(f.intervals.every(timer => timer === null));
});

test("failed switch displays the error and keeps the previous backend selected", async () => {
  const f = fixture({failed: true}), card = await f.mount();
  card.all("button")[1].click();
  const pending = f.dialogs[0].node.all("button")[0].click();
  await new Promise(resolve => setImmediate(resolve));
  f.finish(); await pending;
  assert.match(card.textContent, /Target verification failed/);
  assert.equal(card.all("button")[0].disabled, true);
  assert.equal(card.all("button")[1].disabled, false);
  assert.equal(f.storage.length, 0);
});
