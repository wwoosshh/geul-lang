import test from 'node:test';
import assert from 'node:assert/strict';
import { liftJsxAttribute } from '../src/jsx.mjs';
import { observe, Unsupported } from '../src/core.mjs';

test('JSX attributes retain target, source and their deliberately local scope', () => {
  const artifact = liftJsxAttribute('function Save() { if (!visible) return null; return <button disabled={!allowed || busy}/>; }', { tag: 'button', attribute: 'disabled' });
  assert.deepEqual(artifact.inputs, ['allowed', 'busy']);
  assert.equal(artifact.target.intrinsic, true);
  assert.equal(artifact.mode, 'jsx-attribute-slice');
  assert.deepEqual(observe(artifact.ir, { allowed: true, busy: false }), { kind: 'value', value: false });
  assert.ok(artifact.contract.notProven.includes('이 JSX까지 도달하는 조건'));
  assert.equal(liftJsxAttribute('<Button disabled={busy} />', { tag: 'Button', attribute: 'disabled' }).target.intrinsic, false);
});
test('boolean/string attributes and empty, spread, duplicate and ambiguous targets', () => {
  for (const [source, value] of [['<button disabled />', true], ['<button disabled="false" />', 'false']]) {
    const a = liftJsxAttribute(source, { tag: 'button', attribute: 'disabled' });
    assert.deepEqual(observe(a.ir, {}), { kind: 'value', value });
  }
  for (const source of ['<button {...props} disabled={false}/>', '<button disabled={false} {...props}/>', '<button disabled disabled={false}/>', '<><button disabled/><button disabled/></>', '<button disabled={}/>', '<button disabled="&amp;"/>', '<button disabled="&#65;"/>']) {
    assert.throws(() => liftJsxAttribute(source, { tag: 'button', attribute: 'disabled' }), Unsupported);
  }
  const entityInExpression = liftJsxAttribute('<button disabled={"&amp;"}/>', { tag: 'button', attribute: 'disabled' });
  assert.deepEqual(observe(entityInExpression.ir, {}), { kind: 'value', value: '&amp;' });
  const multiple = '<>\n<button disabled={false}/>\n<button disabled={true}/>\n</>';
  const selected = liftJsxAttribute(multiple, { tag: 'button', attribute: 'disabled', line: 3 });
  assert.deepEqual(observe(selected.ir, {}), { kind: 'value', value: true });
  assert.equal(selected.target.line, 3);
  assert.throws(() => liftJsxAttribute(multiple, { tag: 'button', attribute: 'disabled', line: 1 }), Unsupported);
});
