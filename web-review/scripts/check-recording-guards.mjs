import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
import { liftJsxGuards } from '../src/jsx-guards.mjs';
import { parseSource, hash, location } from '../src/typescript.mjs';
import { encode, observe } from '../src/core.mjs';
import { ENGINE_SHA256 } from '../src/fingerprint.mjs';
import { renderExecution } from '../src/report.mjs';
import { caseChangeScope, describeChangeScope } from './inventory-scope.mjs';

const pkg = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'), root = path.dirname(pkg);
const read = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const selectionBytes = fs.readFileSync(path.join(pkg, 'corpus/recording-guards.json')), selection = JSON.parse(selectionBytes);
const lockBytes = fs.readFileSync(path.join(pkg, 'corpus/lock.json')), lock = JSON.parse(lockBytes);
assert.equal(lock.selectionSha256, hash(fs.readFileSync(path.join(pkg, 'corpus/selection.json'))));
const entry = lock.cases.find(row => row.id === selection.case); assert.ok(entry);
const output = path.join(root, 'build/web-review/recording-guards'); fs.mkdirSync(output, { recursive: true });
const artifacts = {}, scripts = {}, sources = {};
for (const revision of ['before', 'after']) {
  const filename = path.join(root, 'build/web-corpus', selection.case, revision, selection.path);
  const source = fs.readFileSync(filename, 'utf8'), pinned = entry.blobs.find(row => row.revision === revision && row.path === selection.path);
  assert.ok(pinned); assert.equal(hash(source), pinned.sha256);
  const artifact = liftJsxGuards(source, { ...selection.target, ...selection[revision], filename });
  assert.equal(artifact.target.intrinsic, false); assert.equal(artifact.prefix.bindings.length, 1);
  assert.equal(artifact.prefix.bindings[0].name, 'renderRecordingToggle');
  assert.equal(artifact.inputs.includes('renderRecordingToggle'), false);
  assert.deepEqual(artifact.inputs, revision === 'before' ? ['_localRecordingRunning', '_renderRecording'] : ['_isLiveStreamRunning', '_localRecordingRunning', '_renderRecording']);
  assert.ok(artifact.omittedEvaluations.some(row => source.slice(row.source.start, row.source.end).includes("t('recording.recordAudioAndVideo')")));
  const file = parseSource(source, filename), methods = [];
  const visit = node => { if (ts.isMethodDeclaration(node) && node.name.getText(file) === selection.method) methods.push(node); ts.forEachChild(node, visit); }; visit(file);
  assert.equal(methods.length, 1); assert.ok(methods[0].body);
  const method = methods[0], body = method.body.getText(file);
  assert.ok(artifact.prefix.source.start > method.body.getStart() && artifact.root.end < method.body.end);
  // The original body, including its props destructuring and other JSX, is
  // unchanged. A function wrapper supplies a declared test receiver. React and
  // Switch below are recording stubs, not the original component runtime.
  const nativeSource = ts.transpileModule(`(function() ${body}).call(__geulReceiver);`, {
    compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022 }, reportDiagnostics: true,
  });
  assert.equal(nativeSource.diagnostics.filter(row => row.category === ts.DiagnosticCategory.Error).length, 0);
  scripts[revision] = new vm.Script(nativeSource.outputText, { filename: `${revision}-recording-method.js` });
  artifacts[revision] = artifact;
  sources[revision] = { file: filename, sha256: pinned.sha256, method: location(method), methodBodySha256: hash(body), nativeWrapperSha256: hash(nativeSource.outputText) };
  fs.writeFileSync(path.join(output, `${revision}.json`), JSON.stringify(artifact, null, 2) + '\n');
  fs.writeFileSync(path.join(output, `${revision}-method.js`), nativeSource.outputText);
}

