const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const {webcrypto} = require("node:crypto");

function browser(storage = new Map()) {
  const context = {window: {}, URL, TextEncoder, crypto: webcrypto,
    location: {origin: "https://graphmine.example", href: "https://graphmine.example/"},
    localStorage: {getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)}};
  vm.runInNewContext(fs.readFileSync(require.resolve("../../graphmine_agent/static/analytics-query-drafts.js"), "utf8"), context);
  return {drafts: context.window.GraphMineQueryDrafts, storage};
}
const content = query => ({query, parameters: "{}", direction: "directed", projection: "elements"});

test("switching backends hides and restores browser drafts without deleting them", async () => {
  const b = browser(), common = {userId: "owner", conversationId: "conversation", inputId: "input"};
  const local = await b.drafts({...common, backendId: "local"});
  local.put("same-connection", "same-dataset", content("RETURN 'local'"));
  local.select("same-connection", "same-dataset");
  const remote = await b.drafts({...common, backendId: "iu-remote"});
  assert.equal(remote.get("same-connection", "same-dataset"), null);
  assert.equal(remote.selection(), null);
  remote.put("same-connection", "same-dataset", content("RETURN 'remote'"));
  const reopened = await browser(b.storage).drafts({...common, backendId: "local"});
  assert.equal(reopened.get("same-connection", "same-dataset").query, "RETURN 'local'");
  assert.equal(reopened.get("same-connection", "same-dataset").backend_id, "local");
  assert.equal(remote.get("same-connection", "same-dataset").query, "RETURN 'remote'");
});

test("legacy untagged draft keys remain local and never appear in IU", async () => {
  const b = browser();
  const old = await b.drafts({userId: "owner"});
  old.put("source", "dataset", content("RETURN 'retained legacy draft'"));
  for (const [key, raw] of b.storage) {
    const value = JSON.parse(raw); delete value.backend_id; b.storage.set(key, JSON.stringify(value));
  }
  const fresh = browser(b.storage);
  const remote = await fresh.drafts({userId: "owner", backendId: "iu-remote"});
  assert.equal(remote.get("source", "dataset"), null);
  const local = await fresh.drafts({userId: "owner", backendId: "local"});
  assert.equal(local.get("source", "dataset").query, "RETURN 'retained legacy draft'");
  assert.equal(b.storage.size, 1);
});
