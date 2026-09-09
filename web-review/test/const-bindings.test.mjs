import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { liftConstBindings } from '../src/const-bindings.mjs';
import { liftCallBindings } from '../src/result-preview.mjs';
import { observe, compare, encode, decode, Unsupported } from '../src/core.mjs';
import { renderExecution } from '../src/report.mjs';

test('inline const normalization and extracted function preserve selected local values', () => {
  const before = `function caller() {
const settings = records[selected];
const date = settings?.date ? settings.date.trim() : undefined;
const balance = settings?.amount ?? 0;
send({ date, balance });
}`;
  const after = `function normalize(settings: any) { return { date: settings?.date ? settings.date.trim() : undefined, balance: settings?.amount ?? 0 }; }
function caller() { const { date, balance } = normalize(records[selected]); send({ date, balance }); }`;
  const left = liftConstBindings(before, { startLine: 2, endLine: 4, outputs: ['date', 'balance'], filename: '/before.tsx' });
  const right = liftCallBindings(after, { functionName: 'normalize', filename: '/after.tsx' });
  assert.deepEqual(left.observationBindings, right.observationBindings);
  assert.deepEqual(left.inputs, ['records', 'selected']);
  const domains = { records: [encode({ a: { date: ' pad ', amount: 0 } }), encode({ a: null }), encode({})], selected: ['a', 'missing'] };
  const compared = compare(left.ir, right.ir, domains);
  assert.equal(compared.status, 'equal-in-declared-domain');
  assert.equal(compared.checked, 6);
  const native = new vm.Script(`${before.slice(before.indexOf('const settings'), before.indexOf('send('))}\n({ date, balance });`);
  for (const records of domains.records) for (const selected of domains.selected) {
    const actual = native.runInNewContext({ records: decode(records), selected }, { timeout: 100 });
    assert.deepEqual(observe(left.ir, { records, selected }).value, encode(Object.fromEntries(Object.entries(actual))));
  }
  const inputs = { records: domains.records[0], selected: 'a' }, observed = observe(left.ir, inputs, { trace: true });
  assert.ok(observed.trace.every(row => !row.source?.file?.startsWith('/binding/')));
  assert.equal(observed.trace.filter(row => row.event === 'observed-binding').length, 2);
  const report = renderExecution(left, observed, { inputs, snippets: loc => before.slice(loc.start, loc.end) });
  assert.match(report, /앱의 객체 생성이 아니다/);
  assert.match(report, /원본 문자열 자체는 바꾸지 않았다/);
  assert.ok(report.includes('/before.tsx:3'));
});

test('every selected const runs including unused declarations and comma declarators', () => {
  const source = `const chosen = input;
const unused = other.field, extra = 9;
const result = chosen;`;
  const artifact = liftConstBindings(source, { startLine: 1, endLine: 3, outputs: ['result'] });
  assert.equal(artifact.prefix.bindings.length, 4);
  assert.deepEqual(observe(artifact.ir, { input: 3, other: null }), { kind: 'throw', name: 'TypeError' });
  assert.deepEqual(observe(artifact.ir, { input: 3, other: { $record: {} } }).value, { $record: { result: 3 } });
});

test('selected const results link real symbol uses without propagating values across mutation or captures', () => {
  const source = `function Screen() {
const result = input;
const other = 1;
result.amount = 9;
function captured() { return result; }
function shadow(result) { return result; }
type Shape = typeof result;
send({ result });
return <Child amount={result} count={other}/>;
}`;
  const artifact = liftConstBindings(source, { startLine: 2, endLine: 3, outputs: ['result', 'other'], filename: '/result.tsx' });
  const [result, other] = artifact.outputSources.bindings;
  assert.equal(result.useCount, 5); assert.equal(other.useCount, 1);
  assert.equal(result.uses.filter(use => use.nestedFunction).length, 1);
  assert.equal(result.uses.filter(use => use.kind === 'type-only').length, 1);
  const use = result.uses.find(use => use.kind === 'jsx-attribute');
  assert.equal(use.tag, 'Child'); assert.equal(use.attribute, 'amount'); assert.equal(use.direct, true);
  assert.equal(source.slice(use.source.start, use.source.end), 'result');
  const inputs = { input: encode({ amount: 1 }) }, observation = observe(artifact.ir, inputs, { trace: true });
  assert.equal(observation.value.$record.result.$record.amount, 1);
  const report = renderExecution(artifact, observation, { inputs, snippets: loc => source.slice(loc.start, loc.end) });
  assert.match(report, /Child.amount 속성에 직접 참조/);
  assert.match(report, /같은 값이 전달됐다는 뜻은 아니다/);
  assert.ok(artifact.outputSources.bindings.flatMap(binding => binding.uses).every(use => use.source.file === '/result.tsx'));
});

