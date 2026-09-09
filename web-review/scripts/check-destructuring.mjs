import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
import { hash, parseSource } from '../src/typescript.mjs';
import { liftProject } from '../src/project.mjs';
import { observe, encode, decode } from '../src/core.mjs';
import { renderExecution } from '../src/report.mjs';
import { caseChangeScope } from './inventory-scope.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const pkg = path.join(root, 'web-review');
const read = name => JSON.parse(fs.readFileSync(path.join(pkg, 'corpus', name), 'utf8'));
const corpus = read('lock.json'), selection = read('destructuring-functions.json');
assert.equal(corpus.selectionSha256, hash(fs.readFileSync(path.join(pkg, 'corpus/selection.json'))));
const selectionSha256 = hash(fs.readFileSync(path.join(pkg, 'corpus/destructuring-functions.json')));

function independentCases(kind) {
  const cases = [];
  if (kind === 'stream-visible-v1') {
    // Native truthiness is not converted to a boolean return: && can return
    // strings, null, undefined, zero and negative zero unchanged.
    const values = [false, true, null, undefined, 0, -0, '', 'enabled'];
    for (const breakout of values) for (const enabled of values) for (const allowed of values) {
      const value = { isInBreakoutRoom: breakout, liveStreamingEnabled: enabled, liveStreamingAllowed: allowed };
      const expected = breakout ? false : !enabled ? enabled : allowed;
      cases.push({ value, expected: { kind: 'value', value: encode(expected) } });
    }
    cases.push({ value: {}, expected: { kind: 'value', value: encode(undefined) } });
    for (const value of [null, undefined]) cases.push({ value, expected: { kind: 'throw', name: 'TypeError' } });
  } else if (kind === 'recording-sharing-v1') {
    for (const value of [false, true, null, undefined, 0, -0, '', 'shared']) {
      cases.push({ value: { 'features/base/config': { recordingService: { sharingEnabled: value } } },
        expected: { kind: 'value', value: encode(value === null || value === undefined ? false : value) } });
    }
    for (const config of [{}, { recordingService: null }, { recordingService: undefined }, { recordingService: {} }]) {
      cases.push({ value: { 'features/base/config': config }, expected: { kind: 'value', value: false } });
    }
    for (const value of [null, undefined, {}, { 'features/base/config': null }, { 'features/base/config': undefined }]) {
      cases.push({ value, expected: { kind: 'throw', name: 'TypeError' } });
    }
  } else throw new Error('Missing independently authored oracle');
  return cases;
}

const results = [];
for (const target of selection.targets) {
  const original = corpus.cases.find(row => row.id === target.case);
  const declarations = {};
  const sources = {};
  for (const revision of ['before', 'after']) {
    const filename = path.join(root, 'build/web-corpus', target.case, revision, target.path);
    const source = fs.readFileSync(filename, 'utf8');
    const blob = original.blobs.find(row => row.revision === revision && row.path === target.path);
    assert.equal(hash(source), blob.sha256);
    const parsed = parseSource(source, filename);
    const matches = parsed.statements.filter(node => ts.isFunctionDeclaration(node) && node.name?.text === target.functionName && node.body);
    assert.equal(matches.length, 1);
    declarations[revision] = matches[0].getText(parsed);
    sources[revision] = { filename, source, blob };
  }
  assert.equal(declarations.before, declarations.after, 'This support experiment labels the selected declarations as unchanged.');
  const { source, filename, blob } = sources.after;
  const entry = path.basename(filename);
  const artifact = { ...liftProject({ files: { [entry]: source }, entry, functionName: target.functionName, isolation: 'function-body' }), sourceFile: filename };
  assert.equal(artifact.parameterInputs.length, 1);
  const inputName = artifact.parameterInputs[0].input;
  const outputText = ts.transpileModule(declarations.after, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
  const nativeScript = new vm.Script(`${outputText}\nexports.${target.functionName}(inputValue);`);
  const cases = independentCases(target.oracle);
  for (const test of cases) {
    const value = encode(test.value);
    let actual;
    try { actual = { kind: 'value', value: encode(nativeScript.runInNewContext({ exports: {}, inputValue: decode(value) }, { timeout: 100 })) }; }
    catch (error) { if (error.name !== 'TypeError') throw error; actual = { kind: 'throw', name: 'TypeError' }; }
    assert.deepEqual(actual, test.expected);
    assert.deepEqual(observe(artifact.ir, { [inputName]: value }), actual);
  }
  const unsupportedValues = target.oracle === 'stream-visible-v1' ? [0, '', { $opaque: 'truthy-object' }] :
    [0, { $record: { 'features/base/config': 0 } }, { $record: { 'features/base/config': { $opaque: 'truthy-object' } } }];
  for (const value of unsupportedValues) assert.equal(observe(artifact.ir, { [inputName]: value }).kind, 'unsupported');
  const inputs = { [inputName]: encode(cases[0].value) };
  const directory = path.join(root, 'build/web-review/destructuring', target.id);
  fs.mkdirSync(directory, { recursive: true });
  const artifactPath = path.join(directory, 'artifact.json'), inputPath = path.join(directory, 'inputs.json');
  fs.writeFileSync(artifactPath, JSON.stringify(artifact, null, 2) + '\n');
  fs.writeFileSync(inputPath, JSON.stringify(inputs, null, 2) + '\n');
  fs.writeFileSync(path.join(directory, 'explanation.md'), renderExecution(artifact, observe(artifact.ir, inputs, { trace: true }), { inputs, snippets: node => source.slice(node.start, node.end) }));
  const replay = spawnSync(process.execPath, [path.join(pkg, 'src/cli.mjs'), 'run', '--file', artifactPath, '--inputs', inputPath], { encoding: 'utf8', timeout: 10_000 });
  assert.equal(replay.status, 0, replay.stderr);
  assert.deepEqual(JSON.parse(replay.stdout).observation, observe(artifact.ir, inputs));
  results.push({ id: target.id, case: target.case, functionName: target.functionName, sourceSha256: blob.sha256,
    declarationUnchangedAcrossOriginalCommit: true, nativeChecks: cases.length, unsupportedChecks: unsupportedValues.length,
    cliReplayChecks: 1, parameterInputs: artifact.parameterInputs, changeScope: caseChangeScope(target.case, [target.path]), artifactPath });
}
const report = { schema: 'web-destructuring-results-1', selectionSha256, scope: selection.scope,
  nativeChecks: results.reduce((sum, row) => sum + row.nativeChecks, 0),
  unsupportedChecks: results.reduce((sum, row) => sum + row.unsupportedChecks, 0),
  wholeBehaviorCasesVerified: 0, results };
fs.writeFileSync(path.join(root, 'build/web-review/destructuring-results.json'), JSON.stringify(report, null, 2) + '\n');
process.stdout.write(JSON.stringify(report, null, 2) + '\n');
