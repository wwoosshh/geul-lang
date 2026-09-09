import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import clsx from 'clsx';
import { liftJsxFlow } from '../src/jsx-flow.mjs';
import { observe, encode, decode } from '../src/core.mjs';
import { hash } from '../src/typescript.mjs';
import { mobileProfiles, inputSpecificationSha256 } from './mobile-cases.mjs';

const require = createRequire(import.meta.url);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const packageRoot = path.join(root, 'web-review');
const read = filename => JSON.parse(fs.readFileSync(filename, 'utf8'));
const runtimeLock = read(path.join(packageRoot, 'corpus/runtime-lock.json'));
const corpusLockBytes = fs.readFileSync(path.join(packageRoot, 'corpus/lock.json'));
assert.equal(runtimeLock.corpusLockSha256, hash(corpusLockBytes));
assert.equal(runtimeLock.selectionSha256, hash(fs.readFileSync(path.join(packageRoot, 'corpus/runtime-selection.json'))));
const corpus = JSON.parse(corpusLockBytes);
assert.equal(corpus.selectionSha256, hash(fs.readFileSync(path.join(packageRoot, 'corpus/selection.json'))));
const npmLock = read(path.join(packageRoot, 'package-lock.json'));
const verify = spawnSync('python', [path.join(packageRoot, 'scripts/runtime.py'), 'verify'], { encoding: 'utf8', timeout: 10000 });
assert.equal(verify.status, 0, verify.stderr || verify.stdout);
const target = read(path.join(packageRoot, 'corpus/flows.json')).targets.find(target => target.case === runtimeLock.case);
assert.ok(target);
const output = path.join(root, 'build/web-review/react', target.id);
fs.mkdirSync(output, { recursive: true });
const results = [];

