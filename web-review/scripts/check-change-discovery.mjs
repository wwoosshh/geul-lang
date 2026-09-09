import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { discoverChange } from '../src/change-discovery.mjs';
import { hash } from '../src/typescript.mjs';
import { ENGINE_SHA256 } from '../src/fingerprint.mjs';

const pkg = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'), root = path.dirname(pkg);
const selectionBytes = fs.readFileSync(path.join(pkg, 'corpus/discovery.json')), selection = JSON.parse(selectionBytes);
const lockBytes = fs.readFileSync(path.join(pkg, 'corpus/lock.json')), lock = JSON.parse(lockBytes);
assert.equal(lock.selectionSha256, hash(fs.readFileSync(path.join(pkg, 'corpus/selection.json'))));
const results = []; let cliReplays = 0;
function git(project, ...args) {
  const repo = path.join(root, 'build/research', project);
  const result = spawnSync('git', ['-C', repo, '-c', `safe.directory=${repo.replaceAll('\\', '/')}`, ...args], { timeout: 20000, maxBuffer: 16 * 1024 * 1024 });
  assert.equal(result.status, 0, result.stderr?.toString() || result.error?.message); return result.stdout;
}
function cli(...args) {
  const result = spawnSync(process.execPath, [path.join(pkg, 'src/cli.mjs'), ...args], { encoding: 'utf8', timeout: 20000, maxBuffer: 16 * 1024 * 1024 });
  assert.equal(result.status, 0, result.stderr); cliReplays++; return result.stdout;
}
for (const target of selection.targets) {
  const entry = lock.cases.find(row => row.id === target.case); assert.ok(entry);
  const sources = {}, files = {}, sourceHashes = {};
  for (const revision of ['before', 'after']) {
    const blob = entry.blobs.find(row => row.path === target.path && row.revision === revision); assert.ok(blob);
    files[revision] = path.join(root, 'build/web-corpus', target.case, revision, target.path);
    sources[revision] = fs.readFileSync(files[revision], 'utf8');
    assert.equal(hash(sources[revision]), blob.sha256);
    assert.equal(hash(git(entry.project, 'show', `${revision === 'before' ? entry.parent : entry.head}:${target.path}`)), blob.sha256);
    sourceHashes[revision] = blob.sha256;
  }
  const patch = git(entry.project, 'diff', '--no-color', '--no-ext-diff', '--no-textconv', '--no-renames', '--diff-algorithm=myers', '--no-indent-heuristic', '--unified=3', entry.parent, entry.head, '--', target.path).toString('utf8');
  const directory = path.join(root, 'build/web-review/change-discovery', target.id); fs.mkdirSync(directory, { recursive: true });
  const patchFile = path.join(directory, 'source.patch'); fs.writeFileSync(patchFile, patch);
  const pages = []; let beforeOffset = 0, afterOffset = 0;
  while (true) {
    const page = discoverChange(sources.before, sources.after, patch, { beforeFilename: files.before, afterFilename: files.after, patchFilename: patchFile, beforeOffset, afterOffset });
    assert.equal(page.patch.reconstructed, true); assert.equal(page.nativeExecutions, 0); assert.equal(page.semanticCoverage, null);
    if (pages.length) for (const revision of ['before', 'after']) assert.deepEqual(page[revision].candidates.map(row => ({ id: row.id, source: row.source, target: row.target })), pages[0][revision].candidates.map(row => ({ id: row.id, source: row.source, target: row.target })));
    pages.push(page);
    if (page.before.nextOffset === null && page.after.nextOffset === null) break;
    const nextBefore = page.before.nextOffset ?? page.before.counts.candidates, nextAfter = page.after.nextOffset ?? page.after.counts.candidates;
    assert.ok(nextBefore > beforeOffset || nextAfter > afterOffset);
    beforeOffset = nextBefore; afterOffset = nextAfter;
  }
  const candidates = {}, revisions = {};
  for (const revision of ['before', 'after']) {
    candidates[revision] = pages.flatMap(page => page[revision].candidates.filter(row => row.status !== 'not-checked')).sort((a, b) => a.id - b.id);
    assert.equal(candidates[revision].length, pages[0][revision].counts.candidates);
    assert.equal(new Set(candidates[revision].map(row => row.id)).size, candidates[revision].length);
    for (const row of candidates[revision]) {
      assert.equal(row.sourceChange.behaviorImpact, 'not-evaluated');
      if (row.status === 'refused') assert.equal(row.sourceChange.analyzedLines, null);
    }
    revisions[revision] = { candidates: candidates[revision].length, changedLines: pages[0][revision].changedLines.length,
      anchorsIntersecting: candidates[revision].filter(row => row.sourceChange.anchorLines.length).length,
      selectionsIntersecting: candidates[revision].filter(row => row.sourceChange.selectionLines.length).length,
      analyzedSpansIntersecting: candidates[revision].filter(row => row.sourceChange.analyzedLines?.length).length,
      refused: candidates[revision].filter(row => row.status === 'refused').length };
  }
  const anchor = candidates.after.find(row => row.kind === target.anchor.kind && row.source.line === target.anchor.line);
  assert.ok(anchor); assert.equal(anchor.status, 'lowered'); assert.ok(anchor.sourceChange.analyzedLines.length > 0);
  if (target.id === 'actual-tag-row') {
    const entry = candidates.after.find(row => row.kind === 'call-entry' && row.target.callee === 'renameTag');
    assert.deepEqual(entry.sourceChange.analyzedLines, [65, 66, 67, 68]);
    assert.deepEqual(anchor.sourceChange.analyzedLines, [65, 66, 67, 68, 69]);
  }
  const argv = ['discover-change', '--before', files.before, '--after', files.after, '--patch', patchFile];
  assert.deepEqual(JSON.parse(cli(...argv, '--json')), pages[0]);
  fs.writeFileSync(path.join(directory, 'first-page.md'), cli(...argv));
  const focusedPages = []; let focusedBefore = 0, focusedAfter = 0;
  while (true) {
    const page = discoverChange(sources.before, sources.after, patch, { beforeFilename: files.before, afterFilename: files.after, patchFilename: patchFile,
      beforeOffset: focusedBefore, afterOffset: focusedAfter, focus: 'changed-lines' });
    for (const revision of ['before', 'after']) for (const row of page[revision].candidates.filter(row => !row.inFocus)) {
      assert.equal(row.status, 'not-checked'); assert.equal(row.sourceChange.analyzedLines, null);
    }
    focusedPages.push(page);
    if (page.before.nextOffset === null && page.after.nextOffset === null) break;
    const nextBefore = page.before.nextOffset ?? page.before.counts.candidates, nextAfter = page.after.nextOffset ?? page.after.counts.candidates;
    assert.ok(nextBefore > focusedBefore || nextAfter > focusedAfter);
    focusedBefore = nextBefore; focusedAfter = nextAfter;
  }
  const focused = { pages: focusedPages.length, revisions: {} };
  for (const revision of ['before', 'after']) {
    const selected = focusedPages.flatMap(page => page[revision].candidates.filter(row => row.status !== 'not-checked')).sort((a, b) => a.id - b.id);
    const expected = candidates[revision].filter(row => row.sourceChange.selectionLines.length > 0);
    assert.deepEqual(selected, expected, 'Focused lowering must exactly match the corresponding all-candidate results');
    focused.revisions[revision] = { checked: selected.length, outsideFocus: candidates[revision].length - selected.length };
  }
  assert.deepEqual(JSON.parse(cli(...argv, '--focus', 'changed-lines', '--json')), focusedPages[0]);
  fs.writeFileSync(path.join(directory, 'focused-first-page.md'), cli(...argv, '--focus', 'changed-lines'));
  fs.writeFileSync(path.join(directory, 'focused-pages.json'), JSON.stringify(focusedPages, null, 2) + '\n');
  fs.writeFileSync(path.join(directory, 'pages.json'), JSON.stringify(pages, null, 2) + '\n');
  fs.writeFileSync(path.join(directory, 'candidates.json'), JSON.stringify(candidates, null, 2) + '\n');
  const anchorPage = focusedPages.find(page => page.after.candidates[anchor.id].status === 'lowered');
  assert.ok(anchorPage);
  const pageFile = path.join(directory, 'anchor-page.json');
  fs.writeFileSync(pageFile, JSON.stringify(anchorPage, null, 2) + '\n');
  const artifact = JSON.parse(cli('lift-candidate', '--file', pageFile, '--candidate', String(anchor.id), '--revision', 'after', '--json'));
  assert.equal(hash(JSON.stringify(artifact)), anchor.artifactSha256);
  const artifactFile = path.join(directory, 'anchor.json');
  fs.writeFileSync(artifactFile, JSON.stringify(artifact, null, 2) + '\n');
  fs.writeFileSync(path.join(directory, 'anchor-reading.md'), cli('read', '--file', artifactFile));
  results.push({ id: target.id, case: target.case, parent: entry.parent, head: entry.head, sourceHashes, gitBlobsChecked: true,
    patchSha256: hash(patch), pages: pages.length, revisions, focused,
    anchor: { id: anchor.id, revision: 'after', kind: anchor.kind, source: anchor.source, sourceChange: anchor.sourceChange,
      artifactSha256: anchor.artifactSha256, pageFile, pageSha256: hash(fs.readFileSync(pageFile)), candidateReplayVerified: true },
    pagesSha256: hash(fs.readFileSync(path.join(directory, 'pages.json'))), candidatesSha256: hash(fs.readFileSync(path.join(directory, 'candidates.json'))),
    focusedPagesSha256: hash(fs.readFileSync(path.join(directory, 'focused-pages.json'))), directory });
}
const report = { schema: 'web-change-discovery-results-1', engineSha256: ENGINE_SHA256,
  producerSha256: hash(fs.readFileSync(fileURLToPath(import.meta.url))), selectionSha256: hash(selectionBytes), corpusLockSha256: hash(lockBytes),
  cases: results.length, cliReplays, nativeExecutions: 0, wholeBehaviorCasesVerified: 0, humanParticipants: 0, results,
  notes: ['This fixture additionally checks Git blobs against the pinned commits. The general CLI only verifies the supplied source texts and patch contents.',
    'Candidate anchors, selection context and analyzed computation spans are separate source geometry measurements.',
    'Changed-line focus preserves candidate IDs and exactly matches the corresponding all-candidate checks. Fewer selected checks are not a measured runtime or human-review speedup.',
    'Matching lines neither establish a behavioral difference nor match candidates into equivalent actions across revisions.',
    'A refused candidate has unknown analyzed spans; it is not treated as an empty computation.'] };
fs.writeFileSync(path.join(root, 'build/web-review/change-discovery-results.json'), JSON.stringify(report, null, 2) + '\n');
process.stdout.write(JSON.stringify({ engineSha256: ENGINE_SHA256, cliReplays, nativeExecutions: 0, results: results.map(({ id, pages, revisions, focused }) => ({ id, pages, revisions, focused })) }) + '\n');
