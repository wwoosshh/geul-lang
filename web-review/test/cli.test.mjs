import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const cli = fileURLToPath(new URL('../src/cli.mjs', import.meta.url));

test('lift-candidate CLI connects a source inspection to ordinary reading and execution while refusing stale input', t => {
  const w = workspace(t), source = w.write('candidate-source.tsx', 'const result = input.trim();\nconst bad = dangerous();\n');
  const list = w.file('source-candidates.json'), artifact = w.file('candidate-artifact.json');
  assert.equal(w.run('discover', '--file', source, '--json', '--out', list).status, 0);
  const lifted = w.run('lift-candidate', '--file', list, '--candidate', '0', '--out', artifact);
  assert.equal(lifted.status, 0, lifted.stderr);
  assert.equal(w.run('read', '--file', artifact, '--json').status, 0);
  const input = w.write('candidate-input.json', { input: ' value ' });
  const run = w.run('run', '--file', artifact, '--inputs', input, '--json'); assert.equal(run.status, 0, run.stderr);
  assert.deepEqual(JSON.parse(run.stdout).observation, { kind: 'value', value: { $record: { result: 'value' } } });
  assert.equal(w.run('lift-candidate', '--file', list, '--candidate', '1').status, 2);
  assert.equal(w.run('lift-candidate', '--file', list, '--candidate', '0', '--revision', 'after').status, 2);
  w.write('candidate-source.tsx', 'const result = input.toLowerCase();\nconst bad = dangerous();\n');
  assert.equal(w.run('lift-candidate', '--file', list, '--candidate', '0').status, 2);
});

test('lift-candidate CLI persists and replays the patch path for a selected change revision', t => {
  const w = workspace(t), before = w.write('before-candidate.tsx', 'const result = 1;\n'), after = w.write('after-candidate.tsx', 'const result = 2;\n');
  const patch = w.write('candidate.diff', 'diff --git a/input.tsx b/input.tsx\n--- a/input.tsx\n+++ b/input.tsx\n@@ -1 +1 @@\n-const result = 1;\n+const result = 2;\n');
  const list = w.file('change-candidates.json'), artifact = w.file('change-candidate.json');
  assert.equal(w.run('discover-change', '--before', before, '--after', after, '--patch', patch, '--focus', 'changed-lines', '--json', '--out', list).status, 0);
  assert.equal(JSON.parse(fs.readFileSync(list, 'utf8')).patch.file, patch);
  assert.equal(w.run('lift-candidate', '--file', list, '--candidate', '0').status, 2);
  const lifted = w.run('lift-candidate', '--file', list, '--candidate', '0', '--revision', 'after', '--out', artifact);
  assert.equal(lifted.status, 0, lifted.stderr); assert.equal(w.run('read', '--file', artifact, '--json').status, 0);
  w.write('candidate.diff', '');
  assert.equal(w.run('lift-candidate', '--file', list, '--candidate', '0', '--revision', 'after').status, 2);
});

test('discover-change CLI binds two original files to an exact patch and keeps computation unknown for unchecked candidates', t => {
  const w = workspace(t), before = w.write('before.tsx', 'const a = 1;\n'), after = w.write('after.tsx', 'const a = 1;\nconst b = 2;\n');
  const patch = w.write('change.diff', 'diff --git a/input.tsx b/input.tsx\n--- a/input.tsx\n+++ b/input.tsx\n@@ -1,0 +2 @@\n+const b = 2;\n');
  const run = w.run('discover-change', '--before', before, '--after', after, '--patch', patch, '--limit', '1', '--json');
  assert.equal(run.status, 0, run.stderr); const result = JSON.parse(run.stdout);
  assert.equal(result.after.candidates[1].sourceChange.analyzedLines, null); assert.equal(result.after.nextOffset, 1);
  assert.equal(result.patch.reconstructed, true); assert.equal(result.nativeExecutions, 0);
  const focused = w.run('discover-change', '--before', before, '--after', after, '--patch', patch, '--limit', '1', '--focus', 'changed-lines', '--json');
  assert.equal(focused.status, 0, focused.stderr);
  const focusedResult = JSON.parse(focused.stdout);
  assert.equal(focusedResult.before.counts.checked, 0); assert.equal(focusedResult.after.candidates[1].status, 'lowered');
  assert.deepEqual(focusedResult.after.candidates[1].sourceChange.analyzedLines, [2]);
  assert.equal(focusedResult.after.candidates[0].status, 'not-checked');
  const next = w.run('discover-change', '--before', before, '--after', after, '--patch', patch, '--before-offset', '1', '--after-offset', '1');
  assert.equal(next.status, 0, next.stderr); assert.match(next.stdout, /해석한 계산 구간과 교차한 행/);
  assert.equal(w.run('discover-change', '--before', before, '--after', after, '--patch', patch, '--offset', '1').status, 2);
  assert.equal(w.run('discover', '--file', before, '--patch', patch).status, 2);
  assert.equal(w.run('discover', '--file', before, '--focus', 'changed-lines').status, 2);
  w.write('after.tsx', 'const b = 9;\n');
  assert.equal(w.run('discover-change', '--before', before, '--after', after, '--patch', patch).status, 2);
});

test('discover CLI inventories a source file, paginates without execution and returns replayable selectors', t => {
  const w = workspace(t), source = w.write('discover.tsx', 'const first = input.toLowerCase();\nconst bad = sideEffect();\n<button disabled={!ready}/>;');
  const run = w.run('discover', '--file', source, '--kind', 'const', '--limit', '1', '--json');
  assert.equal(run.status, 0, run.stderr);
  const report = JSON.parse(run.stdout);
  assert.equal(report.counts.lowered, 1); assert.equal(report.counts['not-checked'], 1); assert.equal(report.nextOffset, 1);
  const candidate = report.candidates[0], artifact = w.file('discovered.json');
  assert.equal(w.run(candidate.lift.command, '--file', candidate.lift.file, '--start-line', String(candidate.target.startLine), '--end-line', String(candidate.target.endLine), '--outputs', candidate.target.outputs.join(','), '--out', artifact).status, 0);
  assert.equal(w.run('read', '--file', artifact, '--json').status, 0);
  const next = w.run('discover', '--file', source, '--kind', 'const', '--offset', '1');
  assert.equal(next.status, 0, next.stderr); assert.match(next.stdout, /거부/); assert.match(next.stdout, /원본 실행 0회/);
  assert.equal(w.run('discover', '--file', source, '--inputs', w.write('unneeded.json', {})).status, 2);
  assert.equal(w.run('read', '--file', artifact, '--limit', '1').status, 2);
  assert.equal(w.run('read', '--file', w.write('candidate-list.json', report)).status, 2);
});

