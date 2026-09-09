import test from 'node:test';
import assert from 'node:assert/strict';
import { encode, decode } from '../src/core.mjs';
import { diffArrayValues, verifyArrayDelta } from '../src/array-diff.mjs';
import { diffRecordValues } from '../src/record-diff.mjs';
import { describeComparison } from '../src/presentation.mjs';

const pack = value => encode(value, 0, undefined, { arrays: true });
const unpack = value => decode(value, 0, { arrays: true });

test('sequence edits separate before and after positions and keep whole element values', () => {
  const before = [{ id: 'preview' }, { id: 'z' }, { id: 'a' }], after = [{ id: 'z' }, { id: 'b', child: true }, { id: 'a' }];
  const delta = diffArrayValues(pack(before), pack(after));
  assert.equal(delta.status, 'verified-array-observation-delta');
  assert.deepEqual(delta.edits, [
    { beforeStart: 0, afterStart: 0, removed: [pack(before[0])], inserted: [] },
    { beforeStart: 2, afterStart: 1, removed: [], inserted: [pack(after[1])] },
  ]);
  assert.equal(verifyArrayDelta(pack(before), pack(after), delta.edits).reconstructedAfter, true);
  const changed = diffArrayValues(pack([{ id: 'a', amount: 1 }]), pack([{ id: 'a', amount: 2 }]));
  assert.equal(changed.edits[0].removed[0].$record.amount, 1);
  assert.equal(changed.edits[0].inserted[0].$record.amount, 2);
});

test('ordinary native splice reconstructs all pairs including duplicates, reordering, nested arrays and tagged scalars', () => {
  const arrays = [[], [1], [2], [1, 1], [1, 2], [2, 1], [1, 2, 1], [2, 1, 2], [undefined], [null], [0], [-0], [NaN], [Infinity], [[1, 2], []],
    [{ id: 'x', value: 1 }, { id: 'x', value: 2 }], [{ id: 'x', value: 2 }, { id: 'x', value: 1 }], [{ ['__proto__']: 2, constructor: 1 }]];
  for (const before of arrays) for (const after of arrays) {
    const delta = diffArrayValues(pack(before), pack(after));
    assert.equal(delta.status, 'verified-array-observation-delta');
    const copy = unpack(pack(before));
    let shift = 0;
    for (const edit of delta.edits) {
      const start = edit.beforeStart + shift;
      assert.equal(start, edit.afterStart);
      const removed = copy.splice(start, edit.removed.length, ...unpack({ $array: edit.inserted }));
      assert.deepEqual(pack(removed), { $array: edit.removed });
      shift += edit.inserted.length - edit.removed.length;
    }
    assert.deepEqual(pack(copy), pack(after));
  }
});

test('sequence verification rejects incomplete, overlapping, misplaced and tampered edits', () => {
  const before = pack([1, 2, 3]), after = pack([2, 4]), delta = diffArrayValues(before, after);
  const altered = structuredClone(delta.edits); altered[0].removed = [9];
  const misplaced = structuredClone(delta.edits); misplaced[0].afterStart++;
  for (const edits of [[], delta.edits.slice(1), [...delta.edits, delta.edits[0]], altered, misplaced, [null], [{ beforeStart: 0, afterStart: 0, removed: [], inserted: [] }]]) assert.throws(() => verifyArrayDelta(before, after, edits));
  assert.throws(() => verifyArrayDelta(pack([]), pack([1]), [{ beforeStart: 0, afterStart: 0, removed: [], inserted: ['x'.repeat(1000)] }], { byteLimit: 100 }));
});

test('limits and unsupported values return no partial complete sequence', () => {
  for (const options of [{ maxItems: 1 }, { maxEdits: 0 }, { workLimit: 0 }, { byteLimit: 0 }, { maxItems: 1000000 }, { maxEdits: -1 }]) {
    const delta = diffArrayValues(pack([1, 2]), pack([2, 3]), options);
    assert.equal(delta.status, 'not-generated'); assert.equal(Object.hasOwn(delta, 'edits'), false);
  }
  for (const value of [{ $array: [{ $opaque: 'truthy-object' }] }, { $array: [{ $jsx: {} }] }, { $array: Array(1) }, pack({}), { $array: [1], extra: true }]) assert.equal(diffArrayValues(pack([]), value).status, 'not-generated');
});

test('record deltas treat sequence fields as whole ordered values and still verify field presence', () => {
  const before = pack({ rows: [1, 2], other: null }), after = pack({ rows: [2, 1], newField: undefined, other: null });
  const delta = diffRecordValues(before, after);
  assert.equal(delta.status, 'verified-observation-delta');
  assert.equal(delta.changes.length, 2); assert.deepEqual(delta.changes[1].path, ['rows']);
  assert.deepEqual(delta.changes[1].before, pack([1, 2]));
  assert.equal(diffRecordValues(before, { $record: { rows: { $array: Array(1) } } }).status, 'not-generated');
});

test('Korean comparison lists exact removed/added positions and falls back for long lists', () => {
  const comparison = (before, after) => ({ checked: 1, unchanged: 0, unknown: [], changes: [{ inputs: {}, before: { kind: 'value', value: before }, after: { kind: 'value', value: after } }] });
  const before = pack({ rows: [{ id: 'p' }, { id: 'z' }, { id: 'a' }], stable: 'not printed' });
  const after = pack({ rows: [{ id: 'z' }, { id: 'b' }, { id: 'a' }], stable: 'not printed' });
  const text = describeComparison(comparison(before, after));
  assert.match(text, /결과\["rows"\] 목록 3개 → 3개/);
  assert.match(text, /이전 1번째부터 1개 제외/); assert.match(text, /이후 2번째부터 1개 추가/);
  assert.ok(!text.includes('not printed')); assert.ok(!text.includes('"z"')); assert.ok(!text.includes('"a"'));
  assert.match(text, /이후 관찰값을 복원/);
  const long = pack(Array.from({ length: 257 }, (_, index) => index));
  const fallback = describeComparison(comparison(long, pack([])));
  assert.ok(fallback.includes('256')); assert.ok(!fallback.includes('이후 관찰값을 복원'));
});
