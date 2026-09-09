import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import ts from 'typescript';
import { liftJsxFlow, linkJsxFlowProps } from '../src/jsx-flow.mjs';
import { observe, encode, decode, Unsupported } from '../src/core.mjs';
import { renderExecution } from '../src/report.mjs';

test('stored nullable JSX flows through const bindings without recomputing pre-mutation data', () => {
  const body = `const allowed = state.allowed;
const bottom = state.bottom;
const element = allowed ? <button/> : null;
mutate(state);
return <>{bottom && <section>{element}</section>}{!bottom && element && <aside>{element}</aside>}</>;`;
  const source = `function Screen(state: any) {\n${body}\n}`;
  const artifact = liftJsxFlow(source, { tag: 'button', prefixLine: 2 });
  assert.deepEqual(artifact.inputs, ['state']);
  assert.equal(artifact.flow.references.length, 2);
  assert.equal(artifact.prefix.bindings.at(-1).projection, 'jsx-object-or-null');
  const inputs = { state: encode({ allowed: true, bottom: false }) };
  const report = renderExecution(artifact, observe(artifact.ir, inputs, { trace: true }), { inputs, snippets: node => source.slice(node.start, node.end) });
  assert.ok(report.includes('선택 JSX에 진입하는 경로의 계산값은 참이다'));
  assert.ok(report.includes('allowed에 참을 저장했다'));
  assert.ok(report.includes('element에 내부 미확인 객체'));
  assert.ok(!report.includes('조건 allowed ? &lt;button/&gt; : null은 참'));
  const compiled = ts.transpileModule(`function Screen(state) { ${body} } Screen(state);`, { compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022 } }).outputText;
  for (const allowed of [false, true]) for (const bottom of [false, true]) {
    let element, contributed = false;
    const state = { allowed, bottom }, inputs = { state: encode(state) };
    const React = { Fragment: 'fragment', createElement(tag, props, ...children) {
      if (tag === 'button') { element = { tag }; return element; }
      if (children.some(child => element && child === element)) contributed = true;
      return { tag };
    } };
    vm.runInNewContext(compiled, { state: decode(inputs.state), React, mutate(value) { value.allowed = !value.allowed; value.bottom = !value.bottom; } }, { timeout: 100 });
    assert.equal(contributed, allowed);
    assert.equal(observe(artifact.ir, inputs).value, contributed);
  }
});

test('direct child flow is distinct from merely evaluating a JSX expression', () => {
  const artifact = liftJsxFlow('const view = <div>{visible && <button/>}</div>;', { tag: 'button' });
  assert.equal(artifact.flow.route, 'inline-child');
  assert.equal(observe(artifact.ir, { visible: true }).value, true);
  assert.throws(() => liftJsxFlow('const view = <div>{<button/> && other}</div>;', { tag: 'button' }), Unsupported);
});

test('parent flow gates ordered prop evaluation and binds renamed child inputs by declaration', () => {
  const files = { 'parent.tsx': `import { Child } from './child';
export function Parent() { return <>{phone && <Child state={source} enabled={settings.enabled}/>}</>; }`,
    'child.tsx': `export function Child({ state: data, enabled: active }) { return <>{active && data.ready && <button/>}</>; }` };
  const args = { files, entry: 'parent.tsx', tag: 'Child', properties: ['enabled', 'state'],
    context: { configPath: 'tsconfig.json', inventory: [...Object.keys(files), 'tsconfig.json'], metadata: { 'tsconfig.json': '{}' } },
    sink: { tag: 'button' }, assumePlainProps: true };
  const linked = linkJsxFlowProps(args);
  assert.deepEqual(linked.inputs, ['phone', 'settings', 'source']);
  assert.deepEqual(linked.bindings.map(row => row.connection.property), ['state', 'enabled']);
  assert.deepEqual(observe(linked.ir, { phone: false, source: null, settings: null }), { kind: 'value', value: false });
  assert.deepEqual(observe(linked.ir, { phone: true, source: null, settings: null }), { kind: 'throw', name: 'TypeError' });
  assert.equal(observe(linked.ir, { phone: true, source: encode({ ready: true }), settings: encode({ enabled: true }) }).value, true);
  for (const child of [
    `export function Child({state, enabled = false}) { return <>{enabled && <button/>}</>; }`,
    `export function Child({state, enabled}) { enabled = false; return <>{enabled && <button/>}</>; }`,
    `export function Child({state, enabled}) { return <>{unbound && <button/>}</>; }`,
    `export function Child({state, enabled}) { function nested() { return <><button/></>; } return nested(); }`,
  ]) assert.throws(() => linkJsxFlowProps({ ...args, files: { ...files, 'child.tsx': child } }), Unsupported);
  assert.throws(() => linkJsxFlowProps({ ...args, assumePlainProps: false }), Unsupported);
});

test('flow refuses mutable re-reads, captures, ambiguous initializers and unsupported aliases', () => {
  for (const body of [
    'const node = enabled ? <button/> : null; return <>{state.visible && <div>{node}</div>}</>;',
    'const node = enabled ? <button/> : null; function later() { return <>{node}</>; } return later();',
    'const node = enabled ? <button/> : other; return <>{node}</>;',
    'const node = enabled ? <button/> : null; const alias = node; return <>{alias}</>;',
    'let flag = enabled; const node = enabled ? <button/> : null; return <>{flag && <div>{node}</div>}</>;',
  ]) assert.throws(() => liftJsxFlow(`function Screen() { ${body} }`, { tag: 'button' }), Unsupported, body);
});

test('stored flow does not discard statement branches, early returns or out-of-root uses', () => {
  for (const suffix of [
    'if (other) return <>{node}</>;\nreturn null;',
    'if (other) return null;\nreturn <>{node}</>;',
    'if (node) log();\nreturn <>{node}</>;',
    'const unused = node;\nreturn <>{node}</>;',
    'await pause();\nreturn <>{node}</>;',
    'return <>{node}</>;\nreturn <>{node}</>;',
  ]) assert.throws(() => liftJsxFlow(`async function Screen() {\nconst node = enabled ? <button/> : null;\n${suffix}\n}`, { tag: 'button' }), Unsupported, suffix);
  assert.throws(() => liftJsxFlow('function Screen() {\nconst node = enabled ? <button/> : null, unused = work();\nreturn <>{node}</>;\n}', { tag: 'button' }), Unsupported);
});