test('read CLI replays source and IR without pretending it executed an input', t => {
  const w = workspace(t), source = w.write('code.ts', 'const result = ready ? user.name : null;'), artifact = w.file('code.json');
  assert.equal(w.run('lift-expression', '--file', source, '--expression', 'ready ? user.name : null', '--out', artifact).status, 0);
  const reading = w.run('read', '--file', artifact, '--json');
  assert.equal(reading.status, 0, reading.stderr);
  const result = JSON.parse(reading.stdout);
  assert.equal(result.status, 'ir-reading-view');
  assert.equal(result.tree.kind, 'conditional');
  assert.equal(Object.hasOwn(result, 'observation'), false);
  assert.match(w.run('read', '--file', artifact).stdout, /선택하지 않은 갈래는 계산하지 않습니다/);
  assert.equal(w.run('read', '--file', artifact, '--trace').status, 2);
  const original = JSON.parse(fs.readFileSync(artifact));
  w.write('code.json', { ...original, ir: { kind: 'literal', value: true } });
  assert.equal(w.run('read', '--file', artifact).status, 2);
  w.write('code.json', original);
  w.write('code.ts', 'const result = null;');
  assert.equal(w.run('read', '--file', artifact).status, 2);
});

test('call entry CLI replays excluded arguments and rejects edited boundaries or a different target', t => {
  const w = workspace(t), source = w.write('validation.ts', 'function f(){ const value = name.trim(); if (!value) return; save(explode()); }');
  const file = w.file('validation.json'), inputFile = w.write('validation-inputs.json', { name: 'new' });
  const lifted = w.run('lift-call-entry', '--file', source, '--callee', 'save', '--out', file);
  assert.equal(lifted.status, 0, lifted.stderr);
  const run = w.run('run', '--file', file, '--inputs', inputFile, '--json'); assert.equal(run.status, 0, run.stderr);
  assert.deepEqual(JSON.parse(run.stdout).observation, { kind: 'value', value: true });
  const reading = w.run('read', '--file', file); assert.equal(reading.status, 0, reading.stderr);
  assert.match(reading.stdout, /explode\(\)/); assert.match(reading.stdout, /이 호출은 실행하지 않았다/);
  const explanation = w.run('explain', '--file', file, '--inputs', inputFile); assert.equal(explanation.status, 0, explanation.stderr);
  assert.match(explanation.stdout, /호출 식 평가 직전에 도달/);
  const original = JSON.parse(fs.readFileSync(file)), altered = structuredClone(original);
  altered.excludedCall.evaluated = true; w.write('validation.json', altered);
  assert.equal(w.run('read', '--file', file).status, 2);
  w.write('validation.json', original);
  const changedLinks = structuredClone(original); changedLinks.sourceLinks.entry.referenceCount = 1;
  w.write('validation.json', changedLinks);
  assert.equal(w.run('read', '--file', file).status, 2);
  w.write('validation.json', original);
  const otherSource = w.write('other.ts', 'function f(){ other(); }'), other = w.file('other.json');
  assert.equal(w.run('lift-call-entry', '--file', otherSource, '--callee', 'other', '--out', other).status, 0);
  const domains = w.write('validation-domains.json', { name: ['', 'new'] });
  assert.equal(w.run('compare', '--before', file, '--after', other, '--domains', domains).status, 2);
  const afterSource = w.write('after.ts', "function f(){ const value = name.trim(); if (value === 'new') return; save(changed()); }"), after = w.file('after.json');
  assert.equal(w.run('lift-call-entry', '--file', afterSource, '--callee', 'save', '--out', after).status, 0);
  const compared = w.run('compare', '--before', file, '--after', after, '--domains', domains, '--json');
  assert.equal(compared.status, 0, compared.stderr);
  const comparison = JSON.parse(compared.stdout);
  assert.equal(comparison.checked, 2); assert.equal(comparison.unknown.length, 0);
  assert.deepEqual(comparison.changes.map(row => [row.inputs.name, row.before.value, row.after.value]), [['', false, true], ['new', true, false]]);
  assert.equal(comparison.observationMeaning.boundary, 'before-callee-and-arguments');
  assert.deepEqual(comparison.beforeExcludedCall, original.excludedCall);
  assert.deepEqual(comparison.afterExcludedCall, JSON.parse(fs.readFileSync(after)).excludedCall);
  const comparisonText = w.run('compare', '--before', file, '--after', after, '--domains', domains);
  assert.equal(comparisonText.status, 0, comparisonText.stderr);
  assert.match(comparisonText.stdout, /조기 반환으로 호출 식에 도달하지 않음 → 호출 식 평가 직전에 도달/);
  assert.match(comparisonText.stdout, /호출 식 평가 직전에 도달 → 조기 반환으로 호출 식에 도달하지 않음/);
  assert.match(comparisonText.stdout, /explode\(\)/); assert.match(comparisonText.stdout, /changed\(\)/);
  assert.match(comparisonText.stdout, /도달 결과가 같아도/);
  const structuredReading = JSON.parse(w.run('read', '--file', file, '--json').stdout);
  assert.equal(structuredReading.observationMeaning.executed, false);
  assert.deepEqual(structuredReading.sourceLinks, original.sourceLinks);
  assert.equal(structuredReading.tree.children[1].node.children[1].node.reached, false);
  w.write('validation.ts', 'function f(){ const value = name.trim(); if (!value) return; save(changed()); }');
  assert.equal(w.run('run', '--file', file, '--inputs', inputFile).status, 2);
});

