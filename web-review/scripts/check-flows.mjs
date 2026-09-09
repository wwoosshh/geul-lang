import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
import { hash } from '../src/typescript.mjs';
import { liftJsxFlow } from '../src/jsx-flow.mjs';
import { observe, encode, decode, compare } from '../src/core.mjs';
import { summarizeChanges } from '../src/change-rules.mjs';
import { renderExecution } from '../src/report.mjs';
import { describeComparison } from '../src/presentation.mjs';
import { mobileProfiles, inputSpecificationSha256 } from './mobile-cases.mjs';
import { caseChangeScope, describeChangeScope } from './inventory-scope.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const read = name => JSON.parse(fs.readFileSync(path.join(root, 'web-review/corpus', name), 'utf8'));
const selection = read('flows.json'), lock = read('lock.json');
assert.equal(lock.selectionSha256, hash(fs.readFileSync(path.join(root, 'web-review/corpus/selection.json'))));
const bools = [false, true], results = [];
const inputsList = mobileProfiles.flatMap(profile => profile.inputs);

for (const target of selection.targets) {
  assert.equal(target.oracle, 'mobile-scroll-child-delivery-v1');
  const changeScope = caseChangeScope(target.case, [target.path]);
  const directory = path.join(root, 'build/web-review/flows', target.id), artifacts = {}, checked = [];
  for (const revision of ['before', 'after']) {
    const blob = lock.cases.find(item => item.id === target.case)?.blobs.find(blob => blob.revision === revision && blob.path === target.path);
    assert.ok(blob);
    const filename = path.join(root, 'build/web-corpus', target.case, revision, target.path), source = fs.readFileSync(filename, 'utf8');
    assert.equal(hash(source), blob.sha256);
    const artifact = liftJsxFlow(source, { ...target.selector, ...(revision === 'after' ? { prefixLine: target.afterPrefixLine } : {}), filename });
    artifacts[revision] = artifact;
    // Execute exact original text at the selected boundary. No app module or
    // imported package is evaluated. JSX factories/helpers below are explicit
    // normal-completion premises, not validated implementations of React.
    const body = artifact.flow.route === 'stored-const'
      ? source.slice(artifact.prefix.source.start, artifact.flow.returnExpression.end) + ';'
      : `return ${source.slice(artifact.root.start, artifact.root.end)};`;
    const script = new vm.Script(ts.transpileModule(`function selectedRegion() { ${body} } selectedRegion();`, {
      compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022 },
    }).outputText);
    function native(inputs, mutation = false) {
      let element, contributed = false;
      const appState = decode(inputs.appState);
      const mutate = () => { if (mutation && appState) {
        appState.viewModeEnabled = !appState.viewModeEnabled; appState.scrolledOutside = !appState.scrolledOutside;
        appState.openMenu = appState.openMenu ? null : 'canvas'; appState.openSidebar = appState.openSidebar ? null : { name: 'library' };
      } };
      const React = { Fragment: 'fragment', createElement(tag, props, ...children) {
        if (tag === 'button' && props?.className === 'scroll-back-to-content') { element = { tag, props }; return element; }
        if (element && children.includes(element)) contributed = true;
        return { tag };
      } };
      const environment = {
        React, appState, defaultUIEnabled: inputs.defaultUIEnabled, scrollBackToContentUIEnabled: inputs.scrollBackToContentUIEnabled,
        renderSidebars: () => { mutate(); return null; }, renderWelcomeScreen: false, WelcomeScreenCenterTunnel: { Out: 'Welcome' },
        MobileShapeActions: 'MobileShapeActions', Island: 'Island', FixedSideContainer: 'FixedSideContainer',
        SCROLLBAR_WIDTH: 0, SCROLLBAR_MARGIN: 0, app: { scene: { getNonDeletedElementsMap: () => new Map() } },
        actionManager: { renderAction: () => null }, setAppState: () => {}, renderToolbar: () => null, renderAppTopBar: () => null,
        t: key => { mutate(); return key; },
      };
      try { script.runInNewContext(environment, { timeout: 100 }); return { kind: 'value', value: contributed }; }
      catch (error) { if (error.name === 'TypeError') return { kind: 'throw', name: 'TypeError' }; throw error; }
    }
    let inputChecks = 0, mutationChecks = 0, nullishChecks = 0;
    for (const inputs of inputsList) {
      const state = decode(inputs.appState);
      const expected = inputs.scrollBackToContentUIEnabled && state.scrolledOutside && !state.openMenu && !state.openSidebar && (revision === 'after' || !state.viewModeEnabled);
      const observation = observe(artifact.ir, inputs);
      assert.deepEqual(observation, { kind: 'value', value: expected });
      assert.deepEqual(native(inputs), observation);
      inputChecks++;
      if (revision === 'after') { assert.deepEqual(native(inputs, true), observation); mutationChecks++; }
    }
    for (const defaultUIEnabled of bools) for (const scrollBackToContentUIEnabled of bools) for (const appState of [null, { $value: 'undefined' }]) {
      const inputs = { defaultUIEnabled, scrollBackToContentUIEnabled, appState };
      assert.deepEqual(observe(artifact.ir, inputs), native(inputs));
      nullishChecks++;
    }
    const output = path.join(directory, revision);
    fs.mkdirSync(output, { recursive: true });
    const example = { defaultUIEnabled: true, scrollBackToContentUIEnabled: true,
      appState: encode({ viewModeEnabled: true, scrolledOutside: true, openMenu: null, openSidebar: null }) };
    fs.writeFileSync(path.join(output, 'artifact.json'), JSON.stringify(artifact, null, 2) + '\n');
    fs.writeFileSync(path.join(output, 'inputs.json'), JSON.stringify(example, null, 2) + '\n');
    fs.writeFileSync(path.join(output, 'explanation.md'), renderExecution(artifact, observe(artifact.ir, example, { trace: true }), { inputs: example, snippets: node => source.slice(node.start, node.end) }));
    const replay = spawnSync(process.execPath, [path.join(root, 'web-review/src/cli.mjs'), 'run', '--file', path.join(output, 'artifact.json'), '--inputs', path.join(output, 'inputs.json')], { encoding: 'utf8', timeout: 10000 });
    assert.equal(replay.status, 0, replay.stderr);
    assert.deepEqual(JSON.parse(replay.stdout).observation, observe(artifact.ir, example));
    checked.push({ revision, sourceSha256: blob.sha256, route: artifact.flow.route, inputChecks, mutationChecks, nullishChecks, cliReplayChecks: 1 });
  }
  const comparisons = [];
  for (const profile of mobileProfiles) {
  const domains = profile.domains, comparison = compare(artifacts.before.ir, artifacts.after.ir, domains);
  assert.equal(comparison.unknown.length, 0);
  assert.equal(comparison.changes.length, 2);
  const result = { ...comparison, domains, changeRules: summarizeChanges(comparison, domains),
    beforeContract: artifacts.before.contract, afterContract: artifacts.after.contract,
    beforeSource: artifacts.before.source, afterSource: artifacts.after.source,
    assumptions: [...new Set([...comparison.assumptions, ...artifacts.before.contract.assumptions, ...artifacts.after.contract.assumptions])],
    notProven: [...new Set([...comparison.notProven, ...artifacts.before.contract.notProven, ...artifacts.after.contract.notProven])] };
  assert.equal(result.changeRules.status, 'verified-finite-cover');
  const prefix = profile.id === 'nullable-menu' ? '' : profile.id + '-';
  fs.writeFileSync(path.join(directory, prefix + 'domains.json'), JSON.stringify(domains, null, 2) + '\n');
  fs.writeFileSync(path.join(directory, prefix + 'comparison.json'), JSON.stringify({ ...result, inputProfile: profile.id, inputSpecificationSha256, changeScope }, null, 2) + '\n');
  fs.writeFileSync(path.join(directory, prefix + 'comparison.md'), describeComparison(result) + '\n\n' + describeChangeScope(changeScope) + '\n');
  comparisons.push({ profile: profile.id, inputs: comparison.checked, changed: comparison.changes.length, unknown: comparison.unknown.length, rules: result.changeRules.rules.length });
  }
  results.push({ id: target.id, case: target.case, changeScope, checked, comparisons });
}
const output = { schema: 'web-flow-results-1', flowPairsChecked: results.length, inputSpecificationSha256,
  nativeChecks: results.flatMap(result => result.checked).reduce((sum, row) => sum + row.inputChecks + row.mutationChecks + row.nullishChecks, 0),
  wholeBehaviorCasesVerified: 0, scope: selection.scope, results };
fs.writeFileSync(path.join(root, 'build/web-review/flow-results.json'), JSON.stringify(output, null, 2) + '\n');
process.stdout.write(JSON.stringify(output, null, 2) + '\n');
