import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { instrumentTransactionSelection, createTransactionProbe, projectTransactionTrace, attachNativeTraceEvidence } from '../scripts/array-trace-oracle.mjs';
import { ARRAY_PROFILE, encode, observe } from '../src/core.mjs';
import { liftConstBindings } from '../src/const-bindings.mjs';
import { buildExecutionReading } from '../src/report.mjs';

const before = 'const transactionsToDisplay = !isSearching ? previewTransactions.concat(transactions.filter(t => !t.is_child)) : transactions;';
const after = before.replace('!isSearching ?', '!isSearching && !isFiltered ?');
const pack = value => encode(value, 0, undefined, { arrays: true });
function run(source, input, instrumentation) {
  const record = instrumentation && createTransactionProbe(instrumentation);
  try {
    const value = new vm.Script(`${instrumentation?.source ?? source}\ntransactionsToDisplay;`).runInNewContext({ ...input, ...(record ? { [instrumentation.probeName]: record.probe } : {}) }, { timeout: 100 });
    return { outcome: { kind: 'value', value: pack({ transactionsToDisplay: Array.from(value) }) }, events: record?.events };
  } catch (error) {
    if (error.name !== 'TypeError') throw error;
    return { outcome: { kind: 'throw', name: error.name }, events: record?.events };
  }
}

test('native instrumentation preserves original outcomes and records lazy selection and ordered predicates', () => {
  for (const source of [before, after]) {
    const instrumentation = instrumentTransactionSelection(source);
    const artifact = liftConstBindings(source, { startLine: 1, endLine: 1, outputs: ['transactionsToDisplay'], arrayProfile: ARRAY_PROFILE });
    for (const isSearching of [false, true]) for (const isFiltered of [false, true]) {
      const input = { isSearching, isFiltered, previewTransactions: [{ id: 'p' }], transactions: [{ is_child: false }, { is_child: true }, {}] };
      const baseline = run(source, input), instrumented = run(source, input, instrumentation);
      assert.deepEqual(instrumented.outcome, baseline.outcome);
      const observation = observe(artifact.ir, Object.fromEntries(Object.entries(input).map(([name, value]) => [name, pack(value)])), { trace: true });
      const { trace, traceTruncated, ...outcome } = observation;
      assert.deepEqual(outcome, baseline.outcome);
      assert.deepEqual(projectTransactionTrace(observation), instrumented.events);
    }
  }
});

test('a throwing receiver or predicate leaves a matching native record prefix without completed filter or concat', () => {
  for (const source of [before, after]) {
    const instrumentation = instrumentTransactionSelection(source);
    const artifact = liftConstBindings(source, { startLine: 1, endLine: 1, outputs: ['transactionsToDisplay'], arrayProfile: ARRAY_PROFILE });
    for (const [previewTransactions, transactions] of [[null, [{}]], [[], [{ is_child: false }, null, {}]], [[], null]]) {
      const input = { isSearching: false, isFiltered: false, previewTransactions, transactions };
      const baseline = run(source, input), instrumented = run(source, input, instrumentation);
      assert.deepEqual(instrumented.outcome, baseline.outcome); assert.equal(baseline.outcome.kind, 'throw');
      const observation = observe(artifact.ir, Object.fromEntries(Object.entries(input).map(([name, value]) => [name, pack(value)])), { trace: true });
      assert.deepEqual(projectTransactionTrace(observation), instrumented.events);
      assert.equal(instrumented.events.some(row => ['filter-result', 'concat-result'].includes(row.event)), false);
    }
  }
});

test('the fixed-case oracle refuses broader programs and enforces record and source bounds', () => {
  for (const source of [before + '\nwork();', before.replace('!t.is_child', 'mutate(t)'), after.replace('&&', '||'), before.replace('t =>', 'async t =>'), before.replace('previewTransactions.concat', 'other.concat'), before.replace('const ', 'let ')]) assert.throws(() => instrumentTransactionSelection(source));
  assert.throws(() => instrumentTransactionSelection(' '.repeat(65537)));
  assert.throws(() => instrumentTransactionSelection(before, { sourceOffset: -1 }));
  const instrumentation = instrumentTransactionSelection(before, { sourceOffset: 17 });
  for (const probe of instrumentation.probes) { assert.equal(probe.source.start, probe.start + 17); assert.equal(probe.source.end, probe.end + 17); }
  const record = createTransactionProbe(instrumentation, { limit: 1 });
  assert.equal(record.probe(0, false), false); assert.throws(() => record.probe(0, true));
  assert.throws(() => projectTransactionTrace({ kind: 'value', trace: [], traceTruncated: true }));
  assert.throws(() => projectTransactionTrace({ kind: 'unsupported', trace: [], traceTruncated: false }));
  assert.throws(() => projectTransactionTrace({ kind: 'value', trace: [{ event: 'future' }], traceTruncated: false }));
});

