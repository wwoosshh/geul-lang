import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import ts from 'typescript';
import { liftProject } from '../src/project.mjs';
import { encode, decode, observe, compare, Unsupported } from '../src/core.mjs';

const files = {
  'access.ts': 'export function permitted(user: {role: string, suspended: boolean}, owner: boolean) { if (user.suspended) return false; return user.role === "admin" || owner; }',
  'button.ts': 'import { permitted as canDelete } from "./access"; export function disabled(user: {role: string, suspended: boolean}, owner: boolean, locked: boolean) { const allowed = canDelete(user, owner); return !allowed || locked; }',
};
const project = (sources = files) => liftProject({ files: sources, entry: 'button.ts', functionName: 'disabled' });
function nativeModules(sources, entry, name, args) {
  const cache = new Map();
  function load(filename) {
    if (cache.has(filename)) return cache.get(filename);
    const output = ts.transpileModule(sources[filename], { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
    const exports = {};
    vm.runInNewContext(output, { exports, require: spec => load(spec.replace('./', '') + '.ts') }, { timeout: 100 });
    cache.set(filename, exports);
    return exports;
  }
  try { return { kind: 'value', value: encode(load(entry)[name](...args)) }; }
  catch (e) { if (e.name === 'TypeError') return { kind: 'throw', name: 'TypeError' }; throw e; }
}
test('TypeScript symbols resolve aliased cross-file calls and preserve runtime results', () => {
  const a = project();
  assert.deepEqual(a.inputs, ['locked', 'owner', 'user']);
  assert.deepEqual(a.dependencies.map(d => d.function), ['disabled', 'permitted']);
  assert.equal(a.moduleEdges.length, 1);
  assert.ok(a.references.some(r => r.name === 'canDelete' && r.use.file === '/project/button.ts' && r.definition.file === '/project/access.ts'));
  assert.equal(a.engineSha256.length, 64);
  let checks = 0;
  for (const user of [null, {}, { role: 'admin', suspended: false }, { role: 'user', suspended: false }, { role: 'admin', suspended: true }]) {
    for (const owner of [true, false]) for (const locked of [true, false]) {
      const inputs = { user: encode(user), owner, locked };
      assert.deepEqual(observe(a.ir, inputs), nativeModules(files, 'button.ts', 'disabled', [decode(encode(user)), owner, locked]));
      checks++;
    }
  }
  assert.equal(checks, 20);
});
test('const and eager call arguments preserve throws even for unused values', () => {
  const src = { 'button.ts': 'function unused(x: unknown) { return false; } export function disabled(user: any) { return unused(user.a); }' };
  assert.deepEqual(observe(project(src).ir, { user: null }), { kind: 'throw', name: 'TypeError' });
  const initial = { 'button.ts': 'export function disabled(user: any) { const ignored = user.a; return false; }' };
  assert.deepEqual(observe(project(initial).ir, { user: null }), { kind: 'throw', name: 'TypeError' });
  const short = { 'button.ts': 'function unused(x: unknown) { return false; } export function disabled(user: any) { return false && unused(user.a); }' };
  assert.deepEqual(observe(project(short).ir, { user: null }), { kind: 'value', value: false });
});
test('block scope, early return and parameter names cannot collide with internal bindings', () => {
  const src = { 'button.ts': 'const fallback = false; export function disabled(값1: boolean, other: boolean) { if (값1) { const other = false; return other; } return other || fallback; }' };
  const a = project(src);
  for (const first of [false, true]) for (const other of [false, true]) assert.deepEqual(observe(a.ir, { 값1: first, other }), nativeModules(src, 'button.ts', 'disabled', [first, other]));
});
test('a cross-file policy edit produces an exact finite-domain difference', () => {
  const after = { ...files, 'access.ts': files['access.ts'].replace('user.role === "admin" || owner', 'owner') };
  const a = project(), b = project(after);
  const result = compare(a.ir, b.ir, {
    user: [encode({ role: 'admin', suspended: false }), encode({ role: 'user', suspended: false }), encode({ role: 'admin', suspended: true })],
    owner: [false, true], locked: [false, true],
  });
  assert.equal(result.changes.length, 1);
  assert.deepEqual(result.changes[0].before, { kind: 'value', value: false });
  assert.deepEqual(result.changes[0].after, { kind: 'value', value: true });
});
test('unsafe and unresolved projects fail closed, including unused helpers', () => {
  const bodies = [
    'export function disabled(x: any) { return external(x); }',
    'export function disabled(x: any) { x.a = false; return x.a; }',
    'export function disabled(x: any) { let a = x; return a; }',
    'export function disabled(x: any) { return disabled(x); }',
    'export function disabled(x: any) { return a; const a = x; }',
    'export function disabled(x: any = false) { return x; }',
    'export async function disabled(x: any) { return x; }',
    'export function disabled({x = true}: any) { return x; }',
    'export function disabled() { return false; } function uncalled() { external(); }',
    'export function disabled() { return false; unknown(); }',
    'const bad = external(); export function disabled() { return false; }',
    'const bad = (null as any).x; export function disabled() { return false; }',
    'import { f } from "outside"; export function disabled() { return false; }',
    'import { f } from "./missing"; export function disabled() { return f(); }',
    'export function disabled(x: any) { return (() => x)(); }',
  ];
  for (const source of bodies) assert.throws(() => project({ 'button.ts': source }), Unsupported, source);
  assert.throws(() => project({ ...files, '../evil.ts': 'export const x = 1;' }), Unsupported);
  assert.throws(() => project({ ...files, 'button.ts': files['button.ts'].replace('import {', 'import type {') }), Unsupported);
  assert.throws(() => project({ 'button.ts': `export function disabled(x: boolean) { ${'if (x) {} '.repeat(22)} return false; }` }), /IR 크기/);
  assert.throws(() => project({ 'button.ts': 'import { f } from "./helper"; export function disabled() { return f(); }', 'helper.ts': 'import { disabled } from "./button"; export function f() { return false; }' }), /순환 import/);
});
