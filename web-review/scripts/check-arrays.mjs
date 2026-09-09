import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { liftConstBindings } from '../src/const-bindings.mjs';
import { ARRAY_PROFILE, encode, decode, observe, compare } from '../src/core.mjs';
import { hash } from '../src/typescript.mjs';
import { ENGINE_SHA256 } from '../src/fingerprint.mjs';
import { describeComparison, describeChangeSummary } from '../src/presentation.mjs';
import { renderReading } from '../src/reading.mjs';
import { renderIRStructure } from '../src/report.mjs';
import { compareIRStructure } from '../src/ir-structure.mjs';
import { summarizeChanges, verifyChangeRules, summarizeChangeConditions, verifyChangeConditions } from '../src/change-rules.mjs';
import { diffArrayValues, verifyArrayDelta } from '../src/array-diff.mjs';
import { caseChangeScope, describeChangeScope } from './inventory-scope.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..'), pkg = path.join(root, 'web-review');
const read = name => JSON.parse(fs.readFileSync(path.join(pkg, 'corpus', name), 'utf8'));
const corpus = read('lock.json'), selection = read('array-slices.json');
assert.equal(selection.schema, 'web-array-slices-1');
assert.equal(corpus.selectionSha256, hash(fs.readFileSync(path.join(pkg, 'corpus/selection.json'))));
const pack = value => encode(value, 0, undefined, { arrays: true });
const unpack = value => decode(value, 0, { arrays: true });
// Expected indices are fixed independently of the evaluator and the native
// filter call. Equal IDs are intentionally retained; this is not a set model.
const transactionProfiles = [
  { name: 'empty', items: [], keep: [] },
  { name: 'root', items: [{ id: 'a', is_child: false }], keep: [0] },
  { name: 'child', items: [{ id: 'b', is_child: true }], keep: [] },
  { name: 'mixed-order', items: [{ id: 'z', is_child: false }, { id: 'b', is_child: true }, { id: 'a', is_child: false }], keep: [0, 2] },
  { name: 'missing-field', items: [{ id: 'no-flag' }], keep: [0] },
  { name: 'duplicate-ids', items: [{ id: 'a', is_child: false, amount: 1 }, { id: 'a', is_child: false, amount: 2 }], keep: [0, 1] },
  { name: 'nullish-flags', items: [{ id: 'null', is_child: null }, { id: 'undefined', is_child: undefined }], keep: [0, 1] },
  { name: 'falsy-scalars', items: [{ id: 'zero', is_child: 0 }, { id: 'minus-zero', is_child: -0 }, { id: 'empty', is_child: '' }, { id: 'nan', is_child: NaN }], keep: [0, 1, 2, 3] },
  { name: 'truthy-values', items: [{ id: 'one', is_child: 1 }, { id: 'text', is_child: 'yes' }, { id: 'record', is_child: {} }, { id: 'array', is_child: [] }], keep: [] },
  { name: 'child-first', items: [{ id: 'b', is_child: true }, { id: 'a', is_child: false }], keep: [1] },
];
const previewProfiles = [[], [{ id: 'preview' }], [{ id: 'p2' }, { id: 'p1' }], [{ id: 'a', is_child: true }, { id: 'a', is_child: true }]];
const domains = { isSearching: [false, true], isFiltered: [false, true],
  previewTransactions: previewProfiles.map(pack), transactions: transactionProfiles.map(row => pack(row.items)) };
