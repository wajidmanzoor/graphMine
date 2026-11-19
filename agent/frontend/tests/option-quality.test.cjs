const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const context = vm.createContext({window: {}});
for (const name of ['analytics-wire.js', 'analytics-options.js']) vm.runInContext(fs.readFileSync(path.join(__dirname, '../../graphmine_agent/static', name), 'utf8'), context);
const label = context.window.GraphMineOptionQuality;
const exact = {default: 'exact', by_request: {exact: 'exact', approximate: 'exact'}, canonical_requests: {exact: 'exact', approximate: 'exact'}};
const variable = {default: 'heuristic', by_request: {exact: 'exact', heuristic: 'heuristic'}};

test('current server guarantees correct historical approximate badges without changing the saved request', () => {
  const old = {operations: ['densest-subgraph'], parameters: {solution_quality: 'approximate'}, quality: 'approximate'};
  const catalog = {operations: [{id: 'densest-subgraph', quality_guarantees: exact}]};
  assert.equal(label(old, catalog), 'Exact');
  assert.equal(old.parameters.solution_quality, 'approximate');
  assert.equal(label(old, null), 'Requested: Approximate');
});

test('quality edits use server guarantees and restoring the default restores its label', () => {
  const option = {operations: ['community-detection'], parameters: {solution_quality: 'heuristic'}, quality_guarantees: {'community-detection': variable}};
  assert.equal(label(option), 'Heuristic');
  assert.equal(label(option, null, {'community-detection': 'exact'}), 'Exact');
  assert.equal(label(option, null, {'community-detection': undefined}), 'Heuristic');
});

test('multi-operation choices retain mixed guarantees after edits', () => {
  const option = {operations: ['extract', 'community'], parameters: {extract: {}, community: {solution_quality: 'heuristic'}}, quality_guarantees: {extract: exact, community: variable}};
  assert.equal(label(option), 'Mixed guarantees');
  assert.equal(label(option, null, {community: 'exact'}), 'Exact');
});

test('historical duplicate cards collapse by server equivalence while inputs and objectives remain distinct', () => {
  const first = {id: 'option_1', operations: ['densest-subgraph'], input: 'main', parameters: {solution_quality: 'exact', clique_order: 2, members: [9007199254740993n, '001']}};
  const second = {...first, id: 'option_2', parameters: {...first.parameters, solution_quality: 'approximate'}};
  const catalog = {operations: [{id: 'densest-subgraph', quality_guarantees: exact}]};
  const distinct = values => context.window.GraphMineDistinctOptions(values, catalog, context.window.AnalyticsWire);
  assert.equal(distinct([first, second]).length, 1);
  assert.equal(distinct([first, second])[0].id, 'option_1');
  assert.equal(second.parameters.solution_quality, 'approximate');
  assert.equal(distinct([first, {...second, input: 'other'}]).length, 2);
  assert.equal(distinct([first, {...second, parameters: {...second.parameters, clique_order: 3}}]).length, 2);
  assert.equal(context.window.GraphMineDistinctOptions([first, second], null, context.window.AnalyticsWire).length, 2);
});
