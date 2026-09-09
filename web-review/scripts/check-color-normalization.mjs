import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { liftConstBindings } from '../src/const-bindings.mjs';
import { observe, compare, encode, decode } from '../src/core.mjs';
import { hash } from '../src/typescript.mjs';
import { ENGINE_SHA256, ENGINE_RUNTIME } from '../src/fingerprint.mjs';
import { caseChangeScope, describeChangeScope } from './inventory-scope.mjs';

const pkg = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'), root = path.dirname(pkg);
const selectionBytes = fs.readFileSync(path.join(pkg, 'corpus/color-normalization.json')), target = JSON.parse(selectionBytes);
assert.equal(target.id, 'excalidraw-color-normalization');
const lockBytes = fs.readFileSync(path.join(pkg, 'corpus/lock.json')), lock = JSON.parse(lockBytes);
assert.equal(lock.selectionSha256, hash(fs.readFileSync(path.join(pkg, 'corpus/selection.json'))));
const entry = lock.cases.find(row => row.id === target.case); assert.ok(entry);
const directory = path.join(root, 'build/web-review/color-normalization', target.id);
fs.mkdirSync(directory, { recursive: true });
const write = (name, value) => fs.writeFileSync(path.join(directory, name + '.json'), JSON.stringify(value, null, 2) + '\n');
const artifacts = {}, originals = {}, sourceEvidence = {};
for (const revision of ['before', 'after']) {
  const pinned = entry.blobs.find(row => row.path === target.path && row.revision === revision); assert.ok(pinned);
  const filename = path.join(root, 'build/web-corpus', target.case, revision, target.path), source = fs.readFileSync(filename, 'utf8');
  assert.equal(hash(source), pinned.sha256);
  const artifact = liftConstBindings(source, { ...target[revision], filename });
  assert.deepEqual(artifact.inputs, ['inputValue']);
  assert.equal(artifact.prefix.bindings.length, 1);
  const original = source.slice(artifact.prefix.source.start, artifact.prefix.end);
  assert.equal(original, revision === 'before' ? 'const value = inputValue.toLowerCase();' : 'const value = inputValue.toLowerCase().trim();');
  const wrapper = `${original}\nvalue;`;
  artifacts[revision] = artifact; originals[revision] = new vm.Script(wrapper);
  sourceEvidence[revision] = { file: filename, sha256: pinned.sha256, selectedSource: original, selectedSourceSha256: hash(original), wrapperSha256: hash(wrapper) };
  write(revision, artifact);
}
// Expected values are written independently of the evaluator/native methods.
const bases = [['', ''], ['#ABC', '#abc'], ['#AABBCC', '#aabbcc'], ['Red', 'red'], ['TRANSPARENT', 'transparent'], ['NONE', 'none'], ['GG', 'gg'], ['0', '0'],
  ['İ', 'i\u0307'], ['I', 'i'], ['ΟΣ', 'ος'], ['ΟΣΑ', 'οσα'], ['\u{10400}', '\u{10428}'], ['한글', '한글'], ['A B', 'a b'], ['\uD800A\uDC00', '\uD800a\uDC00']];
