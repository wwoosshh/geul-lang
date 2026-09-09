import test from 'node:test';
import assert from 'node:assert/strict';
import { discoverSource, liftSourceCandidate } from '../src/discovery.mjs';
import { discoverChange } from '../src/change-discovery.mjs';
import { liftDiscoveredCandidate } from '../src/discovery-replay.mjs';
import { observe, Unsupported } from '../src/core.mjs';

const filename = '/source.tsx';
const source = 'throw new Error("do not execute");\nconst result = input.trim();\nconst bad = dangerous();\n<button disabled={!busy}/>;\nfunction f(){save(input);}\n';
const report = discoverSource(source, { filename });
const read = file => { assert.equal(file, filename); return source; };

test('a discovered candidate replays its page and returns the same ordinary artifact for every supported mode', () => {
  for (const candidate of report.candidates.filter(row => row.status === 'lowered')) {
    let reads = 0;
    const artifact = liftDiscoveredCandidate(report, { candidateId: candidate.id, readText: file => { reads++; return read(file); } });
    assert.deepEqual(artifact, liftSourceCandidate(source, candidate.kind, candidate.target, filename));
    assert.equal(reads, 1);
  }
  const artifact = liftDiscoveredCandidate(report, { candidateId: 0, readText: read });
  assert.deepEqual(observe(artifact.ir, { input: ' value ' }), { kind: 'value', value: { $record: { result: 'value' } } });
  const reordered = Object.fromEntries(Object.entries(report).reverse());
  assert.deepEqual(liftDiscoveredCandidate(reordered, { candidateId: 0, readText: read }), artifact);
});

test('source changes, altered candidate metadata and fabricated execution claims invalidate the recorded page', () => {
  const edits = [
    row => { row.candidates[0].source.start++; }, row => { row.candidates[0].target.outputs = ['bad']; },
    row => { row.candidates[0].artifactSha256 = '0'.repeat(64); }, row => { row.nativeExecutions = 1; },
    row => { row.counts.lowered++; }, row => { row.source.sha256 = '0'.repeat(64); },
    row => { row.candidates[0].selectionSource.end--; }, row => { row.candidates[0].analyzedSources[0].end--; },
  ];
  for (const edit of edits) {
    const changed = structuredClone(report); edit(changed);
    assert.throws(() => liftDiscoveredCandidate(changed, { candidateId: 0, readText: read }), Unsupported);
  }
  assert.throws(() => liftDiscoveredCandidate(report, { candidateId: 0, readText: () => source.replace('input.trim()', 'input.toLowerCase()') }), Unsupported);
  assert.throws(() => liftDiscoveredCandidate({ ...report, engineSha256: '0'.repeat(64) }, { candidateId: 0, readText: () => assert.fail('Stale engine must fail before source reads') }), Unsupported);
});

test('refused and unchecked candidates require a new inspection and revisions cannot be guessed', () => {
  const limited = discoverSource(source, { filename, limit: 1 });
  assert.throws(() => liftDiscoveredCandidate(report, { candidateId: 1, readText: read }), /IR 추출이 확인된/);
  assert.throws(() => liftDiscoveredCandidate(limited, { candidateId: 2, readText: read }), /IR 추출이 확인된/);
  for (const candidateId of [-1, 0.5, 4096, undefined]) assert.throws(() => liftDiscoveredCandidate(report, { candidateId, readText: read }), Unsupported);
  assert.throws(() => liftDiscoveredCandidate(report, { candidateId: 0, revision: 'after', readText: read }), /단일 파일/);
  assert.throws(() => liftDiscoveredCandidate(report, { candidateId: 0, readText: () => 'x'.repeat(2 * 1024 * 1024 + 1) }), /크기 제한/);
});

test('change candidate extraction replays both sources, patch and focused selection before choosing an explicit revision', () => {
  const beforeFilename = '/before.tsx', afterFilename = '/after.tsx', patchFilename = '/change.diff';
  const before = 'const a = 1;\n', after = before + 'const b = 2;\n';
  const patch = 'diff --git a/input.tsx b/input.tsx\n--- a/input.tsx\n+++ b/input.tsx\n@@ -1,0 +2 @@\n+const b = 2;\n';
  const files = new Map([[beforeFilename, before], [afterFilename, after], [patchFilename, patch]]);
  const change = discoverChange(before, after, patch, { beforeFilename, afterFilename, patchFilename, focus: 'changed-lines', limit: 1 });
  const readText = file => { assert.ok(files.has(file)); return files.get(file); };
  const artifact = liftDiscoveredCandidate(change, { candidateId: 1, revision: 'after', readText });
  assert.deepEqual(observe(artifact.ir, {}), { kind: 'value', value: { $record: { b: 2 } } });
  const all = discoverChange(before, after, patch, { beforeFilename, afterFilename, patchFilename });
  const beforeArtifact = liftDiscoveredCandidate(all, { candidateId: 0, revision: 'before', readText });
  assert.deepEqual(observe(beforeArtifact.ir, {}), { kind: 'value', value: { $record: { a: 1 } } });
  for (const revision of [undefined, 'both']) assert.throws(() => liftDiscoveredCandidate(change, { candidateId: 1, revision, readText }), /revision/);
  assert.throws(() => liftDiscoveredCandidate(change, { candidateId: 0, revision: 'before', readText }), /IR 추출이 확인된/);
  for (const edit of [row => { row.patch.sha256 = '0'.repeat(64); }, row => { row.after.candidates[1].sourceChange.analyzedLines = []; }, row => { row.focus = 'all'; }]) {
    const changed = structuredClone(change); edit(changed);
    assert.throws(() => liftDiscoveredCandidate(changed, { candidateId: 1, revision: 'after', readText }), Unsupported);
  }
  files.set(patchFilename, patch.replace('a/input.tsx', 'a/other.tsx'));
  assert.throws(() => liftDiscoveredCandidate(change, { candidateId: 1, revision: 'after', readText }), Unsupported);
  files.set(patchFilename, patch); files.set(afterFilename, 'const b = 9;\n');
  assert.throws(() => liftDiscoveredCandidate(change, { candidateId: 1, revision: 'after', readText }), Unsupported);
});