function joinedFixture() {
  const artifact = liftConstBindings(before, { startLine: 1, endLine: 1, outputs: ['transactionsToDisplay'], arrayProfile: ARRAY_PROFILE });
  const input = { isSearching: false, isFiltered: true, previewTransactions: [{ id: 'p' }], transactions: [{ is_child: false }, { is_child: true }, {}] };
  const inputs = Object.fromEntries(Object.entries(input).map(([name, value]) => [name, pack(value)]));
  const observation = observe(artifact.ir, inputs, { trace: true });
  const measured = run(before, input, instrumentTransactionSelection(before));
  const identity = { inputs, key: 'fixed', revision: 'before' };
  return { observation, reading: buildExecutionReading(observation), native: { group: 'fixed-domain', ...identity, ...measured }, identity };
}

test('native evidence marks only the matched projection rows and leaves bookkeeping unstamped', () => {
  const f = joinedFixture(), joined = attachNativeTraceEvidence(f.reading, f.observation, f.native, f.identity);
  assert.deepEqual(joined.nativeEvidence.comparedSequences, [1, 3, 4, 5, 6, 9]);
  assert.equal(joined.nativeEvidence.status, 'matched-fixed-native-projection');
  assert.equal(Object.hasOwn(f.reading, 'nativeEvidence'), false);
  assert.match(joined.nativeEvidence.notCompared, /저장·복사 세부 단계/);
  assert.match(joined.nativeEvidence.notCompared, /원본 앱 실행/);
});

test('native evidence refuses another input, revision, record order, outcome or reading row', () => {
  const f = joinedFixture();
  // Files/observations are independent in the producer. Cloning the whole
  // fixture together would retain shared references and mutate both sides.
  const altered = mutate => { const copy = Object.fromEntries(Object.entries(f).map(([key, value]) => [key, structuredClone(value)])); mutate(copy); assert.throws(() => attachNativeTraceEvidence(copy.reading, copy.observation, copy.native, copy.identity)); };
  altered(c => { c.native.inputs.isFiltered = false; });
  altered(c => { c.native.revision = 'after'; });
  altered(c => { c.native.key = 'another'; });
  altered(c => { c.native.group = 'fault-probe'; });
  altered(c => { c.identity.group = 'unknown'; c.native.group = 'unknown'; });
  altered(c => { c.native.events.reverse(); });
  altered(c => { c.native.outcome = { kind: 'throw', name: 'TypeError' }; });
  altered(c => { c.reading.rows[0].source.start++; });
  altered(c => { c.reading.rows[0].sequence = 2; });
  altered(c => { c.reading.truncated = true; });
  altered(c => { c.reading.rows.pop(); });
});

test('fault evidence requires its explicit group and does not mark the IR error location as independently matched', () => {
  const artifact = liftConstBindings(before, { startLine: 1, endLine: 1, outputs: ['transactionsToDisplay'], arrayProfile: ARRAY_PROFILE });
  const input = { isSearching: false, isFiltered: true, previewTransactions: null, transactions: [{}] };
  const inputs = Object.fromEntries(Object.entries(input).map(([name, value]) => [name, pack(value)]));
  const observation = observe(artifact.ir, inputs, { trace: true }), reading = buildExecutionReading(observation);
  const identity = { inputs, key: '0', revision: 'before', group: 'fault-probe' };
  const native = { ...identity, ...run(before, input, instrumentTransactionSelection(before)) };
  const joined = attachNativeTraceEvidence(reading, observation, native, identity);
  assert.equal(joined.outcome, 'throw'); assert.equal(native.outcome.name, 'TypeError');
  assert.equal(joined.nativeEvidence.group, 'fault-probe');
  const thrown = joined.rows.find(row => row.event === 'throw'); assert.ok(thrown);
  assert.equal(joined.nativeEvidence.comparedSequences.includes(thrown.sequence), false);
  assert.deepEqual(joined.nativeEvidence.comparedSequences, [1]);
  const { group, ...ordinaryIdentity } = identity;
  assert.throws(() => attachNativeTraceEvidence(reading, observation, native, ordinaryIdentity));
  assert.match(joined.nativeEvidence.notCompared, /오류 위치/);
});