test('call argument CLI compares prepared payloads and replays its callee assumption and source metadata', t => {
  const w = workspace(t), beforeSource = w.write('before.ts', 'function f(){ const clean = name.trim(); if(!clean)return; save({name:clean}); }');
  const afterSource = w.write('after.ts', 'function f(){ const clean = name.trim(); if(!clean)return; save({name}); }');
  const before = w.file('before.json'), after = w.file('after.json');
  for (const [source, target] of [[beforeSource, before], [afterSource, after]]) {
    const lifted = w.run('lift-call-arguments', '--file', source, '--callee', 'save', '--out', target);
    assert.equal(lifted.status, 0, lifted.stderr);
  }
  const inputs = w.write('inputs.json', { name: ' new ' }), domains = w.write('domains.json', { name: ['', ' new '] });
  const result = w.run('run', '--file', before, '--inputs', inputs, '--json'); assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout).observation, { kind: 'value', value: { $record: { argument1: { $record: { name: 'new' } }, stage: 'arguments-ready' } } });
  const explanation = w.run('explain', '--file', before, '--inputs', inputs); assert.equal(explanation.status, 0, explanation.stderr);
  assert.match(explanation.stdout, /실제 호출은 실행하지 않음/); assert.match(explanation.stdout, /값 읽기는 정상 완료한다고 가정/);
  const compared = w.run('compare', '--before', before, '--after', after, '--domains', domains, '--json'); assert.equal(compared.status, 0, compared.stderr);
  const comparison = JSON.parse(compared.stdout);
  assert.equal(comparison.checked, 2); assert.equal(comparison.changes.length, 1); assert.equal(comparison.unchanged, 1); assert.equal(comparison.unknown.length, 0);
  assert.equal(comparison.observationMeaning.mode, 'call-arguments-slice');
  assert.equal(comparison.changes[0].after.value.$record.argument1.$record.name, ' new ');
  const described = w.run('compare', '--before', before, '--after', after, '--domains', domains);
  assert.equal(described.status, 0, described.stderr); assert.match(described.stdout, /인수별 준비 값/);
  const reading = w.run('read', '--file', before); assert.equal(reading.status, 0, reading.stderr); assert.match(reading.stdout, /1번째 인수의 값/);
  const original = JSON.parse(fs.readFileSync(before)); original.preparedCall.calleeEvaluatedByIR = true;
  w.write('before.json', original); assert.equal(w.run('read', '--file', before).status, 2);
  const entry = w.file('entry.json');
  assert.equal(w.run('lift-call-entry', '--file', afterSource, '--callee', 'save', '--out', entry).status, 0);
  assert.equal(w.run('compare', '--before', entry, '--after', after, '--domains', domains).status, 2);
});

test('read CLI preserves destructuring origins and rejects edited source-only metadata', t => {
  const w = workspace(t), source = w.write('code.tsx', 'function Screen() { const { ready: enabled = fallback } = hook(); return enabled && <button/>; }'), file = w.file('code.json');
  const lifted = w.run('lift-jsx-guards', '--file', source, '--tag', 'button', '--out', file);
  assert.equal(lifted.status, 0, lifted.stderr);
  const result = w.run('read', '--file', file, '--json');
  assert.equal(result.status, 0, result.stderr);
  const reading = JSON.parse(result.stdout), original = JSON.parse(fs.readFileSync(file));
  assert.deepEqual(reading.inputBindings.inputs, original.bindings.inputs);
  assert.equal(Object.hasOwn(reading, 'observation'), false);
  const report = w.run('read', '--file', file);
  assert.equal(report.status, 0, report.stderr);
  assert.match(report.stdout, /hook\(\)/); assert.match(report.stdout, /조건부 기본값 식: fallback/);
  const altered = structuredClone(original);
  altered.bindings.inputs[0].declarations[0].destructuringOrigin.expression.start++;
  w.write('code.json', altered);
  assert.equal(w.run('read', '--file', file).status, 2);
  w.write('code.json', original);
  w.write('code.tsx', 'function Screen() { const { ready: enabled = fallback } = changedHook(); return enabled && <button/>; }');
  assert.equal(w.run('read', '--file', file).status, 2);
});

test('JSX property CLI compares an added attribute and replays its absence rather than inventing undefined', t => {
  const w = workspace(t), before = w.write('before.tsx', 'const view = <input/>;'), after = w.write('after.tsx', 'const view = <input aria-invalid={!!message}/>;');
  for (const [file, name] of [[before, 'before.json'], [after, 'after.json']]) {
    const run = w.run('lift-jsx-property', '--file', file, '--tag', 'input', '--attribute', 'aria-invalid', '--out', w.file(name));
    assert.equal(run.status, 0, run.stderr);
  }
  const inputs = w.write('inputs.json', { message: null }), domains = w.write('domains.json', { message: [null, 'error'] });
  assert.match(w.run('explain', '--file', w.file('before.json'), '--inputs', inputs).stdout, /선택한 원본 태그에 없다/);
  const compare = w.run('compare', '--before', w.file('before.json'), '--after', w.file('after.json'), '--domains', domains, '--json');
  assert.equal(compare.status, 0, compare.stderr); assert.equal(JSON.parse(compare.stdout).changes.length, 2);
  const conditions = JSON.parse(compare.stdout).changeConditions;
  assert.equal(conditions.status, 'verified-finite-change-conditions');
  assert.equal(conditions.rules.length, 1);
  assert.equal(conditions.rules[0].distinctOutcomePairs, 2);
  assert.equal(conditions.envelope.changedRows, 2);
  assert.equal(JSON.parse(compare.stdout).structureComparison.status, 'ir-structural-comparison');
  assert.match(w.run('compare', '--before', w.file('before.json'), '--after', w.file('after.json'), '--domains', domains).stdout, /IR 계산 구조가 바뀌었습니다/);
  const other = w.file('other.json');
  assert.equal(w.run('lift-jsx-property', '--file', after, '--tag', 'input', '--attribute', 'disabled', '--out', other).status, 0);
  assert.equal(w.run('compare', '--before', other, '--after', w.file('after.json'), '--domains', domains).status, 2);
  w.write('before.tsx', 'const view = <input aria-invalid/>;');
  assert.equal(w.run('run', '--file', w.file('before.json'), '--inputs', inputs).status, 2);
});