function native(revision, flags, fault = null) {
  const effects = [], Switch = Object.freeze({ role: 'recording-test-token' });
  let targetFactoryCalls = 0, targetFactoryCompletions = 0, handlerCalls = 0;
  const fail = name => { effects.push(`throw:${name}`); throw new TypeError(name); };
  const receiver = {
    props: { ...flags, shouldRecordAudioAndVideo: false, shouldRecordTranscription: false,
      t: key => { effects.push(`translate:${key}`); if (fault === 'translation') fail(fault); return key; } },
    _onRecordAudioAndVideoSwitchChange() { handlerCalls++; },
    _onTranscriptionSwitchChange() { handlerCalls++; },
    _canStartTranscribing() { effects.push('canStartTranscribing'); if (fault === 'later-transcription-helper') fail(fault); return false; },
    _renderLocalRecordingContent() { effects.push('localRecordingContent'); if (fault === 'later-local-content') fail(fault); return null; },
  };
  if (fault === 'handler-getter') Object.defineProperty(receiver, '_onRecordAudioAndVideoSwitchChange', { get() { fail(fault); } });
  const React = {
    Fragment: Object.freeze({ role: 'fragment-test-token' }),
    createElement(tag, props, ...children) {
      const selected = tag === Switch && props?.id === selection.target.equals;
      effects.push(selected ? 'factory:selected-switch' : `factory:${typeof tag === 'string' ? tag : 'other'}`);
      if (selected) { targetFactoryCalls++; if (fault === 'target-factory') fail(fault); targetFactoryCompletions++; }
      return { tag, props, children };
    },
  };
  let methodOutcome = 'returned';
  try { scripts[revision].runInNewContext({ __geulReceiver: receiver, React, Switch }, { timeout: 100 }); }
  catch (error) { if (error.name !== 'TypeError') throw error; methodOutcome = 'TypeError'; }
  assert.equal(handlerCalls, 0, 'Rendering a test token must not invoke its onChange handler');
  return { methodOutcome, targetFactoryCalls, targetFactoryCompletions, handlerCalls, effects };
}

const names = ['_isLiveStreamRunning', '_renderRecording', '_localRecordingRunning'];
const packFlags = flags => Object.fromEntries(Object.entries(flags).map(([key, value]) => [key, encode(value)]));
// Boolean truth table first; the wider domain tests JavaScript truthiness only.
// No runtime type validity or reachable component state is inferred from it.
const values = [false, true, undefined, null, 0, -0, NaN, 1, '', 'active', {}, { enabled: false }];
const matrix = [], counts = { booleanPairs: 0, booleanChanges: 0, valuePairs: 0, valueChanges: 0, nativeMethodRuns: 0 };
for (const stream of values) for (const recording of values) for (const local of values) {
  const flags = Object.fromEntries(names.map((name, i) => [name, [stream, recording, local][i]]));
  const inputs = packFlags(flags), paired = {};
  for (const revision of ['before', 'after']) {
    const expected = revision === 'before' ? !!recording || !!local : (!stream && !!recording) || !!local;
    const ir = observe(artifacts[revision].ir, inputs), original = native(revision, flags);
    assert.deepEqual(ir, { kind: 'value', value: expected });
    assert.equal(original.methodOutcome, 'returned'); assert.equal(original.targetFactoryCalls, Number(expected));
    assert.equal(original.targetFactoryCompletions, Number(expected)); counts.nativeMethodRuns++;
    paired[revision] = { enteredUnderAssumptions: ir.value, ...original };
  }
  const changed = paired.before.enteredUnderAssumptions !== paired.after.enteredUnderAssumptions;
  assert.equal(changed, !!stream && !!recording && !local);
  if ([stream, recording, local].every(value => typeof value === 'boolean')) { counts.booleanPairs++; counts.booleanChanges += Number(changed); }
  counts.valuePairs++; counts.valueChanges += Number(changed);
  matrix.push({ inputs, changed, ...paired });
}
assert.equal(counts.booleanPairs, 8); assert.equal(counts.booleanChanges, 1);
assert.equal(counts.valuePairs, 1728); assert.equal(counts.valueChanges, 175);
assert.equal(counts.nativeMethodRuns, 3456);

