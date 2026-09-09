import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { ENGINE_SHA256 } from '../src/fingerprint.mjs';
import { hash } from '../src/typescript.mjs';
import { observe } from '../src/core.mjs';
import { diffArrayValues } from '../src/array-diff.mjs';
import { buildExecutionReading } from '../src/report.mjs';
import { attachNativeTraceEvidence } from './array-trace-oracle.mjs';
import { inspectUnifiedPatch, intersectChangedLines } from './diff-spans.mjs';

const pkg = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'), root = path.dirname(pkg);
const output = path.join(root, 'build/web-inspector'), build = path.join(root, 'build/web-review');
const read = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const arrayDir = path.join(build, 'arrays/actual-filter-transaction-selection');
const joinedDir = path.join(build, 'output-props/actual-transaction-selection-destinations');
const arrays = read(path.join(build, 'array-results.json')), joins = read(path.join(build, 'output-prop-results.json'));
const nativeTraces = read(path.join(build, 'array-trace-results.json'));
const sliceScopes = read(path.join(build, 'slice-source-scope-results.json'));
const producerDependencies = Object.fromEntries(['array-trace-oracle.mjs', 'check-array-traces.mjs', 'diff-spans.mjs', 'check-slice-scope.mjs'].map(file => [file, hash(fs.readFileSync(path.join(pkg, 'scripts', file)))]));
assert.equal(sliceScopes.schema, 'web-slice-source-scope-results-1');
assert.equal(sliceScopes.engineSha256, ENGINE_SHA256);
assert.equal(sliceScopes.producerSha256, producerDependencies['check-slice-scope.mjs']);
assert.equal(sliceScopes.parserSha256, producerDependencies['diff-spans.mjs']);
assert.equal(sliceScopes.inventorySha256, hash(fs.readFileSync(path.join(pkg, 'corpus/change-inventory.lock.json'))));
const sourceScope = sliceScopes.results.find(row => row.id === 'actual-filter-transaction-selection');
assert.ok(sourceScope); assert.equal(sourceScope.status, 'source-overlap-only');
assert.equal(sourceScope.semanticCoverage, null); assert.equal(sourceScope.wholeBehaviorVerified, false);
assert.equal(sourceScope.selectionSha256, arrays.selectionSha256);
assert.equal(sourceScope.selectedProducerSha256, arrays.producerSha256);
assert.equal(nativeTraces.engineSha256, ENGINE_SHA256);
assert.equal(nativeTraces.status, 'matched-fixed-projection');
assert.equal(nativeTraces.producerSha256, producerDependencies['check-array-traces.mjs']);
assert.equal(nativeTraces.oracleSha256, producerDependencies['array-trace-oracle.mjs']);
assert.equal(nativeTraces.arrayProducerSha256, arrays.producerSha256);
assert.equal(nativeTraces.domainsSha256, arrays.domainsSha256);
const nativeObservationFile = path.join(build, 'native-traces/actual-filter-transaction-selection/observations.json');
assert.equal(hash(fs.readFileSync(nativeObservationFile)), nativeTraces.observationsSha256);
const nativeObservations = new Map();
const nativeRows = read(nativeObservationFile);
for (const row of nativeRows.filter(row => row.group === 'fixed-domain')) {
  const key = `${row.revision}:${row.key}`; assert.equal(nativeObservations.has(key), false); nativeObservations.set(key, row);
}
assert.equal(nativeObservations.size, 320);
for (const [record, producer] of [[arrays, 'check-arrays.mjs'], [joins, 'check-output-props.mjs']]) {
  assert.equal(record.engineSha256, ENGINE_SHA256);
  assert.equal(record.producerSha256, hash(fs.readFileSync(path.join(pkg, 'scripts', producer))));
}
assert.equal(arrays.selectionSha256, hash(fs.readFileSync(path.join(pkg, 'corpus/array-slices.json'))));
assert.equal(joins.selectionSha256, hash(fs.readFileSync(path.join(pkg, 'corpus/output-prop-links.json'))));
const arrayEvidence = arrays.results.find(row => row.id === 'actual-filter-transaction-selection');
assert.ok(arrayEvidence); assert.equal(arrayEvidence.nativeChecks, 320);
assert.deepEqual(sourceScope.changeScope, arrayEvidence.changeScope);
const domains = read(path.join(arrayDir, 'domains.json')), profiles = read(path.join(arrayDir, 'profiles.json'));
assert.equal(hash(JSON.stringify(domains)), arrays.domainsSha256);
assert.deepEqual(profiles.transactions.map(row => row.items), domains.transactions);
assert.deepEqual(profiles.previews, domains.previewTransactions);
assert.deepEqual(domains.isSearching, [false, true]); assert.deepEqual(domains.isFiltered, [false, true]);
const cli = (...args) => {
  const result = spawnSync(process.execPath, [path.join(pkg, 'src/cli.mjs'), ...args, '--json'], { encoding: 'utf8', maxBuffer: 16 * 1024 * 1024, timeout: 20_000 });
  assert.equal(result.status, 0, result.stderr); return JSON.parse(result.stdout);
};
const readings = {}, artifacts = {}, sources = [];
function addSource(id, revision, role, file, record, alias, initialLine) {
  const text = fs.readFileSync(file, 'utf8');
  assert.equal(hash(text), record.sha256);
  sources.push({ id, revision, role, file, alias, name: path.basename(file), sha256: record.sha256, text, initialLine });
}
for (const revision of ['before', 'after']) {
  const artifactFile = path.join(arrayDir, `${revision}.json`), indexFile = path.join(build, 'prop-projects/actual-mobile-report-filter', revision, 'prop-bindings.json');
  const reading = cli('read', '--file', artifactFile, '--props-index', indexFile);
  assert.deepEqual(reading, read(path.join(joinedDir, `${revision}-reading.json`)));
  assert.equal(Object.hasOwn(reading, 'observation'), false);
  readings[revision] = reading;
  const artifact = read(artifactFile), index = read(indexFile);
  artifacts[revision] = artifact;
  const scoped = sourceScope.revisions[revision];
  assert.equal(scoped.artifactSha256, hash(fs.readFileSync(artifactFile)));
  assert.equal(scoped.sourceSha256, artifact.source.sha256);
  assert.equal(scoped.file, artifact.source.file);
  assert.equal(scoped.absenceAnchor, null); assert.equal(scoped.spans.length, 1);
  assert.equal(scoped.spans[0].start, artifact.prefix.source.start);
  assert.equal(scoped.spans[0].end, artifact.prefix.end);
  assert.equal(artifact.source.sha256, arrayEvidence.sourceSha256[revision]);
  assert.equal(artifact.source.sha256, nativeTraces.sources[revision].sourceSha256);
  assert.equal(arrayEvidence.selectedSourceSha256[revision], nativeTraces.sources[revision].selectedSourceSha256);
  addSource(`parent-${revision}`, revision, 'parent', artifact.source.file, artifact.source, artifact.source.file, artifact.target.startLine);
  const parameter = reading.outputPropLinks.links[0].parameter.source;
  const childRecord = index.sources.find(row => row.file === parameter.file);
  assert.ok(childRecord); assert.ok(parameter.file.startsWith('/project/'));
  const childFile = path.resolve(path.dirname(index.manifest), parameter.file.slice('/project/'.length));
  addSource(`child-${revision}`, revision, 'child', childFile, childRecord, parameter.file, parameter.line);
}
const scopedPatch = fs.readFileSync(path.join(build, 'slice-source-scope/actual-filter-transaction-selection.patch'), 'utf8');
assert.equal(hash(scopedPatch), sourceScope.patchSha256);
const scopedDiff = inspectUnifiedPatch(scopedPatch, sources.find(row => row.id === 'parent-before').text, sources.find(row => row.id === 'parent-after').text);
assert.equal(sourceScope.reconstructedEntireAfterFile, true);
assert.deepEqual(sourceScope.hunks, scopedDiff.hunks);
for (const revision of ['before', 'after']) {
  const scoped = sourceScope.revisions[revision], source = sources.find(row => row.id === `parent-${revision}`);
  assert.equal(scoped.commit, sourceScope.changeScope[revision === 'before' ? 'parent' : 'head']);
  for (const span of scoped.spans) {
    assert.equal(span.line, source.text.slice(0, span.start).split('\n').length);
    assert.equal(span.endLine, source.text.slice(0, span.end - 1).split('\n').length);
    assert.equal(span.selectedTextSha256, hash(source.text.slice(span.start, span.end)));
  }
  const changed = intersectChangedLines(revision === 'before' ? scopedDiff.removed : scopedDiff.added, scoped.spans, source.text);
  assert.deepEqual(scoped.changedLines, changed);
  assert.equal(scoped.intersectingLines, changed.filter(row => row.selectedSpanIndices.length).length);
  assert.equal(scoped.outsideLines, changed.length - scoped.intersectingLines);
}
const comparison = cli('compare', '--before', path.join(arrayDir, 'before.json'), '--after', path.join(arrayDir, 'after.json'), '--domains', path.join(arrayDir, 'domains.json'));
assert.equal(comparison.checked, 160); assert.equal(comparison.changes.length, 34); assert.equal(comparison.unknown.length, 0);
const recordedComparison = read(path.join(arrayDir, 'comparison.json'));
for (const key of ['changes', 'changeRules', 'changeConditions', 'structureComparison']) assert.deepEqual(comparison[key], recordedComparison[key]);
const keyOf = (searching, filtered, transaction, preview) => [Number(searching), Number(filtered), transaction, preview].join(':');
const indices = (axis, value) => domains[axis].findIndex(item => JSON.stringify(item) === JSON.stringify(value));
const changed = new Map(comparison.changes.map(row => [keyOf(row.inputs.isSearching, row.inputs.isFiltered, indices('transactions', row.inputs.transactions), indices('previewTransactions', row.inputs.previewTransactions)), row]));
const states = [];
for (const isSearching of domains.isSearching) for (const isFiltered of domains.isFiltered) for (let transaction = 0; transaction < domains.transactions.length; transaction++) for (let preview = 0; preview < domains.previewTransactions.length; preview++) {
  const inputs = { isSearching, isFiltered, transactions: domains.transactions[transaction], previewTransactions: domains.previewTransactions[preview] };
  const key = keyOf(isSearching, isFiltered, transaction, preview), observations = {}, executions = {};
  for (const revision of ['before', 'after']) {
    const observation = observe(artifacts[revision].ir, inputs, { trace: true });
    assert.equal(observation.kind, 'value'); assert.ok(!observation.traceTruncated);
    observations[revision] = observation;
    const source = sources.find(row => row.id === `parent-${revision}`);
    const execution = buildExecutionReading(observation, { snippets: location => {
      assert.equal(location.file.replaceAll('\\', '/'), source.file.replaceAll('\\', '/'));
      assert.ok(location.start >= 0 && location.end <= source.text.length && location.start <= location.end);
      return source.text.slice(location.start, location.end);
    } });
    assert.equal(execution.status, 'recorded-ir-execution');
    assert.equal(execution.truncated, false);
    assert.equal(execution.rows.length, observation.trace.length);
    executions[revision] = attachNativeTraceEvidence(execution, observation, nativeObservations.get(`${revision}:${key}`), { inputs, key, revision });
  }
  const differs = JSON.stringify(observations.before.value) !== JSON.stringify(observations.after.value);
  assert.equal(differs, changed.has(key));
  if (differs) for (const revision of ['before', 'after']) assert.deepEqual(observations[revision].value, changed.get(key)[revision].value);
  const delta = diffArrayValues(observations.before.value.$record.transactionsToDisplay, observations.after.value.$record.transactionsToDisplay);
  assert.equal(delta.status, 'verified-array-observation-delta');
  states.push({ key, isSearching, isFiltered, transaction, preview, inputs, observations, executions, changed: differs, delta });
}
assert.equal(states.length, comparison.checked);
// Keep the fault probes outside the ordinary 160-pair domain. Their values
// exercise JavaScript boundaries and do not prove the application's callers
// can produce them. Each native row retains its original group and key.
const faultProbes = read(path.join(arrayDir, 'fault-probes.json'));
const faultNative = nativeRows.filter(row => row.group === 'fault-probe');
assert.equal(faultProbes.length, 24); assert.equal(faultNative.length, 24);
const boundaries = [];
const faultShapes = [
  { label: '거래 원소가 null', transactions: { $array: [null] }, previewTransactions: { $array: [] } },
  { label: '거래 원소가 undefined', transactions: { $array: [{ $value: 'undefined' }] }, previewTransactions: { $array: [] } },
  { label: '미리보기 목록이 null', transactions: { $array: [{ $record: { id: 'a' } }] }, previewTransactions: null },
];
for (const isSearching of [false, true]) for (const isFiltered of [false, true]) for (const shape of faultShapes) {
  const { label, ...values } = shape, inputs = { isSearching, isFiltered, ...values };
  const index = boundaries.length, observations = {}, executions = {};
  for (const [offset, revision] of ['before', 'after'].entries()) {
    const probeIndex = index * 2 + offset, key = String(probeIndex), probe = faultProbes[probeIndex];
    assert.equal(probe.revision, revision); assert.deepEqual(probe.inputs, inputs);
    const native = faultNative.filter(row => row.revision === revision && row.key === key);
    assert.equal(native.length, 1);
    const observation = observe(artifacts[revision].ir, inputs, { trace: true });
    const { trace, traceTruncated, ...outcome } = observation;
    assert.equal(traceTruncated, false); assert.deepEqual(outcome, probe.observation);
    observations[revision] = observation;
    const source = sources.find(row => row.id === `parent-${revision}`);
    const reading = buildExecutionReading(observation, { snippets: location => {
      assert.equal(location.file.replaceAll('\\', '/'), source.file.replaceAll('\\', '/'));
      assert.ok(location.start >= 0 && location.end <= source.text.length && location.start <= location.end);
      return source.text.slice(location.start, location.end);
    } });
    executions[revision] = attachNativeTraceEvidence(reading, observation, native[0], { inputs, key, revision, group: 'fault-probe' });
    // The original native checks independently compare only the thrown name.
    // The error location remains an IR record without a native projection mark.
    if (outcome.kind === 'throw') {
      assert.equal(outcome.name, 'TypeError');
      assert.ok(reading.rows.some(row => row.event === 'throw'));
    }
  }
  const beforeKind = observations.before.kind, afterKind = observations.after.kind;
  const expectedThrowsBefore = !isSearching, expectedThrowsAfter = !isSearching && !isFiltered;
  assert.equal(beforeKind === 'throw', expectedThrowsBefore); assert.equal(afterKind === 'throw', expectedThrowsAfter);
  boundaries.push({ key: String(index), label, inputs, observations, executions,
    transition: beforeKind === afterKind ? beforeKind === 'throw' ? 'same-throw-name' : 'same-value' : 'throw-to-value' });
  if (beforeKind === 'value' && afterKind === 'value') assert.deepEqual(observations.before.value, observations.after.value);
}
assert.equal(boundaries.length, 12);
assert.equal(boundaries.filter(row => row.transition === 'throw-to-value').length, 3);
assert.equal(boundaries.flatMap(row => Object.values(row.observations)).filter(row => row.kind === 'throw').length, 9);
assert.equal(boundaries.flatMap(row => Object.values(row.executions)).reduce((sum, row) => sum + row.nativeEvidence.comparedSequences.length, 0), 36);
const labels = {
  empty: '빈 거래 목록', root: '일반 거래 한 개', child: '자식 거래 한 개', 'mixed-order': '일반·자식 거래 혼합',
  'missing-field': 'is_child 필드 없음', 'duplicate-ids': '같은 ID, 다른 금액', 'nullish-flags': 'null·undefined 플래그',
  'falsy-scalars': '거짓으로 취급되는 값', 'truthy-values': '참으로 취급되는 값', 'child-first': '자식 거래가 먼저 오는 목록',
};
const data = {
  schema: 'web-review-inspector-1', status: 'research-demo', engineSha256: ENGINE_SHA256, generatedAt: new Date().toISOString(),
  title: '필터를 켰을 때, 어떤 거래가 남을까', project: 'Actual', caseId: 'actual-mobile-report-filter',
  scope: arrays.scope, humanParticipants: 0, wholeBehaviorCasesVerified: 0,
  profiles: { transactions: profiles.transactions.map(row => ({ ...row, label: labels[row.name] ?? row.name })), previews: profiles.previews },
  states, boundaries, readings, comparison, sources,
  evidence: { pairedInputs: comparison.checked, changedInputs: comparison.changes.length, nativeChecks: arrayEvidence.nativeChecks,
    boundaryNativeChecks: arrayEvidence.boundaryNativeChecks, unsupportedChecks: arrayEvidence.unsupportedChecks,
    sourceConnections: joins.results.reduce((sum, row) => sum + row.childReferences, 0), changeScope: arrayEvidence.changeScope,
    sourceScope,
    arrayProducerSha256: arrays.producerSha256, joinProducerSha256: joins.producerSha256,
    nativeTrace: { originalReexecutions: nativeTraces.originalReexecutions, instrumentedExecutions: nativeTraces.instrumentedExecutions,
      projectedEvents: nativeTraces.projectedEvents, faultRevisionInputs: nativeTraces.faultRevisionInputs, scope: nativeTraces.scope, notProven: nativeTraces.notProven },
    notes: ['이 화면의 입력 변경은 미리 계산한 스냅샷을 선택한다. 원본 Actual 앱을 실행하지 않는다.',
      '선택식 결과를 자식의 실제 값·화면·서버 조회 결과로 취급하지 않는다.', '예시는 JavaScript 의미 경계도 포함하며 실제 사용자 상태의 도달 가능성을 증명하지 않는다.'] },
};
const serialized = JSON.stringify(data);
assert.ok(Buffer.byteLength(serialized) < 8 * 1024 * 1024);
const assets = ['index.html', 'style.css', 'app.mjs'];
const manifest = { schema: 'web-inspector-manifest-1', engineSha256: ENGINE_SHA256, dataSha256: hash(serialized),
  producerSha256: hash(fs.readFileSync(fileURLToPath(import.meta.url))),
  producerDependencies,
  assetHashes: Object.fromEntries(assets.map(file => [file, hash(fs.readFileSync(path.join(pkg, 'inspector', file)))])),
  originalSources: sources.map(({ file, sha256 }) => ({ file, sha256 })), humanParticipants: 0, wholeBehaviorCasesVerified: 0 };
fs.mkdirSync(output, { recursive: true });
fs.writeFileSync(path.join(output, 'data.json'), serialized + '\n');
// Hash actual stored bytes, including the final newline.
manifest.dataSha256 = hash(fs.readFileSync(path.join(output, 'data.json')));
fs.writeFileSync(path.join(output, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
process.stdout.write(JSON.stringify({ status: 'prepared-research-demo', engineSha256: ENGINE_SHA256, states: states.length, boundaryPairs: boundaries.length, sources: sources.length, cliReplays: 3, nativeExecutions: 0, humanParticipants: 0, output }) + '\n');