test('const output source references have explicit truncation and do not make an aborted binding look initialized', () => {
  const source = 'const result = input.value;\n' + Array.from({ length: 2050 }, () => 'use(result);').join('\n');
  const artifact = liftConstBindings(source, { startLine: 1, endLine: 1, outputs: ['result'] });
  const binding = artifact.outputSources.bindings[0];
  assert.equal(binding.useCount, 2050); assert.equal(binding.uses.length, 2048); assert.equal(binding.usesTruncated, true);
  const observed = observe(artifact.ir, { input: null }, { trace: true });
  assert.equal(observed.kind, 'throw');
  const report = renderExecution(artifact, observed);
  assert.match(report, /2050곳 중 2048곳만 표시/); assert.match(report, /초기화가 완료되지 않았을 수도/);
});

test('missing constructed properties and non-string trim receivers do not gain values', () => {
  const source = `const constructed = { present: 1 };
const result = constructed.missing;`;
  const artifact = liftConstBindings(source, { startLine: 1, endLine: 2, outputs: ['result'] });
  assert.equal(observe(artifact.ir, {}).kind, 'unsupported');
  const trim = liftConstBindings('const result = input.trim();', { startLine: 1, endLine: 1, outputs: ['result'] });
  assert.equal(observe(trim.ir, { input: 8 }).kind, 'unsupported');
  assert.equal(observe(trim.ir, { input: null }).kind, 'throw');
});

test('non-contiguous regions, mutation, nested bindings and lexical use before initialization are refused', () => {
  const cases = [
    { source: 'const a = 1;\nwork();\nconst b = 2;', end: 3 },
    { source: 'let a = 1;\nconst b = 2;', end: 2 },
    { source: 'const a = unknown();\nconst b = 2;', end: 2 },
    { source: 'const a = b;\nconst b = 2;', end: 2 },
    { source: 'const a = later;\nconst b = 2;\nconst later = 3;', end: 2 },
    { source: 'const a = a;\nconst b = 2;', end: 2 },
    { source: 'const a = 1;\nconst a = 2;\nconst b = a;', end: 3 },
    { source: 'const { a } = input;\nconst b = a;', end: 2 },
    { source: 'const a = 1;\nfunction nested() { const b = 2; }', end: 2 },
  ];
  for (const item of cases) assert.throws(() => liftConstBindings(item.source, { startLine: 1, endLine: item.end, outputs: ['b'] }), Unsupported, item.source);
  assert.throws(() => liftConstBindings('const a = 1;', { startLine: 1, endLine: 1, outputs: ['missing'] }), Unsupported);
  assert.throws(() => liftConstBindings('const a = 1;', { startLine: 1, endLine: 1, outputs: ['a', 'a'] }), Unsupported);
});

test('pure refactoring comparison detects a changed normalization instead of accepting different structure alone', () => {
  const before = liftConstBindings('const balance = input.amount ?? 0;', { startLine: 1, endLine: 1, outputs: ['balance'] });
  const after = liftCallBindings('function normalize(settings: any) { return { balance: settings.amount || 0 }; } const { balance } = normalize(input);', { functionName: 'normalize' });
  const result = compare(before.ir, after.ir, { input: [encode({ amount: 0 }), encode({ amount: -0 }), encode({ amount: '' }), encode({ amount: 4 })] });
  assert.equal(result.checked, 4);
  assert.equal(result.changes.length, 2); // -0 and empty string are erased by ||.
});
