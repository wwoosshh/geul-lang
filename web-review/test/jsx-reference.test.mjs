import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import ts from 'typescript';
import { liftJsxReference } from '../src/jsx-reference.mjs';
import { observe, encode, Unsupported } from '../src/core.mjs';

test('reference paths observe object contribution at each child slot separately', () => {
  const source = `const result = <>
{bottom && <section>{node}</section>}
{!bottom && node && <aside>{node}</aside>}
</>;`;
  const first = liftJsxReference(source, { name: 'node', line: 2 });
  const second = liftJsxReference(source, { name: 'node', line: 3 });
  const script = new vm.Script(ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022 } }).outputText);
  for (const bottom of [false, true]) for (const node of [null, undefined, false, 0, 'text', { privateProps: () => {} }]) {
    const passed = { section: false, aside: false };
    const React = { Fragment: 'fragment', createElement(tag, props, ...children) {
      if (tag in passed) passed[tag] = children.some(child => child === node && child !== null && typeof child === 'object');
      return { tag };
    } };
    script.runInNewContext({ bottom, node, React }, { timeout: 100 });
    const inputs = { bottom, node: node && typeof node === 'object' ? { $opaque: 'truthy-object' } : encode(node) };
    assert.equal(observe(first.ir, inputs).value, passed.section);
    assert.equal(observe(second.ir, inputs).value, passed.aside);
  }
});

test('only direct child reads are selected and identical names require exact positions', () => {
  assert.throws(() => liftJsxReference('const x = <>{node}{node}</>;', { name: 'node' }), Unsupported);
  assert.throws(() => liftJsxReference('const x = <Box value={node}/>;', { name: 'node' }), Unsupported);
  const artifact = liftJsxReference('const x = <>{node}{node}</>;', { name: 'node', column: 14 });
  assert.equal(artifact.target.column, 14);
  assert.ok(artifact.contract.notProven.some(item => item.includes('동일')));
  assert.equal(observe(artifact.ir, { node: { $opaque: 'truthy-object' } }).value, true);
});
