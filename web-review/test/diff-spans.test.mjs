import test from 'node:test';
import assert from 'node:assert/strict';
import { inspectUnifiedPatch, intersectChangedLines } from '../scripts/diff-spans.mjs';

const headers = 'diff --git a/input.ts b/input.ts\nindex aaaaaaa..bbbbbbb 100644\n--- a/input.ts\n+++ b/input.ts\n';

test('unified patch reconstruction verifies multiple ordered hunks and unchanged gaps', () => {
  const before = 'a\nb\nc\nd\ne\n', after = 'a\nB\nc\nd\nextra\ne\n';
  const patch = headers + '@@ -2 +2 @@\n-b\n+B\n@@ -4,0 +5 @@\n+extra\n';
  const result = inspectUnifiedPatch(patch, before, after);
  assert.deepEqual(result.removed.map(row => row.line), [2]);
  assert.deepEqual(result.added.map(row => row.line), [2, 5]);
  assert.equal(result.hunks.length, 2); assert.equal(result.reconstructed, true);
  const selected = intersectChangedLines(result.added, [{ start: 8, end: 13 }], after);
  assert.deepEqual(selected.map(row => row.relation), ['line-outside-selected-source', 'line-intersects-selected-source']);
});

test('empty files, omitted counts, context lines, Unicode and CRLF keep exact source offsets', () => {
  const added = inspectUnifiedPatch(headers + '@@ -0,0 +1 @@\n+🙂글\n', '', '🙂글\n');
  assert.deepEqual(added.added, [{ line: 1, start: 0, end: 4 }]);
  const deleted = inspectUnifiedPatch(headers + '@@ -1 +0,0 @@\n-🙂글\n', '🙂글\n', '');
  assert.deepEqual(deleted.removed, added.added);
  const before = 'one\r\ntwo\r\n', after = 'one\r\nTWO\r\n';
  const result = inspectUnifiedPatch(headers + '@@ -1,2 +1,2 @@\n one\r\n-two\r\n+TWO\r\n', before, after);
  assert.deepEqual(result.added, [{ line: 2, start: 5, end: 10 }]);
  assert.equal(inspectUnifiedPatch('', before, before).hunks.length, 0);
});

test('EOF newline changes are verified rather than lost by splitting lines', () => {
  const marker = '\\ No newline at end of file\n';
  const patch = headers + '@@ -1 +1 @@\n-same\n' + marker + '+same\n';
  assert.equal(inspectUnifiedPatch(patch, 'same', 'same\n').reconstructed, true);
  assert.throws(() => inspectUnifiedPatch(headers + '@@ -1 +1 @@\n-same\n+same\n', 'same', 'same\n'));
  assert.throws(() => inspectUnifiedPatch(patch, 'same\n', 'same\n'));
  assert.throws(() => inspectUnifiedPatch('', 'same', 'same\n'));
  assert.equal(inspectUnifiedPatch(headers + '@@ -1 +1 @@\n-old\n' + marker + '+new\n' + marker, 'old', 'new').reconstructed, true);
});

test('a large unchanged prefix does not exceed the JavaScript argument limit', () => {
  const prefix = 'a\n'.repeat(140000);
  const result = inspectUnifiedPatch(headers + '@@ -140001 +140001 @@\n-b\n+c\n', prefix + 'b\n', prefix + 'c\n');
  assert.equal(result.added[0].start, 280000);
  assert.equal(result.added[0].line, 140001);
});

test('missing hunks, bad counts, wrong content, duplicated lines and unbound spans are refused', () => {
  const patch = headers + '@@ -2 +2 @@\n-b\n+B\n';
  for (const bad of [patch.replace('-b', '-x'), patch.replace('-2 +2', '-2,2 +2'), patch.slice(0, -1), patch + 'garbage\n', patch + '@@ -2 +2 @@\n-b\n+B\n']) {
    assert.throws(() => inspectUnifiedPatch(bad, 'a\nb\n', 'a\nB\n'));
  }
  assert.throws(() => inspectUnifiedPatch(patch, 'a\nb\nc\n', 'a\nB\nC\n'));
  assert.throws(() => inspectUnifiedPatch('diff --git a/x b/x\nBinary files a/x and b/x differ\n', 'a', 'b'));
  assert.throws(() => inspectUnifiedPatch(patch + headers, 'a\nb\n', 'a\nB\n'));
  const result = inspectUnifiedPatch(patch, 'a\nb\n', 'a\nB\n');
  assert.throws(() => intersectChangedLines(result.added, [{ start: 0, end: 10 }], 'a\nB\n'));
  assert.throws(() => intersectChangedLines([...result.added, ...result.added], [], 'a\nB\n'));
});
