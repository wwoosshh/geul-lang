import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { liftRecord } from '../src/record-slice.mjs';
import { liftProject } from '../src/project.mjs';
import { observe, encode, decode, evaluate, Unsupported } from '../src/core.mjs';
import { renderExecution } from '../src/report.mjs';

const lift = expression => liftRecord(`const result = ${expression};`, { line: 1 });
const ownTree = value => value !== null && typeof value === 'object'
  ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, ownTree(item)])) : value;
function native(expression, inputs) {
  try {
    const result = new vm.Script(`(${expression})`).runInNewContext(Object.fromEntries(Object.entries(inputs).map(([name, value]) => [name, decode(value)])), { timeout: 100 });
    return { kind: 'value', value: encode(ownTree(result)) };
  } catch (error) {
    if (error.name !== 'TypeError') throw error;
    return { kind: 'throw', name: 'TypeError' };
  }
}

test('spread and shorthand retain missing, present undefined, zero and overwrite order', () => {
  const cases = ['{ ...draft, date: date }', '{ date: date, ...draft }', '{ ...draft, amount }', '{ amount: 1, ...draft, amount: amount }'];
  const drafts = [{}, { amount: undefined }, { amount: 0 }, { amount: -0 }, { date: 'old', amount: NaN }, { amount: Infinity }];
  for (const expression of cases) for (const draft of drafts) for (const amount of [undefined, 0, -0, 9]) {
    const inputs = { draft: encode(draft), amount: encode(amount), date: 'new' };
    assert.deepEqual(observe(lift(expression).ir, inputs), native(expression, inputs));
  }
  const artifact = lift('{ ...draft, date: date }');
  assert.deepEqual(observe(artifact.ir, { draft: encode({}), date: 'new' }).value, encode({ date: 'new' }));
  assert.deepEqual(observe(artifact.ir, { draft: encode({ amount: undefined }), date: 'new' }).value, encode({ date: 'new', amount: undefined }));
});

test('nullish and scalar empty spreads do not throw, while unsupported objects do not become empty', () => {
  const artifact = lift('{ ...input, present: true }');
  for (const value of [undefined, null, false, true, 0, -0, NaN, Infinity]) {
    const inputs = { input: encode(value) };
    assert.deepEqual(observe(artifact.ir, inputs), native('{ ...input, present: true }', inputs));
  }
  for (const input of ['', 'abc', { $opaque: 'truthy-object' }]) assert.equal(observe(artifact.ir, { input }).kind, 'unsupported');
  const jsx = liftProject({ files: { 'a.tsx': 'export function f() { return { ...<div /> }; }' }, entry: 'a.tsx', functionName: 'f' });
  assert.equal(observe(jsx.ir, {}).kind, 'unsupported');
});

test('a copied __proto__ field and shorthand __proto__ are data; prototype setter syntax is refused', () => {
  const input = { $record: { ['__proto__']: { $record: { polluted: true } }, constructor: 3 } };
  for (const expression of ['{ ...input }', '{ __proto__ }']) {
    const artifact = lift(expression), inputs = { input, __proto__: null };
    Object.defineProperty(inputs, '__proto__', { value: encode({ x: 1 }), enumerable: true });
    assert.deepEqual(observe(artifact.ir, inputs), native(expression, inputs));
  }
  assert.equal({}.polluted, undefined);
  for (const expression of ['{ __proto__: null }', '{ "__proto__": input }', '{ [name]: 1 }', '{ get x() { return 1; } }']) assert.throws(() => lift(expression), Unsupported);
});

test('all earlier property calculations run even if their values will be overwritten', () => {
  for (const expression of ['{ x: broken.value, x: 3 }', '{ ...broken.value, ...draft }', '{ ...draft, date: broken.value }']) {
    const inputs = { broken: null, draft: encode({ amount: 0 }) };
    assert.deepEqual(observe(lift(expression).ir, inputs), native(expression, inputs));
  }
  const expression = '{ ...draft, amount: amount }', artifact = lift(expression);
  const inputs = { draft: encode({ amount: 0 }), amount: 7 }, observed = observe(artifact.ir, inputs, { trace: true });
  assert.deepEqual(observed.trace.map(row => row.event), ['record-spread', 'record-copy-field', 'record-field', 'record-overwrite']);
  const report = renderExecution(artifact, observed, { inputs });
  assert.match(report, /없는 속성을 만들거나 기본값을 채우지 않는다/);
  assert.match(report, /덮어썼다/);
});

test('spread is shallow and does not erase a constructed nested object prototype boundary', () => {
  const project = source => liftProject({ files: { 'a.ts': source }, entry: 'a.ts', functionName: 'f' });
  const nested = project('export function f() { const original = { nested: { present: 1 } }; const copy = { ...original }; return copy.nested.missing; }');
  assert.equal(observe(nested.ir, {}).kind, 'unsupported');
  const present = project('export function f(input: any) { const copy = { ...input }; return copy.nested.present; }');
  assert.deepEqual(observe(present.ir, { input: encode({ nested: { present: 5 } }) }), { kind: 'value', value: 5 });
  const copied = project('export function f() { const original = { present: 1 }; return { ...original }; }');
  assert.deepEqual(observe(copied.ir, {}).value, encode({ present: 1 }));
});

test('record selection is source-bound, scopes undefined and distinguishes same-line literals', () => {
  const source = 'function f(undefined: number) {\n const x = { ...draft, value: undefined };\n return x;\n}';
  const artifact = liftRecord(source, { line: 2, filename: '/tmp/test.ts' });
  assert.deepEqual(artifact.inputs, ['draft', 'undefined']);
  assert.deepEqual(artifact.bindings.inputs.find(row => row.name === 'undefined').declarations.map(row => row.kind), ['parameter']);
  assert.equal(artifact.context.reachabilityProven, false);
  assert.deepEqual(lift('{ value: undefined }').inputs, []);
  assert.throws(() => liftRecord('const x = { a: {} };', { line: 1 }), Unsupported);
  assert.deepEqual(liftRecord('const x = { a: {} };', { line: 1, column: 16 }).inputs, []);
  for (const opts of [{ line: 0 }, { line: 2 }, { line: 1, column: 0 }]) assert.throws(() => liftRecord('const x = {};', opts), Unsupported);
  assert.throws(() => lift('{ ...external() }'), Unsupported);
});

test('copy work and trace sizes stay bounded without dropping repeated copies', () => {
  const artifact = lift('{ ...input, ...input }'), input = Object.fromEntries(Array.from({ length: 600 }, (_, i) => ['key' + i, i]));
  assert.throws(() => evaluate(artifact.ir, { input: Object.assign(Object.create(null), input) }, { steps: 20 }), /복사 단계 제한/);
  const result = observe(artifact.ir, { input: encode(input) }, { trace: true });
  assert.equal(result.kind, 'value');
  assert.equal(result.trace.length, 512);
  assert.equal(result.traceTruncated, true);
});

test('the input codec refuses to turn a non-enumerable field into an enumerable spread field', () => {
  const source = Object.create(null);
  Object.defineProperty(source, 'hidden', { value: 7, enumerable: false });
  assert.deepEqual({ ...source }, {});
  assert.throws(() => encode(source), /열거 불가능/);
});