for (const pinned of runtimeLock.revisions) {
  const revision = pinned.revision, caseInfo = corpus.cases.find(item => item.id === runtimeLock.case);
  assert.equal(pinned.commit, caseInfo[revision === 'before' ? 'parent' : 'head']);
  for (const entry of pinned.packages) {
    const installed = npmLock.packages['node_modules/' + entry.name];
    assert.equal(installed.version, entry.version);
    assert.equal(installed.integrity, entry.integrity);
    assert.equal(require(entry.name + '/package.json').version, entry.version);
  }
  const sources = {}, omittedStyleImports = [];
  for (const blob of pinned.blobs) {
    const filename = path.join(root, 'build/web-runtime', runtimeLock.case, revision, blob.path);
    const source = fs.readFileSync(filename, 'utf8');
    assert.equal(hash(source), blob.sha256);
    if (blob.path.endsWith('.tsx')) sources[blob.path] = source;
  }
  const components = {};
  // This runtime oracle executes only the two hash-bound component modules.
  // The analyzer does not use execution to resolve dependencies. The import
  // allowlist and explicit skipped CSS keep this oracle's scope inspectable.
  for (const [filename, source] of Object.entries(sources)) {
    const module = { exports: {} };
    const compiled = ts.transpileModule(source, { fileName: filename, compilerOptions: {
      target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, esModuleInterop: true,
    } }).outputText;
    const limitedRequire = specifier => {
      if (specifier === 'react') return React;
      if (specifier === 'clsx') return clsx;
      if (specifier === './Island.scss' || specifier === './FixedSideContainer.scss') {
        omittedStyleImports.push({ file: filename, specifier }); return {};
      }
      throw new Error(`Unreviewed runtime import: ${specifier}`);
    };
    vm.runInNewContext(compiled, { exports: module.exports, module, require: limitedRequire }, { timeout: 1000, filename });
    Object.assign(components, module.exports);
  }
  assert.ok(components.Island && components.FixedSideContainer);
  const sourceFile = path.join(root, 'build/web-corpus', runtimeLock.case, revision, target.path);
  const source = fs.readFileSync(sourceFile, 'utf8');
  const blob = caseInfo.blobs.find(blob => blob.revision === revision && blob.path === target.path);
  assert.equal(hash(source), blob.sha256);
  const artifact = liftJsxFlow(source, { ...target.selector, ...(revision === 'after' ? { prefixLine: target.afterPrefixLine } : {}), filename: sourceFile });
  const body = artifact.flow.route === 'stored-const' ? source.slice(artifact.prefix.source.start, artifact.flow.returnExpression.end) + ';' : `return ${source.slice(artifact.root.start, artifact.root.end)};`;
  const compiled = new vm.Script(ts.transpileModule(`function selectedRegion() { ${body} } selectedRegion();`, {
    compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022 },
  }).outputText);
  function render(inputs, { mutate = false, dropChildren = false, throwBeforeReturn = false } = {}) {
    const appState = decode(inputs.appState);
    const alter = () => { if (mutate) {
      appState.viewModeEnabled = !appState.viewModeEnabled; appState.scrolledOutside = !appState.scrolledOutside;
      appState.openMenu = appState.openMenu ? null : 'canvas'; appState.openSidebar = appState.openSidebar ? null : { name: 'library' };
    } };
    const environment = {
      React, appState, defaultUIEnabled: inputs.defaultUIEnabled, scrollBackToContentUIEnabled: inputs.scrollBackToContentUIEnabled,
      Island: dropChildren ? () => null : components.Island, FixedSideContainer: components.FixedSideContainer,
      renderSidebars: () => { if (throwBeforeReturn) throw new Error('deliberate helper failure'); alter(); return null; },
      renderWelcomeScreen: false, WelcomeScreenCenterTunnel: { Out: () => null }, MobileShapeActions: () => null,
      SCROLLBAR_WIDTH: 0, SCROLLBAR_MARGIN: 0, app: { scene: { getNonDeletedElementsMap: () => new Map() } },
      actionManager: { renderAction: () => null }, setAppState: () => {}, renderToolbar: () => null, renderAppTopBar: () => null,
      t: key => { alter(); return key; },
    };
    const tree = compiled.runInNewContext(environment, { timeout: 100 });
    assert.ok(React.isValidElement(tree));
    const html = renderToStaticMarkup(tree);
    const count = [...html.matchAll(/<button\b[^>]*class="scroll-back-to-content"/g)].length;
    return { count, html };
  }
  let renderChecks = 0, mutationChecks = 0;
  for (const inputs of mobileProfiles.flatMap(profile => profile.inputs)) {
    const { scrollBackToContentUIEnabled } = inputs;
    const { viewModeEnabled, scrolledOutside, openMenu, openSidebar } = decode(inputs.appState);
    const expected = scrollBackToContentUIEnabled && scrolledOutside && !openMenu && !openSidebar && (revision === 'after' || !viewModeEnabled);
    const observation = observe(artifact.ir, inputs);
    assert.deepEqual(observation, { kind: 'value', value: expected });
    const actual = render(inputs);
    assert.equal(actual.count, Number(expected));
    renderChecks++;
    if (revision === 'after') { assert.equal(render(inputs, { mutate: true }).count, Number(expected)); mutationChecks++; }
  }
  const example = { defaultUIEnabled: true, scrollBackToContentUIEnabled: true,
    appState: encode({ viewModeEnabled: true, scrolledOutside: true, openMenu: null, openSidebar: null }) };
  fs.writeFileSync(path.join(output, revision + '.html'), '<!doctype html>\n<meta charset="utf-8">\n' + render(example).html + '\n');
  const outsideContract = { ...example, appState: encode({ viewModeEnabled: false, scrolledOutside: true, openMenu: null, openSidebar: null }) };
  const model = observe(artifact.ir, outsideContract);
  assert.equal(model.value, true);
  assert.equal(render(outsideContract, { dropChildren: true }).count, 0);
  assert.throws(() => render(outsideContract, { throwBeforeReturn: true }), /deliberate helper failure/);
  results.push({ revision, commit: pinned.commit, sourceSha256: blob.sha256, packageVersions: Object.fromEntries(pinned.packages.map(item => [item.name, item.version])),
    renderChecks, mutationChecks, executedOriginalModules: pinned.blobs.filter(blob => blob.path.endsWith('.tsx')), omittedStyleImports,
    boundaryCounterexamples: [
      { change: 'Island 테스트 대역이 children을 버림', model: model.value, htmlButtonCount: 0, lesson: '자식 자리 전달은 부모 컴포넌트의 실제 렌더링과 다르다.' },
      { change: 'renderSidebars 테스트 대역이 예외를 던짐', model: model.value, runtime: 'throw', lesson: '생략한 평가의 정상 완료 가정을 제거하면 모델 결과를 화면 동작으로 해석할 수 없다.' },
    ] });
}
const report = { schema: 'web-react-results-1', runtimeLockSha256: hash(fs.readFileSync(path.join(packageRoot, 'corpus/runtime-lock.json'))),
  inputSpecificationSha256, inputProfiles: mobileProfiles.map(profile => ({ id: profile.id, inputs: profile.inputs.length })),
  npmLockSha256: hash(fs.readFileSync(path.join(packageRoot, 'package-lock.json'))),
  engineSha256: (await import('../src/fingerprint.mjs')).ENGINE_SHA256,
  wholeBehaviorCasesVerified: 0, renderChecks: results.reduce((sum, item) => sum + item.renderChecks + item.mutationChecks, 0),
  scope: '고정된 React 서버 렌더러, 실제 Island·FixedSideContainer 원본과 명시한 정상 helper 대역에서 선택 MobileMenu 구간의 HTML button 개수를 대조했다.',
  substitutes: ['MobileShapeActions', 'WelcomeScreenCenterTunnel.Out', 'renderSidebars', 'renderToolbar', 'renderAppTopBar', 't', 'app.scene.getNonDeletedElementsMap', 'actionManager.renderAction', 'setAppState', 'SCROLLBAR_WIDTH', 'SCROLLBAR_MARGIN', 'renderWelcomeScreen=false'],
  notProven: ['원본 컴포넌트의 구간 이전 hooks·호출·상태 도달', '대역 함수와 실제 의존성의 일치', '원본 CSS·화면 배치·가림·브라우저 DOM·hydration', '클릭 이벤트·서버·전체 사용자 흐름', '도메인 밖 입력과 다른 React 버전'], results };
fs.writeFileSync(path.join(root, 'build/web-review/react-results.json'), JSON.stringify(report, null, 2) + '\n');
process.stdout.write(JSON.stringify(report, null, 2) + '\n');