test('explain with a props index replays both originals and keeps the join source-only', t => {
  const w = workspace(t);
  const parent = w.write('parent.tsx', 'import { Child } from "./child";\nfunction Parent() {\nconst result = input;\nreturn <Child data={result}/>;\n}');
  w.write('child.tsx', 'export function Child({ data }) { useSelected(data); return <List rows={data}/>; }');
  w.write('tsconfig.json', { compilerOptions: { module: 'esnext', moduleResolution: 'bundler' } });
  w.write('inventory.json', ['parent.tsx', 'child.tsx', 'tsconfig.json']);
  const manifest = w.write('project.json', { files: ['parent.tsx', 'child.tsx'], entry: 'parent.tsx', tag: 'Child', properties: ['data'], context: { metadata: ['tsconfig.json'], inventory: 'inventory.json', configPath: 'tsconfig.json' } });
  const slice = w.file('const.json'), index = w.file('props.json'), inputs = w.write('inputs.json', { input: 7 });
  assert.equal(w.run('lift-const-bindings', '--file', parent, '--start-line', '3', '--end-line', '3', '--outputs', 'result', '--out', slice).status, 0);
  assert.equal(w.run('index-props', '--file', manifest, '--out', index).status, 0);
  const result = w.run('explain', '--file', slice, '--inputs', inputs, '--props-index', index, '--json');
  assert.equal(result.status, 0, result.stderr);
  const data = JSON.parse(result.stdout);
  assert.equal(data.outputPropLinks.status, 'source-indexes-linked');
  assert.equal(w.run('read', '--file', index).status, 2);
  assert.equal(data.observation.value.$record.result, 7);
  assert.match(w.run('explain', '--file', slice, '--inputs', inputs, '--props-index', index).stdout, /useSelected\(data\)/);
  const reading = w.run('read', '--file', slice, '--props-index', index, '--json');
  assert.equal(reading.status, 0, reading.stderr);
  const readData = JSON.parse(reading.stdout);
  assert.equal(readData.status, 'ir-reading-view');
  assert.equal(readData.outputPropLinks.status, 'source-indexes-linked');
  assert.equal(Object.hasOwn(readData, 'observation'), false);
  const readText = w.run('read', '--file', slice, '--props-index', index).stdout;
  assert.match(readText, /useSelected\(data\)/);
  assert.match(readText, /실행 결과가 아닌 원본 탐색/);
  assert.equal(w.run('run', '--file', slice, '--inputs', inputs, '--props-index', index).status, 2);
  w.write('child.tsx', 'export function Child({ data }) { return null; }');
  assert.equal(w.run('explain', '--file', slice, '--inputs', inputs, '--props-index', index).status, 2);
  assert.equal(w.run('read', '--file', slice, '--props-index', index).status, 2);
});

test('array CLI binds the explicit profile to source replay and refuses profile tampering', t => {
  const w = workspace(t), source = w.write('arrays.ts', 'const result = rows.filter(t => !t.hidden);');
  const artifact = w.file('arrays.json'), inputs = w.write('inputs.json', { rows: { $array: [{ $record: { hidden: false } }, { $record: { hidden: true } }] } });
  const lifted = w.run('lift-const-bindings', '--file', source, '--start-line', '1', '--end-line', '1', '--outputs', 'result', '--array-profile', 'dense-standard-array-1', '--out', artifact);
  assert.equal(lifted.status, 0, lifted.stderr);
  const run = w.run('explain', '--file', artifact, '--inputs', inputs);
  assert.equal(run.status, 0, run.stderr); assert.match(run.stdout, /2개 중 1개를 원래 순서로/);
  const original = JSON.parse(fs.readFileSync(artifact));
  w.write('arrays.json', { ...original, ir: { ...original.ir, valueProfile: 'silently-wider' } });
  assert.equal(w.run('run', '--file', artifact, '--inputs', inputs).status, 2);
  w.write('arrays.json', { ...original, target: { ...original.target, arrayProfile: undefined } });
  assert.equal(w.run('run', '--file', artifact, '--inputs', inputs).status, 2);
  assert.equal(w.run('lift-expression', '--file', source, '--expression', 'rows', '--array-profile', 'dense-standard-array-1').status, 2);
});

test('prop-equation CLI binds delivery assumptions, selected sink and original project files', t => {
  const w = workspace(t);
  w.write('parent.tsx', 'import { Child } from "./child"; export const Parent = () => <Child busy={loading} />;');
  w.write('child.tsx', 'export const Child = ({ busy }) => <button disabled={busy} hidden={!busy} />;');
  w.write('tsconfig.json', { compilerOptions: { module: 'esnext', moduleResolution: 'bundler' } });
  w.write('inventory.json', ['parent.tsx', 'child.tsx', 'tsconfig.json']);
  const manifest = { files: ['parent.tsx', 'child.tsx'], entry: 'parent.tsx', tag: 'Child', properties: ['busy'], assumePlainProps: true,
    sink: { tag: 'button', attribute: 'disabled' }, context: { metadata: ['tsconfig.json'], inventory: 'inventory.json', configPath: 'tsconfig.json' } };
  const file = w.write('project.json', manifest), artifact = w.file('prop.json'), inputs = w.write('inputs.json', { loading: true });
  let run = w.run('lift-prop-expression', '--file', file, '--out', artifact);
  assert.equal(run.status, 0, run.stderr);
  run = w.run('explain', '--file', artifact, '--inputs', inputs);
  assert.equal(run.status, 0, run.stderr);
  assert.match(run.stdout, /파일 사이에서 결합한 식/);
  const domains = w.write('domains.json', { loading: [false, true] });
  assert.equal(w.run('compare', '--before', artifact, '--after', artifact, '--domains', domains).status, 0);
  const other = w.write('other.json', { ...manifest, sink: { tag: 'button', attribute: 'hidden' } }), otherArtifact = w.file('other-artifact.json');
  assert.equal(w.run('lift-prop-expression', '--file', other, '--out', otherArtifact).status, 0);
  assert.equal(w.run('compare', '--before', artifact, '--after', otherArtifact, '--domains', domains).status, 2);
  w.write('project.json', { ...manifest, assumePlainProps: false });
  assert.equal(w.run('run', '--file', artifact, '--inputs', inputs).status, 2);
});

