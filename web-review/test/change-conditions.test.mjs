import test from 'node:test';
import assert from 'node:assert/strict';
import { compare, Unsupported } from '../src/core.mjs';
import { liftExpression } from '../src/typescript.mjs';
import { summarizeChanges, summarizeChangeConditions, verifyChangeConditions } from '../src/change-rules.mjs';
import { describeComparison } from '../src/presentation.mjs';

const expression = text => liftExpression(`const result = ${text};`, text).ir;

test('different result pairs share a change condition without sharing an outcome', () => {
  const domains = { enabled: [false, true], n: [0, 1, 2] };
  const result = compare(expression('n'), expression('enabled ? n + 1 : n'), domains);
  const conditions = summarizeChangeConditions(result, domains);
  assert.equal(summarizeChanges(result, domains).rules.length, 3);
  assert.equal(conditions.status, 'verified-finite-change-conditions');
  assert.deepEqual(conditions.rules, [{ axes: [[1], [0, 1, 2]], matchedRows: 3, distinctOutcomePairs: 3 }]);
  assert.equal(conditions.envelope.unchangedRows, 0);
  assert.equal(verifyChangeConditions(conditions.rules, result, domains).coveredChangedRows, 3);
});

test('all 256 tables independently preserve changed membership and envelope exceptions', () => {
  const domains = { a: [false, true], b: [false, true] };
  for (let table = 0; table < 256; table++) {
    const result = { checked: 4, changes: [], unknown: [], unchanged: 0 }, states = [];
    for (let row = 0; row < 4; row++) {
      const state = (table >> (row * 2)) & 3, inputs = { a: !!(row & 2), b: !!(row & 1) };
      states.push(state);
      if (!state) result.unchanged++;
      else if (state === 3) result.unknown.push({ inputs });
      else result.changes.push({ inputs, before: { kind: 'value', value: row }, after: { kind: 'value', value: row + state } });
    }
    const summary = summarizeChangeConditions(result, domains);
    assert.equal(summary.status, 'verified-finite-change-conditions');
    for (let row = 0; row < 4; row++) {
      const matches = summary.rules.filter(rule => rule.axes[0].includes(row >> 1) && rule.axes[1].includes(row & 1));
      assert.equal(matches.length, [1, 2].includes(states[row]) ? 1 : 0);
      for (const rule of matches) { assert.equal('before' in rule, false); assert.equal('after' in rule, false); }
    }
    if (!result.changes.length) { assert.equal(summary.envelope, null); continue; }
    const changedCells = [0, 1, 2, 3].filter(row => [1, 2].includes(states[row]));
    const contained = [0, 1, 2, 3].filter(row => changedCells.some(other => (other >> 1) === (row >> 1)) && changedCells.some(other => (other & 1) === (row & 1)));
    assert.equal(summary.envelope.matchedRows, contained.length);
    assert.equal(summary.envelope.changedRows, changedCells.length);
    assert.equal(summary.envelope.unchangedRows, contained.filter(row => !states[row]).length);
    assert.equal(summary.envelope.unknownRows, contained.filter(row => states[row] === 3).length);
  }
});

test('an envelope with unchanged and unknown holes is never described as sufficient', () => {
  const domains = { a: [false, true], b: [false, true] };
  const result = { checked: 4, unchanged: 1, unknown: [{ inputs: { a: false, b: true } }], changes: [false, true].map(value => ({
    inputs: { a: value, b: value }, before: { kind: 'value', value: 0 }, after: { kind: 'value', value: 1 },
  })) };
  const changeConditions = summarizeChangeConditions(result, domains);
  assert.equal(changeConditions.envelope.matchedRows, 4);
  const report = describeComparison({ ...result, domains, changeConditions });
  assert.ok(report.startsWith('# 변경 범위\n\n변경이 발견된 입력의 공통 범위:'));
  assert.match(report, /변경 2개, 동일 1개, 미확인 1개/);
  assert.match(report, /공통 조건만으로 변경을 단정할 수 없습니다/);
  assert.match(report, /서로 다른 전후 결과/);
  assert.match(report, /도메인 밖 입력의 결과는 보증하지 않습니다/);
});

test('condition verification rejects invented shared outcomes, broadening, gaps and duplicate unknowns', () => {
  const domains = { a: [false, true] }, result = {
    checked: 2, unchanged: 0, unknown: [{ inputs: { a: true } }],
    changes: [{ inputs: { a: false }, before: { kind: 'value', value: 0 }, after: { kind: 'value', value: 1 } }],
  };
  const rule = summarizeChangeConditions(result, domains).rules[0];
  for (const rules of [[], [rule, rule], [{ ...rule, axes: [[0, 1]], matchedRows: 2 }], [{ ...rule, before: result.changes[0].before }], [{ ...rule, distinctOutcomePairs: 2 }]]) {
    assert.throws(() => verifyChangeConditions(rules, result, domains), Unsupported);
  }
  assert.equal(summarizeChangeConditions(result, domains, { rowLimit: 0 }).status, 'not-generated');
  assert.equal(summarizeChangeConditions(result, domains, { workLimit: 0 }).optimization, 'work-limit');
  const duplicate = { checked: 2, changes: [], unchanged: 0, unknown: [{ inputs: { a: true } }, { inputs: { a: true } }] };
  assert.equal(summarizeChangeConditions(duplicate, domains).status, 'not-generated');
  assert.equal(summarizeChanges(duplicate, domains).status, 'not-generated');
});

test('zero-input single observation and no changes retain their exact scope', () => {
  const changed = { checked: 1, changes: [{ inputs: {}, before: { kind: 'value', value: 1 }, after: { kind: 'throw', name: 'TypeError' } }], unknown: [], unchanged: 0 };
  const summary = summarizeChangeConditions(changed, {});
  assert.deepEqual(summary.rules, [{ axes: [], matchedRows: 1, distinctOutcomePairs: 1 }]);
  assert.equal(summary.envelope.matchedRows, 1);
  const empty = summarizeChangeConditions({ checked: 1, changes: [], unknown: [], unchanged: 1 }, {});
  assert.deepEqual(empty.rules, []);
  assert.equal(empty.envelope, null);
});
