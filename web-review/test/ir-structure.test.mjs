import test from 'node:test';
import assert from 'node:assert/strict';
import { compareIRStructure } from '../src/ir-structure.mjs';
import { liftConstBindings } from '../src/const-bindings.mjs';
import { liftExpression } from '../src/typescript.mjs';
import { ARRAY_PROFILE, observe } from '../src/core.mjs';
import { renderIRStructure } from '../src/report.mjs';

const expression = text => liftExpression(`const result = ${text};`, text).ir;
const bindings = (text, outputs = ['result']) => liftConstBindings(text, { filename: '/original.ts', startLine: 1, endLine: text.split('\n').length, outputs, arrayProfile: ARRAY_PROFILE }).ir;

test('a changed selection condition is separate from unchanged branch structure despite callback offsets', () => {
  const before = bindings('const result = !searching ? preview.concat(rows.filter(t => !t.child)) : rows;');
  const after = bindings('const result = !searching && !filtered ? preview.concat(rows.filter(item => !item.child)) : rows;');
  const comparison = compareIRStructure(before, after);
  assert.equal(comparison.status, 'ir-structural-comparison');
  assert.equal(comparison.sameStructure, false);
  assert.equal(comparison.changes.length, 1);
  assert.equal(comparison.changes[0].kind, 'condition-changed');
  assert.equal(comparison.changes[0].before.path, '$.value.condition');
  assert.equal(comparison.changes[0].sameBranchStructure, true);
  assert.deepEqual(comparison.changes[0].branches.map(row => row.branch), ['yes', 'no']);
  const text = renderIRStructure(comparison, {}, {}, { beforeSnippets: () => '!searching', afterSnippets: () => '!searching && !filtered' });
  assert.match(text, /두 결과 갈래의 IR 구조는 유지/);
  assert.match(text, /앞선 계산값이 달라지면 다른 결과/);
  assert.match(text, /!searching &amp;&amp; !filtered/);
});

test('alpha renaming preserves lexical binding but input changes and shadowing do not disappear', () => {
  const a = bindings('const source = input;\nconst result = source;');
  const b = bindings('const renamed = input;\nconst result = renamed;');
  assert.equal(compareIRStructure(a, b).sameStructure, true);
  assert.equal(compareIRStructure(a, bindings('const renamed = other;\nconst result = renamed;')).sameStructure, false);
  const nested = expression('input');
  const wrap = name => ({ kind: 'let', name, value: nested, body: { kind: 'let', name: 'inner', value: { kind: 'literal', value: 1 }, body: { kind: 'local', name } } });
  const outer = wrap('outer'), inner = structuredClone(outer);
  inner.body.body.name = 'inner';
  assert.equal(compareIRStructure(outer, inner).sameStructure, false);
  assert.equal(compareIRStructure(wrap('outer'), wrap('renamed')).sameStructure, true);
});

test('same branch structure does not imply the same branch value after a preceding binding changes', () => {
  const before = bindings('const value = 1;\nconst result = flag ? value : 0;');
  const after = bindings('const value = 2;\nconst result = other ? value : 0;');
  const comparison = compareIRStructure(before, after);
  assert.equal(comparison.changes.length, 2);
  assert.equal(comparison.changes[0].kind, 'structure-replaced');
  assert.equal(comparison.changes[1].kind, 'condition-changed');
  assert.notDeepEqual(observe(before, { flag: true }), observe(after, { other: true }));
  assert.match(comparison.scope, /같은 갈래 구조가 같은 결과값/);
});

test('evaluation order, projection, profile, optional access and literal data are significant', () => {
  for (const [a, b] of [['a && b', 'b && a'], ['a ?? b', 'a || b'], ['x.value', 'x?.value'], ['"source"', '"definition"']]) {
    assert.equal(compareIRStructure(expression(a), expression(b)).sameStructure, false);
  }
  const record = bindings('const result = { ...data, amount: 0 };');
  const reordered = bindings('const result = { amount: 0, ...data };');
  assert.equal(compareIRStructure(record, reordered).sameStructure, false);
  const projected = structuredClone(record);
  projected.body.projection = 'jsx-property-values';
  assert.equal(compareIRStructure(record, projected).sameStructure, false);
  const profile = structuredClone(record); delete profile.valueProfile;
  assert.equal(compareIRStructure(record, profile).sameStructure, false);
  const literal = { kind: 'literal', value: { $record: { source: 'a', name: 'b' } } };
  const altered = structuredClone(literal); altered.value.$record.source = 'changed';
  assert.equal(compareIRStructure(literal, altered).sameStructure, false);
});

test('metadata is ignored only at known positions and no partial changes are reported on refusal', () => {
  const a = expression('x ? y : z'), b = structuredClone(a);
  b.source = { file: '/another.ts', start: 0, end: 1, line: 1, column: 1 };
  assert.equal(compareIRStructure(a, b).sameStructure, true);
  b.futureEffect = 'do not ignore';
  assert.equal(compareIRStructure(a, b).status, 'not-generated');
  assert.equal(compareIRStructure(a, { kind: 'future-operation' }).status, 'not-generated');
  for (const options of [{ nodeLimit: 1 }, { textLimit: 1 }, { changeLimit: 0 }, { nodeLimit: Infinity }]) {
    const comparison = compareIRStructure(a, expression('p ? q : r'), options);
    assert.equal(comparison.status, 'not-generated');
    assert.equal(Object.hasOwn(comparison, 'changes'), false);
  }
  const limited = compareIRStructure(expression('a + b'), expression('c + d'), { changeLimit: 1 });
  assert.equal(limited.status, 'not-generated');
});