test('record CLI replays object selection and reports missing fields without executing its callback', t => {
  const w = workspace(t), file = w.write('record.tsx', 'const callback = e => send({ ...draft, date: e.target.value });');
  const artifactFile = w.file('record.json');
  assert.equal(w.run('lift-record', '--file', file, '--line', '1', '--out', artifactFile).status, 0);
  const inputs = w.write('record-inputs.json', { draft: { $record: {} }, e: { $record: { target: { $record: { value: 'new' } } } } });
  const result = w.run('run', '--file', artifactFile, '--inputs', inputs);
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout).observation.value, { $record: { date: 'new' } });
  const explained = w.run('explain', '--file', artifactFile, '--inputs', inputs);
  assert.equal(explained.status, 0, explained.stderr);
  assert.match(explained.stdout, /없는 속성을 만들거나 기본값을 채우지 않는다/);
  assert.match(explained.stdout, /콜백·함수 호출·상태 갱신은 실행하지 않았다/);
  const domains = w.write('domains.json', { draft: [{ $record: {} }], e: [{ $record: { target: { $record: { value: 'new' } } } }] });
  assert.equal(w.run('compare', '--before', artifactFile, '--after', artifactFile, '--domains', domains).status, 0);
  const artifact = JSON.parse(fs.readFileSync(artifactFile, 'utf8'));
  artifact.target.line = 2;
  w.write('record.json', artifact);
  assert.equal(w.run('run', '--file', artifactFile, '--inputs', inputs).status, 2);
});
function workspace(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'geul-web-cli-'));
  // This exact directory was allocated by the test, contains only test data,
  // and is never computed from user file contents.
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  return {
    write(name, content) { const file = path.join(directory, name); fs.writeFileSync(file, typeof content === 'string' ? content : JSON.stringify(content)); return file; },
    file: name => path.join(directory, name),
    run(...args) { return spawnSync(process.execPath, [cli, ...args], { cwd: directory, encoding: 'utf8', timeout: 10000 }); },
  };
}
test('CLI replays source and IR, rejects stale source and avoids overwriting outputs', t => {
  const w = workspace(t), source = w.write('a.ts', 'export const result = !busy;'), output = w.file('a.json');
  assert.equal(w.run('lift-expression', '--file', source, '--expression', '!busy', '--out', output).status, 0);
  const inputs = w.write('inputs.json', { busy: false });
  assert.deepEqual(JSON.parse(w.run('run', '--file', output, '--inputs', inputs).stdout).observation, { kind: 'value', value: true });
  const before = fs.readFileSync(output, 'utf8');
  assert.equal(w.run('lift-expression', '--file', source, '--expression', '!busy', '--out', output).status, 2);
  assert.equal(fs.readFileSync(output, 'utf8'), before);
  const artifact = JSON.parse(before); artifact.ir.op = '+';
  w.write('a.json', artifact);
  assert.equal(w.run('run', '--file', output, '--inputs', inputs).status, 2);
  w.write('a.json', before);
  const staleEngine = JSON.parse(before); staleEngine.engineSha256 = '0'.repeat(64);
  w.write('a.json', staleEngine);
  assert.equal(w.run('run', '--file', output, '--inputs', inputs).status, 2);
  w.write('a.json', before);
  w.write('a.ts', '// changed\nexport const result = !busy;');
  assert.equal(w.run('run', '--file', output, '--inputs', inputs).status, 2);
});
test('project manifest and JSX artifact replay use the same CLI', t => {
  const w = workspace(t);
  w.write('a.ts', 'export function decision(busy: boolean) { return !busy; }');
  const manifest = w.write('project.json', { files: ['a.ts'], entry: 'a.ts', functionName: 'decision' });
  const result = w.run('lift-project', '--file', manifest, '--out', w.file('project-result.json'));
  assert.equal(result.status, 0, result.stderr);
  const inputs = w.write('inputs.json', { busy: true });
  assert.equal(JSON.parse(w.run('run', '--file', w.file('project-result.json'), '--inputs', inputs).stdout).observation.value, false);
  const explained = w.run('explain', '--file', w.file('project-result.json'), '--inputs', inputs, '--out', w.file('explanation.md'));
  assert.equal(explained.status, 0, explained.stderr);
  assert.match(fs.readFileSync(w.file('explanation.md'), 'utf8'), /결과: \*\*거짓\*\*/);
  const tsx = w.write('b.tsx', 'export const B = () => <button disabled={busy} />;');
  assert.equal(w.run('lift-jsx-attribute', '--file', tsx, '--tag', 'button', '--attribute', 'disabled', '--out', w.file('jsx.json')).status, 0);
  assert.equal(JSON.parse(w.run('run', '--file', w.file('jsx.json'), '--inputs', inputs).stdout).observation.value, true);
  const domains = w.write('domains.json', { busy: [false, true] });
  assert.equal(w.run('compare', '--before', w.file('project-result.json'), '--after', w.file('jsx.json'), '--domains', domains).status, 2);
  const comparison = w.run('compare', '--before', w.file('jsx.json'), '--after', w.file('jsx.json'), '--domains', domains, '--json');
  assert.equal(comparison.status, 0, comparison.stderr);
  assert.equal(JSON.parse(comparison.stdout).status, 'equal-in-declared-domain');
  assert.equal(JSON.parse(comparison.stdout).changeRules.status, 'verified-finite-cover');
});
test('CLI errors are nonzero for missing arguments, invalid domains, duplicate files and unknown inputs', t => {
  const w = workspace(t);
  assert.equal(w.run('lift-expression').status, 2);
  w.write('a.ts', 'export function decision(x: boolean) { return x; }');
  const manifest = w.write('project.json', { files: ['a.ts', 'a.ts'], entry: 'a.ts', functionName: 'decision' });
  assert.equal(w.run('lift-project', '--file', manifest).status, 2);
  fs.linkSync(w.file('a.ts'), w.file('alias.ts'));
  w.write('project.json', { files: ['a.ts', 'alias.ts'], entry: 'a.ts', functionName: 'decision' });
  assert.equal(w.run('lift-project', '--file', manifest).status, 2);
  w.write('project.json', { files: ['a.ts'], entry: 'a.ts', functionName: 'decision' });
  assert.equal(w.run('lift-project', '--file', manifest, '--out', w.file('result.json')).status, 0);
  const inputs = w.write('inputs.json', {});
  assert.equal(w.run('run', '--file', w.file('result.json'), '--inputs', inputs).status, 2);
  w.write('inputs.json', 'null');
  assert.equal(w.run('run', '--file', w.file('result.json'), '--inputs', inputs).status, 2);
});
test('CLI context binds settings and invalidates the artifact when a package condition changes', t => {
  const w = workspace(t);
  w.write('policy.ts', 'export function allowed(owner: boolean) { return owner; }');
  w.write('main.ts', 'import { allowed } from "#policy"; export function disabled(owner: boolean) { return !allowed(owner); }');
  w.write('tsconfig.json', { compilerOptions: { moduleResolution: 'Bundler', module: 'esnext' } });
  w.write('package.json', { imports: { '#policy': './policy.ts' } });
  w.write('inventory.json', ['policy.ts', 'main.ts', 'tsconfig.json', 'package.json']);
  const manifest = w.write('project.json', { files: ['policy.ts', 'main.ts'], entry: 'main.ts', functionName: 'disabled', context: { metadata: ['tsconfig.json', 'package.json'], inventory: 'inventory.json', configPath: 'tsconfig.json' } });
  const result = w.run('lift-project', '--file', manifest, '--out', w.file('result.json'));
  assert.equal(result.status, 0, result.stderr);
  const inputs = w.write('inputs.json', { owner: false });
  assert.equal(JSON.parse(w.run('run', '--file', w.file('result.json'), '--inputs', inputs).stdout).observation.value, true);
  w.write('package.json', { imports: { '#policy': './unloaded.ts' } });
  assert.equal(w.run('run', '--file', w.file('result.json'), '--inputs', inputs).status, 2);
});

