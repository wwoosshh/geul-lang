import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { spawnSync } from 'node:child_process';
import { liftConstBindings } from '../src/const-bindings.mjs';
import { liftProject } from '../src/project.mjs';
import { liftCallArguments } from '../src/call-entry.mjs';
import { observe, evaluate, encode, Unsupported, STRING_LIMIT } from '../src/core.mjs';
import { buildArtifactReading, renderReading } from '../src/reading.mjs';
import { renderExecution } from '../src/report.mjs';
import { ENGINE_SHA256, ENGINE_RUNTIME } from '../src/fingerprint.mjs';

const source = 'const result = input.toLowerCase().trim();';
const artifact = liftConstBindings(source, { startLine: 1, endLine: 1, outputs: ['result'] });
const native = new vm.Script(source + '\nresult;');
const samples = [
  ['', ''], [' AbC ', 'abc'], ['\u0130', 'i\u0307'], ['I', 'i'], ['\u0131', '\u0131'],
  ['ΟΣ', 'ος'], ['ΟΣΑ', 'οσα'], ['Σ', 'σ'], ['Ο\u0301Σ', 'ο\u0301ς'],
  ['\u{10400}', '\u{10428}'], ['ẞ', 'ß'], ['ß', 'ß'], ['한글', '한글'],
  ['\uFEFF\u00A0A\u2028', 'a'], ['\u200BA\u200B', '\u200Ba\u200B'],
  ['\uD800A\uDC00', '\uD800a\uDC00'], ['A\u0000B', 'a\u0000b'],
];

test('Unicode lowercase preserves expansion, context, surrogate pairs and trim boundaries', () => {
  for (const [input, expected] of samples) {
    assert.equal(native.runInNewContext({ input }, { timeout: 100 }), expected);
    assert.deepEqual(observe(artifact.ir, { input }), { kind: 'value', value: { $record: { result: expected } } });
  }
  const points = ['A', 'I', 'İ', 'Σ', 'Ο', '\u0301', '\u0345', '\u200D', '\u{10400}', '\uD800', '\uDC00', ' ', '\uFEFF', '\u200B', '한', 'ẞ'];
  let seed = 721;
  for (let index = 0; index < 200; index++) {
    let input = '';
    for (let part = 0; part < 13; part++) { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; input += points[seed >>> 28]; }
    const expected = native.runInNewContext({ input }, { timeout: 100 });
    assert.equal(observe(artifact.ir, { input }).value.$record.result, expected);
  }
});

test('non-string receivers stay unsupported and a lower-case failure skips trim', () => {
  for (const input of [null, undefined]) {
    assert.throws(() => native.runInNewContext({ input }, { timeout: 100 }), { name: 'TypeError' });
    const observed = observe(artifact.ir, { input: encode(input) }, { trace: true });
    assert.equal(observed.kind, 'throw');
    assert.equal(observed.trace.filter(row => row.event === 'intrinsic').length, 0);
    assert.equal(observed.trace.find(row => row.event === 'throw').key, 'toLowerCase');
  }
  for (const input of [0, false, {}, { toLowerCase: 1 }]) assert.equal(observe(artifact.ir, { input: encode(input) }).kind, 'unsupported');
  for (const expression of ['input?.toLowerCase()', 'input.toLowerCase?.()', 'input.toLowerCase(1)', 'input.toLocaleLowerCase()', 'input["toLowerCase"]()', 'input.toLowerCase.call(input)']) {
    assert.throws(() => liftConstBindings(`const result = ${expression};`, { startLine: 1, endLine: 1, outputs: ['result'] }), Unsupported);
  }
});

test('lowercase charges expanded strings and refuses results beyond the string limit', () => {
  const ir = artifact.ir.value.value; // toLowerCase, before trim
  assert.equal(ir.name, 'string.toLowerCase');
  assert.equal(observe(ir, { input: 'A'.repeat(40000) }).kind, 'value');
  assert.equal(observe(ir, { input: 'İ'.repeat(40000) }).kind, 'unsupported');
  assert.throws(() => evaluate(ir, { input: 'İ'.repeat(STRING_LIMIT / 2 + 1) }, { steps: 10 * STRING_LIMIT }), /길이 제한/);
});

