const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const {getEventListeners} = require("node:events");
const {join} = require("node:path");
const {test} = require("node:test");
const vm = require("node:vm");

function runtime(fetch) {
  const context = vm.createContext({window: {}, fetch, Headers, FormData, Response, Blob, AbortController, DOMException, URLSearchParams, setTimeout, clearTimeout});
  for (const name of ["analytics-wire.js", "analytics-async.js", "analytics-transport.js", "analytics-client.js"]) {
    vm.runInContext(readFileSync(join(__dirname, "../../graphmine_agent/static", name), "utf8"), context, {filename: name});
  }
  const state = {base: "http://graphmine.test", token: "test-token"};
  const api = context.window.GraphMineTransport({state, W: context.window.AnalyticsWire});
  return {context, state, api, client: context.window.GraphMineClient(api, context.window.AnalyticsWire), async: context.window.GraphMineAsync};
}

test("transport keeps exact IDs, authorization and structured API errors", async () => {
  const calls = [];
  const f = runtime(async (url, options) => {
    calls.push({url, options});
    return calls.length === 1 ? new Response('{"id":9007199254740993,"label":"001"}')
      : Response.json({error: {code: "revision_conflict", message: "Changed revision", details: {revision: 2}}}, {status: 409});
  });
  const value = await f.api("/api/items");
  assert.equal(value.id, 9007199254740993n); assert.equal(value.label, "001");
  assert.equal(calls[0].url, "http://graphmine.test/api/items");
  assert.equal(calls[0].options.headers.get("Authorization"), "Bearer test-token");
  await assert.rejects(f.api("/api/items"), error => error.status === 409 && error.code === "revision_conflict" && error.details.revision === 2);
});

test("aborting during a concurrency retry stops its timer and prevents a second request", async () => {
  let requests = 0;
  const f = runtime(async () => { requests++; return Response.json({error: {code: "concurrency_limit"}}, {status: 429, headers: {"Retry-After": "60"}}); });
  const controller = new AbortController();
  const pending = f.api("/api/items", {signal: controller.signal}, 2);
  await new Promise(resolve => setTimeout(resolve, 15));
  controller.abort();
  await assert.rejects(pending, error => error.name === "AbortError");
  assert.equal(requests, 1); assert.equal(getEventListeners(controller.signal, "abort").length, 0);
});

test("mutations never repeat automatically even when read retries are requested", async () => {
  let requests = 0;
  const f = runtime(async () => { requests++; return Response.json({error: {code: "concurrency_limit"}}, {status: 429}); });
  await assert.rejects(f.api("/api/work", {method: "POST", body: "{}"}, 3), error => error.status === 429);
  assert.equal(requests, 1);
});

test("unreadable proxy errors retain status and retry timing", async () => {
  const f = runtime(async () => new Response("<html>Unavailable</html>", {status: 503, headers: {"Retry-After": "12"}}));
  await assert.rejects(f.api("/api/items"), error => error.status === 503 && error.code === "invalid_response" && error.retryAfter === 12000);
});

for (const fails of [false, true]) test(`a superseded read rejects late ${fails ? "errors" : "data"} even if transport ignores cancellation`, async () => {
  const f = runtime(async () => Response.json({}));
  let resolve, reject, valid = true;
  const operation = new Promise((a, b) => { resolve = a; reject = b; });
  const scope = f.async.readScope({api: () => operation, signal: new AbortController().signal, current: () => valid});
  const pending = scope.get("/api/items"); valid = false;
  if (fails) reject(new Error("Stale failure")); else resolve({id: "old"});
  await assert.rejects(pending, error => error.name === "AbortError");
  assert.equal(scope.current(), false);
});

test("an invalid read scope never starts HTTP work", async () => {
  const f = runtime(async () => Response.json({}));
  const scope = f.async.readScope({api: () => { throw new Error("HTTP must not start"); }, signal: new AbortController().signal, current: () => false});
  await assert.rejects(scope.get("/api/items"), error => error.name === "AbortError");
});

test("client encodes path and query values while retaining bigint JSON bodies", async () => {
  const calls = [], controller = new AbortController();
  const f = runtime(async (url, options) => { calls.push({url, options}); return Response.json({ok: true}); });
  await f.client("post", "/api/database-sources/{source_id}/queries", {path: {source_id: "a/?"}, query: {after: 9007199254740993n, absent: null}, body: {statement: "RETURN $id", parameters: {id: 9007199254740993n}}, signal: controller.signal});
  assert.equal(calls[0].url, "http://graphmine.test/api/database-sources/a%2F%3F/queries?after=9007199254740993");
  assert.equal(calls[0].options.body, '{"statement":"RETURN $id","parameters":{"id":9007199254740993}}');
  assert.equal(calls[0].options.signal, controller.signal);
  await assert.rejects(f.client("get", "/api/files/{file_id}", {path: {file_id: ".."}}), /invalid API path/);
  assert.equal(calls.length, 1);
});

test("empty responses, binary exports and multipart uploads preserve their contracts", async () => {
  const seen = [];
  const f = runtime(async (_, options) => { seen.push(options); return seen.length === 1 ? new Response(null, {status: 204}) : new Response(new Uint8Array([0, 255, 1])); });
  assert.equal(await f.api("/api/item", {method: "DELETE"}), null);
  const data = new FormData(); data.append("file", new Blob(["graph"]), "input.json");
  const blob = await f.api("/api/export", {method: "POST", body: data, asBlob: true});
  assert.deepEqual([...new Uint8Array(await blob.arrayBuffer())], [0, 255, 1]);
  assert.equal(seen[1].body, data); assert.equal(seen[1].headers.has("Content-Type"), false);
});

test("retry hints are bounded and completed delay listeners are removed", async () => {
  const f = runtime(async () => Response.json({}));
  assert.equal(f.async.retryAfter("999999"), 300000);
  assert.equal(f.async.retryAfter("not a date"), 0);
  assert.equal(f.async.backoff(100, 999999), 300000);
  const controller = new AbortController();
  await f.async.delay(1, controller.signal);
  assert.equal(getEventListeners(controller.signal, "abort").length, 0);
});

test("entity labels quote string IDs only where they could be misread", () => {
  const {idLabel} = runtime(async () => new Response("{}")).context.window.AnalyticsWire;
  assert.equal(idLabel("Dara"), "Dara");
  assert.equal(idLabel("user-12"), "user-12");
  assert.equal(idLabel("7"), '"7"');
  assert.equal(idLabel("-0.5e3"), '"-0.5e3"');
  assert.equal(idLabel("true"), '"true"');
  assert.equal(idLabel(" padded"), '" padded"');
  assert.equal(idLabel(""), '""');
  assert.equal(idLabel(7), "7");
  assert.equal(idLabel(9007199254740993n), "9007199254740993");
});