test('function-body CLI binds the whole original file and explains exact source locations', t => {
  const w = workspace(t);
  const source = 'import { unavailable } from "package";\ninitialize();\nexport function normalize(date: string) { return { date: date.trim() !== "" ? date : undefined }; }';
  w.write('original.tsx', source);
  const result = w.run('lift-function', '--file', w.file('original.tsx'), '--function', 'normalize', '--out', w.file('body.json'));
  assert.equal(result.status, 0, result.stderr);
  const inputs = w.write('inputs.json', { date: '  2026-09-09  ' });
  const run = w.run('run', '--file', w.file('body.json'), '--inputs', inputs);
  assert.equal(run.status, 0, run.stderr);
  assert.deepEqual(JSON.parse(run.stdout).observation.value, { $record: { date: '  2026-09-09  ' } });
  const report = w.run('explain', '--file', w.file('body.json'), '--inputs', inputs);
  assert.equal(report.status, 0, report.stderr);
  assert.ok(report.stdout.includes(w.file('original.tsx').replaceAll('\\', '/') + ':3>'));
  assert.ok(report.stdout.includes('date.trim()'));
  assert.ok(report.stdout.includes('String.prototype.trim'));
  assert.ok(report.stdout.includes('원본 모듈 초기화'));
  w.write('original.tsx', source.replace('initialize()', 'changedInitialization()'));
  assert.equal(w.run('run', '--file', w.file('body.json'), '--inputs', inputs).status, 2);
});

test('destructured argument input mapping and field reads survive CLI replay and tamper checks', t => {
  const w = workspace(t);
  const source = w.write('original.ts', 'export function decide({ allowed: enabled }: any) { return enabled; }');
  const output = w.file('body.json');
  const lifted = w.run('lift-function', '--file', source, '--function', 'decide', '--out', output);
  assert.equal(lifted.status, 0, lifted.stderr);
  const inputs = w.write('inputs.json', { 인수1: { $record: { allowed: true } } });
  const explanation = w.run('explain', '--file', output, '--inputs', inputs);
  assert.equal(explanation.status, 0, explanation.stderr);
  assert.match(explanation.stdout, /객체로 받는 함수 인수/);
  assert.match(explanation.stdout, /"allowed" 속성에서 읽은 참을 enabled에 저장했다/);
  const artifact = JSON.parse(fs.readFileSync(output, 'utf8'));
  artifact.parameterInputs[0].input = 'different';
  w.write('body.json', artifact);
  assert.equal(w.run('run', '--file', output, '--inputs', inputs).status, 2);
});

test('function result source index rejects execution and edited binding evidence', t => {
  const w = workspace(t);
  const source = w.write('original.ts', 'function normalize(x: any) { return x; } const { balance } = normalize(input); sink({ balance });');
  const output = w.file('links.json');
  const lifted = w.run('index-function-result', '--file', source, '--function', 'normalize', '--out', output);
  assert.equal(lifted.status, 0, lifted.stderr);
  const explanation = w.run('explain', '--file', output);
  assert.equal(explanation.status, 0, explanation.stderr);
  assert.match(explanation.stdout, /반환값의 소스 연결/);
  assert.match(explanation.stdout, /도달·실행은 미확인/);
  assert.equal(w.run('run', '--file', output).status, 2);
  const artifact = JSON.parse(fs.readFileSync(output, 'utf8'));
  artifact.connections[0].uses[0].payloadName = 'different';
  w.write('links.json', artifact);
  assert.equal(w.run('explain', '--file', output).status, 2);
});

