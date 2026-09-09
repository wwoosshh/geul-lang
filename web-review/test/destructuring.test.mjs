import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import ts from 'typescript';
import { liftProject } from '../src/project.mjs';
import { encode, decode, observe, Unsupported } from '../src/core.mjs';
import { renderExecution } from '../src/report.mjs';

const lift = source => liftProject({ files: { 'a.ts': source }, entry: 'a.ts', functionName: 'run', isolation: 'function-body' });
function native(source, args) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { exports }, { timeout: 100 });
  try { return { kind: 'value', value: encode(exports.run(...args.map(value => decode(encode(value))))) }; }
  catch (error) { if (error.name === 'TypeError') return { kind: 'throw', name: 'TypeError' }; throw error; }
}

test('object parameter bindings preserve aliases, eager unused reads and nullish failures', () => {
  const source = 'export function run({ a: first, "b": second, unused }: any) { return first && second; }';
  const artifact = lift(source);
  assert.deepEqual(artifact.inputs, ['인수1']);
  assert.equal(artifact.parameterInputs[0].binding, 'object-pattern');
  for (const first of [false, true, 0, '', null, undefined, 3]) for (const second of [false, true, null, 0, 'yes']) {
    const object = { a: first, b: second };
    assert.deepEqual(observe(artifact.ir, { 인수1: encode(object) }), native(source, [object]));
  }
  for (const value of [null, undefined, {}]) assert.deepEqual(observe(artifact.ir, { 인수1: encode(value) }), native(source, [value]));
  const unused = lift('export function run({ unused }: any) { return true; }');
  assert.deepEqual(observe(unused.ir, { 인수1: null }), { kind: 'throw', name: 'TypeError' });
});

test('const destructuring initializes once and preserves binding order and source traces', () => {
  const source = 'export function run(input: any) { const { a: first, b: second } = input, result = first || second; return result; }';
  const artifact = lift(source);
  for (const value of [null, undefined, {}, { a: false, b: 'b' }, { a: 'a', b: null }]) {
    assert.deepEqual(observe(artifact.ir, { input: encode(value) }), native(source, [value]));
  }
  const traced = observe(artifact.ir, { input: encode({ a: false, b: true }) }, { trace: true });
  const fields = traced.trace.filter(event => event.event === 'bind').map(event => event.name);
  assert.deepEqual(fields, ['input', '구조 분해 입력', 'first', 'second', 'result']);
  assert.ok(artifact.references.some(row => row.name === 'first' && row.definition.line === 1));
  const explanation = renderExecution(artifact, traced);
  assert.match(explanation, /"a" 속성에서 읽은 거짓을 first에 저장했다/);
  assert.match(explanation, /"b" 속성에서 읽은 참을 second에 저장했다/);
});

test('all call arguments run before destructuring a null first argument', () => {
  const files = {
    'helper.ts': 'export function select({ value }: any, ignored: any) { return value; }',
    'a.ts': 'import { select } from "./helper"; export function run(first: any, second: any) { return select(first, second.field); }',
  };
  const artifact = liftProject({ files, entry: 'a.ts', functionName: 'run' });
  const observed = observe(artifact.ir, { first: null, second: { $opaque: 'truthy-object' } });
  // second.field is unknown before the native call can destructure first=null.
  assert.equal(observed.kind, 'unsupported');
  const traced = observe(artifact.ir, { first: null, second: null }, { trace: true });
  assert.equal(traced.kind, 'throw');
  const failure = traced.trace.find(event => event.event === 'throw');
  assert.equal(failure.source.file, '/project/a.ts');
  assert.equal(observe(artifact.ir, { first: encode({ value: 7 }), second: encode({ field: 1 }) }).value, 7);
});

test('generated input names avoid actual parameter names and all bindings remain eager', () => {
  const source = 'export function run({ x }: any, 인수1: any, { y }: any) { return x && 인수1 && y; }';
  const artifact = lift(source);
  assert.deepEqual(artifact.parameterInputs.map(row => row.input), ['인수1_', '인수1', '인수3']);
  assert.equal(observe(artifact.ir, { 인수1_: encode({ x: true }), 인수1: true, 인수3: encode({ y: 'ok' }) }).value, 'ok');
  assert.deepEqual(observe(artifact.ir, { 인수1_: encode({ x: false }), 인수1: true, 인수3: null }), { kind: 'throw', name: 'TypeError' });
});

test('defaults, rest, nesting, computed keys, empty patterns and duplicate bindings fail closed', () => {
  for (const parameter of ['{ x = 1 }', '{ ...rest }', '{ x: { y } }', '{ ["x"]: value }', '{}', '[value]', '{ x: value, y: value }']) {
    assert.throws(() => lift(`export function run(${parameter}: any) { return true; }`), Unsupported, parameter);
    assert.throws(() => lift(`export function run(input: any) { const ${parameter} = input; return true; }`), Unsupported, parameter);
  }
  assert.throws(() => lift('export function run({x}: any) { const x = 1; return x; }'), Unsupported);
  assert.throws(() => lift('export function run(input: any) { const { x } = x; return x; }'), Unsupported);
});
