import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import ts from 'typescript';
import { liftJsxGuards } from '../src/jsx-guards.mjs';
import { observe, encode, decode, Unsupported } from '../src/core.mjs';

test('explicit const prefix preserves eager unused initializers and native JSX entry', () => {
  const body = `const allowed = user.allowed;
const unused = other.value;
const enabled = allowed && !locked;
const view = enabled && <button/>;`;
  const artifact = liftJsxGuards('function Screen() {\n' + body + '\n}', { tag: 'button', prefixLine: 2 });
  assert.deepEqual(artifact.inputs, ['locked', 'other', 'user']);
  assert.equal(artifact.prefix.bindings.length, 3);
  const native = new vm.Script(ts.transpileModule(body, { compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022 } }).outputText);
  for (const user of [null, {}, { allowed: false }, { allowed: true }]) for (const other of [null, {}, { value: 5 }]) for (const locked of [false, true]) {
    const inputs = { user: encode(user), other: encode(other), locked };
    let expected, reached = false;
    try {
      native.runInNewContext({ user: decode(inputs.user), other: decode(inputs.other), locked, React: { createElement() { reached = true; return {}; } } }, { timeout: 100 });
      expected = { kind: 'value', value: reached };
    } catch (error) { if (error.name !== 'TypeError') throw error; expected = { kind: 'throw', name: 'TypeError' }; }
    assert.deepEqual(observe(artifact.ir, inputs), expected);
  }
});

test('prefix refuses skipped effects, temporal dead zones and ambiguous region boundaries', () => {
  for (const source of [
    'function X() {\nconst a = x;\nmutate();\nreturn a && <button/>; }',
    'function X() {\nconst a = b;\nconst b = x;\nreturn a && <button/>; }',
    'function X() {\nconst a = x;\nreturn b && <button/>;\nconst b = x; }',
    'function X() {\nconst a = x;\nconst view = view && <button/>; }',
    'function X() {\nlet a = x;\nreturn a && <button/>; }',
    'function X() {\nconst a = x;\nconst a = y;\nreturn a && <button/>; }',
    'function X() {\nconst {a} = x;\nreturn a && <button/>; }',
  ]) assert.throws(() => liftJsxGuards(source, { tag: 'button', prefixLine: 2 }), Unsupported, source);
});
