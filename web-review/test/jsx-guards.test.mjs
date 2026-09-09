import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import ts from 'typescript';
import { liftJsxGuards } from '../src/jsx-guards.mjs';
import { observe, encode, Unsupported } from '../src/core.mjs';
import { renderExecution } from '../src/report.mjs';

test('nested JSX guards agree with native whole-expression evaluation on non-Boolean operands', () => {
  const expressions = [
    'a && <div>{b ? <section>{c || <button/>}</section> : null}</div>',
    'a ? null : <div>{b ?? <button/>}</div>',
    '<><i/>{a && <div>{b && <button/>}</div>}</>',
    '(<button/> || a) && b',
  ];
  const values = [false, true, 0, -0, '', 'ok', null, undefined, NaN];
  let checked = 0;
  for (const expression of expressions) {
    const source = `export const result = ${expression};`;
    const artifact = liftJsxGuards(source, { tag: 'button' });
    const compiled = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
    const script = new vm.Script(compiled);
    for (const a of values) for (const b of values) for (const c of [false, true, null]) {
      let reached = false;
      const React = { Fragment: 'fragment', createElement(tag) { if (tag === 'button') reached = true; return { tag }; } };
      script.runInNewContext({ exports: {}, React, a, b, c }, { timeout: 100 });
      assert.deepEqual(observe(artifact.ir, { a: encode(a), b: encode(b), c: encode(c) }), { kind: 'value', value: reached });
      checked++;
    }
  }
  assert.equal(checked, 972);
});

test('path failures short-circuit and omitted evaluations remain explicit assumptions', () => {
  const source = 'function Screen() { if (early) return null; return <Box x={mutate()}><Other/>{outer && <div>{user.allowed && <button disabled={broken()}/>}</div>}</Box>; }';
  const artifact = liftJsxGuards(source, { tag: 'button' });
  assert.deepEqual(artifact.inputs, ['outer', 'user']);
  assert.equal(artifact.guards.length, 2);
  assert.equal(artifact.omittedEvaluations.length, 3);
  assert.ok(artifact.contract.notProven.some(item => item.includes('앞선 return')));
  assert.equal(observe(artifact.ir, { outer: false, user: null }).value, false);
  assert.equal(observe(artifact.ir, { outer: true, user: null }).kind, 'throw');
  // This is entry before evaluating the target's own broken() attribute.
  assert.equal(observe(artifact.ir, { outer: true, user: { $record: { allowed: true } } }).value, true);
});

test('selectors preserve exact source and reject unsupported path or ambiguous targets', () => {
  const source = 'const view = <>\n<button className="first"/>\n<button className="second"/>\n</>;';
  const artifact = liftJsxGuards(source, { tag: 'button', attribute: 'className', equals: 'second' });
  assert.equal(artifact.target.line, 3);
  assert.equal(source.slice(artifact.source.start, artifact.source.end), '<button className="second"/>');
  assert.equal(liftJsxGuards(source, { tag: 'button', line: 2 }).target.line, 2);
  for (const text of [source, 'const result = values.map(value => value && <button/>);', 'const result = call(<button/>);', 'const result = check() && <button/>;', 'const result = <Box child={<button/>}/>;']) {
    // An arrow expression body has a legitimate local root. Its invocation is
    // a precondition, never inferred from map(), so select that case separately.
    if (text.includes('.map')) {
      const a = liftJsxGuards(text, { tag: 'button' });
      assert.deepEqual(a.inputs, ['value']);
      assert.equal(text.slice(a.root.start, a.root.end), 'value && <button/>');
    } else assert.throws(() => liftJsxGuards(text, { tag: 'button' }), Unsupported, text);
  }
  assert.throws(() => liftJsxGuards(source, { tag: 'button', attribute: 'className' }), Unsupported);
});

test('nullish gate explanation distinguishes the generated check from the original value', () => {
  const source = 'const result = value ?? <button/>;';
  const artifact = liftJsxGuards(source, { tag: 'button' });
  const report = renderExecution(artifact, observe(artifact.ir, { value: null }, { trace: true }), { snippets: node => source.slice(node.start, node.end) });
  assert.ok(report.includes('value이 null·undefined인지 판정한 값은 참'));
  assert.ok(!report.includes('조건 value은 참'));
});