test('function result explanation accepts parameter inputs but preserves source-only run and prototype boundaries', t => {
  const w = workspace(t);
  const source = w.write('original.ts', 'function normalize(x: any) { return { balance: x }; } function caller() { const { balance } = normalize(actual()); sink({ balance }); }');
  const output = w.file('links.json');
  assert.equal(w.run('index-function-result', '--file', source, '--function', 'normalize', '--out', output).status, 0);
  const inputs = w.write('inputs.json', { x: 0 });
  const explanation = w.run('explain', '--file', output, '--inputs', inputs);
  assert.equal(explanation.status, 0, explanation.stderr);
  assert.match(explanation.stdout, /실제 요청 실행을 확인한 결과는 아니다/);
  assert.match(explanation.stdout, /actual\(\)/);
  assert.ok(explanation.stdout.includes(source.replaceAll('\\', '/')));
  const result = w.run('explain', '--file', output, '--inputs', inputs, '--json');
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).projections[0].value, 0);
  assert.equal(w.run('run', '--file', output, '--inputs', inputs).status, 2);
  const artifact = JSON.parse(fs.readFileSync(output, 'utf8'));
  artifact.callContext.reachabilityProven = true;
  w.write('links.json', artifact);
  assert.equal(w.run('explain', '--file', output, '--inputs', inputs).status, 2);
  const missing = w.write('missing.ts', 'function normalize(x: any) { return { balance: x }; } const { missing } = normalize(x); sink({ missing });');
  const missingOutput = w.file('missing.json');
  assert.equal(w.run('index-function-result', '--file', missing, '--function', 'normalize', '--out', missingOutput).status, 0);
  const unsupported = w.run('explain', '--file', missingOutput, '--inputs', inputs, '--json');
  assert.equal(unsupported.status, 2, unsupported.stderr);
  assert.equal(JSON.parse(unsupported.stdout).bindingObservation.kind, 'unsupported');
});

test('caller-input CLI evaluates a dynamic lookup and keeps incompatible input boundaries separate', t => {
  const w = workspace(t);
  const source = w.write('original.ts', 'function normalize(settings: any) { return { balance: settings?.amount ?? 0 }; } const { balance } = normalize(accounts[selected]); sink({ balance });');
  const output = w.file('links.json');
  assert.equal(w.run('index-function-result', '--file', source, '--function', 'normalize', '--out', output).status, 0);
  const inputs = w.write('caller.json', { accounts: { $record: { first: { $record: { amount: 17 } } } }, selected: 'first' });
  const explained = w.run('explain', '--file', output, '--caller-inputs', inputs);
  assert.equal(explained.status, 0, explained.stderr);
  assert.match(explained.stdout, /지정한 호출 지점 입력/);
  assert.match(explained.stdout, /속성 키 식 selected/);
  assert.ok(explained.stdout.includes(source.replaceAll('\\', '/')));
  const json = w.run('explain', '--file', output, '--caller-inputs', inputs, '--json');
  assert.equal(json.status, 0, json.stderr);
  assert.equal(JSON.parse(json.stdout).projections[0].value, 17);
  assert.equal(w.run('explain', '--file', output, '--inputs', inputs, '--caller-inputs', inputs).status, 2);
  assert.equal(w.run('run', '--file', output, '--caller-inputs', inputs).status, 2);
  w.write('caller.json', { accounts: { $record: {} }, selected: 7 });
  const unsupported = w.run('explain', '--file', output, '--caller-inputs', inputs, '--json');
  assert.equal(unsupported.status, 2, unsupported.stderr);
  assert.equal(JSON.parse(unsupported.stdout).observation.kind, 'unsupported');
});

test('const and call binding CLI compare identical observations and reject changed selectors or output names', t => {
  const w = workspace(t);
  const before = w.write('before.ts', 'const original = input ?? 0;\nconst balance = original;');
  const after = w.write('after.ts', 'function normalize(value: any) { return { balance: value ?? 0 }; } const { balance } = normalize(input);');
  const beforeFile = w.file('before.json'), afterFile = w.file('after.json');
  assert.equal(w.run('lift-const-bindings', '--file', before, '--start-line', '1', '--end-line', '2', '--outputs', 'balance', '--out', beforeFile).status, 0);
  assert.equal(w.run('lift-call-bindings', '--file', after, '--function', 'normalize', '--out', afterFile).status, 0);
  const inputs = w.write('inputs.json', { input: 0 }), domains = w.write('domains.json', { input: [null, 0, 4] });
  for (const file of [beforeFile, afterFile]) {
    const run = w.run('run', '--file', file, '--inputs', inputs);
    assert.equal(run.status, 0, run.stderr);
    assert.deepEqual(JSON.parse(run.stdout).observation.value, { $record: { balance: 0 } });
    const explain = w.run('explain', '--file', file, '--inputs', inputs);
    assert.equal(explain.status, 0, explain.stderr);
    assert.match(explain.stdout, /보고용 관찰/);
  }
  const compared = w.run('compare', '--before', beforeFile, '--after', afterFile, '--domains', domains, '--json');
  assert.equal(compared.status, 0, compared.stderr);
  assert.equal(JSON.parse(compared.stdout).status, 'equal-in-declared-domain');
  assert.deepEqual(JSON.parse(compared.stdout).observationBindings.names, ['balance']);
  const different = w.file('different.json');
  assert.equal(w.run('lift-const-bindings', '--file', before, '--start-line', '1', '--end-line', '2', '--outputs', 'original', '--out', different).status, 0);
  assert.equal(w.run('compare', '--before', different, '--after', afterFile, '--domains', domains).status, 2);
  const altered = JSON.parse(fs.readFileSync(beforeFile, 'utf8'));
  altered.target.endLine = 1;
  w.write('before.json', altered);
  assert.equal(w.run('run', '--file', beforeFile, '--inputs', inputs).status, 2);
});