// These are counterexamples to treating an entry condition as completed JSX
// creation, a successful method return, or actual screen visibility.
const counterexamples = [];
for (const fault of ['translation', 'handler-getter', 'target-factory', 'later-transcription-helper', 'later-local-content']) {
  const flags = { _isLiveStreamRunning: false, _renderRecording: fault !== 'later-local-content', _localRecordingRunning: fault === 'later-local-content' };
  for (const revision of ['before', 'after']) {
    const inputs = packFlags(flags), ir = observe(artifacts[revision].ir, inputs), original = native(revision, flags, fault);
    assert.deepEqual(ir, { kind: 'value', value: true }); assert.equal(original.methodOutcome, 'TypeError');
    const later = fault.startsWith('later-');
    assert.equal(original.targetFactoryCalls, Number(later || fault === 'target-factory'));
    assert.equal(original.targetFactoryCompletions, Number(later));
    counterexamples.push({ fault, revision, inputs, entryModel: ir, original });
  }
}
const cli = (...args) => {
  const result = spawnSync(process.execPath, [path.join(pkg, 'src/cli.mjs'), ...args], { encoding: 'utf8', maxBuffer: 8 * 1024 * 1024, timeout: 20_000 });
  assert.equal(result.status, 0, result.stderr); return result.stdout;
};
const exampleInputs = packFlags({ _isLiveStreamRunning: true, _renderRecording: true, _localRecordingRunning: false });
fs.writeFileSync(path.join(output, 'inputs.json'), JSON.stringify(exampleInputs, null, 2) + '\n');
for (const revision of ['before', 'after']) {
  const artifactFile = path.join(output, `${revision}.json`), artifact = artifacts[revision], source = fs.readFileSync(sources[revision].file, 'utf8');
  const replay = JSON.parse(cli('read', '--file', artifactFile, '--json'));
  assert.equal(Object.hasOwn(replay, 'observation'), false);
  const execution = JSON.parse(cli('run', '--file', artifactFile, '--inputs', path.join(output, 'inputs.json'), '--json'));
  assert.deepEqual(execution.observation, { kind: 'value', value: revision === 'before' });
  assert.deepEqual(execution.source, artifact.source); assert.deepEqual(execution.scope, artifact.contract);
  fs.writeFileSync(path.join(output, `${revision}-reading.md`), cli('read', '--file', artifactFile));
  fs.writeFileSync(path.join(output, `${revision}-execution.md`), renderExecution(artifact, observe(artifact.ir, exampleInputs, { trace: true }), { inputs: exampleInputs, snippets: row => source.slice(row.start, row.end) }));
}
fs.writeFileSync(path.join(output, 'observations.json'), JSON.stringify(matrix, null, 2) + '\n');
fs.writeFileSync(path.join(output, 'counterexamples.json'), JSON.stringify(counterexamples, null, 2) + '\n');
const booleanDomains = Object.fromEntries(names.map(name => [name, [false, true]]));
fs.writeFileSync(path.join(output, 'boolean-domains.json'), JSON.stringify(booleanDomains, null, 2) + '\n');
const compareArgs = ['compare', '--before', path.join(output, 'before.json'), '--after', path.join(output, 'after.json'), '--domains', path.join(output, 'boolean-domains.json')];
const comparison = JSON.parse(cli(...compareArgs, '--json'));
assert.equal(comparison.checked, 8); assert.equal(comparison.changes.length, 1); assert.equal(comparison.unknown.length, 0);
assert.deepEqual(comparison.changes[0].inputs, exampleInputs);
assert.deepEqual(comparison.changes[0].before, { kind: 'value', value: true });
assert.deepEqual(comparison.changes[0].after, { kind: 'value', value: false });
fs.writeFileSync(path.join(output, 'boolean-comparison.json'), JSON.stringify(comparison, null, 2) + '\n');
fs.writeFileSync(path.join(output, 'boolean-comparison.md'), cli(...compareArgs));
let refusedAmbiguousSelections = 0;
for (const revision of ['before', 'after']) {
  const result = spawnSync(process.execPath, [path.join(pkg, 'src/cli.mjs'), 'lift-jsx-guards', '--file', sources[revision].file,
    '--tag', selection.target.tag, '--attribute', selection.target.attribute, '--equals', selection.target.equals, '--json'],
  { encoding: 'utf8', timeout: 20_000 });
  assert.equal(result.status, 2); assert.match(result.stdout + result.stderr, /정확히 한 곳이어야 합니다: 2곳/); refusedAmbiguousSelections++;
}
const scope = caseChangeScope(selection.case, [selection.path]);
const report = { schema: 'web-recording-guards-results-1', engineSha256: ENGINE_SHA256,
  producerSha256: hash(fs.readFileSync(fileURLToPath(import.meta.url))), selectionSha256: hash(selectionBytes), corpusLockSha256: hash(lockBytes),
  ...counts, counterexampleMethodRuns: counterexamples.length, cliReplays: 8, refusedAmbiguousSelections, sources, changeScope: scope,
  declaredEnvironment: { props: 'Plain flags from the finite domain; both checked props false; t returns its key.',
    canStartTranscribing: false, localRecordingContent: null, eventHandlers: 'Stored functions; never invoked.',
    elementFactory: 'Recording stub returning plain objects; Switch and Fragment are tokens. No React renderer or actual Switch code.',
    faultOverrides: 'Only the named counterexample point throws TypeError; all other stubs retain their defaults.' },
  observationsSha256: hash(fs.readFileSync(path.join(output, 'observations.json'))),
  counterexamplesSha256: hash(fs.readFileSync(path.join(output, 'counterexamples.json'))),
  originalReactExecutions: 0, wholeBehaviorCasesVerified: 0, humanParticipants: 0,
  scope: selection.scope, notProven: selection.notProven, output };
