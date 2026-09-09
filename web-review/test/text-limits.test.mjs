import test from 'node:test';
import assert from 'node:assert/strict';
import { STRING_LIMIT, encode, decode, observe, compare, Unsupported } from '../src/core.mjs';
import { liftConstBindings } from '../src/const-bindings.mjs';
import { liftExpression } from '../src/typescript.mjs';

const lift = expression => liftExpression(`const result = ${expression};`, expression).ir;

test('string codecs and concatenation refuse oversized values before allocating a larger result', () => {
  const oversized = 'x'.repeat(STRING_LIMIT + 1);
  assert.throws(() => encode(oversized), Unsupported);
  assert.throws(() => decode(oversized), Unsupported);
  assert.throws(() => encode({ [oversized]: 1 }), Unsupported);
  assert.throws(() => decode({ $record: { [oversized]: 1 } }), Unsupported);
  const half = 'x'.repeat(STRING_LIMIT / 2 + 1);
  const result = observe(lift('left + right'), { left: half, right: half });
  assert.equal(result.kind, 'unsupported'); assert.match(result.reason, /연결 결과의 길이 제한/);
});

test('small source with repeated string doubling exhausts the work budget instead of building gigabytes', () => {
  const declarations = ['const x0 = seed;'];
  for (let i = 1; i <= 30; i++) declarations.push(`const x${i} = x${i - 1} + x${i - 1};`);
  const artifact = liftConstBindings(declarations.join('\n'), { startLine: 1, endLine: 31, outputs: ['x30'] });
  const result = observe(artifact.ir, { seed: 'x' });
  assert.equal(result.kind, 'unsupported'); assert.match(result.reason, /문자열 처리/);
});

test('scalar string conversion and operations below the work cap retain native values', () => {
  const prefix = 'x'.repeat(20000);
  for (const suffix of [undefined, null, false, true, -0, NaN, Infinity, 4, 'text']) {
    assert.deepEqual(observe(lift('prefix + suffix'), { prefix, suffix: encode(suffix) }), { kind: 'value', value: encode(prefix + suffix) });
  }
  for (const [expression, inputs, expected] of [
    ['+value', { value: ' '.repeat(20000) + '3' }, 3],
    ['left < right', { left: prefix + 'a', right: prefix + 'b' }, true],
    ['left === right', { left: prefix, right: prefix }, true],
  ]) assert.deepEqual(observe(lift(expression), inputs), { kind: 'value', value: expected });
});

test('string processing is charged across revisions and includes trim but not constant-time truthiness', () => {
  const value = 'x'.repeat(40000), ir = lift('value + suffix');
  assert.equal(observe(ir, { value, suffix: '!' }).kind, 'value');
  assert.throws(() => compare(ir, ir, { value: [value], suffix: ['!'] }, { workLimit: 50000 }), /비교 전체의 실행 작업량 제한/);
  const long = ' '.repeat(100001);
  const trim = liftConstBindings('const result = value.trim();', { startLine: 1, endLine: 1, outputs: ['result'] });
  assert.equal(observe(trim.ir, { value: long }).kind, 'unsupported');
  assert.deepEqual(observe(lift('!!value'), { value: long }), { kind: 'value', value: true });
});
