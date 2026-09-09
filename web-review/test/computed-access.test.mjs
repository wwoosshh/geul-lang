import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { encode, decode, observe, compare } from '../src/core.mjs';
import { liftExpression } from '../src/typescript.mjs';
import { liftProject } from '../src/project.mjs';
import { liftJsxGuards } from '../src/jsx-guards.mjs';
import { renderExecution } from '../src/report.mjs';

const lift = expression => liftExpression(`const result = ${expression};`, expression);
const input = values => Object.fromEntries(Object.entries(values).map(([name, value]) => [name, encode(value)]));
function native(expression, inputs) {
  try { return { kind: 'value', value: encode(new vm.Script(expression).runInNewContext(Object.fromEntries(Object.entries(inputs).map(([name, value]) => [name, decode(value)])), { timeout: 100 })) }; }
  catch (error) { if (error.name === 'TypeError') return { kind: 'throw', name: 'TypeError' }; throw error; }
}

test('computed string keys preserve own records, missing values, Unicode and special property names', () => {
  const record = Object.fromEntries([['', 0], ['계정1', -0], ['__proto__', 17], ['constructor', 'value'], ['toString', false], ['a\nb', undefined]]);
  const expression = 'records[key]', artifact = lift(expression);
  assert.deepEqual(artifact.inputs, ['key', 'records']);
  for (const key of ['', '계정1', '__proto__', 'constructor', 'toString', 'a\nb', 'missing', '0', 'undefined']) {
    for (const records of [record, {}, null, undefined]) {
      const values = input({ records, key });
      assert.deepEqual(observe(artifact.ir, values), native(expression, values));
    }
  }
  for (const key of [0, -0, true, null, undefined, {}, []]) {
    // Arrays are already outside the input codec. No implicit string coercion.
    if (Array.isArray(key)) continue;
    assert.equal(observe(artifact.ir, input({ records: record, key })).kind, 'unsupported');
  }
});

test('optional key reads preserve chain continuation, parentheses and skipped key evaluation', () => {
  for (const expression of ['record?.[key].field', '(record?.[key]).field', 'record[key]?.field', 'record?.[key]?.[other]']) {
    const artifact = lift(expression);
    for (const record of [null, undefined, {}, { item: null }, { item: { field: 7 } }]) {
      const values = input({ record, key: 'item', other: 'field' });
      assert.deepEqual(observe(artifact.ir, values), native(expression, values), expression);
    }
  }
  const expression = 'record?.[keys.name]', artifact = lift(expression);
  const inputs = input({ record: null, keys: null });
  const observed = observe(artifact.ir, inputs, { trace: true });
  assert.deepEqual(observe(artifact.ir, inputs), native(expression, inputs));
  assert.deepEqual(observed.trace.map(row => row.event), ['optional-stop']);
  assert.equal(observed.trace[0].computed, true);
  assert.match(renderExecution(artifact, observed, { inputs, snippets: loc => artifact.source.expression && `const result = ${expression};`.slice(loc.start, loc.end) }), /키 식 keys.name의 계산/);
});

test('base evaluation precedes computed key and a normal null access still evaluates its key expression', () => {
  const baseFirst = observe(lift('root.record[keys.name]').ir, input({ root: null, keys: null }), { trace: true });
  assert.deepEqual(baseFirst.trace.map(row => [row.event, row.key]), [['throw', 'record']]);
  const keyFirst = observe(lift('record[keys.name]').ir, input({ record: null, keys: null }), { trace: true });
  assert.deepEqual(keyFirst.trace.map(row => [row.event, row.key]), [['throw', 'name']]);
  const normal = observe(lift('record[key]').ir, input({ record: null, key: 'chosen' }), { trace: true });
  assert.deepEqual(normal.trace.map(row => row.event), ['access-key', 'throw']);
  const stopped = observe(lift('record?.[key]').ir, input({ record: null, key: {} }));
  assert.deepEqual(stopped, { kind: 'value', value: { $value: 'undefined' } });
  assert.equal(observe(lift('record[key]').ir, input({ record: null, key: {} })).kind, 'unsupported');
});

test('computed input dependencies survive finite comparison, lexical indexing and pure local calls', () => {
  const before = lift('record[key]'), after = lift('record[key] ?? 0');
  const result = compare(before.ir, after.ir, { record: [{ $record: { a: 0 } }], key: ['a', 'b'] });
  assert.equal(result.checked, 2);
  assert.equal(result.changes.length, 1);
  assert.equal(result.changes[0].inputs.key, 'b');
  const source = 'function Screen(records: any, chosen: string) { return records[chosen] && <button/>; }';
  const guarded = liftJsxGuards(source, { tag: 'button' });
  assert.deepEqual(guarded.inputs, ['chosen', 'records']);
  assert.deepEqual(guarded.bindings.inputs.map(row => row.name).sort(), ['chosen', 'records']);
  assert.ok(guarded.bindings.inputs.every(row => row.declarations[0].kind === 'parameter'));
  const project = liftProject({ files: { 'a.ts': 'function key(input: string) { return input; } export function read(records: any, selected: string) { return records[key(selected)]; }' }, entry: 'a.ts', functionName: 'read' });
  assert.deepEqual(project.inputs, ['records', 'selected']);
  assert.equal(observe(project.ir, input({ records: { entry: 4 }, selected: 'entry' })).value, 4);
});

test('computed reads preserve constructed-record prototype and opaque-value limits', () => {
  const project = liftProject({ files: { 'a.ts': 'export function read(key: string) { const record = { own: 3 }; return record[key]; }' }, entry: 'a.ts', functionName: 'read' });
  assert.equal(observe(project.ir, { key: 'own' }).value, 3);
  for (const key of ['missing', '__proto__', 'constructor']) assert.equal(observe(project.ir, { key }).kind, 'unsupported');
  assert.equal(observe(lift('record[key]').ir, { record: { $opaque: 'truthy-object' }, key: 'x' }).kind, 'unsupported');
});
