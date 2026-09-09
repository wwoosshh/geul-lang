import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import ts from 'typescript';
import { encode, decode, observe, compare, Unsupported } from '../src/core.mjs';
import { liftExpression } from '../src/typescript.mjs';

const lift = expr => liftExpression(`const result = ${expr};`, expr).ir;
const input = values => Object.fromEntries(Object.entries(values).map(([k, v]) => [k, encode(v)]));
function native(expr, encodedInputs) {
  const context = Object.fromEntries(Object.entries(encodedInputs).map(([k, v]) => [k, decode(v)]));
  // Only explicit test expressions are executed. The analyzer never runs an
  // upstream file, its module initializers or imported dependencies.
  const javascript = ts.transpileModule(`(${expr})`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  try { return { kind: 'value', value: encode(vm.runInNewContext(javascript, context, { timeout: 100 })) }; }
  catch (error) { if (error.name === 'TypeError') return { kind: 'throw', name: 'TypeError' }; throw error; }
}
test('encoded values preserve undefined, NaN, infinity, negative zero and missing properties', () => {
  for (const value of [undefined, null, NaN, Infinity, -Infinity, -0, 0, false, '']) assert.ok(Object.is(decode(encode(value)), value));
  const value = decode({ $record: { '__proto__': null, constructor: false, x: { $value: 'undefined' } } });
  assert.equal(Object.getPrototypeOf(value), null);
  assert.ok(Object.hasOwn(value, 'x'));
  assert.throws(() => encode({ get x() { throw Error('must not run'); } }), Unsupported);
  for (const bad of [[], { $value: 'unknown' }, { $record: [] }, { $record: null }, { x: 1 }, Infinity]) assert.throws(() => decode(bad), Unsupported);
});
test('short circuit preserves operands and suppresses errors on the unvisited side', () => {
  assert.deepEqual(observe(lift('x && y.a'), input({ x: 0, y: null })), { kind: 'value', value: 0 });
  assert.deepEqual(observe(lift('x || y.a'), input({ x: 'yes', y: null })), { kind: 'value', value: 'yes' });
  assert.deepEqual(observe(lift('x ?? y.a'), input({ x: false, y: null })), { kind: 'value', value: false });
  assert.deepEqual(observe(lift('x && y.a'), input({ x: true, y: null })), { kind: 'throw', name: 'TypeError' });
  const skipped = observe(lift('x && y.a'), input({ x: 0, y: null }), { trace: true });
  assert.equal(skipped.value, 0);
  assert.deepEqual(skipped.trace.map(t => t.event), ['short-circuit']);
  assert.equal(skipped.trace[0].evaluatedRight, false);
  const failed = observe(lift('x && y.a'), input({ x: true, y: null }), { trace: true });
  assert.equal(failed.kind, 'throw');
  assert.equal(failed.trace.at(-1).event, 'throw');
});
test('optional chain continuation and parenthesis boundary differ', () => {
  for (const expr of ['x?.a.b', 'x?.a?.b', '(x?.a).b', 'x.a?.b', "x?.['a'].b"]) {
    for (const x of [null, undefined, {}, { a: null }, { a: { b: false } }]) {
      assert.deepEqual(observe(lift(expr), input({ x })), native(expr, input({ x })), expr);
    }
  }
  assert.throws(() => lift('x?.a!.b'), Unsupported);
});
test('scalar operator differential against native JS, including non-Boolean operands', () => {
  const values = [undefined, null, false, true, '', '0', '1', 'text', -0, 0, 1, -1, NaN, Infinity, -Infinity];
  const ops = ['===', '!==', '&&', '||', '??', '<', '<=', '>', '>=', '+', '-', '*', '/', '%'];
  let checked = 0;
  for (const op of ops) {
    const expression = `x ${op} y`, ir = lift(expression);
    // Compile once, use a fresh restricted context for each pair.
    const script = new vm.Script(expression);
    for (const x of values) for (const y of values) {
      const encoded = input({ x, y });
      const actual = script.runInNewContext({ x, y }, { timeout: 100 });
      assert.deepEqual(observe(ir, encoded), { kind: 'value', value: encode(actual) }, `${expression}: ${JSON.stringify(encoded)}`);
      checked++;
    }
  }
  assert.equal(checked, 3150);
});
test('unary operators, conditional, assertions and nullish equality preserve JS values', () => {
  for (const expr of ['!x', '!!x', '+x', '-x', 'typeof x', 'x == null', 'x != null', 'x ? 1 : 2', '(x as boolean)', 'x!', '(x satisfies unknown)']) {
    for (const x of [undefined, null, false, true, '', '12', 'bad', -0, 1, NaN, Infinity]) {
      assert.deepEqual(observe(lift(expr), input({ x })), native(expr, input({ x })), expr);
    }
  }
});
test('ambiguous, effectful and unsupported source is rejected', () => {
  for (const expr of ['f(x)', 'x++', 'x = y', 'x[key()]', 'new X()', 'x == y', 'x != y', '[x]', '{x: 1}', 'x & y', '() => x', 'x?.f()', '1n']) {
    assert.throws(() => lift(expr), Unsupported, expr);
  }
  assert.throws(() => liftExpression('const x = y; const z = y;', 'y'), /2곳/);
  assert.throws(() => liftExpression('const x = ;', 'x'), Unsupported);
  assert.throws(() => liftExpression('class A { #x = 1; f(other: A) { return other.#x; } }', 'other.#x'), Unsupported);
  assert.equal(observe(lift('x'), {}).kind, 'unsupported');
  for (const invalid of [null, undefined, [], false, 1, '']) assert.equal(observe(lift('true'), invalid).kind, 'unsupported');
  assert.equal(observe(lift('x === y'), input({ x: {}, y: {} })).kind, 'unsupported');
  assert.equal(observe(lift('x.a'), input({ x: 'str' })).kind, 'unsupported');
  assert.deepEqual(observe(lift('x === null'), input({ x: {} })), { kind: 'value', value: false });
  assert.deepEqual(observe(lift('x !== null'), input({ x: {} })), { kind: 'value', value: true });
});
test('domain comparison reports changed cases and never generalizes finite enumeration', () => {
  const before = lift('!webKit && !!enabled'), after = lift('!webKit && enabled !== false');
  const result = compare(before, after, { webKit: [false, true], enabled: [{ $value: 'undefined' }, false, true] });
  assert.equal(result.status, 'different-in-declared-domain');
  assert.equal(result.checked, 6);
  assert.equal(result.changes.length, 1);
  assert.deepEqual(result.changes[0].inputs, { enabled: { $value: 'undefined' }, webKit: false });
  assert.equal(compare(before, before, { webKit: [false], enabled: [false] }).status, 'equal-in-declared-domain');
  assert.throws(() => compare(before, after, { webKit: [false] }), Unsupported);
  assert.throws(() => compare(lift('x'), lift('x'), { x: [] }), Unsupported);
  assert.throws(() => compare(lift('x'), lift('x'), { x: [1, 2] }, { limit: 1 }), Unsupported);
  assert.throws(() => compare(lift('x'), lift('x'), { x: [true] }, { workLimit: 1 }), Unsupported);
  assert.throws(() => compare(lift('x'), lift('x'), { x: ['large'] }, { inputByteLimit: 1 }), Unsupported);
  const partial = compare(lift('x.a'), lift('x.a'), { x: [1, { $record: { a: true } }] });
  assert.equal(partial.status, 'inconclusive');
  assert.equal(partial.unknown.length, 1);
  for (const options of [{ workLimit: NaN }, { workLimit: Infinity }, { workLimit: -1 }, { limit: 0 }, { limit: 65537 }, { workLimit: 8000001 }, { inputByteLimit: '100' }]) assert.throws(() => compare(lift('x'), lift('x'), { x: [true] }, options), Unsupported);
  for (const domains of [null, [], false]) assert.throws(() => compare(lift('x'), lift('x'), domains), Unsupported);
});
test('source slice has spans, raw source digest and no implicit binding resolution', () => {
  const result = liftExpression('const enabled = false;\nconst value = enabled !== false;', 'enabled !== false', 'sample.ts');
  assert.equal(result.source.line, 2);
  assert.equal(result.source.sha256.length, 64);
  assert.deepEqual(result.inputs, ['enabled']);
  assert.equal(result.mode, 'expression-slice');
});
