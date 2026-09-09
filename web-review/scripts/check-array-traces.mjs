import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { instrumentTransactionSelection, createTransactionProbe, projectTransactionTrace } from './array-trace-oracle.mjs';
import { liftConstBindings } from '../src/const-bindings.mjs';
import { encode, decode, observe } from '../src/core.mjs';
import { ENGINE_SHA256 } from '../src/fingerprint.mjs';
import { hash } from '../src/typescript.mjs';

const pkg = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'), root = path.dirname(pkg);
const read = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const arrayResults = read(path.join(root, 'build/web-review/array-results.json'));
const selectionFile = path.join(pkg, 'corpus/array-slices.json'), selection = read(selectionFile);
assert.equal(arrayResults.engineSha256, ENGINE_SHA256);
assert.equal(arrayResults.producerSha256, hash(fs.readFileSync(path.join(pkg, 'scripts/check-arrays.mjs'))));
assert.equal(arrayResults.selectionSha256, hash(fs.readFileSync(selectionFile)));
assert.equal(selection.targets.length, 1);
const target = selection.targets[0]; assert.equal(target.id, 'actual-filter-transaction-selection');
const previous = arrayResults.results.find(row => row.id === target.id); assert.ok(previous);
const directory = path.join(root, 'build/web-review/arrays', target.id), domains = read(path.join(directory, 'domains.json'));
assert.equal(hash(JSON.stringify(domains)), arrayResults.domainsSha256);
const output = path.join(root, 'build/web-review/native-traces', target.id);
const artifacts = {}, originals = {}, instrumented = {}, sourceRecords = {}, code = {};
for (const revision of ['before', 'after']) {
  const artifact = read(path.join(directory, `${revision}.json`)), source = fs.readFileSync(artifact.source.file, 'utf8');
  assert.equal(hash(source), previous.sourceSha256[revision]);
  assert.deepEqual(liftConstBindings(source, { ...target[revision], outputs: target.outputs, arrayProfile: target.arrayProfile, filename: artifact.source.file }), artifact);
  artifacts[revision] = artifact;
  const selected = source.slice(artifact.prefix.source.start, artifact.prefix.end);
  assert.equal(hash(selected), previous.selectedSourceSha256[revision]);
  const instrumentation = instrumentTransactionSelection(selected, { sourceOffset: artifact.prefix.source.start });
  originals[revision] = new vm.Script(`${selected}\ntransactionsToDisplay;`);
  instrumented[revision] = { ...instrumentation, script: new vm.Script(`${instrumentation.source}\ntransactionsToDisplay;`) };
  code[revision] = instrumentation.source;
  sourceRecords[revision] = { file: artifact.source.file, sourceSha256: hash(source), selectedSourceSha256: hash(selected),
    instrumentedSourceSha256: hash(instrumentation.source), probes: instrumentation.probes };
}
const pack = value => encode(value, 0, undefined, { arrays: true });
function native(revision, inputs, withProbes) {
  const record = withProbes && createTransactionProbe(instrumented[revision]);
  const context = Object.fromEntries(Object.entries(inputs).map(([name, value]) => [name, decode(value, 0, { arrays: true })]));
  if (record) { assert.equal(Object.hasOwn(context, instrumented[revision].probeName), false); context[instrumented[revision].probeName] = record.probe; }
  let outcome;
  try {
    const value = (withProbes ? instrumented[revision].script : originals[revision]).runInNewContext(context, { timeout: 100 });
    assert.ok(Array.isArray(value)); assert.equal(Reflect.ownKeys(value).length, value.length + 1);
    // As in check-arrays, only the outer array crosses VM realms; the fixed
    // inputs are decoded plain snapshots, with unmodified standard methods.
    outcome = { kind: 'value', value: pack({ transactionsToDisplay: Array.from(value) }) };
  } catch (error) { if (error.name !== 'TypeError') throw error; outcome = { kind: 'throw', name: error.name }; }
  return { outcome, ...(record ? { events: record.events } : {}) };
}
const rows = [];
function check(revision, inputs, group, key) {
  const baseline = native(revision, inputs, false), measured = native(revision, inputs, true);
  assert.deepEqual(measured.outcome, baseline.outcome, `${revision}:${key}: instrumentation changed outcome`);
  const observation = observe(artifacts[revision].ir, inputs, { trace: true });
  const { trace, traceTruncated, ...outcome } = observation;
  assert.deepEqual(outcome, baseline.outcome, `${revision}:${key}: IR differs from untouched native source`);
  const projected = projectTransactionTrace(observation);
  assert.deepEqual(projected, measured.events, `${revision}:${key}: projected event order, value or source differs`);
  rows.push({ revision, group, key, inputs, outcome, events: measured.events, irRecordedEvents: trace.length });
}
for (const isSearching of domains.isSearching) for (const isFiltered of domains.isFiltered) for (let t = 0; t < domains.transactions.length; t++) for (let p = 0; p < domains.previewTransactions.length; p++) {
  const inputs = { isSearching, isFiltered, transactions: domains.transactions[t], previewTransactions: domains.previewTransactions[p] };
  for (const revision of ['before', 'after']) check(revision, inputs, 'fixed-domain', [Number(isSearching), Number(isFiltered), t, p].join(':'));
}
const faults = read(path.join(directory, 'fault-probes.json')); assert.equal(faults.length, 24);
for (const [index, fault] of faults.entries()) {
  check(fault.revision, fault.inputs, 'fault-probe', String(index));
  assert.deepEqual(rows.at(-1).outcome, fault.observation);
}
assert.equal(rows.length, 344);
const result = {
  schema: 'web-array-native-traces-1', status: 'matched-fixed-projection', engineSha256: ENGINE_SHA256,
  producerSha256: hash(fs.readFileSync(fileURLToPath(import.meta.url))), oracleSha256: hash(fs.readFileSync(new URL('./array-trace-oracle.mjs', import.meta.url))),
  arrayProducerSha256: arrayResults.producerSha256, selectionSha256: arrayResults.selectionSha256, domainsSha256: arrayResults.domainsSha256,
  case: target.case, target: target.id, sources: sourceRecords, pairedInputs: 160, faultRevisionInputs: faults.length,
  originalReexecutions: rows.length, instrumentedExecutions: rows.length,
  projectedEvents: rows.reduce((sum, row) => sum + row.events.length, 0), thrownOutcomes: rows.filter(row => row.outcome.kind === 'throw').length,
  scope: '원본 선택 const와 계측본의 결과·TypeError를 대조하고, 공통된 조건·단락 앞값·필터 판단·완료 길이의 값과 순서·원본 구간을 IR 기록과 대조',
  notProven: [
    '임의 TypeScript 프로그램의 계측 의미 보존; 두 고정 선택식 모양만 허용한다.',
    'IR 기록 전체: 저장·복사 세부 단계·오류 위치·실행 시간·스택은 대조하지 않았다.',
    '도메인 밖 값, 변경된 내장 메서드·prototype·getter·Proxy·객체 별칭의 의미.',
    '원본 앱의 hook·상태·React·DOM·서버 실행과 사람의 검토 개선.',
  ],
  notes: ['기존 배열 검사의 같은 입력을 다시 실행했다. 새로운 사용자 입력 범위나 새로운 사례로 집계하지 않는다.', '계측 probe는 입력·내장 메서드를 바꾸지 않고 관찰한 동일 값을 반환한다. 원본과 계측본의 결과를 매 입력에서 별도로 비교했다.'],
  wholeBehaviorCasesVerified: 0, humanParticipants: 0,
};
fs.mkdirSync(output, { recursive: true });
for (const revision of ['before', 'after']) fs.writeFileSync(path.join(output, `${revision}-instrumented.js`), code[revision] + '\n');
fs.writeFileSync(path.join(output, 'observations.json'), JSON.stringify(rows, null, 2) + '\n');
result.observationsSha256 = hash(fs.readFileSync(path.join(output, 'observations.json')));
fs.writeFileSync(path.join(root, 'build/web-review/array-trace-results.json'), JSON.stringify(result, null, 2) + '\n');
process.stdout.write(JSON.stringify({ status: result.status, engineSha256: ENGINE_SHA256, originalReexecutions: result.originalReexecutions,
  instrumentedExecutions: result.instrumentedExecutions, projectedEvents: result.projectedEvents, thrownOutcomes: result.thrownOutcomes, output }) + '\n');
