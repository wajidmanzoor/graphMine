const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const context = vm.createContext({window: {}, TextEncoder, TextDecoder});
for (const name of ['analytics-wire.js', 'analytics-view-style.js']) vm.runInContext(fs.readFileSync(path.join(__dirname, '../../graphmine_agent/static', name), 'utf8'), context);
const S = context.window.GraphMineViewStyle, W = context.window.AnalyticsWire;

test('score ramps stay finite with extreme values and distinguish negative, zero, positive', () => {
  assert.equal(S.fraction(0, -1e308, 1e308), .5);
  const source = {vertices: [-1, 0, 1].map((v, i) => ({id: i, view: {score: v, display_name: 'Entity ' + i}})), edges: []};
  const data = S.renderData(W, source, {nodes: {size: {field: 'score', scale: 'sqrt'}, lightness: {field: 'score', scale: 'diverging', domain: [-1, 1]}}});
  assert.equal(data.elements[1].data.color, 'hsl(206 0% 94%)');
  assert.notEqual(data.elements[0].data.color, data.elements[2].data.color);
  assert.ok(data.elements.every(e => e.data.size >= 14 && e.data.size <= 36));
});

test('typed IDs, parallel directed records and display rule bounds survive rendering', () => {
  const source = {vertices: [0, '0', 9007199254740993n].map(id => ({id, label: 'Duplicate name'})), edges: [{id: 'a', source: 0, target: '0', weight: 0}, {id: 'b', source: 0, target: '0', weight: 100, view: {edge_role: 'derived'}}]};
  const data = S.renderData(W, source, {edges: {width: {field: 'weight', scale: 'sqrt'}}});
  assert.equal(new Set(data.elements.map(e => e.data.id)).size, 5);
  assert.equal(data.elements[4].data.lineStyle, 'dashed');
  assert.equal(data.elements[3].data.width, 1);
  assert.equal(data.elements[4].data.width, 4);
});

test('many categories share gray without merging their identity or permitting unsafe field paths', () => {
  const source = {vertices: Array.from({length: 20}, (_, id) => ({id, view: {group: id}})), edges: []};
  const data = S.renderData(W, source, {nodes: {color: {field: 'group'}}});
  assert.equal(data.legend.length, 20);
  assert.equal(new Set(data.legend.map(v => v.color)).size, 8);
  assert.equal(new Set(data.elements.map(v => v.data.category)).size, 20);
  assert.equal(S.field({}, '__proto__.polluted'), null);
});

test('saved property filters handle absence and explicit dates consistently in private and shared views', () => {
  assert.equal(S.passes({attributes: {created: '2026-11-18'}}, {field: 'attributes.created', operator: 'gte', value: Date.parse('2026-11-17')}), true);
  assert.equal(S.passes({}, {field: 'score', operator: 'gte', value: 0}), false);
  assert.equal(S.passes({view: {score: 0}}, {field: 'score', operator: 'exists'}), true);
});
