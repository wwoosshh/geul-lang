import test from 'node:test';
import assert from 'node:assert/strict';
import { discoverChange, renderChangeDiscovery } from '../src/change-discovery.mjs';
import { Unsupported } from '../src/core.mjs';

const headers = 'diff --git a/input.tsx b/input.tsx\n--- a/input.tsx\n+++ b/input.tsx\n';
function replaced(before, after, oldLine, newLine = oldLine) {
  return headers + `@@ -${oldLine} +${newLine} @@\n-${before.split('\n')[oldLine - 1]}\n+${after.split('\n')[newLine - 1]}\n`;
}
const entry = side => side.candidates.find(row => row.kind === 'call-entry');
const args = side => side.candidates.find(row => row.kind === 'call-arguments');

test('a changed prefix is connected even when the final call line did not change', () => {
  const before = 'function f(){\nconst clean = input.trim();\nif(!clean)return;\nsave(clean);\n}\n';
  const after = before.replace('if(!clean)', 'if(clean === "a")');
  const report = discoverChange(before, after, replaced(before, after, 3));
  assert.equal(report.patch.reconstructed, true); assert.equal(report.patch.gitIdentityVerified, false);
  for (const side of [report.before, report.after]) {
    assert.deepEqual(entry(side).sourceChange.anchorLines, []);
    assert.deepEqual(entry(side).sourceChange.selectionLines, [3]);
    assert.deepEqual(entry(side).sourceChange.analyzedLines, [3]);
    assert.deepEqual(entry(side).analyzedSources.map(row => row.role), ['call-prefix']);
    assert.deepEqual(args(side).analyzedSources.map(row => row.role), ['call-prefix', 'argument1']);
    assert.equal(entry(side).sourceChange.behaviorImpact, 'not-evaluated');
  }
  assert.equal(report.nativeExecutions, 0); assert.equal(report.semanticCoverage, null);
  assert.equal(Object.hasOwn(report, 'changes'), false);
  assert.match(renderChangeDiscovery(report), /실행 결과의 비교가 아닙니다/);
});

test('changed arguments are outside the call entry computation and inside argument preparation', () => {
  const before = 'function f(){\nsave(input.field);\n}\n', after = before.replace('input.field', 'input.other');
  const report = discoverChange(before, after, replaced(before, after, 2));
  for (const side of [report.before, report.after]) {
    assert.deepEqual(entry(side).sourceChange.anchorLines, [2]);
    assert.deepEqual(entry(side).analyzedSources, []);
    assert.deepEqual(entry(side).sourceChange.analyzedLines, []);
    assert.deepEqual(args(side).sourceChange.analyzedLines, [2]);
    assert.equal(args(side).analyzedSources.length, 1);
  }
});

test('trailing comments and indentation before a call do not extend the preceding computation onto the call line', () => {
  for (const gap of ['', '  // gap after the prefix\n']) {
    const before = `function f(){\n  const clean = input.trim();\n${gap}  save(clean);\n}\n`;
    const after = before.replace('save(clean)', 'save(clean.toLowerCase())'), line = gap ? 4 : 3;
    const report = discoverChange(before, after, replaced(before, after, line));
    for (const side of [report.before, report.after]) {
      assert.deepEqual(entry(side).sourceChange.anchorLines, [line]);
      assert.deepEqual(entry(side).sourceChange.analyzedLines, []);
      assert.deepEqual(args(side).sourceChange.analyzedLines, [line]);
    }
    if (gap) {
      const commentAfter = before.replace('gap after the prefix', 'changed gap');
      const comment = discoverChange(before, commentAfter, replaced(before, commentAfter, 3));
      assert.deepEqual(entry(comment.after).sourceChange.analyzedLines, []);
      assert.deepEqual(entry(comment.after).sourceChange.selectionLines, [3]);
    }
  }
});

test('a JSX spread on another line changes selection context and leaves the refused computation unknown', () => {
  const before = '<button\ndisabled={ready}\n/>;\n', after = '<button\ndisabled={ready}\n{...rest}\n/>;\n';
  const patch = headers + '@@ -2,0 +3 @@\n+{...rest}\n';
  const report = discoverChange(before, after, patch);
  assert.equal(report.before.candidates[0].status, 'lowered');
  const row = report.after.candidates[0]; assert.equal(row.status, 'refused');
  assert.deepEqual(row.sourceChange.anchorLines, []); assert.deepEqual(row.sourceChange.selectionLines, [3]);
  assert.equal(row.sourceChange.analyzedLines, null);
  assert.equal(Object.hasOwn(row, 'analyzedSources'), false);
});

