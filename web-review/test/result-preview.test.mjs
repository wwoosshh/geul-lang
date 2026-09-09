import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import ts from 'typescript';
import { previewFunctionResult } from '../src/result-preview.mjs';
import { renderFunctionResultPreview } from '../src/report.mjs';
import { encode, decode, Unsupported } from '../src/core.mjs';

const preview = (source, inputs) => previewFunctionResult(source, { functionName: 'normalize', filename: '/source.tsx', inputs });

test('verified body values and aliased result bindings agree with native execution without invoking a payload sink', () => {
  const source = `function normalize(input: any) {
  return { value: input?.value ?? 0, label: input?.label ? input.label.trim() : undefined };
}
function caller(input: any) {
  const { value: balance, label } = normalize(input);
  sink({ amount: balance, label });
}`;
  const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  const script = new vm.Script(`${compiled}\nconst { value: balance, label } = normalize(input); ({ balance, label });`);
  for (const value of [null, undefined, 0, -0, 23, NaN, Infinity]) for (const label of [null, undefined, '', '  ', ' text ']) {
    const input = encode({ value, label });
    const result = preview(source, { input });
    assert.equal(result.observation.kind, 'value');
    assert.equal(result.bindingObservation.kind, 'value');
    const native = script.runInNewContext({ input: decode(input) }, { timeout: 100 });
    assert.deepEqual(result.projections.map(row => row.value), [encode(native.balance), encode(native.label)]);
    assert.ok(result.projections.every(row => row.status === 'scalar-at-binding'));
  }
  const result = preview(source, { input: { $record: { value: 0, label: ' hello ' } } });
  const report = renderFunctionResultPreview(result, { snippets: loc => source.slice(loc.start, loc.end) });
  assert.match(report, /실제 요청 실행을 확인한 결과는 아니다/);
  assert.match(report, /balance/);
  assert.match(report, /hello/);
  assert.match(report, /String.prototype.trim/);
  assert.match(report, /함수 본문 진입점/);
});

test('constructed missing fields retain their unknown prototype while input records allow missing fields', () => {
  const constructed = preview(`function normalize(input: any) { return { value: input }; }
const { missing } = normalize(input); sink({ missing });`, { input: 4 });
  assert.equal(constructed.observation.kind, 'value');
  assert.equal(constructed.bindingObservation.kind, 'unsupported');
  assert.equal(constructed.projections[0].status, 'unavailable');
  const passed = preview(`function normalize(input: any) { return input; }
const { missing } = normalize(input); sink({ missing });`, { input: { $record: {} } });
  assert.equal(passed.bindingObservation.kind, 'value');
  assert.deepEqual(passed.projections[0].value, { $value: 'undefined' });
});

test('null destructuring throws and unsupported bodies never gain invented binding values', () => {
  const source = `function normalize(input: any) { return input; }
const { value } = normalize(input); sink({ value });`;
  for (const input of [null, { $value: 'undefined' }]) {
    const result = preview(source, { input });
    assert.equal(result.observation.kind, 'value');
    assert.equal(result.bindingObservation.kind, 'throw');
    assert.equal(result.projections[0].status, 'unavailable');
  }
  const invalid = preview(`function normalize(input: any) { return { value: input.trim() }; }
const { value } = normalize(input); sink({ value });`, { input: 9 });
  assert.equal(invalid.observation.kind, 'unsupported');
  assert.equal(invalid.bindingObservation, null);
  assert.equal(invalid.projections[0].status, 'unavailable');
  assert.throws(() => preview(`function normalize(input: any) { return external(input); }
const value = normalize(input); sink({ value });`, { input: 9 }), Unsupported);
});

test('returned object bindings remain snapshots even when a later source use mutates them', () => {
  const source = `function normalize(input: any) { return { value: input }; }
const object = normalize(input); object.value = 99; sink({ object });`;
  const result = preview(source, { input: 3 });
  assert.equal(result.projections[0].status, 'object-snapshot');
  assert.deepEqual(result.projections[0].value, { $record: { value: 3 } });
  const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  let actual;
  new vm.Script(compiled).runInNewContext({ input: 3, sink: payload => { actual = payload.object.value; } }, { timeout: 100 });
  assert.equal(actual, 99);
  const report = renderFunctionResultPreview(result, { snippets: loc => source.slice(loc.start, loc.end) });
  assert.match(report, /이후 사용 시점의 값은 미확인/);
});
