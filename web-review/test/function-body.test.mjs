import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import ts from 'typescript';
import { liftProject } from '../src/project.mjs';
import { observe, encode, decode, Unsupported } from '../src/core.mjs';

function lift(source, name = 'normalize') { return liftProject({ files: { 'original.tsx': source }, entry: 'original.tsx', functionName: name, isolation: 'function-body' }); }
const body = `export function normalize(settings: {date?: string, amount?: number} | undefined) {
  return { date: settings?.date && settings.date.trim() !== '' ? settings.date : undefined,
    balance: settings?.amount != null ? settings.amount : undefined };
}`;
test('original function body is isolated without executing its surrounding module', () => {
  const source = 'import { unknown } from "external"; sideEffect(); const captured = false;\n' + body;
  const a = lift(source);
  assert.equal(a.mode, 'function-body-slice');
  assert.equal(a.sources[0].sha256.length, 64);
  assert.equal(a.dependencies[0].source.line, 2);
  assert.ok(a.contract.notProven.includes('원본 모듈 초기화·주변 코드의 실행'));
  assert.throws(() => liftProject({ files: { 'original.tsx': source }, entry: 'original.tsx', functionName: 'normalize' }), Unsupported);
});
test('object fields, undefined and standard trim match native function results', () => {
  const a = lift(body), exports = {};
  vm.runInNewContext(ts.transpileModule(body, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { exports }, { timeout: 100 });
  let cases = 0;
  for (const date of [undefined, null, '', ' ', '\n\t', '\u00a0', '  2026-09-09  ', 'date']) {
    for (const amount of [undefined, null, 0, -0, 1, NaN]) {
      const settings = encode({ date, amount });
      const actual = exports.normalize(decode(settings));
      // The declared return observation is own data fields. Copying those
      // fields crosses the VM realm without pretending to preserve prototype.
      assert.deepEqual(observe(a.ir, { settings }), { kind: 'value', value: encode(Object.fromEntries(Object.entries(actual))) });
      cases++;
    }
  }
  assert.equal(cases, 48);
  assert.deepEqual(observe(a.ir, { settings: { $value: 'undefined' } }).value, { $record: { balance: { $value: 'undefined' }, date: { $value: 'undefined' } } });
});
test('free captures and helper bindings remain unsupported in an isolated body', () => {
  for (const source of [
    'const captured = false; export function normalize() { return captured; }',
    'function helper() { return false; } export function normalize() { return helper(); }',
    'export function normalize() { return normalize(); }',
    'const undefined = 1; export function normalize() { return undefined; }',
    'import { undefined } from "external"; export function normalize() { return undefined; }',
    'export function normalize(x: any) { return x?.trim(); }',
    'export function normalize(x: any) { return x.trim(1); }',
  ]) assert.throws(() => lift(source), Unsupported, source);
  const shadow = lift('export function normalize(undefined: any) { return undefined; }');
  assert.equal(observe(shadow.ir, { undefined: 3 }).value, 3);
});
test('object access preserves explicit fields and exposes unknown prototype reads', () => {
  const source = 'export function normalize(x: any) { const result = { value: x }; return result.value; }';
  assert.equal(observe(lift(source).ir, { x: 3 }).value, 3);
  const missing = lift('export function normalize() { const result = { value: true }; return result.toString; }');
  assert.equal(observe(missing.ir, {}).kind, 'unsupported');
  for (const value of ['{ __proto__: null }', '{ get value() { return 1; } }', '{ ...unknown() }', '{ [x]: 1 }', '{ method() {} }']) {
    assert.throws(() => lift(`export function normalize(x: any) { return ${value}; }`), Unsupported);
  }
  const wrongDate = observe(lift(body).ir, { settings: { $record: { date: 5 } } });
  assert.equal(wrongDate.kind, 'unsupported');
});

test('field and intrinsic traces preserve evaluation order and failed partial construction', () => {
  const a = lift('export function normalize(date: any) { return { first: 1, date: date.trim(), last: 3 }; }');
  const success = observe(a.ir, { date: ' x ' }, { trace: true });
  const actions = success.trace.filter(event => event.event !== 'bind');
  assert.deepEqual(actions.map(event => event.event), ['record-field', 'intrinsic', 'record-field', 'record-field']);
  assert.equal(actions[1].input.value, ' x ');
  assert.equal(actions[1].result.value, 'x');
  assert.equal(actions[2].value.value, 'x');
  const failure = observe(a.ir, { date: null }, { trace: true });
  assert.equal(failure.kind, 'throw');
  assert.deepEqual(failure.trace.filter(event => event.event !== 'bind').map(event => event.event), ['record-field', 'throw']);
});

test('binder recovery for invalid duplicate lexical declarations is not executable support', () => {
  for (const source of [
    'export function normalize() { const x = 1; const x = 2; return x; }',
    'export function normalize(x: any) { const x = 2; return x; }',
    'export function normalize(x: any, x: any) { return x; }',
  ]) {
    assert.throws(() => lift(source), Unsupported);
    assert.throws(() => liftProject({ files: { 'a.ts': source }, entry: 'a.ts', functionName: 'normalize' }), Unsupported);
  }
});

test('shared constructed records cannot expand into an unbounded observation tree', () => {
  let source = 'export function normalize() { const value0 = { value: 1 };';
  for (let i = 1; i <= 24; i++) source += `const value${i} = { left: value${i - 1}, right: value${i - 1} };`;
  source += 'return value24; }';
  const result = observe(lift(source).ir, {});
  assert.equal(result.kind, 'unsupported');
  assert.match(result.reason, /관찰 값의 전개/);
  const wide = { text: 'x'.repeat(2000) };
  let value = wide;
  for (let i = 0; i < 16; i++) value = { left: value, right: value };
  assert.throws(() => encode(value), /관찰 값의 전개/);
});