test('project and call preparation share string semantics and reading keeps the correct operation', () => {
  const project = liftProject({ files: { 'f.ts': 'export function f(input: string){return input.toLowerCase().trim();}' }, entry: 'f.ts', functionName: 'f' });
  const call = liftCallArguments('function f(){const clean = input.toLowerCase(); if(!clean)return; save(clean.trim());}', { callee: 'save' });
  for (const [input, expected] of samples) {
    assert.equal(observe(project.ir, { input }).value, expected);
    const row = observe(call.ir, { input }).value.$record;
    if (input === '') assert.equal(row.stage, 'early-return');
    else { assert.equal(row.stage, 'arguments-ready'); assert.equal(row.argument1, expected); }
  }
  assert.ok(artifact.contract.assumptions.some(text => text.includes('toLowerCase')));
  assert.ok(project.contract.assumptions.some(text => text.includes('toLowerCase')));
  const reading = buildArtifactReading(call);
  const serialized = JSON.stringify(reading);
  assert.match(serialized, /standard-string-to-lower-case/);
  assert.match(serialized, /빈 문자열인지/);
  const text = renderReading(call, reading);
  assert.match(text, /유니코드 기본 규칙으로 소문자 변환/);
  const observed = observe(artifact.ir, { input: ' İ ' }, { trace: true });
  assert.deepEqual(observed.trace.filter(row => row.event === 'intrinsic').map(row => row.name), ['string.toLowerCase', 'string.trim']);
  const report = renderExecution(artifact, observed);
  assert.match(report, /toLowerCase/); assert.match(report, /trim/);
});

test('a different runtime Unicode descriptor invalidates the engine fingerprint', () => {
  const url = new URL('../src/fingerprint.mjs', import.meta.url).href;
  const child = spawnSync(process.execPath, ['--input-type=module', '-e', `Object.defineProperty(process.versions,'unicode',{value:'test-other-unicode'}); const m=await import(${JSON.stringify(url)}); process.stdout.write(JSON.stringify({hash:m.ENGINE_SHA256,runtime:m.ENGINE_RUNTIME}));`], { encoding: 'utf8', timeout: 10000 });
  assert.equal(child.status, 0, child.stderr);
  const changed = JSON.parse(child.stdout);
  assert.notEqual(changed.hash, ENGINE_SHA256);
  assert.deepEqual(changed.runtime, { ...ENGINE_RUNTIME, unicode: 'test-other-unicode' });
});

test('compact string reading follows execution order while preserving every source-linked operation', () => {
  const reading = buildArtifactReading(artifact), calculation = reading.tree.children[0].node;
  assert.deepEqual(calculation.stringPipeline.operations.map(row => row.name), ['string.toLowerCase', 'string.trim']);
  assert.ok(calculation.fragment.indexOf('소문자 변환') < calculation.fragment.indexOf('양끝 공백'));
  assert.match(calculation.fragment, /null·undefined는 TypeError/);
  assert.equal(calculation.children[0].node.children[0].node.kind, 'input');
  for (const operation of calculation.stringPipeline.operations) assert.ok(operation.source && operation.path);
  const reverse = liftConstBindings('const result = input.trim().toLowerCase();', { startLine: 1, endLine: 1, outputs: ['result'] });
  const reversed = buildArtifactReading(reverse).tree.children[0].node;
  assert.deepEqual(reversed.stringPipeline.operations.map(row => row.name), ['string.trim', 'string.toLowerCase']);
  assert.ok(reversed.fragment.indexOf('양끝 공백') < reversed.fragment.indexOf('소문자 변환'));
  const branched = liftConstBindings('const result = (condition ? input : other).toLowerCase();', { startLine: 1, endLine: 1, outputs: ['result'] });
  assert.equal(buildArtifactReading(branched).tree.children[0].node.stringPipeline, undefined);
});
