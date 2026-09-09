import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import ts from 'typescript';
import { fileURLToPath } from 'node:url';
import { liftJsxGuards } from '../src/jsx-guards.mjs';
import { observe, encode, decode } from '../src/core.mjs';
import { hash } from '../src/typescript.mjs';
import { renderExecution } from '../src/report.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const read = name => JSON.parse(fs.readFileSync(path.join(root, 'web-review/corpus', name), 'utf8'));
const lock = read('lock.json'), targets = read('guards.json').targets;
assert.equal(lock.selectionSha256, hash(fs.readFileSync(path.join(root, 'web-review/corpus/selection.json'))));
// These expectations are deliberately independent of the extracted ancestor
// expressions. They refer to entry into the selected node, NOT its later use.
function casesFor(oracle, revision) {
  const cases = [];
  if (oracle === 'desktop-scroll-v1') {
    for (const formFactor of ['phone', 'desktop']) for (const toast of [null, false, '', { message: 'notice' }])
      for (const scrolledOutside of [false, true]) for (const ui of [false, true]) {
        cases.push({ inputs: { editorInterface: encode({ formFactor }), appState: encode({ toast, scrolledOutside }), scrollBackToContentUIEnabled: ui },
          expected: formFactor !== 'phone' && !toast && scrolledOutside && ui });
      }
  } else if (['mobile-scroll-v1', 'mobile-scroll-prefix-v1'].includes(oracle)) {
    for (const viewModeEnabled of [false, true]) for (const defaultUIEnabled of [false, true])
      for (const scrolledOutside of [false, true]) for (const ui of [false, true])
        for (const openMenu of [null, 'canvas']) for (const openSidebar of [null, { name: 'library' }]) {
          const appState = encode({ viewModeEnabled, scrolledOutside, openMenu, openSidebar });
          const inputs = revision === 'before' || oracle === 'mobile-scroll-prefix-v1' ? { appState, defaultUIEnabled, scrollBackToContentUIEnabled: ui }
            : { appState, shouldRenderScrollBackToContent: scrolledOutside && ui };
          cases.push({ inputs, expected: (revision === 'after' || !viewModeEnabled) && scrolledOutside && ui && !openMenu && !openSidebar });
        }
    if (oracle === 'mobile-scroll-prefix-v1') {
      for (const ui of [false, true]) for (const defaultUIEnabled of [false, true]) cases.push({
        inputs: { appState: null, scrollBackToContentUIEnabled: ui, defaultUIEnabled }, expected: false,
        expectedObservation: ui || defaultUIEnabled ? { kind: 'throw', name: 'TypeError' } : { kind: 'value', value: false },
      });
    }
  } else throw new Error(`Missing independent oracle: ${oracle}`);
  return cases;
}

