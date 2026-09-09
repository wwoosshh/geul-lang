import test from 'node:test';
import assert from 'node:assert/strict';
import { liftJsxGuards } from '../src/jsx-guards.mjs';
import { observe } from '../src/core.mjs';
import { renderInputBindings } from '../src/report.mjs';
import { buildReading, renderReading } from '../src/reading.mjs';

test('input origin index finds lexical declarations without substituting earlier values', () => {
  const source = 'const flag = false; function Screen(user: any) { const flag = user.allowed; user.allowed = false; return flag && <button/>; }';
  const artifact = liftJsxGuards(source, { tag: 'button' });
  const input = artifact.bindings.inputs.find(item => item.name === 'flag');
  assert.equal(input.status, 'declaration-found');
  assert.equal(input.declarations[0].kind, 'const');
  assert.equal(source.slice(input.declarations[0].initializer.start, input.declarations[0].initializer.end), 'user.allowed');
  // Retain point-in-time input; copying the initializer here would be wrong.
  assert.deepEqual(artifact.inputs, ['flag']);
  assert.equal(observe(artifact.ir, { flag: true }).value, true);
});

test('stored JSX index separates symbol uses, shadowed names, captures and type references', () => {
  const source = `function Screen(enabled: boolean) {
    const element = enabled ? <button/> : null;
    type Shape = typeof element;
    function shadow(element: any) { return element; }
    function capture() { return element; }
    const object = { element };
    pass(element);
    return <>{element}{enabled && element && <div>{element}</div>}</>;
  }`;
  const result = liftJsxGuards(source, { tag: 'button' }).bindings.storedResult;
  assert.equal(result.name, 'element');
  assert.equal(result.useCount, 7);
  assert.deepEqual(result.uses.map(item => item.kind), ['type-only', 'return-value', 'object-shorthand', 'call-argument', 'jsx-child', 'condition-value', 'jsx-child']);
  assert.equal(result.uses.filter(item => item.nestedFunction).length, 1);
  assert.equal(result.usesTruncated, false);
});

test('unresolved imports are linked only to their local binding declaration', () => {
  const source = 'import { allowed as enabled } from "external"; const node = enabled && missing && <button/>; export { node as output };';
  const artifact = liftJsxGuards(source, { tag: 'button' });
  assert.equal(artifact.bindings.inputs.find(item => item.name === 'enabled').declarations[0].kind, 'import-binding');
  assert.equal(artifact.bindings.inputs.find(item => item.name === 'missing').status, 'unresolved-in-file');
  assert.equal(artifact.bindings.storedResult.uses[0].kind, 'export-reference');
  assert.equal(artifact.bindings.storedResult.useCount, 1);
});

test('destructured input links its enclosing initializer without confusing aliases or shadows', () => {
  const source = 'const enabled = false; function Screen() { const { ready: enabled, extra } = read("<tag>"); return enabled && <button/>; }';
  const artifact = liftJsxGuards(source, { tag: 'button' });
  const input = artifact.bindings.inputs.find(item => item.name === 'enabled'), declaration = input.declarations[0];
  const origin = declaration.destructuringOrigin, text = location => source.slice(location.start, location.end);
  assert.equal(declaration.kind, 'destructured-binding');
  assert.equal(origin.kind, 'variable-pattern'); assert.equal(origin.runtimeValueProven, false);
  assert.equal(origin.nestingDepth, 1);
  assert.equal(text(origin.pattern), '{ ready: enabled, extra }');
  assert.equal(text(origin.expression), 'read("<tag>")');
  assert.equal(declaration.initializer, undefined);
  assert.deepEqual(artifact.inputs, ['enabled']);
  assert.equal(observe(artifact.ir, { enabled: true }).value, true);
  const report = renderInputBindings(artifact, { snippets: text });
  assert.match(report, /패턴을 받는 선언의 초기화 식/);
  assert.match(report, /read\("&lt;tag&gt;"\)/);
  assert.doesNotMatch(report, /read\("<tag>"\)/);
  assert.match(report, /hook을 실행하지 않았으며/);
  const reading = renderReading(artifact, buildReading(artifact.ir), { snippets: text });
  assert.ok(reading.includes(report));
});

test('nested pattern defaults and enclosing parameter defaults remain separate source expressions', () => {
  for (const [prefix, kind, expression, depth] of [
    ['function Screen() { const [, { ready: enabled = fallback }, ...rest] = hook();', 'variable-pattern', 'hook()', 2],
    ['function Screen({ account: { enabled = fallback } = empty } = readDefault()) {', 'parameter-pattern', 'readDefault()', 2],
    ['function Screen() { const { [key()]: enabled = fallback } = hook();', 'variable-pattern', 'hook()', 1],
  ]) {
    const source = prefix + ' return enabled && <button/>; }';
    const artifact = liftJsxGuards(source, { tag: 'button' });
    const declaration = artifact.bindings.inputs.find(row => row.name === 'enabled').declarations[0];
    const origin = declaration.destructuringOrigin, text = location => source.slice(location.start, location.end);
    assert.equal(text(declaration.initializer), 'fallback');
    assert.equal(declaration.initializerRole, 'default-value');
    assert.equal(origin.kind, kind); assert.equal(origin.nestingDepth, depth);
    assert.equal(text(origin.expression), expression);
    assert.equal(origin.expressionRole, kind === 'parameter-pattern' ? 'parameter-default' : 'declaration-initializer');
    assert.equal(observe(artifact.ir, { enabled: false }).value, false);
    const report = renderInputBindings(artifact, { snippets: text });
    assert.match(report, /조건부 기본값 식: fallback/);
    assert.ok(report.includes(kind === 'parameter-pattern' ? '매개변수 기본값 식' : '패턴을 받는 선언의 초기화 식'));
  }
});

test('argument and catch patterns without defaults do not invent initializer values', () => {
  for (const [source, kind] of [
    ['function Screen({ enabled }) { return enabled && <button/>; }', 'parameter-pattern'],
    ['function Screen() { try { work(); } catch ({ enabled }) { return enabled && <button/>; } }', 'catch-pattern'],
  ]) {
    const artifact = liftJsxGuards(source, { tag: 'button' });
    const declaration = artifact.bindings.inputs.find(row => row.name === 'enabled').declarations[0];
    assert.equal(declaration.destructuringOrigin.kind, kind);
    assert.equal(declaration.destructuringOrigin.expression, undefined);
    assert.equal(declaration.initializer, undefined);
    assert.match(renderInputBindings(artifact), /실제 (전달값|예외값) 미확인/);
  }
});
