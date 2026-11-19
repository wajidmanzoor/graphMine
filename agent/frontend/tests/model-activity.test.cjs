const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const {join} = require("node:path");
const {test} = require("node:test");
const vm = require("node:vm");
const context = vm.createContext({window: {}});
vm.runInContext(readFileSync(join(__dirname, "../../graphmine_agent/static/analytics-incremental.js"), "utf8"), context);
const calls = events => JSON.parse(JSON.stringify(context.window.GraphMineModelCalls(events)));
const event = (type, payload) => ({type: `workflow.${type}`, payload});
const numbered = events => events.map((row, index) => ({sequence: index + 1, ...row}));

test("three model calls produce three entries, not one per event or code stage", () => {
  const events = [];
  for (const stage of ["route", "plan", "answer"]) {
    const payload = {call_id: stage, stage};
    events.push(event("model_call", payload));
    if (stage !== "answer") {
      events.push(event("reasoning.delta", {...payload, text: "fragment"}));
      events.push(event("reasoning", {...payload, text: `Raw ${stage}\n  unchanged`}));
    }
    events.push(event("diagnostics", {...payload, outcome: "ok"}));
  }
  events.push(event("planning", {stage: "validation", status: "passed"}));
  const rows = calls(numbered(events));
  assert.equal(rows.length, 3);
  assert.deepEqual(rows.map(row => row.text), ["Raw route\n  unchanged", "Raw plan\n  unchanged", ""]);
  assert.ok(rows.every(row => !row.running));
});

test("a retry keeps the failed call's partial text separate from the successful call", () => {
  const rows = calls(numbered([
    event("model_call", {call_id: "one", stage: "plan"}),
    event("reasoning.delta", {call_id: "one", stage: "plan", text: "Partial "}),
    event("reasoning.delta", {call_id: "one", stage: "plan", text: "thought"}),
    event("diagnostics", {call_id: "one", stage: "plan", outcome: "planner_timeout"}),
    event("model_call", {call_id: "two", stage: "plan"}),
    event("reasoning", {call_id: "two", stage: "plan", text: "Retried thought"}),
    event("diagnostics", {call_id: "two", stage: "plan", outcome: "ok"}),
  ]));
  assert.deepEqual(rows.map(row => [row.text, row.outcome]), [["Partial thought", "planner_timeout"], ["Retried thought", "ok"]]);
});

test("legacy reasoning and diagnostics pair, while repeated attempts remain separate", () => {
  const rows = calls(numbered([
    event("reasoning.delta", {stage: "plan", text: "First"}),
    event("reasoning", {stage: "plan", text: "First complete"}),
    event("diagnostics", {stage: "plan", outcome: "failed"}),
    event("reasoning", {stage: "plan", text: "Second complete"}),
    event("reasoning", {stage: "plan", text: "Third complete"}),
  ]));
  assert.deepEqual(rows.map(row => row.text), ["First complete", "Second complete", "Third complete"]);
});

test("historical answer calls are counted without inventing or duplicating reasoning", () => {
  const payload = {workflow_id: "w", revision: 1};
  const events = numbered([
    event("answer", {...payload, pending: true, source: "facts"}),
    event("answer", {...payload, pending: false, source: "model"}),
  ]);
  assert.equal(calls(events).length, 1);
  assert.equal(calls(events)[0].text, "");
  assert.equal(calls(events)[0].unrecorded, true);
  events.push(event("model_call", {...payload, call_id: "answer-1", stage: "answer"}));
  events.push(event("diagnostics", {...payload, call_id: "answer-1", stage: "answer", outcome: "ok"}));
  assert.equal(calls(events).length, 1);
  assert.equal(calls(events)[0].key, "answer-1");
});

test("a new answer call remains live after the planner's assistant message", () => {
  const rows = calls(numbered([
    event("chat", {role: "assistant", status: "ready"}),
    event("model_call", {call_id: "a", stage: "answer"}),
    event("reasoning.delta", {call_id: "a", stage: "answer", text: "Writing"}),
  ]));
  assert.equal(rows.length, 1);
  assert.equal(rows[0].running, true);
  assert.equal(rows[0].text, "Writing");
});

test("code-only work and scalar fact answers do not invent a model call", () => {
  assert.equal(calls(numbered([
    event("planning", {stage: "route", status: "calculate", source: "direct"}),
    event("planning", {stage: "validation", status: "passed"}),
    event("answer", {workflow_id: "w", revision: 1, source: "facts", pending: false}),
  ])).length, 0);
});

test("one parallel completion records five samples without inventing five requests", () => {
  const rows = calls(numbered([
    event("model_call", {call_id: "choices", stage: "candidates", samples: 5}),
    event("diagnostics", {call_id: "choices", stage: "candidates", samples: 5, outcome: "ok"}),
  ]));
  assert.equal(rows.length, 1);
  assert.equal(rows[0].samples, 5);
  assert.equal(rows[0].text, "");
  assert.equal(rows[0].running, false);
});

vm.runInContext(readFileSync(join(__dirname, "../../graphmine_agent/static/analytics-activity.js"), "utf8"), context);
const steps = (events, options) => JSON.parse(JSON.stringify(context.window.GraphMineActivitySteps(numbered(events), options)));

test("planning status updates replace the same Activity stage", () => {
  const rows = steps([event("planning", {stage: "family", status: "running"}), event("planning", {stage: "family", status: "selected", family_id: "dense"})]);
  assert.equal(rows.length, 1); assert.equal(rows[0].state, "done"); assert.equal(rows[0].latest.family_id, "dense");
});
test("a finished turn never leaves an uncompleted stage spinning", () => {
  const rows = steps([event("planning", {stage: "candidates", status: "running"}), event("chat", {role: "assistant", status: "options"})]);
  assert.equal(rows[0].state, "incomplete");
});
test("completed model diagnostics finish candidates even without a selected event", () => {
  const rows = steps([event("planning", {stage: "candidates", status: "running"}), event("model_call", {stage: "candidates", call_id: "c"}), event("diagnostics", {stage: "candidates", call_id: "c", outcome: "ok", seconds: 1.2}), event("chat", {role: "assistant", status: "options"})]);
  assert.equal(rows.length, 1); assert.equal(rows[0].state, "done"); assert.equal(rows[0].calls[0].seconds, 1.2);
});
test("a pending answer stays live after planning has finished", () => {
  const events = [event("chat", {role: "assistant", status: "ready"}), event("model_call", {stage: "answer", call_id: "a"})];
  assert.equal(steps(events, {answer: {pending: true}})[0].state, "running");
  assert.equal(steps(events, {answer: {pending: false}})[0].state, "incomplete");
});
test("failed calls retain their failure state", () => {
  const rows = steps([event("planning", {stage: "route", status: "running"}), event("diagnostics", {stage: "route", call_id: "r", outcome: "planner_timeout"}), event("chat", {role: "assistant", status: "failed"})]);
  assert.equal(rows[0].state, "failed");
});