for (const values of Object.values(domains)) assert.equal(new Set(values.map(value => JSON.stringify(value))).size, values.length);
const results = [];
for (const target of selection.targets) {
  assert.equal(target.oracle, 'actual-transaction-order-v1'); assert.equal(target.arrayProfile, ARRAY_PROFILE);
  assert.deepEqual(target.outputs, ['transactionsToDisplay']);
  const entry = corpus.cases.find(row => row.id === target.case), sources = {}, files = {}, artifacts = {}, native = {}, selectedSource = {};
  for (const revision of ['before', 'after']) {
    const blob = entry?.blobs.find(row => row.path === target.path && row.revision === revision); assert.ok(blob);
    files[revision] = path.join(root, 'build/web-corpus', target.case, revision, target.path);
    sources[revision] = fs.readFileSync(files[revision], 'utf8'); assert.equal(hash(sources[revision]), blob.sha256);
    const artifact = artifacts[revision] = liftConstBindings(sources[revision], { ...target[revision], outputs: target.outputs, arrayProfile: target.arrayProfile, filename: files[revision] });
    assert.equal(artifact.prefix.bindings.length, 1);
    const output = artifact.outputSources.bindings[0];
    assert.equal(output.name, 'transactionsToDisplay'); assert.equal(output.useCount, 1);
    assert.equal(output.uses[0].kind, 'jsx-attribute'); assert.equal(output.uses[0].tag, 'TransactionListWithBalances');
    assert.equal(output.uses[0].attribute, 'transactions'); assert.equal(output.uses[0].nestedFunction, false);
    selectedSource[revision] = sources[revision].slice(artifact.prefix.source.start, artifact.prefix.end);
    // Exact original statement; no rewriting into a model-shaped fixture.
    native[revision] = new vm.Script(`${selectedSource[revision]}\ntransactionsToDisplay;`);
    assert.ok(artifact.bindings.inputs.every(input => input.name !== 't'));
  }
  function nativeObservation(revision, inputs) {
    try {
      const result = native[revision].runInNewContext(Object.fromEntries(Object.entries(inputs).map(([name, value]) => [name, unpack(value)])), { timeout: 100 });
      assert.ok(Array.isArray(result));
      assert.equal(Reflect.ownKeys(result).length, result.length + 1);
      // Source-selected operations allocate only the outer array. Elements are
      // host-realm snapshot values passed to the native VM, not transformed IR.
      return { kind: 'value', value: pack({ transactionsToDisplay: Array.from(result) }) };
    } catch (error) {
      if (error.name !== 'TypeError') throw error;
      return { kind: 'throw', name: error.name };
    }
  }
  let nativeChecks = 0, expectedChanged = 0;
  for (const [transactionIndex, profile] of transactionProfiles.entries()) for (const [previewIndex, preview] of previewProfiles.entries()) for (const isSearching of domains.isSearching) for (const isFiltered of domains.isFiltered) {
    const inputs = { isSearching, isFiltered, transactions: domains.transactions[transactionIndex], previewTransactions: domains.previewTransactions[previewIndex] };
    const chosen = [...preview, ...profile.keep.map(index => profile.items[index])];
    const expectedBefore = { kind: 'value', value: pack({ transactionsToDisplay: isSearching ? profile.items : chosen }) };
    const expectedAfter = { kind: 'value', value: pack({ transactionsToDisplay: isSearching || isFiltered ? profile.items : chosen }) };
    for (const revision of ['before', 'after']) {
      const expected = revision === 'before' ? expectedBefore : expectedAfter;
      assert.deepEqual(observe(artifacts[revision].ir, inputs), expected, `${revision}: ${profile.name}`);
      assert.deepEqual(nativeObservation(revision, inputs), expected, `${revision}: ${profile.name}: native`);
      nativeChecks++;
    }
    if (JSON.stringify(expectedBefore) !== JSON.stringify(expectedAfter)) expectedChanged++;
  }
  // Fault probes are separate from the ordinary transaction-list domain and
  // do not assert the actual TypeScript caller can produce these snapshots.
  const faultInputs = [];
  for (const isSearching of [false, true]) for (const isFiltered of [false, true]) {
    faultInputs.push({ isSearching, isFiltered, transactions: pack([null]), previewTransactions: pack([]) });
    faultInputs.push({ isSearching, isFiltered, transactions: pack([undefined]), previewTransactions: pack([]) });
    faultInputs.push({ isSearching, isFiltered, transactions: pack([{ id: 'a' }]), previewTransactions: null });
  }
  let boundaryNativeChecks = 0, thrownChecks = 0;
  const faultObservations = [];
  for (const inputs of faultInputs) for (const revision of ['before', 'after']) {
    const actual = observe(artifacts[revision].ir, inputs), expected = nativeObservation(revision, inputs);
    assert.deepEqual(actual, expected); boundaryNativeChecks++;
    if (actual.kind === 'throw') thrownChecks++;
    faultObservations.push({ revision, inputs, observation: actual });
  }
  let unsupportedChecks = 0;
  for (const value of [pack({}), 1, 'list', { $opaque: 'truthy-object' }]) for (const name of ['transactions', 'previewTransactions']) for (const revision of ['before', 'after']) {
    const inputs = { isSearching: false, isFiltered: false, transactions: pack([]), previewTransactions: pack([]), [name]: value };
    assert.equal(observe(artifacts[revision].ir, inputs).kind, 'unsupported'); unsupportedChecks++;
  }
  const rawComparison = compare(artifacts.before.ir, artifacts.after.ir, domains);
  assert.equal(rawComparison.unknown.length, 0); assert.equal(rawComparison.checked, 160);
  assert.equal(rawComparison.changes.length, expectedChanged);
  const observationDeltas = rawComparison.changes.map(row => {
    const before = row.before.value.$record.transactionsToDisplay, after = row.after.value.$record.transactionsToDisplay;
    const delta = diffArrayValues(before, after);
    assert.equal(delta.status, 'verified-array-observation-delta');
    assert.equal(verifyArrayDelta(before, after, delta.edits).reconstructedAfter, true);
    return { inputs: row.inputs, before, after, delta };
  });
  const changeRules = summarizeChanges(rawComparison, domains);
  assert.equal(changeRules.status, 'verified-finite-cover'); verifyChangeRules(changeRules.rules, rawComparison, domains);
  const changeConditions = summarizeChangeConditions(rawComparison, domains);
  assert.equal(changeConditions.status, 'verified-finite-change-conditions'); verifyChangeConditions(changeConditions.rules, rawComparison, domains);
  assert.equal(changeConditions.envelope.matchedRows, 40);
  assert.equal(changeConditions.envelope.changedRows, 34);
  assert.equal(changeConditions.envelope.unchangedRows, 6);
  assert.equal(changeConditions.envelope.unknownRows, 0);
  // Independent membership over every original native-checked input, retaining
  // the cases where both selected lists happen to contain the same values.
  for (const isSearching of domains.isSearching) for (const isFiltered of domains.isFiltered) for (let t = 0; t < transactionProfiles.length; t++) for (let p = 0; p < previewProfiles.length; p++) {
    const profile = transactionProfiles[t], combined = [...previewProfiles[p], ...profile.keep.map(index => profile.items[index])];
    const expected = !isSearching && isFiltered && JSON.stringify(pack(combined)) !== JSON.stringify(pack(profile.items));
    const tuple = { isSearching: domains.isSearching.indexOf(isSearching), isFiltered: domains.isFiltered.indexOf(isFiltered), transactions: t, previewTransactions: p };
    const matches = changeConditions.rules.filter(rule => rule.axes.every((values, axis) => values.includes(tuple[changeConditions.names[axis]])));
    assert.equal(matches.length, expected ? 1 : 0);
  }
  const structureComparison = compareIRStructure(artifacts.before.ir, artifacts.after.ir);
  assert.equal(structureComparison.status, 'ir-structural-comparison');
  assert.equal(structureComparison.changes.length, 1);
  assert.equal(structureComparison.changes[0].kind, 'condition-changed');
  assert.equal(structureComparison.changes[0].sameBranchStructure, true);
  const conditionChange = structureComparison.changes[0];
  assert.equal(sources.before.slice(conditionChange.before.source.start, conditionChange.before.source.end), '!isSearching');
  assert.equal(sources.after.slice(conditionChange.after.source.start, conditionChange.after.source.end), '!isSearching && !isFiltered');
  const comparison = { ...rawComparison, changeRules, changeConditions, structureComparison, observationBindings: artifacts.before.observationBindings, domains,
    beforeContract: artifacts.before.contract, afterContract: artifacts.after.contract,
    assumptions: [...new Set([...rawComparison.assumptions, ...artifacts.before.contract.assumptions, ...artifacts.after.contract.assumptions])] };
  const changeScope = caseChangeScope(target.case, [target.path]), directory = path.join(root, 'build/web-review/arrays', target.id);
  fs.mkdirSync(directory, { recursive: true });
  const inputs = { isSearching: false, isFiltered: true, transactions: domains.transactions[3], previewTransactions: domains.previewTransactions[1] };
  for (const [name, value] of Object.entries({ ...artifacts, inputs, domains, comparison, 'fault-probes': faultObservations, 'observation-deltas': observationDeltas,
    profiles: { transactions: transactionProfiles.map(({ name, items, keep }) => ({ name, items: pack(items), nonChildIndices: keep })), previews: previewProfiles.map(pack) } })) fs.writeFileSync(path.join(directory, `${name}.json`), JSON.stringify(value, null, 2) + '\n');
  const staticReadingNodes = {}, inputOriginDeclarations = {};
  for (const revision of ['before', 'after']) {
    fs.writeFileSync(path.join(directory, `${revision}-selected.js`), selectedSource[revision] + '\ntransactionsToDisplay;\n');
    const replay = spawnSync(process.execPath, [path.join(pkg, 'src/cli.mjs'), 'explain', '--file', path.join(directory, `${revision}.json`), '--inputs', path.join(directory, 'inputs.json')], { encoding: 'utf8', timeout: 10_000 });
    assert.equal(replay.status, 0, replay.stderr); assert.ok(!replay.stdout.includes('/binding/original'));
    fs.writeFileSync(path.join(directory, `${revision}.md`), describeChangeScope(changeScope) + '\n\n' + replay.stdout);
    const readingReplay = spawnSync(process.execPath, [path.join(pkg, 'src/cli.mjs'), 'read', '--file', path.join(directory, `${revision}.json`), '--json'], { encoding: 'utf8', timeout: 10_000, maxBuffer: 8 * 1024 * 1024 });
    assert.equal(readingReplay.status, 0, readingReplay.stderr);
    const reading = JSON.parse(readingReplay.stdout);
    assert.equal(reading.status, 'ir-reading-view');
    assert.equal(Object.hasOwn(reading, 'observation'), false);
    assert.equal(reading.engineSha256, ENGINE_SHA256);
    assert.deepEqual(reading.inputBindings.inputs, artifacts[revision].bindings.inputs);
    const origins = new Map(reading.inputBindings.inputs.map(input => [input.name, input.declarations[0]]));
    for (const [name, call] of [['transactions', 'useTransactions('], ['previewTransactions', 'usePreviewTransactions('], ['isSearching', 'useTransactionsSearch(']]) {
      const origin = origins.get(name)?.destructuringOrigin;
      assert.equal(origin?.kind, 'variable-pattern'); assert.equal(origin.runtimeValueProven, false);
      assert.ok(sources[revision].slice(origin.expression.start, origin.expression.end).startsWith(call));
    }
    if (revision === 'after') {
      const definition = origins.get('isFiltered');
      assert.equal(sources[revision].slice(definition.initializer.start, definition.initializer.end), 'filterConditions.length > 0');
    }
    inputOriginDeclarations[revision] = origins.size;
    staticReadingNodes[revision] = reading.nodeCount;
    fs.writeFileSync(path.join(directory, `${revision}-reading.json`), readingReplay.stdout);
    fs.writeFileSync(path.join(directory, `${revision}-reading.md`), describeChangeScope(changeScope) + '\n\n' + renderReading(artifacts[revision], reading));
  }
  const replay = spawnSync(process.execPath, [path.join(pkg, 'src/cli.mjs'), 'compare', '--before', path.join(directory, 'before.json'), '--after', path.join(directory, 'after.json'), '--domains', path.join(directory, 'domains.json'), '--json'], { encoding: 'utf8', timeout: 10_000, maxBuffer: 8 * 1024 * 1024 });
  assert.equal(replay.status, 0, replay.stderr);
  const replayed = JSON.parse(replay.stdout);
  for (const field of ['status', 'checked', 'changes', 'unknown', 'changeRules', 'changeConditions', 'structureComparison']) assert.deepEqual(replayed[field], comparison[field]);
  const structureReport = renderIRStructure(structureComparison, artifacts.before, artifacts.after, {
    beforeSnippets: loc => sources.before.slice(loc.start, loc.end), afterSnippets: loc => sources.after.slice(loc.start, loc.end),
  });
  fs.writeFileSync(path.join(directory, 'structure.md'), describeChangeScope(changeScope) + '\n\n' + structureReport + '\n');
  const sourceLink = (revision, line) => `[${revision === 'before' ? '변경 전' : '변경 후'}](<${files[revision].replaceAll('\\', '/')}:${line}>)`;
  fs.writeFileSync(path.join(directory, 'comparison.md'), `${describeChangeSummary(comparison)}\n\n${describeChangeScope(changeScope)}\n\n# 필터를 켰을 때 선택하는 거래 목록\n\n원본: ${sourceLink('before', target.before.startLine)}, ${sourceLink('after', target.after.startLine)}.\n\n예시 입력에서는 검색은 꺼져 있고 필터는 켜져 있다. 변경 전 결과의 ID 순서는 [preview, z, a], 변경 후는 [z, b, a]다. 미리보기 원소가 빠지고 자식 거래 b가 포함된다. 이 ID 표시는 예시를 읽기 위한 것이며 실제 비교는 원소의 모든 관찰 필드와 순서를 대조한다.\n\n이 결과는 함수 안의 목록 선택식에 한정한다. 이미 검색 중이면 두 버전 모두 transactions를 그대로 선택하며, 검색·필터가 모두 꺼져 있으면 미리보기 목록 뒤에 is_child가 거짓으로 취급되는 거래를 이어 붙인다. 필터가 켜지고 검색이 꺼진 경우에만 선택식이 달라지지만, 두 목록의 내용이 우연히 같다면 관찰 차이는 없다.\n\n${describeComparison(comparison)}\n\n추가 오류 입력 ${faultInputs.length}개를 변경 전후 원본과 ${boundaryNativeChecks}회 대조했고 TypeError 관찰은 ${thrownChecks}회였다. 이 입력들은 실제 사용자 상태가 가능하다는 증거가 아니다. 미지원 프로필 ${unsupportedChecks}회는 네이티브 일치 건수에 포함하지 않았다.\n\n서버에서 어떤 거래가 조회되는지, 필터 설정이 언제 바뀌는지, 자식 컴포넌트가 전달 목록을 어떤 행으로 표시하는지, 전체 커밋이 요구사항을 충족하는지는 확인하지 않았다.\n`);
  results.push({ id: target.id, case: target.case, engineSha256: ENGINE_SHA256, sourceSha256: Object.fromEntries(Object.entries(sources).map(([revision, source]) => [revision, hash(source)])),
    selectedSourceSha256: Object.fromEntries(Object.entries(selectedSource).map(([revision, source]) => [revision, hash(source)])),
    outputSourceUses: Object.fromEntries(Object.entries(artifacts).map(([revision, artifact]) => [revision, artifact.outputSources.bindings])),
    pairedInputs: comparison.checked, changedInputs: comparison.changes.length, rules: changeRules.rules.length,
    changeConditionRules: changeConditions.rules.length, changedEnvelope: changeConditions.envelope, irStructureChanges: structureComparison.changes.length,
    nativeChecks, boundaryNativeChecks, thrownChecks, unsupportedChecks, verifiedSequenceDeltas: observationDeltas.length, staticReadingNodes, inputOriginDeclarations, cliReplayChecks: 5, changeScope, directory });
}
const result = { schema: 'web-array-slice-results-1', engineSha256: ENGINE_SHA256,
  producerSha256: hash(fs.readFileSync(fileURLToPath(import.meta.url))), selectionSha256: hash(fs.readFileSync(path.join(pkg, 'corpus/array-slices.json'))), domainsSha256: hash(JSON.stringify(domains)),
  scope: selection.scope, wholeBehaviorCasesVerified: 0, results };
fs.writeFileSync(path.join(root, 'build/web-review/array-results.json'), JSON.stringify(result, null, 2) + '\n');
process.stdout.write(JSON.stringify({ ...result, results: results.map(({ changeScope, ...row }) => row) }, null, 2) + '\n');
