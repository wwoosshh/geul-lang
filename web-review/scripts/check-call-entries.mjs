import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
import { liftCallEntry } from '../src/call-entry.mjs';
import { parseSource, hash, location } from '../src/typescript.mjs';
import { encode, observe } from '../src/core.mjs';
import { ENGINE_SHA256 } from '../src/fingerprint.mjs';
import { caseChangeScope, describeChangeScope } from './inventory-scope.mjs';

const pkg = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'), root = path.dirname(pkg);
const selectionBytes = fs.readFileSync(path.join(pkg, 'corpus/call-entries.json')), selection = JSON.parse(selectionBytes);
const lockBytes = fs.readFileSync(path.join(pkg, 'corpus/lock.json')), lock = JSON.parse(lockBytes);
assert.equal(lock.selectionSha256, hash(fs.readFileSync(path.join(pkg, 'corpus/selection.json'))));
const results = [];
for (const target of selection.targets) {
  assert.equal(target.id, 'actual-tag-rename-validation', 'A new target requires an independent oracle');
  const pinned = lock.cases.find(row => row.id === target.case)?.blobs.find(row => row.revision === target.revision && row.path === target.path); assert.ok(pinned);
  const filename = path.join(root, 'build/web-corpus', target.case, target.revision, target.path), source = fs.readFileSync(filename, 'utf8');
  assert.equal(hash(source), pinned.sha256);
  const artifact = liftCallEntry(source, { callee: target.callee, line: target.line, filename });
  assert.deepEqual(artifact.inputs, ['name', 'tag']); assert.equal(artifact.earlyReturns.length, 1);
  assert.equal(artifact.entryRegion.bindings.length, 1); assert.equal(artifact.entryRegion.bindings[0].name, 'trimmed');
  const linked = artifact.sourceLinks, sourceOf = row => source.slice(row.start, row.end);
  assert.equal(linked.status, 'source-links-only');
  assert.equal(sourceOf(linked.callee.declarations[0].destructuringOrigin.expression), 'useRenameTagMutation()');
  assert.equal(linked.entry.name, 'onRename'); assert.equal(linked.entry.referenceCount, 2); assert.equal(linked.entry.referencesTruncated, false);
  assert.deepEqual(linked.entry.references.map(row => row.kind), ['direct-call', 'object-property']);
  const [direct, property] = linked.entry.references;
  assert.equal(sourceOf(direct.expression), 'onRename(e.currentTarget.value)');
  assert.deepEqual(direct.context.precedingStatements.map(row => sourceOf(row.source)), ['e.preventDefault();', 'e.stopPropagation();']);
  assert.deepEqual(direct.context.guards.map(row => [sourceOf(row.condition), row.accepts]), [["e.key === 'Enter'", 'truthy']]);
  assert.equal(property.property, 'onUpdate'); assert.equal(property.jsxContainer.tag, 'InputCell'); assert.equal(property.jsxContainer.attribute, 'inputProps');
  assert.deepEqual(property.context.guards.map(row => [sourceOf(row.condition), row.accepts]), [["focusedField === 'tag'", 'truthy']]);
  const file = parseSource(source, filename), callbacks = [];
  const visit = node => { if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.name.text === target.callback) callbacks.push(node); ts.forEachChild(node, visit); }; visit(file);
  assert.equal(callbacks.length, 1); const callback = callbacks[0].initializer;
  assert.ok(ts.isArrowFunction(callback)); assert.equal(callback.parameters[0].name.getText(file), 'name');
  assert.deepEqual(artifact.functionBody, location(callback.body));
  // Execute the unchanged original arrow function with explicit name/tag
  // snapshots and a recording callee. No hook, event or mutation is started.
  const callbackSource = callback.getText(file);
  const nativeSource = ts.transpileModule(`(${callbackSource})(__geulName);`, { compilerOptions: { target: ts.ScriptTarget.ES2022 }, reportDiagnostics: true });
  assert.equal(nativeSource.diagnostics.filter(row => row.category === ts.DiagnosticCategory.Error).length, 0);
  const script = new vm.Script(nativeSource.outputText);
  function native(name, tag, fault = null) {
    const calls = [];
    let completion = 'returned', callee = payload => {
      // The callback creates this flat object in a different VM realm. Copy
      // its checked own data fields instead of widening the production codec.
      const descriptors = Object.getOwnPropertyDescriptors(payload);
      assert.deepEqual(Object.keys(descriptors), ['id', 'tag']); assert.equal(Object.getOwnPropertySymbols(payload).length, 0);
      for (const descriptor of Object.values(descriptors)) assert.ok(Object.hasOwn(descriptor, 'value') && descriptor.enumerable);
      calls.push(encode(Object.fromEntries(Object.entries(descriptors).map(([key, descriptor]) => [key, descriptor.value]))));
      if (fault === 'callee-throws') throw new TypeError('callee');
    };
    if (fault === 'callee-not-callable') callee = 0;
    try { script.runInNewContext({ __geulName: name, tag, renameTag: callee }, { timeout: 100 }); }
    catch (error) { if (error.name !== 'TypeError') throw error; completion = 'TypeError'; }
    return { completion, calls };
  }
  const names = ['', ' ', '\t\n', '\u00a0', '\ufeff', 'old', ' old ', 'new', '\tnew\n', '\u200b', '한글', null, undefined];
  const tags = [null, undefined, {}, { tag: 'old', id: 't1' }, { tag: 'new', id: 't1' }, { tag: '', id: 't1' },
    { tag: '한글', id: 0 }, { tag: undefined }, { tag: null }];
  const rows = [], counts = { inputChecks: 0, reached: 0, earlyReturns: 0, prefixTypeErrors: 0 };
  for (const name of names) for (const tag of tags) {
    const inputs = { name: encode(name), tag: encode(tag) }, observation = observe(artifact.ir, inputs), original = native(name, tag);
    let expected;
    if (name == null) expected = { kind: 'throw', name: 'TypeError' };
    else if (name.trim() === '') expected = { kind: 'value', value: false };
    else if (tag == null) expected = { kind: 'throw', name: 'TypeError' };
    else expected = { kind: 'value', value: name.trim() !== tag.tag };
    assert.deepEqual(observation, expected);
    assert.equal(original.completion, expected.kind === 'throw' ? 'TypeError' : 'returned');
    assert.equal(original.calls.length, Number(expected.kind === 'value' && expected.value));
    counts.inputChecks++; if (expected.kind === 'throw') counts.prefixTypeErrors++; else if (expected.value) counts.reached++; else counts.earlyReturns++;
    rows.push({ inputs, observation, original });
  }
  assert.equal(counts.inputChecks, 117);
  const counterexamples = [];
  for (const fault of ['callee-not-callable', 'callee-throws', 'argument-getter']) {
    const plainTag = { tag: 'old', id: 't1' }, inputs = { name: 'new', tag: encode(plainTag) }, actualTag = { ...plainTag };
    if (fault === 'argument-getter') Object.defineProperty(actualTag, 'id', { get() { throw new TypeError('id'); } });
    const observation = observe(artifact.ir, inputs), original = native('new', actualTag, fault);
    assert.deepEqual(observation, { kind: 'value', value: true }); assert.equal(original.completion, 'TypeError');
    assert.equal(original.calls.length, Number(fault === 'callee-throws'));
    counterexamples.push({ fault, inputs, observation, original, note: fault === 'argument-getter'
      ? 'Native id getter is outside the plain-record profile and occurs in excluded argument evaluation; the IR receives its plain snapshot.'
      : 'The callee is excluded from the entry model. Reaching its expression does not prove an invocation succeeds.' });
  }
  const unsupported = [];
  for (const name of [1, true, {}]) {
    const inputs = { name: encode(name), tag: encode({ tag: 'old' }) }, observation = observe(artifact.ir, inputs), original = native(name, { tag: 'old' });
    assert.equal(observation.kind, 'unsupported'); assert.equal(original.completion, 'TypeError');
    unsupported.push({ inputs, observation, original });
  }
  const directory = path.join(root, 'build/web-review/call-entries', target.id); fs.mkdirSync(directory, { recursive: true });
  const artifactFile = path.join(directory, 'artifact.json');
  fs.writeFileSync(artifactFile, JSON.stringify(artifact, null, 2) + '\n');
  fs.writeFileSync(path.join(directory, 'native.js'), nativeSource.outputText);
  let cliReplays = 0;
  const cli = (...args) => {
    const run = spawnSync(process.execPath, [path.join(pkg, 'src/cli.mjs'), ...args], { encoding: 'utf8', maxBuffer: 8 * 1024 * 1024, timeout: 20_000 });
    assert.equal(run.status, 0, run.stderr); cliReplays++; return run.stdout;
  };
  for (const [name, inputs, expected] of [
    ['empty-name', { name: ' ', tag: null }, { kind: 'value', value: false }],
    ['changed-name', { name: 'new', tag: encode({ tag: 'old', id: 't1' }) }, { kind: 'value', value: true }],
    ['null-tag', { name: 'new', tag: null }, { kind: 'throw', name: 'TypeError' }],
  ]) {
    const inputFile = path.join(directory, name + '.json'); fs.writeFileSync(inputFile, JSON.stringify(inputs, null, 2) + '\n');
    assert.deepEqual(JSON.parse(cli('run', '--file', artifactFile, '--inputs', inputFile, '--json')).observation, expected);
    fs.writeFileSync(path.join(directory, name + '.md'), cli('explain', '--file', artifactFile, '--inputs', inputFile));
  }
  fs.writeFileSync(path.join(directory, 'reading.md'), cli('read', '--file', artifactFile));
  const reading = JSON.parse(cli('read', '--file', artifactFile, '--json'));
  assert.deepEqual(reading.sourceLinks, linked); assert.equal(reading.observationMeaning.executed, false);
  const readingRules = [];
  function collectRules(node) { if (node.readingRule) readingRules.push(node); node.children.forEach(row => collectRules(row.node)); }
  collectRules(reading.tree);
  assert.equal(readingRules.length, 1); assert.equal(readingRules[0].readingRule.name, 'string-falsiness-is-empty');
  assert.equal(sourceOf(readingRules[0].source), '!trimmed');
  assert.equal(readingRules[0].children[0].node.normalCompletionType, 'string');
  fs.writeFileSync(path.join(directory, 'reading.json'), JSON.stringify(reading, null, 2) + '\n');
  for (const [name, value] of Object.entries({ observations: rows, counterexamples, unsupported })) fs.writeFileSync(path.join(directory, name + '.json'), JSON.stringify(value, null, 2) + '\n');
  const changeScope = caseChangeScope(target.case, [target.path]);
  fs.writeFileSync(path.join(directory, 'scope.md'), `${describeChangeScope(changeScope)}\n\n# 태그 이름 검증과 호출 직전의 경계\n\n${target.expected}\n\n정상 프로필 ${counts.inputChecks}개 중 호출식 직전 도달 ${counts.reached}개, 조기 반환 ${counts.earlyReturns}개, 선행 TypeError ${counts.prefixTypeErrors}개다. 인수나 호출 자체는 글 모델에서 실행하지 않는다. 원본 callback은 hook·React·서버 대신 같은 입력과 기록용 callee를 제공해 별도 실행했다.\n\n호출 대상·인수·callee의 오류 3개는 진입이 호출 성공을 뜻하지 않는 반례다. 숫자·불리언·객체의 trim은 미지원 3개이며 네이티브 성공 건수에 합치지 않는다. 변경 후 callback만 분석했으며 전체 커밋의 전후 동등성 결과가 아니다. 전체 행동 0/12, 사람 참가자 0명.\n`);
  results.push({ id: target.id, ...counts, counterexamples: counterexamples.length, unsupportedProfiles: unsupported.length, cliReplays,
    sourceReferenceChecks: 2, sourceLinkExecutions: 0, sourceLinksSha256: hash(JSON.stringify(linked)),
    readingRewrites: readingRules.length, readingRuntimeExecutions: 0,
    sourceSha256: pinned.sha256, callbackSourceSha256: hash(callbackSource), nativeWrapperSha256: hash(nativeSource.outputText),
    observationsSha256: hash(fs.readFileSync(path.join(directory, 'observations.json'))),
    counterexamplesSha256: hash(fs.readFileSync(path.join(directory, 'counterexamples.json'))),
    unsupportedSha256: hash(fs.readFileSync(path.join(directory, 'unsupported.json'))), changeScope, directory });
}
const report = { schema: 'web-call-entry-results-1', engineSha256: ENGINE_SHA256,
  producerSha256: hash(fs.readFileSync(fileURLToPath(import.meta.url))), selectionSha256: hash(selectionBytes), corpusLockSha256: hash(lockBytes),
  wholeBehaviorCasesVerified: 0, humanParticipants: 0, originalReactExecutions: 0, results };
fs.writeFileSync(path.join(root, 'build/web-review/call-entry-results.json'), JSON.stringify(report, null, 2) + '\n');
process.stdout.write(JSON.stringify({ ...report, results: results.map(({ changeScope, ...row }) => row) }) + '\n');