const padding = [['none', '', false], ['space', ' ', true], ['tab', '\t', true], ['nbsp', '\u00A0', true], ['bom', '\uFEFF', true], ['zero-width-space', '\u200B', false]];
const rows = bases.flatMap(([base, lower]) => padding.map(([padName, pad, removed]) => ({
  input: pad + base + pad, padding: padName, expected: { before: pad + lower + pad, after: removed ? lower : pad + lower + pad },
})));
rows.push({ input: null, throws: true }, { input: undefined, throws: true });
const domains = { inputValue: rows.map(row => encode(row.input)) };
assert.equal(rows.length, 98); assert.equal(new Set(domains.inputValue.map(value => JSON.stringify(value))).size, rows.length);
const observations = []; let nativeExecutions = 0, typeErrors = 0;
function runOriginal(revision, inputValue, prefix = '') {
  try {
    const context = vm.createContext({ inputValue });
    if (prefix) vm.runInContext(prefix, context, { timeout: 100 });
    return { kind: 'value', value: { $record: { value: encode(originals[revision].runInContext(context, { timeout: 100 })) } } };
  } catch (error) { if (error.name !== 'TypeError') throw error; return { kind: 'throw', name: 'TypeError' }; }
}
for (const row of rows) for (const revision of ['before', 'after']) {
  const inputs = { inputValue: encode(row.input) };
  const expected = row.throws ? { kind: 'throw', name: 'TypeError' } : { kind: 'value', value: { $record: { value: row.expected[revision] } } };
  const original = runOriginal(revision, row.input); nativeExecutions++;
  assert.deepEqual(original, expected);
  const observation = observe(artifacts[revision].ir, inputs); assert.deepEqual(observation, original);
  if (observation.kind === 'throw') typeErrors++;
  observations.push({ revision, inputs, padding: row.padding ?? null, observation, original });
}
const comparison = compare(artifacts.before.ir, artifacts.after.ir, domains);
assert.equal(comparison.status, 'different-in-declared-domain');
assert.equal(comparison.checked, 98); assert.equal(comparison.changes.length, 64); assert.equal(comparison.unknown.length, 0);
assert.equal(nativeExecutions, 196); assert.equal(typeErrors, 4);
const unsupported = [];
for (const inputValue of [0, false, {}]) for (const revision of ['before', 'after']) {
  const inputs = { inputValue: encode(inputValue) }, observation = observe(artifacts[revision].ir, inputs);
  assert.equal(observation.kind, 'unsupported');
  unsupported.push({ revision, inputs, observation, original: runOriginal(revision, inputValue) });
}
const boundaries = [];
for (const [method, revision] of [['toLowerCase', 'before'], ['trim', 'after']]) {
  const inputs = { inputValue: ' Red ' }, prefix = `String.prototype.${method} = function(){return 'changed-standard-method';};`;
  const original = runOriginal(revision, decode(inputs.inputValue), prefix), observation = observe(artifacts[revision].ir, inputs);
  assert.notDeepEqual(original, observation);
  boundaries.push({ revision, method, inputs, prefixSha256: hash(prefix), original, observation, status: 'outside-unmodified-standard-method-assumption' });
}
for (const [name, value] of Object.entries({ domains, comparison, observations, unsupported, boundaries })) write(name, value);
const example = { inputValue: ' Red ' }, nullInput = { inputValue: null };
write('example-inputs', example); write('null-inputs', nullInput);
let cliReplays = 0;
function cli(...args) {
  const result = spawnSync(process.execPath, [path.join(pkg, 'src/cli.mjs'), ...args], { encoding: 'utf8', timeout: 20000, maxBuffer: 8 * 1024 * 1024 });
  assert.equal(result.status, 0, result.stderr); cliReplays++; return result.stdout;
}
for (const revision of ['before', 'after']) {
  const file = path.join(directory, revision + '.json');
  fs.writeFileSync(path.join(directory, `${revision}-reading.md`), cli('read', '--file', file));
  for (const [name, inputs] of [['example', example], ['null', nullInput]]) {
    const inputFile = path.join(directory, `${name}-inputs.json`);
    assert.deepEqual(JSON.parse(cli('run', '--file', file, '--inputs', inputFile, '--json')).observation, observe(artifacts[revision].ir, inputs));
    fs.writeFileSync(path.join(directory, `${revision}-${name}.md`), cli('explain', '--file', file, '--inputs', inputFile));
  }
}
const compareArgs = ['compare', '--before', path.join(directory, 'before.json'), '--after', path.join(directory, 'after.json'), '--domains', path.join(directory, 'domains.json')];
const replay = JSON.parse(cli(...compareArgs, '--json'));
assert.equal(replay.checked, comparison.checked); assert.deepEqual(replay.changes, comparison.changes);
const changeScope = caseChangeScope(target.case, [target.path]);
fs.writeFileSync(path.join(directory, 'review.md'), [
  '# 색상 입력의 문자열 계산 변경', '', '고정한 원본 const 한 문장을 비교한다. 앞선 callback 호출과 뒤의 색상 해석·상태·저장은 이 계산에 포함하지 않는다.', '',
  `Node ${ENGINE_RUNTIME.node}, V8 ${ENGINE_RUNTIME.v8}, Unicode ${ENGINE_RUNTIME.unicode}, ICU ${ENGINE_RUNTIME.icu}.`, '',
  '입력 98개 중 양끝 제거 대상 문자가 있는 64개에서 관찰 문자열이 달랐다. 0폭 공백은 제거되지 않으며 문자열 내부 공백도 유지된다. null·undefined는 전후 모두 TypeError다.', '',
  describeChangeScope(changeScope), '', cli(...compareArgs),
].join('\n'));
const report = { schema: 'web-color-normalization-results-1', engineSha256: ENGINE_SHA256, runtime: ENGINE_RUNTIME,
  producerSha256: hash(fs.readFileSync(fileURLToPath(import.meta.url))), selectionSha256: hash(selectionBytes), corpusLockSha256: hash(lockBytes),
  id: target.id, sourceEvidence, inputPairs: 98, changes: 64, nativeExecutions, typeErrors,
  unsupportedChecks: unsupported.length, unsupportedNativeExecutions: unsupported.length,
  boundaryCounterexamples: boundaries.length, boundaryNativeExecutions: boundaries.length, cliReplays,
  observationsSha256: hash(fs.readFileSync(path.join(directory, 'observations.json'))),
  domainsSha256: hash(fs.readFileSync(path.join(directory, 'domains.json'))), changeScope, directory,
  humanParticipants: 0, wholeBehaviorCasesVerified: 0,
  notes: ['196 native executions evaluate only the exact selected const and return its local value.',
    'Both native source and IR use this Node runtime’s standard string methods; this does not independently validate the Unicode implementation or another browser runtime.',
    'Six unsupported-input executions and two modified-standard-method counterexamples are separate from the matching native checks.',
    'The input domain includes Unicode and invalid-color strings for language semantics; it is not a set of valid colors or actual browser flows.',
    'No normalizeInputColor, regex, hook, state update, React rendering or persistence behavior is executed by this slice.'] };
fs.writeFileSync(path.join(root, 'build/web-review/color-normalization-results.json'), JSON.stringify(report, null, 2) + '\n');
process.stdout.write(JSON.stringify(report) + '\n');
