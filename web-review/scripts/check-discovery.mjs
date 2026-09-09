import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { discoverSource } from '../src/discovery.mjs';
import { ENGINE_SHA256, ENGINE_RUNTIME } from '../src/fingerprint.mjs';
import { hash } from '../src/typescript.mjs';

const pkg = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'), root = path.dirname(pkg);
const selectionBytes = fs.readFileSync(path.join(pkg, 'corpus/discovery.json')), selection = JSON.parse(selectionBytes);
const lockBytes = fs.readFileSync(path.join(pkg, 'corpus/lock.json')), lock = JSON.parse(lockBytes);
assert.equal(lock.selectionSha256, hash(fs.readFileSync(path.join(pkg, 'corpus/selection.json'))));
assert.equal(selection.targets.length, 3);
const results = []; let cliReplays = 0;
function cli(...args) {
  const result = spawnSync(process.execPath, [path.join(pkg, 'src/cli.mjs'), ...args], { encoding: 'utf8', timeout: 20000, maxBuffer: 8 * 1024 * 1024 });
  assert.equal(result.status, 0, result.stderr); cliReplays++; return result.stdout;
}
for (const target of selection.targets) {
  const entry = lock.cases.find(row => row.id === target.case), blob = entry?.blobs.find(row => row.revision === target.revision && row.path === target.path);
  assert.ok(blob);
  const filename = path.join(root, 'build/web-corpus', target.case, target.revision, target.path), text = fs.readFileSync(filename, 'utf8');
  assert.equal(hash(text), blob.sha256);
  const directory = path.join(root, 'build/web-review/discovery', target.id); fs.mkdirSync(directory, { recursive: true });
  const pages = []; let offset = 0;
  do {
    const page = discoverSource(text, { filename, offset });
    assert.equal(page.nativeExecutions, 0); assert.equal(page.semanticCoverage, null); assert.equal(page.wholeBehaviorVerified, false);
    assert.ok(page.counts.checked > 0);
    assert.ok(page.candidates.every(row => path.resolve(row.source.file) === filename));
    assert.ok(page.candidates.filter(row => row.refusalSource).every(row => path.resolve(row.refusalSource.file) === filename));
    if (pages.length) assert.deepEqual(page.candidates.map(row => ({ id: row.id, source: row.source, target: row.target })), pages[0].candidates.map(row => ({ id: row.id, source: row.source, target: row.target })));
    pages.push(page); offset = page.nextOffset;
    if (offset !== null) assert.ok(offset > page.selection.offset);
  } while (offset !== null);
  const candidates = pages.flatMap(page => page.candidates.filter(row => row.status !== 'not-checked')).sort((a, b) => a.id - b.id);
  assert.equal(candidates.length, pages[0].counts.candidates);
  assert.equal(new Set(candidates.map(row => row.id)).size, candidates.length);
  for (const [index, row] of candidates.entries()) assert.equal(row.id, index);
  const first = JSON.parse(cli('discover', '--file', filename, '--json'));
  assert.deepEqual(first, pages[0]);
  fs.writeFileSync(path.join(directory, 'first-page.md'), cli('discover', '--file', filename));
  fs.writeFileSync(path.join(directory, 'pages.json'), JSON.stringify(pages, null, 2) + '\n');
  fs.writeFileSync(path.join(directory, 'candidates.json'), JSON.stringify(candidates, null, 2) + '\n');
  const anchors = candidates.filter(row => row.kind === target.anchor.kind && row.source.line === target.anchor.line);
  assert.equal(anchors.length, 1); const anchor = anchors[0]; assert.equal(anchor.status, 'lowered');
  const opts = anchor.target;
  const argv = anchor.kind === 'const' ? ['--start-line', String(opts.startLine), '--end-line', String(opts.endLine), '--outputs', opts.outputs.join(',')]
    : ['--callee', opts.callee, '--line', String(opts.line)];
  const artifact = JSON.parse(cli(anchor.lift.command, '--file', filename, ...argv, '--json'));
  assert.equal(hash(JSON.stringify(artifact)), anchor.artifactSha256);
  const anchorPage = pages.find(page => page.candidates[anchor.id].status === 'lowered');
  assert.ok(anchorPage);
  const pageFile = path.join(directory, 'anchor-page.json');
  fs.writeFileSync(pageFile, JSON.stringify(anchorPage, null, 2) + '\n');
  const replay = JSON.parse(cli('lift-candidate', '--file', pageFile, '--candidate', String(anchor.id), '--json'));
  assert.deepEqual(replay, artifact, 'Candidate replay must agree with the original explicit selector CLI');
  const artifactFile = path.join(directory, 'anchor.json'); fs.writeFileSync(artifactFile, JSON.stringify(artifact, null, 2) + '\n');
  fs.writeFileSync(path.join(directory, 'anchor-reading.md'), cli('read', '--file', artifactFile));
  const counts = Object.fromEntries(['lowered', 'refused'].map(status => [status, candidates.filter(row => row.status === status).length]));
  results.push({ id: target.id, case: target.case, file: filename, sourceSha256: blob.sha256, pages: pages.length,
    candidates: candidates.length, sourceSites: pages[0].counts.sourceSites, counts,
    emptyPrefixEntries: candidates.filter(row => row.kind === 'call-entry' && row.status === 'lowered' && row.prefixStatements === 0).length,
    anchor: { id: anchor.id, kind: anchor.kind, source: anchor.source, artifactSha256: anchor.artifactSha256,
      pageFile, pageSha256: hash(fs.readFileSync(pageFile)), candidateReplayVerified: true },
    pagesSha256: hash(fs.readFileSync(path.join(directory, 'pages.json'))), candidatesSha256: hash(fs.readFileSync(path.join(directory, 'candidates.json'))), directory });
}
const report = { schema: 'web-discovery-results-1', engineSha256: ENGINE_SHA256, runtime: ENGINE_RUNTIME,
  producerSha256: hash(fs.readFileSync(fileURLToPath(import.meta.url))), selectionSha256: hash(selectionBytes), corpusLockSha256: hash(lockBytes),
  sourceFiles: results.length, cliReplays, nativeExecutions: 0, wholeBehaviorCasesVerified: 0, humanParticipants: 0, results,
  notes: ['Three fixed corpus files test discovery and pagination; they are not an unbiased sample of frontend language coverage.',
    'The source is parsed and lowered, never executed. Replaying a discovered anchor checks selectors and provenance, not native behavior.',
    'A call entry and argument preparation at the same location are distinct candidates. Empty-prefix entry checks remain separate.',
    'Each const statement is a separate snapshot. Hook calls, previous statements, actual React delivery and later effects are not inferred.'] };
fs.writeFileSync(path.join(root, 'build/web-review/discovery-results.json'), JSON.stringify(report, null, 2) + '\n');
process.stdout.write(JSON.stringify({ engineSha256: ENGINE_SHA256, cliReplays, nativeExecutions: 0, results: results.map(({ id, candidates, sourceSites, pages, counts, emptyPrefixEntries }) => ({ id, candidates, sourceSites, pages, counts, emptyPrefixEntries })) }) + '\n');