const results = [];
for (const target of targets) for (const revision of target.revisions ?? ['before', 'after']) {
  const blob = lock.cases.find(item => item.id === target.case)?.blobs.find(blob => blob.revision === revision && blob.path === target.path);
  assert.ok(blob);
  const filename = path.join(root, 'build/web-corpus', target.case, revision, target.path);
  const source = fs.readFileSync(filename, 'utf8');
  assert.equal(hash(source), blob.sha256);
  const artifact = liftJsxGuards(source, { ...target.selector, filename });
  if (target.oracle === 'mobile-scroll-v1' && revision === 'after') {
    const stored = artifact.bindings.storedResult;
    assert.equal(stored.name, 'scrollBackToContentButton');
    assert.deepEqual(stored.uses.map(use => use.kind), ['jsx-child', 'condition-value', 'jsx-child']);
    const input = artifact.bindings.inputs.find(input => input.name === 'shouldRenderScrollBackToContent');
    assert.equal(input.status, 'declaration-found');
    const initializer = input.declarations[0].initializer;
    assert.equal(source.slice(initializer.start, initializer.end), 'scrollBackToContentUIEnabled && appState.scrolledOutside');
  }
  // Execute the exact original guard expressions separately. This does not
  // execute omitted siblings, JSX props, the whole component or a renderer.
  const originals = artifact.guards.map(guard => new vm.Script(`(${source.slice(guard.conditionSource.start, guard.conditionSource.end)})`));
  const nativeRegion = artifact.prefix ? new vm.Script(ts.transpileModule(source.slice(artifact.prefix.source.start, artifact.root.end),
    { compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022 } }).outputText) : undefined;
  let originalGuardEvaluations = 0;
  const cases = casesFor(target.oracle, revision);
  for (const item of cases) {
    const context = Object.fromEntries(Object.entries(item.inputs).map(([name, value]) => [name, decode(value)]));
    const expected = item.expectedObservation ?? { kind: 'value', value: item.expected };
    if (nativeRegion) {
      let reached = false, actual;
      try {
        nativeRegion.runInNewContext({ ...context, t: key => key, React: { createElement(tag) { if (tag === 'button') reached = true; return { tag }; } } }, { timeout: 100 });
        actual = { kind: 'value', value: reached };
      } catch (error) { if (error.name !== 'TypeError') throw error; actual = { kind: 'throw', name: 'TypeError' }; }
      assert.deepEqual(actual, expected, JSON.stringify(item.inputs));
      assert.deepEqual(observe(artifact.ir, item.inputs), expected);
      continue;
    }
    let nativeReached = true;
    for (const [index, guard] of artifact.guards.entries()) {
      const value = originals[index].runInNewContext(context, { timeout: 100 });
      originalGuardEvaluations++;
      const accepted = guard.accepts === 'nullish' ? value == null : guard.accepts === 'truthy' ? !!value : !value;
      if (!accepted) { nativeReached = false; break; }
    }
    assert.equal(nativeReached, item.expected, JSON.stringify(item.inputs));
    assert.deepEqual(observe(artifact.ir, item.inputs), expected);
  }
  const directory = path.join(root, 'build/web-review/guards', target.id, revision);
  fs.mkdirSync(directory, { recursive: true });
  const example = cases.find(item => item.expected);
  const explanation = renderExecution(artifact, observe(artifact.ir, example.inputs, { trace: true }), { inputs: example.inputs, snippets: node => source.slice(node.start, node.end) });
  fs.writeFileSync(path.join(directory, 'artifact.json'), JSON.stringify(artifact, null, 2) + '\n');
  fs.writeFileSync(path.join(directory, 'inputs.json'), JSON.stringify(example.inputs, null, 2) + '\n');
  fs.writeFileSync(path.join(directory, 'explanation.md'), explanation);
  results.push({ id: target.id, revision, case: target.case, sourceSha256: blob.sha256, inputChecks: cases.length,
    originalGuardEvaluations, originalConstRegionEvaluations: nativeRegion ? cases.length : 0,
    guardCount: artifact.guards.length, omittedEvaluationCount: artifact.omittedEvaluations.length, artifact });
}
const output = { schema: 'web-guard-results-1', sourceCaseCount: new Set(results.map(item => item.case)).size,
  expressionPathsChecked: results.length, inputChecks: results.reduce((sum, item) => sum + item.inputChecks, 0),
  originalGuardEvaluations: results.reduce((sum, item) => sum + item.originalGuardEvaluations, 0),
  originalConstRegionEvaluations: results.reduce((sum, item) => sum + item.originalConstRegionEvaluations, 0),
  wholeBehaviorCasesVerified: 0,
  notProven: ['선행 평가의 정상 완료·입력 불변', '지역 변수 정의와 입력 스냅샷의 일치', '선택 요소의 생성 성공·사용처·렌더링', '변경 전후 관찰 루트의 동등성'], results };
fs.writeFileSync(path.join(root, 'build/web-review/guard-results.json'), JSON.stringify(output, null, 2) + '\n');
process.stdout.write(JSON.stringify({ ...output, results: results.map(({ artifact, ...item }) => item) }, null, 2) + '\n');
