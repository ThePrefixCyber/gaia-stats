'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { sortRows, formatValue, render } = require('../../web/cohort/tables.js');

// Minimal DOM contract for deterministic interaction tests without third-party dependencies.
class Element {
  constructor(tag, ownerDocument) {
    this.tagName = tag.toUpperCase(); this.ownerDocument = ownerDocument;
    this.children = []; this.attributes = {}; this.events = {}; this.text = '';
  }
  set textContent(text) { this.text = String(text); this.children = []; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.text = ''; this.children = children; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(key, callback) { this.events[key] = callback; }
}
const doc = { createElement: tag => new Element(tag, doc) };
const target = () => Object.assign(doc.createElement('div'), { id: 'comparison' });
const head = root => root.children[0].children[1].children[0].children;
const body = root => root.children[0].children[2].children;
const click = (root, index) => head(root)[index].children[0].events.click();
const names = root => body(root).map(row => row.children[0].textContent);

const rows = [
  { faction: 'Tile 10', mean_score: 10, samples: 1200, win_share: .25, round1: 10, round1_n: 1200 },
  { faction: 'Tile 2', mean_score: -2, samples: 2, win_share: 1, round1: -2, round1_n: 2 },
  { faction: 'Unknown', mean_score: null, samples: 0, win_share: null, round1: null, round1_n: 0 },
  { faction: 'Zero', mean_score: 0, samples: 10, win_share: 0, round1: 0, round1_n: 10 },
  { faction: 'Tie', mean_score: 10, samples: 100, win_share: .5, round1: 10, round1_n: 100 }
];

test('numbers sort by raw numeric values, including negatives, zero, and stable ties', () => {
  assert.deepEqual(sortRows(rows, 'mean_score').map(row => row.faction), ['Tile 2', 'Zero', 'Tile 10', 'Tie', 'Unknown']);
  assert.deepEqual(sortRows(rows, 'mean_score', 'descending').map(row => row.faction), ['Tile 10', 'Tie', 'Zero', 'Tile 2', 'Unknown']);
  assert.equal(rows[0].faction, 'Tile 10');
});
test('missing and non-finite values stay last in both directions', () => {
  const data = [{ n: NaN }, { n: null }, {}, { n: Infinity }, { n: 0 }];
  for (const direction of ['ascending', 'descending']) assert.equal(sortRows(data, 'n', direction)[0].n, 0);
});
test('text uses case-insensitive natural ordering', () => {
  const data = [{ n: 'Tile 10' }, { n: 'tile 2' }, { n: 'Tile 1' }];
  assert.deepEqual(sortRows(data, 'n').map(row => row.n), ['Tile 1', 'tile 2', 'Tile 10']);
});
test('formatting separates counts, signed VP, percentages, zero and missing values', () => {
  assert.equal(formatValue('samples', 12345), '12,345');
  assert.equal(formatValue('faction', 'hadsch-hallas'), 'Hadsch Hallas');
  assert.equal(formatValue('mean_score', -12.345), '-12.35');
  assert.equal(formatValue('mean_rank', 2.125), '2.13');
  assert.equal(formatValue('frequency', .125), '12.5%');
  assert.equal(formatValue('win_share', 0), '0%');
  assert.equal(formatValue('mean_score', 0), '0');
  assert.equal(formatValue('mean_score', null), 'Unavailable');
  assert.equal(formatValue('mean_score', Infinity), 'Unavailable');
});
test('render creates semantic controls, announces sort, keeps the header button and raw values', () => {
  const root = target(); render(root, rows, ['faction', 'samples', 'round1']);
  assert.equal(root.attributes.role, 'region'); assert.equal(root.tabIndex, 0);
  const th = head(root)[2], button = th.children[0];
  assert.equal(th.attributes.scope, 'col'); assert.equal(button.type, 'button');
  assert.equal(button.attributes['aria-label'], 'Round 1: sort ascending');
  assert.equal(body(root)[0].children[2].textContent, '101,200 samples');
  click(root, 2);
  assert.deepEqual(names(root), ['Tile 2', 'Zero', 'Tile 10', 'Tie', 'Unknown']);
  assert.equal(head(root)[2].children[0], button);
  assert.equal(th.attributes['aria-sort'], 'ascending');
  assert.match(root.children[1].textContent, /Round 1, ascending/);
  click(root, 2);
  assert.equal(th.attributes['aria-sort'], 'descending');
  assert.equal(button.attributes['aria-label'], 'Round 1: sort ascending');
  assert.deepEqual(names(root), ['Tile 10', 'Tie', 'Zero', 'Tile 2', 'Unknown']);
  click(root, 0);
  assert.equal(th.attributes['aria-sort'], undefined);
  assert.equal(head(root)[0].attributes['aria-sort'], 'ascending');
  assert.equal(rows[0].round1, 10);
});
test('sort survives a data refresh, is independent per table, and resets when a column disappears', () => {
  const root = target(), other = target();
  render(root, rows, ['faction', 'mean_score']); click(root, 1); click(root, 1);
  render(root, rows.slice(0, 4), ['faction', 'mean_score']);
  assert.equal(head(root)[1].attributes['aria-sort'], 'descending');
  assert.deepEqual(names(root), ['Tile 10', 'Zero', 'Tile 2', 'Unknown']);
  render(other, rows, ['faction', 'mean_score']);
  assert.equal(head(other)[1].attributes['aria-sort'], undefined);
  render(root, rows, ['faction', 'samples']);
  assert.equal(head(root)[1].attributes['aria-sort'], undefined);
});
test('empty data displays useful copy, disables sorting, and later data recovers', () => {
  const root = target(); render(root, [], ['faction', 'samples']);
  assert.equal(head(root)[0].children[0].disabled, true);
  assert.equal(body(root)[0].children[0].colSpan, 2);
  assert.match(root.children[0].children[0].textContent, /No observations/);
  render(root, rows, ['faction', 'samples']); click(root, 1);
  assert.equal(names(root)[0], 'Unknown');
});
test('labels use textContent and cannot inject markup', () => {
  const root = target(); render(root, [{ faction: '<img src=x onerror=alert(1)>' }], ['faction']);
  assert.equal(body(root)[0].children[0].children[0].tagName, 'SPAN');
  assert.equal(names(root)[0], '<Img Src=X Onerror=Alert(1)>');
});
test('optional tile labels change display only, preserving sorting inputs', () => {
  globalThis.GaiaTiles = { metric: (kind, value) => `${kind}: ${value}`, position: () => 'Research track' };
  try {
    const root = target(); render(root, [{ label: 'tech1', 'adv-terra': 7 }], ['label', 'adv-terra'], { kind: 'basic-tech-score' });
    assert.equal(names(root)[0], 'basic-tech-score: tech1');
    assert.equal(head(root)[1].children[0].attributes['aria-label'], 'Research track: sort ascending');
  } finally { delete globalThis.GaiaTiles; }
});

test('human-readable labels sort by visible text, not internal tile IDs', () => {
  globalThis.GaiaTiles = { metric: (_, value) => ({tech1: 'Zebra', tech2: 'Alpha'})[value] };
  try {
    const root = target(); render(root, [{label:'tech1'}, {label:'tech2'}], ['label'], {kind:'basic-tech-score'});
    click(root, 0); assert.deepEqual(names(root), ['Alpha', 'Zebra']);
  } finally { delete globalThis.GaiaTiles; }
});


test('integrated final-scoring baselines retain percentage and percentage-point units', () => {
  assert.equal(formatValue('win_baseline', .5), '50%');
  assert.equal(formatValue('win_difference', .25), '25 pp');
  assert.equal(formatValue('win_difference', -.125), '-12.5 pp');
  assert.equal(formatValue('win_baseline_samples', 12345), '12,345');
  const root=target();render(root,[{win_share:.75,win_baseline:.5,win_difference:.25}],['win_share','win_baseline','win_difference']);
  assert.match(head(root)[2].textContent,/percentage points/);
  assert.equal(body(root)[0].children[0].title,'75%');
  assert.equal(body(root)[0].children[2].title,'25 percentage points');
});