test('guard CLI replays selectors and exposes skipped evaluations in its report', t => {
  const w = workspace(t);
  const source = w.write('screen.tsx', 'const view = <Box x={work()}>{enabled && <button className="save"/>}</Box>;');
  const output = w.file('guards.json');
  assert.equal(w.run('lift-jsx-guards', '--file', source, '--tag', 'button', '--attribute', 'className', '--equals', 'save', '--out', output).status, 0);
  const inputs = w.write('inputs.json', { enabled: true });
  assert.equal(JSON.parse(w.run('run', '--file', output, '--inputs', inputs).stdout).observation.value, true);
  const report = w.run('explain', '--file', output, '--inputs', inputs);
  assert.equal(report.status, 0, report.stderr);
  assert.ok(report.stdout.includes('상위 태그 바인딩과 속성 평가'));
  assert.ok(report.stdout.includes('앞선 return'));
  const domains = w.write('domains.json', { enabled: [false, true] });
  const comparison = w.run('compare', '--before', output, '--after', output, '--domains', domains, '--json');
  assert.equal(comparison.status, 0, comparison.stderr);
  assert.ok(JSON.parse(comparison.stdout).assumptions.includes('생략된 선행 평가가 예외를 내거나 이후 조건의 입력을 바꾸지 않음'));
  const artifact = JSON.parse(fs.readFileSync(output));
  artifact.omittedEvaluations = [];
  w.write('guards.json', artifact);
  assert.equal(w.run('run', '--file', output, '--inputs', inputs).status, 2);
});

test('guard prefix CLI replays the selected start boundary and prior calculations', t => {
  const w = workspace(t);
  const source = w.write('prefix.tsx', 'function Screen() {\nconst allowed = user.allowed;\nconst unused = other.value;\nreturn allowed && <button/>;\n}');
  const output = w.file('prefix.json');
  const lift = w.run('lift-jsx-guards', '--file', source, '--tag', 'button', '--prefix-line', '2', '--out', output);
  assert.equal(lift.status, 0, lift.stderr);
  const inputs = w.write('inputs.json', { user: { $record: { allowed: false } }, other: null });
  const run = w.run('run', '--file', output, '--inputs', inputs);
  assert.equal(run.status, 0, run.stderr);
  assert.equal(JSON.parse(run.stdout).observation.kind, 'throw');
  const report = w.run('explain', '--file', output, '--inputs', inputs);
  assert.equal(report.status, 0, report.stderr);
  assert.ok(report.stdout.includes('선행 계산의 시작'));
  assert.ok(report.stdout.includes('other.value'));
  const artifact = JSON.parse(fs.readFileSync(output));
  artifact.prefix.line = 3;
  w.write('prefix.json', artifact);
  assert.equal(w.run('run', '--file', output, '--inputs', inputs).status, 2);
});

test('component prop CLI preserves project provenance and never runs a navigation index', t => {
  const w = workspace(t);
  w.write('child.tsx', 'export const Child = ({ busy: pending }) => <button disabled={pending}/>;');
  w.write('parent.tsx', 'import { Child } from "./child"; const page = <Child busy={locked}/>;');
  w.write('tsconfig.json', { compilerOptions: { moduleResolution: 'Bundler', module: 'esnext' } });
  w.write('inventory.json', ['child.tsx', 'parent.tsx', 'tsconfig.json']);
  const manifest = w.write('project.json', { files: ['child.tsx', 'parent.tsx'], entry: 'parent.tsx', tag: 'Child', properties: ['busy'],
    context: { metadata: ['tsconfig.json'], inventory: 'inventory.json', configPath: 'tsconfig.json' } });
  const result = w.run('index-props', '--file', manifest, '--out', w.file('props.json'));
  assert.equal(result.status, 0, result.stderr);
  const report = w.run('explain', '--file', w.file('props.json'));
  assert.equal(report.status, 0, report.stderr);
  assert.ok(report.stdout.includes('pending'));
  assert.ok(report.stdout.includes(w.file('child.tsx').replaceAll('\\', '/')));
  assert.ok(report.stdout.includes('locked'));
  assert.equal(w.run('run', '--file', w.file('props.json')).status, 2);
  w.write('child.tsx', 'export const Child = ({ busy: changed }) => <button disabled={changed}/>;');
  assert.equal(w.run('explain', '--file', w.file('props.json')).status, 2);
});

test('JSX reference CLI keeps opaque input data unknown while tracing object contribution', t => {
  const w = workspace(t);
  const source = w.write('reference.tsx', 'const view = <>{visible && <div>{element}</div>}</>;');
  const output = w.file('reference.json');
  assert.equal(w.run('lift-jsx-reference', '--file', source, '--name', 'element', '--out', output).status, 0);
  const inputs = w.write('inputs.json', { visible: true, element: { $opaque: 'truthy-object' } });
  const result = w.run('run', '--file', output, '--inputs', inputs);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).observation.value, true);
  const report = w.run('explain', '--file', output, '--inputs', inputs);
  assert.equal(report.status, 0, report.stderr);
  assert.ok(report.stdout.includes('내부 미확인 객체'));
  assert.ok(report.stdout.includes('객체 값을 전달했다'));
  assert.ok(report.stdout.includes('동일하다는 사실'));
});

test('JSX flow CLI replays stored const projection and compares equivalent child delivery modes', t => {
  const w = workspace(t);
  const before = w.write('before.tsx', 'const page = <>{visible && <button/>}</>;');
  const after = w.write('after.tsx', 'function Screen() {\nconst node = visible ? <button/> : null;\nreturn <>{node}</>;\n}');
  for (const [source, output] of [[before, 'before.json'], [after, 'after.json']]) {
    const result = w.run('lift-jsx-flow', '--file', source, '--tag', 'button', '--out', w.file(output));
    assert.equal(result.status, 0, result.stderr);
  }
  const inputs = w.write('inputs.json', { visible: true });
  const report = w.run('explain', '--file', w.file('after.json'), '--inputs', inputs);
  assert.equal(report.status, 0, report.stderr);
  assert.ok(report.stdout.includes('정상 생성된 객체 또는 null로만 투영'));
  assert.ok(report.stdout.includes('자식 참조 1'));
  const domains = w.write('domains.json', { visible: [false, true] });
  const comparison = w.run('compare', '--before', w.file('before.json'), '--after', w.file('after.json'), '--domains', domains, '--json');
  assert.equal(comparison.status, 0, comparison.stderr);
  assert.equal(JSON.parse(comparison.stdout).status, 'equal-in-declared-domain');
  const artifact = JSON.parse(fs.readFileSync(w.file('after.json')));
  artifact.flow.references = [];
  w.write('after.json', artifact);
  assert.equal(w.run('run', '--file', w.file('after.json'), '--inputs', inputs).status, 2);
});
