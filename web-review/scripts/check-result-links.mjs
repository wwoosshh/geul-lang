import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import vm from 'node:vm';
import ts from 'typescript';
import { indexFunctionResult } from '../src/function-results.mjs';
import { previewFunctionResult } from '../src/result-preview.mjs';
import { renderFunctionResultLinks, renderFunctionResultPreview } from '../src/report.mjs';
import { encode, decode } from '../src/core.mjs';
import { hash } from '../src/typescript.mjs';
import { caseChangeScope, describeChangeScope } from './inventory-scope.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const pkg = path.join(root, 'web-review');
const read = name => JSON.parse(fs.readFileSync(path.join(pkg, 'corpus', name), 'utf8'));
const corpus = read('lock.json'), selection = read('result-links.json');
assert.equal(corpus.selectionSha256, hash(fs.readFileSync(path.join(pkg, 'corpus/selection.json'))));
const results = [];
for (const target of selection.targets) {
  const entry = corpus.cases.find(row => row.id === target.case);
  const blob = entry.blobs.find(row => row.path === target.path && row.revision === target.revision);
  assert.ok(blob);
  const filename = path.join(root, 'build/web-corpus', target.case, target.revision, target.path);
  const source = fs.readFileSync(filename, 'utf8');
  assert.equal(hash(source), blob.sha256);
  const artifact = indexFunctionResult(source, { functionName: target.functionName, filename });
  assert.deepEqual(artifact.connections.map(row => row.property), target.expectedProperties);
  for (const connection of artifact.connections) {
    assert.equal(connection.localName, connection.property);
    assert.equal(connection.uses.length, target.expectedCallees.length);
    assert.deepEqual(connection.uses.map(use => source.slice(use.callee.start, use.callee.end)), target.expectedCallees);
    assert.ok(connection.uses.every(use => use.kind === 'direct-payload-property' && use.payloadName === connection.property && use.argumentIndex === 0 && !use.nestedFunction && !use.optionalCall));
  }
  assert.equal(artifact.otherDirectCalls.length, 0);
  assert.equal(artifact.otherFunctionReferences.length, 0);
  assert.equal(artifact.callContext.guards.length, 0);
  assert.deepEqual(artifact.callContext.enclosingFunctions.map(row => row.name), [null, 'onNext', 'SelectLinkedAccountsModal']);
  const exits = artifact.callContext.precedingStatements.filter(row => row.immediateExits);
  assert.equal(exits.length, 1);
  assert.equal(source.slice(exits[0].immediateExits.condition.start, exits[0].immediateExits.condition.end), 'externalAccountIndex === -1');
  assert.deepEqual(exits[0].immediateExits.branches.map(row => [row.accepts, row.kind]), [['truthy', 'return']]);
  const providerNames = ['simpleFin', 'pluggyai', 'akahu', 'enableBanking'];
  for (const connection of artifact.connections) connection.uses.forEach((use, index) => {
    assert.deepEqual(use.context.guards.map(row => [source.slice(row.condition.start, row.condition.end), row.accepts]),
      providerNames.slice(0, Math.min(index + 1, 4)).map((name, guardIndex) => [`propsWithSortedExternalAccounts.syncSource === '${name}'`, index === guardIndex ? 'truthy' : 'falsy']));
    assert.deepEqual(use.context.boundaries, []);
  });
  const changeScope = caseChangeScope(target.case, [target.path], { kind: 'source-bindings' });
  const directory = path.join(root, 'build/web-review/result-links', target.id);
  fs.mkdirSync(directory, { recursive: true });
  const output = path.join(directory, 'artifact.json');
  fs.writeFileSync(output, JSON.stringify(artifact, null, 2) + '\n');
  fs.writeFileSync(path.join(directory, 'source-links.md'), describeChangeScope(changeScope) + '\n\n' + renderFunctionResultLinks(artifact, { snippets: node => source.slice(node.start, node.end) }));
  const replay = spawnSync(process.execPath, [path.join(pkg, 'src/cli.mjs'), 'explain', '--file', output], { encoding: 'utf8', timeout: 10_000 });
  assert.equal(replay.status, 0, replay.stderr);
  assert.match(replay.stdout, /도달·실행은 미확인/);
  // Independent native execution of the ORIGINAL function and result declaration.
  // The original dynamic account lookup is supplied a fixed one-entry record;
  // the preview still takes function parameters and does not infer that lookup.
  const fnSource = source.slice(artifact.functionDeclaration.start, artifact.functionDeclaration.end);
  const resultSource = source.slice(artifact.resultDeclaration.start, artifact.resultDeclaration.end);
  const native = new vm.Script(ts.transpileModule(`${fnSource}\nconst ${resultSource};\n({ startingDate, startingBalance });`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText);
  const examples = [
    { settings: null, expected: [undefined, undefined] },
    { settings: undefined, expected: [undefined, undefined] },
    { settings: {}, expected: [undefined, undefined] },
    { settings: { date: '  ', amount: 0 }, expected: [undefined, 0] },
    { settings: { date: ' 2026-09-09 ', amount: 0 }, expected: [' 2026-09-09 ', 0] },
    { settings: { date: 'invalid-date', amount: -0 }, expected: ['invalid-date', -0] },
    { settings: { date: null, amount: NaN }, expected: [undefined, NaN] },
    { settings: { date: '', amount: null }, expected: [undefined, undefined] },
  ];
  for (const example of examples) {
    const inputs = { settings: encode(example.settings) };
    const preview = previewFunctionResult(source, { ...artifact.target, filename, inputs });
    const record = Object.assign(Object.create(null), { 'account-1': decode(inputs.settings) });
    const actual = native.runInNewContext({ exports: {}, customStartingDates: record, chosenExternalAccountId: 'account-1' }, { timeout: 100 });
    assert.deepEqual([encode(actual.startingDate), encode(actual.startingBalance)], example.expected.map(encode));
    assert.deepEqual(preview.projections.map(row => row.value), example.expected.map(encode));
    assert.ok(preview.projections.every(row => row.status === 'scalar-at-binding'));
  }
  const previewInputs = { settings: { $record: { date: ' 2026-09-09 ', amount: 0 } } };
  const preview = previewFunctionResult(source, { ...artifact.target, filename, inputs: previewInputs });
  const inputFile = path.join(directory, 'preview-inputs.json');
  fs.writeFileSync(inputFile, JSON.stringify(previewInputs, null, 2) + '\n');
  fs.writeFileSync(path.join(directory, 'preview.json'), JSON.stringify(preview, null, 2) + '\n');
  const previewScope = caseChangeScope(target.case, [target.path]);
  fs.writeFileSync(path.join(directory, 'preview.md'), describeChangeScope(previewScope) + '\n\n' + renderFunctionResultPreview(preview, { snippets: loc => source.slice(loc.start, loc.end) }));
  const previewReplay = spawnSync(process.execPath, [path.join(pkg, 'src/cli.mjs'), 'explain', '--file', output, '--inputs', inputFile], { encoding: 'utf8', timeout: 10_000 });
  assert.equal(previewReplay.status, 0, previewReplay.stderr);
  assert.match(previewReplay.stdout, /실제 요청 실행을 확인한 결과는 아니다/);
  assert.match(previewReplay.stdout, /연산|trim/);
  assert.match(previewReplay.stdout, /externalAccountIndex/);
  const accounts = { first: { date: ' 2026-09-09 ', amount: 0 }, second: { date: '', amount: 25 } };
  const callerExamples = [
    { records: accounts, key: 'first', expected: [' 2026-09-09 ', 0] },
    { records: accounts, key: 'second', expected: [undefined, 25] },
    { records: accounts, key: 'missing', expected: [undefined, undefined] },
    { records: null, key: 'first', throws: true },
    { records: undefined, key: 'first', throws: true },
    { records: {}, key: 'first', expected: [undefined, undefined] },
    { records: { '': { date: '한국어 날짜', amount: -0 } }, key: '', expected: ['한국어 날짜', -0] },
    { records: Object.fromEntries([['__proto__', { date: null, amount: 2 }]]), key: '__proto__', expected: [undefined, 2] },
  ];
  for (const example of callerExamples) {
    const inputs = { customStartingDates: encode(example.records), chosenExternalAccountId: example.key };
    const result = previewFunctionResult(source, { ...artifact.target, filename, inputs, inputBoundary: 'call-arguments' });
    const environment = { exports: {}, customStartingDates: decode(inputs.customStartingDates), chosenExternalAccountId: example.key };
    assert.deepEqual(result.execution.inputs, ['chosenExternalAccountId', 'customStartingDates']);
    if (example.throws) {
      assert.throws(() => native.runInNewContext(environment, { timeout: 100 }), error => error.name === 'TypeError');
      assert.equal(result.observation.kind, 'throw');
      assert.equal(result.observation.name, 'TypeError');
      assert.equal(result.bindingObservation, null);
    } else {
      const actual = native.runInNewContext(environment, { timeout: 100 });
      assert.deepEqual([encode(actual.startingDate), encode(actual.startingBalance)], example.expected.map(encode));
      assert.deepEqual(result.projections.map(row => row.value), example.expected.map(encode));
    }
  }
  let callerUnsupportedChecks = 0;
  for (const key of [0, false, { $record: {} }]) {
    const result = previewFunctionResult(source, { ...artifact.target, filename, inputBoundary: 'call-arguments',
      inputs: { customStartingDates: encode(accounts), chosenExternalAccountId: key } });
    assert.equal(result.observation.kind, 'unsupported');
    callerUnsupportedChecks++;
  }
  const callerInputs = { customStartingDates: encode(accounts), chosenExternalAccountId: 'first' };
  const callerPreview = previewFunctionResult(source, { ...artifact.target, filename, inputs: callerInputs, inputBoundary: 'call-arguments' });
  const callerInputFile = path.join(directory, 'caller-inputs.json');
  fs.writeFileSync(callerInputFile, JSON.stringify(callerInputs, null, 2) + '\n');
  fs.writeFileSync(path.join(directory, 'caller-preview.json'), JSON.stringify(callerPreview, null, 2) + '\n');
  fs.writeFileSync(path.join(directory, 'caller-preview.md'), describeChangeScope(previewScope) + '\n\n' + renderFunctionResultPreview(callerPreview, { snippets: loc => source.slice(loc.start, loc.end) }));
  const callerReplay = spawnSync(process.execPath, [path.join(pkg, 'src/cli.mjs'), 'explain', '--file', output, '--caller-inputs', callerInputFile], { encoding: 'utf8', timeout: 10_000 });
  assert.equal(callerReplay.status, 0, callerReplay.stderr);
  assert.match(callerReplay.stdout, /지정한 호출 지점 입력/);
  assert.match(callerReplay.stdout, /1번째 호출 인수/);
  assert.match(callerReplay.stdout, /실제 앱의 호출 도달/);
  results.push({ id: target.id, case: target.case, revision: target.revision, sourceSha256: blob.sha256,
    engineSha256: artifact.engineSha256, linkedBindings: artifact.connections.length,
    linkedPayloadProperties: artifact.connections.reduce((sum, row) => sum + row.uses.length, 0),
    distinctCallSites: new Set(artifact.connections.flatMap(row => row.uses.map(use => use.call.start))).size,
    sourceBranchPaths: artifact.connections[0].uses.length, sourceEarlyExitStatements: exits.length,
    parameterInputNativeChecks: examples.length,
    callerInputNativeChecks: callerExamples.length, callerUnsupportedChecks,
    cliReplayChecks: 3, changeScope, previewChangeScope: previewScope, artifact: output });
}
const result = { schema: 'web-result-link-results-1', selectionSha256: hash(fs.readFileSync(path.join(pkg, 'corpus/result-links.json'))),
  scope: selection.scope, sourceIndexExecutionChecks: 0, parameterInputNativeChecks: results.reduce((sum, row) => sum + row.parameterInputNativeChecks, 0),
  callerInputNativeChecks: results.reduce((sum, row) => sum + row.callerInputNativeChecks, 0),
  callerUnsupportedChecks: results.reduce((sum, row) => sum + row.callerUnsupportedChecks, 0),
  previewScopes: ['함수 매개변수 입력에서 본문·결과 바인딩', '호출 지점 스냅샷에서 인수·선택 함수 본문·결과 바인딩; 실제 함수 바인딩은 가정'],
  actualRequestExecutionChecks: 0, wholeBehaviorCasesVerified: 0, results };
fs.writeFileSync(path.join(root, 'build/web-review/result-link-results.json'), JSON.stringify(result, null, 2) + '\n');
process.stdout.write(JSON.stringify(result, null, 2) + '\n');
