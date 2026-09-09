import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';
import vm from 'node:vm';
import { liftJsxProperty } from '../src/jsx-property.mjs';
import { encode, decode, observe, compare, Unsupported } from '../src/core.mjs';
import { renderExecution } from '../src/report.mjs';
import { describeComparison } from '../src/presentation.mjs';

const options = { tag: 'input', attribute: 'aria-invalid', filename: '/input.tsx' };
function native(source, inputs, attribute = 'aria-invalid') {
  const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, jsxFactory: 'capture' } }).outputText;
  const capture = (tag, props) => Object.hasOwn(props ?? {}, attribute) ? { [attribute]: props[attribute] } : {};
  try { return { kind: 'value', value: encode(new vm.Script(js + '\nview;').runInNewContext({ capture, ...Object.fromEntries(Object.entries(inputs).map(([key, value]) => [key, decode(value)])) }, { timeout: 100 })) }; }
  catch (error) { if (error.name !== 'TypeError') throw error; return { kind: 'throw', name: error.name }; }
}

test('JSX property projection preserves absent, present undefined, null, false and shorthand true', () => {
  for (const source of ['const view = <input/>;', 'const view = <input aria-invalid/>;', 'const view = <input aria-invalid={value}/>;']) {
    const artifact = liftJsxProperty(source, options);
    assert.equal(artifact.target.provided, source.includes('aria-invalid'));
    assert.equal(Object.hasOwn(artifact.bindings, 'storedResult'), false);
    for (const value of [undefined, null, false, true, '', 'false', 'error', 0, -0, NaN]) {
      const inputs = { value: encode(value) };
      assert.deepEqual(observe(artifact.ir, inputs), native(source, inputs));
    }
  }
  const absent = liftJsxProperty('const view = <input/>;', options), present = liftJsxProperty('const view = <input aria-invalid={value}/>;', options);
  const comparison = compare(absent.ir, present.ir, { value: [encode(undefined), null, false] });
  assert.equal(comparison.changes.length, 3);
  const text = describeComparison(comparison);
  assert.match(text, /속성 추가: 없음 → 미정/); assert.match(text, /속성 추가: 없음 → 거짓/);
});

test('selecting an opening element detects addition/removal and refuses ambiguous, spread and special props', () => {
  const source = 'const view = <>\n<input aria-invalid={false}/>\n<input/>\n</>;';
  assert.throws(() => liftJsxProperty(source, options), Unsupported);
  assert.equal(liftJsxProperty(source, { ...options, line: 3 }).target.provided, false);
  assert.equal(liftJsxProperty(source, { ...options, line: 2 }).target.provided, true);
  for (const source of ['const view = <input {...props}/>;', 'const view = <input aria-invalid={true} {...props}/>;', 'const view = <input aria-invalid aria-invalid={false}/>;', 'const view = <input aria-invalid={}/>;', 'const view = <input aria-invalid="&amp;"/>;']) assert.throws(() => liftJsxProperty(source, options), Unsupported);
  for (const attribute of ['key', 'ref', 'children', '__proto__']) assert.throws(() => liftJsxProperty('const view = <input/>;', { ...options, attribute }), Unsupported);
  assert.throws(() => liftJsxProperty(source, { ...options, line: 0 }), Unsupported);
});

test('other attribute failures and parent reachability stay outside the property observation', () => {
  const source = 'const view = <input prior={other.value} aria-invalid={!!message}/>;';
  const artifact = liftJsxProperty(source, options), inputs = { message: 'error', other: null };
  assert.equal(observe(artifact.ir, inputs).value.$record['aria-invalid'], true);
  assert.equal(native(source, inputs).kind, 'throw');
  assert.equal(artifact.omittedAttributes.length, 1);
  const report = renderExecution(artifact, observe(artifact.ir, inputs, { trace: true }), { inputs, snippets: source_ => source.slice(source_.start, source_.end) });
  assert.match(report, /prior=/); assert.match(report, /실제 props 객체·DOM 생성 결과가 아니다/);
  const absent = liftJsxProperty('const view = <input prior={other.value}/>;', options);
  const beforeReport = renderExecution(absent, observe(absent.ir, {}));
  assert.match(beforeReport, /선택한 원본 태그에 없다/); assert.match(beforeReport, /전체 props 객체가 비었다는 뜻은 아니다/);
});

test('undefined remains a snapshot identifier and selected expression failures are preserved', () => {
  const source = 'function Frame(undefined) { return <input aria-invalid={undefined}/>; }';
  const artifact = liftJsxProperty(source, options);
  assert.deepEqual(artifact.inputs, ['undefined']);
  assert.equal(observe(artifact.ir, { undefined: 'shadowed' }).value.$record['aria-invalid'], 'shadowed');
  const access = liftJsxProperty('const view = <input aria-invalid={data.error}/>;', options);
  assert.deepEqual(observe(access.ir, { data: null }), { kind: 'throw', name: 'TypeError' });
  assert.equal(observe(access.ir, { data: { $opaque: 'truthy-object' } }).kind, 'unsupported');
});