fs.writeFileSync(path.join(root, 'build/web-review/recording-guards-results.json'), JSON.stringify(report, null, 2) + '\n');
fs.writeFileSync(path.join(output, 'comparison.md'), [
  '# 녹화 토글의 지역 조건과 JSX 진입', '', describeChangeScope(scope), '',
  '원본 _renderSessionToggles 메서드에서 renderRecordingToggle을 계산한 뒤 녹화 Switch에 진입하는 경로를 연결했다. 지역 이름을 독립 입력으로 남기지 않는다. 시작점 이전의 props 구조 분해와 메서드 호출 조건은 글 모델 밖이다.', '',
  '불리언 8쌍에서는 live stream=true, recording permission=true, local recording=false일 때만 진입 조건이 참에서 거짓으로 바뀐다. local recording=true이면 두 버전 모두 토글 진입을 유지한다.', '',
  '더 넓은 JavaScript 값 1,728쌍에서 조건 변화 175개를 확인했다. 불리언 8쌍을 포함하는 집합이며 추가로 합산하지 않는다. 이 값들이 실제 props로 가능한지는 증명하지 않는다.', '',
  '원본 메서드 본문은 바꾸지 않고 시험용 this와 요소 생성기를 공급해 3,456회 실행했다. React·Switch 구현·상위 render·녹화 이벤트를 실행한 결과가 아니다. 생성기에 도달한 호출과 정상 완료를 따로 센다.', '',
  '| 반례 | 글의 진입 조건 | 대상 생성기 호출 | 대상 생성기 정상 완료 | 메서드 결과 |',
  '|---|---|---:|---:|---|',
  ...counterexamples.filter(row => row.revision === 'after').map(row => `| ${row.fault} | 참 | ${row.original.targetFactoryCalls} | ${row.original.targetFactoryCompletions} | ${row.original.methodOutcome} |`), '',
  '번역 함수·대상 속성 getter·생성기·뒤의 helper에 예외를 넣은 10회 실행은 조건만으로 생성·반환·화면 표시를 보장할 수 없다는 반례다. 원본 버그 발견이나 전체 의미 보존 성공으로 세지 않는다.', '',
  '전체 행동 0/12, 사람 참가자 0명. before/after-reading.md는 원본 연결을 포함한 구조 설명, before/after-execution.md는 한 입력의 계산 기록이다.', '',
].join('\n'));
process.stdout.write(JSON.stringify(report) + '\n');
