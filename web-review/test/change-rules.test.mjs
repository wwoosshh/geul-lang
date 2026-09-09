import test from 'node:test';
import assert from 'node:assert/strict';
import { compare, Unsupported } from '../src/core.mjs';
import { liftExpression } from '../src/typescript.mjs';
import { summarizeChanges, verifyChangeRules } from '../src/change-rules.mjs';
import { describeComparison } from '../src/presentation.mjs';

test('irrelevant finite inputs disappear from a rule without asserting unbounded equivalence', () => {
  const expression = text => liftExpression(`const result = ${text};`, text).ir;
  const domains = { enabled: [false, true], busy: [false, true], noise: [false, true] };
  const result = compare(expression('busy && enabled'), expression('noise ? enabled : enabled'), domains);
  const summary = summarizeChanges(result, domains);
  assert.equal(summary.status, 'verified-finite-cover');
  assert.equal(summary.rules.length, 1);
  assert.equal(summary.rules[0].matchedRows, 2);
  assert.deepEqual(summary.rules[0].axes[summary.names.indexOf('noise')], [0, 1]);
  assert.equal(summary.rules[0].before.value, false);
  assert.equal(summary.rules[0].after.value, true);
  const limited = summarizeChanges(result, domains, { workLimit: 0 });
  assert.equal(limited.optimization, 'work-limit');
  assert.equal(limited.rules.length, 2);
  assert.equal(limited.verification.coveredChangedRows, 2);
  const text = describeComparison({ ...result, domains, changeRules: summary });
  assert.ok(text.includes('busy = 거짓 그리고 enabled = 참'));
  assert.ok(!text.includes('noise ='));
  assert.ok(text.includes('도메인 안에서 제한하지 않습니다'));
});

test('all 256 two-input tables preserve changes, unknown holes and differing outcomes', () => {
  const domains = { a: [false, true], b: [false, true] };
  for (let table = 0; table < 256; table++) {
    const result = { checked: 4, changes: [], unknown: [], unchanged: 0 };
    const states = [];
    for (let row = 0; row < 4; row++) {
      const state = (table >> (row * 2)) & 3;
      states.push(state);
      const inputs = { a: !!(row & 2), b: !!(row & 1) };
      if (state === 0) result.unchanged++;
      else if (state === 3) result.unknown.push({ inputs });
      else result.changes.push({ inputs, before: { kind: 'value', value: 0 }, after: { kind: 'value', value: state } });
    }
    const summary = summarizeChanges(result, domains);
    assert.equal(summary.status, 'verified-finite-cover');
    // Independent membership check over every original truth-table cell.
    for (let row = 0; row < 4; row++) {
      const matches = summary.rules.filter(rule => rule.axes[0].includes(row >> 1) && rule.axes[1].includes(row & 1));
      assert.equal(matches.length, [1, 2].includes(states[row]) ? 1 : 0);
      if (matches.length) assert.equal(matches[0].after.value, states[row]);
    }
  }
});

test('verification rejects summaries that include unknown rows, overlap or omit changes', () => {
  const result = { checked: 2, changes: [{ inputs: { a: false }, before: { kind: 'value', value: 0 }, after: { kind: 'value', value: 1 } }], unknown: [{ inputs: { a: true } }], unchanged: 0 };
  const domains = { a: [false, true] }, summary = summarizeChanges(result, domains);
  const rule = summary.rules[0];
  assert.throws(() => verifyChangeRules([{ ...rule, axes: [[0, 1]], matchedRows: 2 }], result, domains), Unsupported);
  assert.throws(() => verifyChangeRules([rule, rule], result, domains), Unsupported);
  assert.throws(() => verifyChangeRules([], result, domains), Unsupported);
  assert.equal(summarizeChanges({ ...result, checked: 3 }, domains).status, 'not-generated');
  assert.equal(summarizeChanges(result, { a: [false, false] }).status, 'not-generated');
  assert.throws(() => verifyChangeRules(summary.rules, { ...result, unknown: [{ inputs: { a: false } }] }, domains), Unsupported);
});