test('same-line comments and unsupported prefixes never become a claim of behavioral change or equivalence', () => {
  const before = 'const value = input; // old\n', after = 'const value = input; // new\n';
  const report = discoverChange(before, after, replaced(before, after, 1));
  assert.deepEqual(report.after.candidates[0].sourceChange.analyzedLines, [1]);
  assert.equal(report.after.candidates[0].sourceChange.behaviorImpact, 'not-evaluated');
  const oldBody = 'function f(){\ndoWork();\nsave();\n}\n', newBody = oldBody.replace('doWork()', 'otherWork()');
  const unsupported = discoverChange(oldBody, newBody, replaced(oldBody, newBody, 2));
  assert.equal(entry(unsupported.after).status, 'refused');
  assert.deepEqual(entry(unsupported.after).sourceChange.selectionLines, [2]);
  assert.equal(entry(unsupported.after).sourceChange.analyzedLines, null);
});

test('each revision retains its own page boundary and validates the exact supplied patch', () => {
  const before = 'const a = 1;\n', after = before + 'const b = 2;\n';
  const patch = headers + '@@ -1,0 +2 @@\n+const b = 2;\n';
  const report = discoverChange(before, after, patch, { limit: 1 });
  assert.equal(report.before.nextOffset, null); assert.equal(report.after.nextOffset, 1);
  assert.equal(report.after.candidates[1].status, 'not-checked');
  assert.deepEqual(report.after.candidates[1].sourceChange.anchorLines, [2]);
  assert.equal(report.after.candidates[1].sourceChange.analyzedLines, null);
  const next = discoverChange(before, after, patch, { limit: 1, beforeOffset: 1, afterOffset: 1 });
  assert.equal(next.before.counts.checked, 0); assert.equal(next.after.candidates[1].status, 'lowered');
  for (const args of [[before, 'const b = 9;\n', patch], [before, after, ''], [before, after, patch + headers]]) assert.throws(() => discoverChange(...args), Unsupported);
  const equal = discoverChange(before, before, ''); assert.deepEqual(equal.before.changedLines, []);
});

test('source overlap expansion is bounded even when many unchecked attributes share one large element', () => {
  const oldProps = Array.from({ length: 300 }, (_, i) => `p${i}={0}`), newProps = oldProps.map(text => text.replace('{0}', '{1}'));
  const before = ['<Box', ...oldProps, '/>;', ''].join('\n'), after = ['<Box', ...newProps, '/>;', ''].join('\n');
  const patch = headers + '@@ -1,302 +1,302 @@\n <Box\n' + oldProps.map(text => '-' + text + '\n').join('') + newProps.map(text => '+' + text + '\n').join('') + ' />;\n';
  assert.throws(() => discoverChange(before, after, patch, { limit: 1 }), /연결 제한/);
});

test('changed-line focus spends the check limit on intersecting selection contexts and leaves other computations unknown', () => {
  const before = 'const outside = 0;\nfunction f(){\nconst clean = input.trim();\nif(!clean)return;\nsave(clean);\n}\n';
  const after = before.replace('if(!clean)', 'if(clean === "a")'), patch = replaced(before, after, 4);
  const report = discoverChange(before, after, patch, { focus: 'changed-lines', limit: 1 });
  assert.equal(report.focus, 'changed-lines');
  for (const side of [report.before, report.after]) {
    assert.equal(side.counts.checked, 1); assert.equal(entry(side).status, 'lowered');
    assert.deepEqual(entry(side).sourceChange.anchorLines, []); assert.deepEqual(entry(side).sourceChange.analyzedLines, [4]);
    assert.equal(side.candidates[0].status, 'not-checked'); assert.equal(side.candidates[0].sourceChange.analyzedLines, null);
    assert.equal(side.nextOffset, args(side).id); assert.equal(side.counts.outsideFocus, 2);
  }
  const empty = discoverChange(before, before, '', { focus: 'changed-lines' });
  assert.equal(empty.before.counts.checked, 0); assert.equal(empty.before.nextOffset, null);
  assert.throws(() => discoverChange(before, after, patch, { focus: 'changed-behavior' }), Unsupported);
  assert.match(renderChangeDiscovery(report), /간접 의존성/);
  const jsxBefore = '<button\ndisabled={ready}\n/>;\n', jsxAfter = '<button\ndisabled={ready}\n{...rest}\n/>;\n';
  const jsx = discoverChange(jsxBefore, jsxAfter, headers + '@@ -2,0 +3 @@\n+{...rest}\n', { focus: 'changed-lines' });
  assert.equal(jsx.after.candidates[0].inFocus, true); assert.equal(jsx.after.candidates[0].status, 'refused');
  assert.equal(jsx.before.candidates[0].status, 'not-checked');
});
