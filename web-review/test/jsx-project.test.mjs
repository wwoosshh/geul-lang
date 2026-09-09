import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import ts from 'typescript';
import { liftProject } from '../src/project.mjs';
import { observe, encode, decode, compare, Unsupported } from '../src/core.mjs';

const policy = 'export function allowed(user: any, owner: boolean) { if (user.suspended) return false; return user.role === "admin" || owner; }';
const screen = 'import { allowed } from "./policy"; export function DeleteButton(user: any, owner: boolean, locked: boolean, visible: boolean) { if (!visible) return null; const disabled = !allowed(user, owner) || locked; return <button disabled={disabled}>삭제</button>; }';
function lift(source = screen, rule = policy) { return liftProject({ files: { 'screen.tsx': source, 'policy.ts': rule }, entry: 'screen.tsx', functionName: 'DeleteButton' }); }

function native(sources) {
  const modules = {};
  const make = (tag, attributes, ...children) => ({ $jsx: { tag, attributes: encode(Object.fromEntries(Object.entries(attributes ?? {}))), children: children.map(c => c && c.$jsx ? c : encode(c)) } });
  for (const [name, source] of Object.entries(sources)) {
    const exports = {};
    const code = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, jsxFactory: '__make' } }).outputText;
    vm.runInNewContext(code, { exports, __make: make, require: spec => modules[spec] }, { timeout: 100 });
    modules[name] = exports;
  }
  return modules.screen.DeleteButton;
}
test('pure cross-file JSX preserves branch reachability, props and native construction arguments', () => {
  const artifact = lift(), run = native({ './policy': policy, screen });
  let count = 0;
  for (const user of [null, { role: 'admin', suspended: false }, { role: 'user', suspended: false }, { role: 'admin', suspended: true }]) {
    for (const owner of [false, true]) for (const locked of [false, true]) for (const visible of [false, true]) {
      const inputs = { user: encode(user), owner, locked, visible };
      let expected;
      try {
        const result = run(decode(inputs.user), owner, locked, visible);
        expected = { kind: 'value', value: result?.$jsx ? result : encode(result) };
      } catch (e) { if (e.name === 'TypeError') expected = { kind: 'throw', name: 'TypeError' }; else throw e; }
      assert.deepEqual(observe(artifact.ir, inputs), expected);
      count++;
    }
  }
  assert.equal(count, 32);
  assert.match(artifact.contract.observation, /JSX/);
});
test('hidden branch suppresses helper failure and a policy edit changes only the expected button', () => {
  const a = lift(), b = lift(screen, policy.replace('user.role === "admin" || owner', 'owner'));
  assert.deepEqual(observe(a.ir, { user: null, owner: false, locked: false, visible: false }), { kind: 'value', value: null });
  const result = compare(a.ir, b.ir, { user: [encode({ role: 'admin', suspended: false }), encode({ role: 'user', suspended: false })], owner: [false, true], locked: [false, true], visible: [false, true] });
  assert.equal(result.changes.length, 1);
  assert.equal(result.changes[0].before.value.$jsx.attributes.$record.disabled, false);
  assert.equal(result.changes[0].after.value.$jsx.attributes.$record.disabled, true);
  const traced = observe(a.ir, { user: null, owner: false, locked: false, visible: false }, { trace: true });
  assert.ok(traced.trace.some(t => t.event === 'branch' && t.selected === 'yes'));
  assert.ok(!traced.trace.some(t => t.source?.file === '/project/policy.ts'));
  assert.ok(!traced.trace.some(t => t.event === 'jsx'));
  const shown = observe(a.ir, { user: encode({ role: 'admin', suspended: false }), owner: false, locked: false, visible: true }, { trace: true });
  assert.ok(shown.trace.some(t => t.source?.file === '/project/policy.ts'));
  assert.ok(shown.trace.some(t => t.event === 'jsx' && t.attributes.disabled.value === false));
  assert.equal(shown.traceTruncated, false);
});
test('conditional JSX keeps zero as a value and supports nested basic elements', () => {
  for (const source of [
    'export function DeleteButton(x: any) { return x && <button disabled>삭제</button>; }',
    'export function DeleteButton(x: any) { return <div>상태: {x ? <span>참</span> : null}</div>; }',
    'export function DeleteButton(x: any) { return <div>\n  <span>{x}</span>\n</div>; }',
  ]) {
    const ir = lift(source).ir, run = native({ './policy': policy, screen: source });
    for (const x of [0, false, true, null, '']) {
      const result = run(x);
      assert.deepEqual(observe(ir, { x }), { kind: 'value', value: result?.$jsx ? result : encode(result) });
    }
  }
});
test('custom components, effects, special props and undecoded JSX text fail closed', () => {
  for (const jsx of ['<Button/>', '<><button/></>', '<button {...props}/>', '<button key="a"/>', '<button ref={x}/>', '<button children="x"/>', '<button disabled disabled/>', '<button onClick={() => x}/>', '<button>&amp;</button>', '<button>\n name\n</button>']) {
    assert.throws(() => lift(`export function DeleteButton(x: any) { return ${jsx}; }`), Unsupported, jsx);
  }
  assert.throws(() => lift('/** @jsx custom */\n' + screen), /pragma/);
});
