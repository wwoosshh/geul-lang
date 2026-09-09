import test from 'node:test';
import assert from 'node:assert/strict';
import { diffRecordValues } from '../src/record-diff.mjs';
import { encode, decode, compare } from '../src/core.mjs';
import { liftRecord } from '../src/record-slice.mjs';
import { summarizeChanges } from '../src/change-rules.mjs';
import { describeComparison } from '../src/presentation.mjs';

test('field differences separate omission, undefined, null, negative zero and literal dotted names', () => {
  const before = encode({ removed: undefined, 'a.b': 0, nested: { amount: null }, unchanged: 3 });
  const after = encode({ added: undefined, 'a.b': -0, nested: {}, unchanged: 3 });
  const delta = diffRecordValues(before, after);
  assert.equal(delta.status, 'verified-observation-delta');
  assert.deepEqual(delta.changes, [
    { kind: 'changed', path: ['a.b'], before: 0, after: { $value: '-0' } },
    { kind: 'added', path: ['added'], after: { $value: 'undefined' } },
    { kind: 'removed', path: ['nested', 'amount'], before: null },
    { kind: 'removed', path: ['removed'], before: { $value: 'undefined' } },
  ]);
  assert.equal(diffRecordValues(encode({ value: NaN }), encode({ value: NaN })).changes.length, 0);
});

test('deltas applied as ordinary own-field edits reconstruct every pair of representative records', () => {
  const records = [{}, { amount: undefined }, { amount: null }, { amount: 0 }, { amount: -0 },
    { amount: NaN }, { amount: Infinity }, { amount: {} }, { amount: { nested: 3 } },
    { ['__proto__']: { constructor: 4 } }, { constructor: 'own', ['a.b']: 2 }];
  for (const before of records) for (const after of records) {
    const delta = diffRecordValues(encode(before), encode(after));
    assert.equal(delta.status, 'verified-observation-delta');
    const edited = decode(encode(before));
    for (const change of delta.changes) {
      let parent = edited;
      for (const key of change.path.slice(0, -1)) parent = parent[key];
      const key = change.path.at(-1);
      if (change.kind === 'removed') delete parent[key];
      else Object.defineProperty(parent, key, { value: decode(change.after), enumerable: true, configurable: true, writable: true });
    }
    assert.deepEqual(encode(edited), encode(after));
  }
  assert.equal({}.nested, undefined);
});

test('resource limits and unsupported observations never produce a partial complete delta', () => {
  const before = encode({ a: 1, b: 2 }), after = encode({ a: 3, b: 4 });
  for (const options of [{ maxChanges: 1 }, { workLimit: 1 }, { byteLimit: 0 }, { maxDepth: 0 }, { maxChanges: -1 }]) {
    const delta = diffRecordValues(before, after, options);
    assert.equal(delta.status, 'not-generated');
    assert.equal(Object.hasOwn(delta, 'changes'), false);
  }
  for (const unsupported of [null, { $opaque: 'truthy-object' }, { $record: { value: { $jsx: {} } } }, { $value: 'wrong' }]) {
    assert.equal(diffRecordValues(before, unsupported).status, 'not-generated');
  }
});

test('comparison text names the changed output fields without reprinting unchanged payloads', () => {
  const before = liftRecord('const x = { keep: "unchanged payload", amount: amount };', { line: 1 });
  const after = liftRecord('const x = { keep: "unchanged payload" };', { line: 1 });
  const domains = { amount: [{ $value: 'undefined' }, 0, { $value: '-0' }] };
  const comparison = compare(before.ir, after.ir, domains);
  const report = describeComparison({ ...comparison, domains, changeRules: summarizeChanges(comparison, domains) });
  assert.match(report, /결과\["amount"\] 속성 삭제/);
  assert.match(report, /미정\(undefined\) → 없음/);
  assert.match(report, /그 밖의 관찰 필드 값·존재 여부는 같다/);
  assert.ok(!report.includes('unchanged payload'));
  assert.match(report, /전체 화면·기획 의도·서버의 동작은 보증하지 않습니다/);
});
