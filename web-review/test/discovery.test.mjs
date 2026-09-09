import test from 'node:test';
import assert from 'node:assert/strict';
import { discoverSource, renderDiscovery } from '../src/discovery.mjs';
import { liftConstBindings } from '../src/const-bindings.mjs';
import { liftCallEntry, liftCallArguments } from '../src/call-entry.mjs';
import { liftJsxAttribute } from '../src/jsx.mjs';
import { hash } from '../src/typescript.mjs';
import { Unsupported } from '../src/core.mjs';

const source = [
  'const outer = input.toLowerCase();',
  'const object = {x: input}, unused = other.value;',
  'const {value} = getState();',
  'function handler(){',
  '  const clean = input.trim();',
  '  if(!clean)return;',
  '  save({value:clean});',
  '}',
  'const view = <button disabled={!ready} onClick={()=>handler()} />;',
  'function bad(){',
  '  update();',
  '  finish();',
  '}',
].join('\n');

test('discovery reuses actual lowerers and retains separate source sites and observation modes', () => {
  const report = discoverSource(source, { filename: '/source.tsx', limit: 128 });
  assert.deepEqual(report.counts, { candidates: 11, sourceSites: 9, checked: 11, lowerCalls: 10, lowered: 6, refused: 5, 'not-checked': 0, emptyPrefixEntries: 0, focusCandidates: 11, outsideFocus: 0 });
  assert.equal(report.nativeExecutions, 0); assert.equal(report.semanticCoverage, null); assert.equal(report.wholeBehaviorVerified, false);
  assert.equal(report.nextOffset, null);
  for (const row of report.candidates.filter(row => row.status === 'lowered')) {
    const options = { ...row.target, filename: '/source.tsx' };
    const artifact = row.kind === 'const' ? liftConstBindings(source, options) : row.kind === 'jsx-attribute' ? liftJsxAttribute(source, options)
      : row.kind === 'call-entry' ? liftCallEntry(source, options) : liftCallArguments(source, options);
    assert.equal(row.artifactSha256, hash(JSON.stringify(artifact)));
    assert.deepEqual(row.inputs, artifact.inputs); assert.deepEqual(row.contract, artifact.contract);
    assert.equal(row.nativeVerified, false);
  }
  const constRow = report.candidates.find(row => row.target.startLine === 2);
  assert.deepEqual(constRow.target.outputs, ['object', 'unused']); assert.deepEqual(constRow.inputs, ['input', 'other']);
  assert.equal(report.candidates.find(row => row.target.attribute === 'onClick').status, 'refused');
  for (const row of report.candidates) {
    assert.equal(row.source.file, '/source.tsx');
    if (row.refusalSource) { assert.equal(row.refusalSource.file, '/source.tsx'); assert.ok(source.slice(row.refusalSource.start, row.refusalSource.end)); }
  }
  assert.match(renderDiscovery(report), /원본 실행 0회/);
  assert.doesNotMatch(renderDiscovery(report), /\/binding\//);
});

test('same-line selectors and JSX duplicate/spread ambiguity are refused instead of choosing one candidate', () => {
  const input = [
    'const a = 1; const b = 2;',
    'function f(){save();} function g(){save();}',
    '<button disabled={x} disabled={y}/>;',
    '<button disabled={x} {...rest}/>;',
    '<button disabled={x}/>; <button disabled={y}/>;',
  ].join('\n');
  const report = discoverSource(input, { limit: 128 });
  assert.equal(report.counts.lowered, 0); assert.equal(report.counts.refused, report.counts.candidates);
  assert.equal(report.counts['not-checked'], 0);
  assert.ok(report.candidates.every(row => row.reason));
  assert.equal(report.candidates.filter(row => row.kind === 'jsx-attribute').length, 5);
});

test('pagination labels every unexamined candidate and never inherits support from a previous page', () => {
  const input = Array.from({ length: 8 }, (_, index) => `const value${index} = input;`).join('\n');
  const first = discoverSource(input, { limit: 2 }), second = discoverSource(input, { limit: 2, offset: 2 });
  assert.deepEqual(first.candidates.filter(row => row.status === 'lowered').map(row => row.id), [0, 1]);
  assert.deepEqual(second.candidates.filter(row => row.status === 'lowered').map(row => row.id), [2, 3]);
  assert.equal(second.candidates[0].status, 'not-checked'); assert.equal(second.counts['not-checked'], 6);
  assert.equal(first.nextOffset, 2); assert.equal(second.nextOffset, 4);
  assert.match(renderDiscovery(second), /--offset 4/);
  const done = discoverSource(input, { offset: 8 }); assert.equal(done.nextOffset, null); assert.equal(done.counts.checked, 0);
  for (const options of [{ limit: 0 }, { limit: 129 }, { offset: -1 }, { offset: 9 }, { offset: 0.5 }, { kind: 'functions' }]) {
    assert.throws(() => discoverSource(input, options), Unsupported);
  }
});

test('discovery keeps source execution, preceding effects and noncandidate syntax outside its result', () => {
  const input = ['throw new Error("source must not execute");', 'const value = input.trim();',
    'function empty(){save(explode());}', 'function returned(){return save();}',
    'const arrow = () => save();', 'object.save();'].join('\n');
  const report = discoverSource(input, { kind: 'call-entry' });
  assert.equal(report.counts.candidates, 1); assert.equal(report.counts.lowered, 1);
  assert.equal(report.counts.emptyPrefixEntries, 1);
  assert.equal(report.candidates[0].prefixStatements, 0); assert.deepEqual(report.candidates[0].inputs, []);
  assert.equal(discoverSource(input, { kind: 'call-arguments' }).candidates[0].status, 'refused');
  const statements = discoverSource(input, { kind: 'const' });
  assert.equal(statements.candidates[0].status, 'lowered');
  assert.ok(statements.candidates[0].contract.notProven.some(text => text.includes('앞선 코드')));
  assert.throws(() => discoverSource('const = ;'), Unsupported);
  assert.throws(() => discoverSource('const x=1;\n'.repeat(4097)), /구문 후보 제한/);
  assert.throws(() => discoverSource('{'.repeat(140) + 'const x=1;' + '}'.repeat(140)), /깊이 제한/);
});

test('large sources stop repeated lowering at the charged source budget without declaring omitted candidates unsupported', () => {
  const input = '/*' + 'a'.repeat(1024 * 1024) + '*/\n' + Array.from({ length: 18 }, (_, i) => `const x${i} = input;`).join('\n');
  const report = discoverSource(input, { limit: 128 });
  assert.equal(report.counts.lowered, 15); assert.equal(report.counts['not-checked'], 3);
  assert.equal(report.nextOffset, 15); assert.ok(report.bounds.chargedSourceBytes <= report.bounds.sourceWorkLimit);
  assert.ok(report.candidates.slice(15).every(row => row.status === 'not-checked' && /작업량/.test(row.reason)));
});

test('source focus preserves all candidate IDs and resumes at the next matching candidate across gaps', () => {
  const input = Array.from({ length: 8 }, (_, i) => `const value${i} = input;`).join('\n');
  const focusSpans = [2, 7].map(i => { const start = input.indexOf(`const value${i}`); return { start, end: start + 5 }; });
  const first = discoverSource(input, { limit: 1, focusSpans });
  assert.deepEqual(first.candidates.filter(row => row.status === 'lowered').map(row => row.id), [2]);
  assert.equal(first.nextOffset, 7); assert.equal(first.counts.focusCandidates, 2); assert.equal(first.counts.outsideFocus, 6);
  assert.equal(first.candidates[0].status, 'not-checked'); assert.equal(first.candidates[0].inFocus, false);
  const next = discoverSource(input, { offset: first.nextOffset, limit: 1, focusSpans });
  assert.deepEqual(next.candidates.filter(row => row.status === 'lowered').map(row => row.id), [7]); assert.equal(next.nextOffset, null);
  const all = discoverSource(input);
  assert.deepEqual(first.candidates[2], all.candidates[2]); assert.deepEqual(next.candidates[7], all.candidates[7]);
  const none = discoverSource(input, { focusSpans: [] });
  assert.equal(none.counts.checked, 0); assert.equal(none.counts.outsideFocus, 8); assert.equal(none.nextOffset, null);
});

test('source focus validates sorted nonoverlapping original bounds instead of accepting arbitrary selectors', () => {
  const input = 'const x=1;';
  for (const focusSpans of [null, {}, [{}], [{ start: -1, end: 1 }], [{ start: 2, end: 2 }], [{ start: 0, end: 100 }], [{ start: 2, end: 4 }, { start: 3, end: 6 }], Array(65537).fill({ start: 0, end: 1 })]) {
    assert.throws(() => discoverSource(input, { focusSpans }), Unsupported);
  }
});
