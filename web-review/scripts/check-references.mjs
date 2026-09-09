import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import ts from 'typescript';
import { fileURLToPath } from 'node:url';
import { hash } from '../src/typescript.mjs';
import { liftJsxReference } from '../src/jsx-reference.mjs';
import { observe, encode } from '../src/core.mjs';
import { renderExecution } from '../src/report.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const read = name => JSON.parse(fs.readFileSync(path.join(root, 'web-review/corpus', name), 'utf8'));
const selection = read('references.json'), lock = read('lock.json');
assert.equal(lock.selectionSha256, hash(fs.readFileSync(path.join(root, 'web-review/corpus/selection.json'))));
const blob = lock.cases.find(item => item.id === selection.case)?.blobs.find(blob => blob.revision === selection.revision && blob.path === selection.path);
assert.ok(blob);
const filename = path.join(root, 'build/web-corpus', selection.case, selection.revision, selection.path);
const source = fs.readFileSync(filename, 'utf8');
assert.equal(hash(source), blob.sha256);
const results = [];
for (const target of selection.targets) {
  const artifact = liftJsxReference(source, { ...target, filename });
  const original = source.slice(artifact.root.start, artifact.root.end);
  const script = new vm.Script(ts.transpileModule(`const result = ${original};`, { compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022 } }).outputText);
  let checked = 0;
  for (const bottom of [false, true]) for (const value of [null, undefined, false, 0, 'text', { privateProps: () => {} }]) {
    let contributed = false;
    const React = { Fragment: 'fragment', createElement(tag, props, ...children) {
      if (tag === target.container && props?.className === target.className) contributed = children.some(child => child === value && child !== null && typeof child === 'object');
      return { tag };
    } };
    // Run the exact original return expression with explicitly normal,
    // effect-free substitutes for the omitted helpers and component bindings.
    // These substitutes are assumptions of this test, not verified app code.
    const environment = {
      React, shouldRenderDefaultBottomBar: bottom, scrollBackToContentButton: value,
      renderSidebars: () => null, renderWelcomeScreen: false, WelcomeScreenCenterTunnel: { Out: 'Welcome' },
      MobileShapeActions: 'MobileShapeActions', Island: 'Island', FixedSideContainer: 'FixedSideContainer',
      SCROLLBAR_WIDTH: 0, SCROLLBAR_MARGIN: 0, appState: {}, app: { scene: { getNonDeletedElementsMap: () => new Map() } },
      actionManager: { renderAction: () => null }, setAppState: () => {}, renderToolbar: () => null, renderAppTopBar: () => null,
    };
    script.runInNewContext(environment, { timeout: 100 });
    const inputs = { shouldRenderDefaultBottomBar: bottom, scrollBackToContentButton: value && typeof value === 'object' ? { $opaque: 'truthy-object' } : encode(value) };
    const expected = bottom === target.whenBottom && value !== null && typeof value === 'object';
    assert.equal(contributed, expected);
    assert.deepEqual(observe(artifact.ir, inputs), { kind: 'value', value: expected });
    checked++;
  }
  const directory = path.join(root, 'build/web-review/references', `mobile-scroll-${target.line}`);
  fs.mkdirSync(directory, { recursive: true });
  const inputs = { shouldRenderDefaultBottomBar: target.whenBottom, scrollBackToContentButton: { $opaque: 'truthy-object' } };
  fs.writeFileSync(path.join(directory, 'artifact.json'), JSON.stringify(artifact, null, 2) + '\n');
  fs.writeFileSync(path.join(directory, 'inputs.json'), JSON.stringify(inputs, null, 2) + '\n');
  fs.writeFileSync(path.join(directory, 'explanation.md'), renderExecution(artifact, observe(artifact.ir, inputs, { trace: true }), { inputs, snippets: node => source.slice(node.start, node.end) }));
  results.push({ line: target.line, inputChecks: checked, sourceSha256: blob.sha256, artifact });
}
const output = { schema: 'web-reference-results-1', case: selection.case, referencePathsChecked: results.length,
  inputChecks: results.reduce((sum, item) => sum + item.inputChecks, 0), wholeBehaviorCasesVerified: 0,
  notProven: ['생략한 helper·컴포넌트가 실제로 정상·무효과라는 사실', '변수 값이 앞선 JSX 생성 결과와 동일하다는 사실', 'React·DOM 렌더링'], results };
fs.writeFileSync(path.join(root, 'build/web-review/reference-results.json'), JSON.stringify(output, null, 2) + '\n');
process.stdout.write(JSON.stringify({ ...output, results: results.map(({ artifact, ...item }) => item) }, null, 2) + '\n');
