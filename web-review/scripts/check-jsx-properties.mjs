import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import ts from 'typescript';
import React from 'react';
import ReactDOM from 'react-dom';
import { renderToStaticMarkup } from 'react-dom/server';
import { liftJsxProperty } from '../src/jsx-property.mjs';
import { encode, decode, observe, compare } from '../src/core.mjs';
import { hash } from '../src/typescript.mjs';
import { ENGINE_SHA256 } from '../src/fingerprint.mjs';
import { describeComparison, describeChangeSummary } from '../src/presentation.mjs';
import { summarizeChanges } from '../src/change-rules.mjs';
import { caseChangeScope, describeChangeScope } from './inventory-scope.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..'), pkg = path.join(root, 'web-review');
const read = name => JSON.parse(fs.readFileSync(path.join(pkg, 'corpus', name), 'utf8'));
const corpus = read('lock.json'), selection = read('jsx-properties.json');
assert.equal(corpus.selectionSha256, hash(fs.readFileSync(path.join(pkg, 'corpus/selection.json'))));
const samples = [
  { value: null, invalid: false, typeProfile: true }, { value: '', invalid: false, typeProfile: true },
  { value: ' ', invalid: true, typeProfile: true }, { value: 'Invalid hex length', invalid: true, typeProfile: true }, { value: 'Invalid color', invalid: true, typeProfile: true },
  { value: undefined, invalid: false }, { value: false, invalid: false }, { value: true, invalid: true },
  { value: 0, invalid: false }, { value: -0, invalid: false }, { value: NaN, invalid: false }, { value: 1, invalid: true }, { value: {}, invalid: true },
];
const domains = { errorMessage: samples.map(row => encode(row.value)) }, results = [];
for (const target of selection.targets) {
  assert.equal(target.tag, 'input'); assert.equal(target.attribute, 'aria-invalid');
  assert.equal(React.version, target.reactProbeVersion); assert.equal(ReactDOM.version, target.reactProbeVersion);
  const entry = corpus.cases.find(row => row.id === target.case), artifacts = {}, sourceFiles = {}, sourceTexts = {}, native = {}, probes = {}, rows = [];
  const directory = path.join(root, 'build/web-review/jsx-properties', target.id);
  fs.mkdirSync(directory, { recursive: true });
  for (const revision of ['before', 'after']) {
    const blob = entry.blobs.find(row => row.revision === revision && row.path === target.path); assert.ok(blob);
    const file = sourceFiles[revision] = path.join(root, 'build/web-corpus', target.case, revision, target.path);
    const text = sourceTexts[revision] = fs.readFileSync(file, 'utf8'); assert.equal(hash(text), blob.sha256);
    const artifact = artifacts[revision] = liftJsxProperty(text, { tag: target.tag, attribute: target.attribute, filename: file });
    assert.equal(artifact.target.provided, target[revision + 'Provided']);
    if (revision === 'after') {
      const expression = artifact.ir.properties[0].value.source;
      assert.equal(text.slice(expression.start, expression.end), target.afterExpression);
    }
    const raw = artifact.target.provided ? text.slice(artifact.source.start, artifact.source.end) : '';
    // Deliberately isolated JSX probe: retain the selected original attribute
    // text, omit other props/children/hooks and use a capture factory, not React.
    probes[revision] = `const view = <input ${raw}/>;`;
    const js = ts.transpileModule(probes[revision], { compilerOptions: { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, jsxFactory: 'capture' } }).outputText;
    native[revision] = new vm.Script(js + '\nview;');
    fs.writeFileSync(path.join(directory, `${revision}-selected-property.tsx`), '// Isolated probe; not the original component. See comparison.md for omitted scope.\n' + probes[revision] + '\n');
    fs.writeFileSync(path.join(directory, `${revision}.json`), JSON.stringify(artifact, null, 2) + '\n');
  }
  let jsxNativeChecks = 0, reactProbeChecks = 0;
  for (const [i, sample] of samples.entries()) for (const revision of ['before', 'after']) {
    const inputs = { errorMessage: domains.errorMessage[i] };
    const expected = { kind: 'value', value: encode(revision === 'before' ? {} : { 'aria-invalid': sample.invalid }) };
    const observation = observe(artifacts[revision].ir, inputs);
    assert.deepEqual(observation, expected);
    const capture = (tag, props) => {
      assert.equal(tag, 'input');
      return Object.hasOwn(props ?? {}, target.attribute) ? { [target.attribute]: props[target.attribute] } : {};
    };
    const actual = native[revision].runInNewContext({ capture, errorMessage: decode(inputs.errorMessage) }, { timeout: 100 });
    assert.deepEqual(encode(actual), expected.value); jsxNativeChecks++;
    // A separate fixed React 19.0.0 host-element probe. This is not claimed to
    // execute the selected upstream component or its original runtime/build.
    const html = renderToStaticMarkup(React.createElement('input', decode(observation.value)));
    const match = html.match(/aria-invalid="(true|false)"/);
    const htmlValue = match?.[1] ?? null;
    assert.equal(htmlValue, revision === 'before' ? null : String(sample.invalid)); reactProbeChecks++;
    rows.push({ revision, inputs, typeProfile: !!sample.typeProfile, observation, reactProbe: { version: React.version, html, attribute: htmlValue },
      // WAI-ARIA 1.2 defines absence and false as the same default false token.
      // A normative interpretation, not a measured accessibility-tree result.
      declaredAriaInvalid: revision === 'before' ? false : sample.invalid });
  }
  const rawComparison = compare(artifacts.before.ir, artifacts.after.ir, domains);
  assert.equal(rawComparison.checked, samples.length); assert.equal(rawComparison.changes.length, samples.length);
  assert.equal(rawComparison.unknown.length, 0);
  const comparison = { ...rawComparison, domains, changeRules: summarizeChanges(rawComparison, domains), beforeContract: artifacts.before.contract, afterContract: artifacts.after.contract };
  const declaredAriaChanges = samples.filter(row => row.invalid).length;
  const validTypeDeclaredAriaChanges = samples.filter(row => row.typeProfile && row.invalid).length;
  const inputs = { errorMessage: 'Invalid color' };
  for (const [name, value] of Object.entries({ domains, comparison, inputs, probes: rows })) fs.writeFileSync(path.join(directory, `${name}.json`), JSON.stringify(value, null, 2) + '\n');
  const changeScope = caseChangeScope(target.case, [target.path]);
  for (const revision of ['before', 'after']) {
    const replay = spawnSync(process.execPath, [path.join(pkg, 'src/cli.mjs'), 'explain', '--file', path.join(directory, `${revision}.json`), '--inputs', path.join(directory, 'inputs.json')], { encoding: 'utf8', timeout: 10_000 });
    assert.equal(replay.status, 0, replay.stderr);
    fs.writeFileSync(path.join(directory, `${revision}.md`), describeChangeScope(changeScope) + '\n\n' + replay.stdout);
  }
  const replay = spawnSync(process.execPath, [path.join(pkg, 'src/cli.mjs'), 'compare', '--before', path.join(directory, 'before.json'), '--after', path.join(directory, 'after.json'), '--domains', path.join(directory, 'domains.json'), '--json'], { encoding: 'utf8', timeout: 10_000 });
  assert.equal(replay.status, 0, replay.stderr);
  assert.deepEqual(JSON.parse(replay.stdout).changes, comparison.changes);
  const sourceLink = revision => `[${revision === 'before' ? '변경 전' : '변경 후'}](<${sourceFiles[revision].replaceAll('\\', '/')}:${artifacts[revision].target.element.line}>)`;
  fs.writeFileSync(path.join(directory, 'comparison.md'), `${describeChangeSummary(comparison)}\n\n${describeChangeScope(changeScope)}\n\n# 색상 입력에 aria-invalid 속성을 추가한 변화\n\n원본 태그: ${sourceLink('before')}, ${sourceLink('after')}. 변경 전에는 선택 속성이 없고 변경 후에는 원본의 !!errorMessage를 계산한다. 다른 속성 ${artifacts.after.omittedAttributes.length}개와 hooks·콜백은 이 계산에서 실행하지 않았다.\n\n${describeComparison(comparison)}\n\n선택 속성만 남긴 별도 JSX 조각의 생성 인자를 ${jsxNativeChecks}회 대조했다. 전체 원본 input·ColorInput 컴포넌트의 실행이 아니다. 추가 React ${React.version} 실험 ${reactProbeChecks}회에서는 속성이 없던 HTML에 aria-invalid="true" 또는 "false"가 생겼다. 이 실험은 검토 도구에 고정한 React의 기본 input이며 원본 앱의 실행 환경·CSS·접근성 트리를 재현하지 않는다.\n\n데이터 관찰은 ${samples.length}개 입력 모두에서 속성 추가를 기록하지만, [WAI-ARIA 1.2의 aria-invalid](https://www.w3.org/TR/wai-aria-1.2/#aria-invalid)는 속성 없음과 false를 모두 기본 false로 해석한다. 이 규범에 따른 선언 상태가 달라지는 입력은 ${declaredAriaChanges}개이며 실제 보조 기술을 실행한 수치가 아니다. 그중 원본의 string|null 타입 모양에 맞춘 입력에서는 ${validTypeDeclaredAriaChanges}개다. 타입에 맞는다는 사실도 실제 상태 도달의 증거는 아니다.\n\n이 결과만으로 색상 판별이 정확해졌거나, 화면에 오류 메시지가 보이거나, 스크린리더 안내가 올바르게 작동한다고 판단하면 안 된다. 입력 처리·오류 상태 갱신·role=alert 내용·CSS와 실제 사용 경로는 별도다.\n`);
  results.push({ id: target.id, case: target.case, engineSha256: ENGINE_SHA256,
    sourceSha256: Object.fromEntries(Object.entries(sourceTexts).map(([revision, text]) => [revision, hash(text)])),
    selectedProbeSha256: Object.fromEntries(Object.entries(probes).map(([revision, text]) => [revision, hash(text)])),
    pairedInputs: samples.length, propertyPresenceChanges: comparison.changes.length, jsxNativeChecks, reactProbeChecks,
    reactProbeVersion: React.version, originalComponentExecutions: 0, typeProfileInputs: samples.filter(row => row.typeProfile).length,
    declaredAriaChanges, validTypeDeclaredAriaChanges, cliReplayChecks: 3, changeScope, directory });
}
const result = { schema: 'web-jsx-property-results-1', engineSha256: ENGINE_SHA256, producerSha256: hash(fs.readFileSync(fileURLToPath(import.meta.url))),
  selectionSha256: hash(fs.readFileSync(path.join(pkg, 'corpus/jsx-properties.json'))), domainsSha256: hash(JSON.stringify(domains)),
  scope: selection.scope, wholeBehaviorCasesVerified: 0, results };
fs.writeFileSync(path.join(root, 'build/web-review/jsx-property-results.json'), JSON.stringify(result, null, 2) + '\n');
process.stdout.write(JSON.stringify({ ...result, results: results.map(({ changeScope, ...row }) => row) }, null, 2) + '\n');
