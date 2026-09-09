import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import ts from 'typescript';
import { previewFunctionResult } from '../src/result-preview.mjs';
import { renderFunctionResultPreview } from '../src/report.mjs';
import { encode, decode, Unsupported } from '../src/core.mjs';

const preview = (source, inputs) => previewFunctionResult(source, { functionName: 'normalize', filename: '/caller.tsx', inputs, inputBoundary: 'call-arguments' });

test('original dynamic lookup, helper body and result binding execute in one parameter-preserving model', () => {
  const source = `function normalize(settings: any) {
  return { amount: settings?.amount ?? 0, date: settings?.date ? settings.date.trim() : undefined };
}
const { amount: balance, date } = normalize(records[selected]);
sink({ balance, date });`;
  const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  for (const selected of ['first', 'second', 'missing']) {
    const records = { first: { amount: 0, date: ' padded ' }, second: { amount: -0, date: '' } };
    const inputs = { records: encode(records), selected };
    const result = preview(source, inputs);
    assert.deepEqual(result.execution.inputs, ['records', 'selected']);
    assert.equal(result.observation.kind, 'value');
    assert.equal(result.bindingObservation.kind, 'value');
    let native;
    new vm.Script(compiled).runInNewContext({ records: decode(inputs.records), selected, sink: payload => { native = payload; } }, { timeout: 100 });
    assert.deepEqual(result.projections.map(row => row.value), [encode(native.balance), encode(native.date)]);
    assert.equal(result.observation.trace.filter(row => row.event === 'computed-read').length, 1);
    assert.equal(result.observation.trace.filter(row => row.bindingRole === 'call-argument').length, 1);
    const report = renderFunctionResultPreview(result, { snippets: loc => source.slice(loc.start, loc.end) });
    assert.match(report, /지정한 호출 지점 입력/);
    assert.match(report, /실제 앱의 호출 도달/);
    assert.match(report, /1번째 호출 인수/);
    assert.ok(report.includes('records\\[selected\\]'));
    assert.ok(!report.includes('원래 호출 인수 식을 평가한 값이라는 증거가 아니다'));
  }
});

test('unused arguments are evaluated before parameter destructuring and are not substituted repeatedly', () => {
  const source = `function normalize({ value }: any, unused: any) { return { a: value, b: value }; }
const { a, b } = normalize(first, second.field); sink({ a, b });`;
  const failed = preview(source, { first: null, second: null });
  assert.equal(failed.observation.kind, 'throw');
  assert.deepEqual(failed.observation.trace.map(row => [row.event, row.key ?? row.bindingRole]), [['bind', 'call-argument'], ['throw', 'field']]);
  const failedBinding = preview(source, { first: null, second: { $record: { field: 7 } } });
  assert.equal(failedBinding.observation.kind, 'throw');
  assert.equal(failedBinding.observation.trace.at(-1).key, 'value');
  assert.equal(failedBinding.observation.trace.filter(row => row.bindingRole === 'call-argument').length, 2);
  const succeeded = preview(source, { first: { $record: { value: 5 } }, second: { $record: {} } });
  assert.deepEqual(succeeded.projections.map(row => row.value), [5, 5]);
  assert.equal(succeeded.observation.trace.filter(row => row.bindingRole === 'destructured-property').length, 1);
});

test('argument objects retain constructed prototype limits and lexical input names do not collide with parameter names', () => {
  const source = `function normalize(input: any, other: any) { return { value: input.value + other }; }
const { value } = normalize({ value: other }, input); sink({ value });`;
  assert.equal(preview(source, { other: 'a', input: 2 }).projections[0].value, 'a2');
  const missing = `function normalize(input: any) { return { value: input.missing }; }
const { value } = normalize({ own: number }); sink({ value });`;
  assert.equal(preview(missing, { number: 3 }).observation.kind, 'unsupported');
  const noArguments = `function normalize() { return { value: 9 }; } const { value } = normalize(); sink({ value });`;
  assert.deepEqual(preview(noArguments, {}).execution.inputs, []);
  assert.equal(preview(noArguments, {}).projections[0].value, 9);
});

test('incomplete argument contracts and source-visible function aliases or assignments do not become call models', () => {
  for (const source of [
    'function normalize(x: any) { return x; } const value = normalize(); sink({ value });',
    'function normalize(x: any) { return x; } const value = normalize(input, extra); sink({ value });',
    'function normalize(x: any) { return x; } const value = normalize(effect()); sink({ value });',
    'function normalize(x: any) { return x; } const alias = normalize; const value = normalize(input); sink({ value });',
    'function normalize(x: any) { return x; } normalize = other; const value = normalize(input); sink({ value });',
  ]) assert.throws(() => preview(source, { input: 4 }), Unsupported);
});
