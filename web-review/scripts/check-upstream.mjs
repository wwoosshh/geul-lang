import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { liftJsxFlow } from '../src/jsx-flow.mjs';
import { observe } from '../src/core.mjs';
import { hash } from '../src/typescript.mjs';
import { ENGINE_SHA256 } from '../src/fingerprint.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const packageRoot = path.join(root, 'web-review');
const worktree = path.join(root, 'build/runtime-apps/excalidraw-scroll-a1d9b16');
const read = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const corpusBytes = fs.readFileSync(path.join(packageRoot, 'corpus/lock.json'));
const corpus = JSON.parse(corpusBytes);
assert.equal(corpus.selectionSha256, hash(fs.readFileSync(path.join(packageRoot, 'corpus/selection.json'))));
const caseInfo = corpus.cases.find(row => row.id === 'excalidraw-scroll-back-view-mode');
const target = read(path.join(packageRoot, 'corpus/flows.json')).targets.find(row => row.case === caseInfo.id);
const fixture = path.join(packageRoot, 'upstream-tests/excalidraw-scroll.test.tsx');
const fixtureBytes = fs.readFileSync(fixture);
const fixtureRelative = 'packages/excalidraw/tests/geul-scroll-observation.test.tsx';
const installedFixture = path.join(worktree, fixtureRelative);
const vitest = path.join(worktree, 'node_modules/vitest/vitest.mjs');
assert.ok(fs.existsSync(vitest), 'Prepare the isolated upstream worktree and frozen dependencies; see upstream-tests/README.md.');

function git(...args) {
  const result = spawnSync('git', ['-c', `safe.directory=${worktree.replaceAll('\\', '/')}`, ...args], {
    cwd: worktree, maxBuffer: 16 * 1024 * 1024, timeout: 30_000,
  });
  assert.equal(result.status, 0, result.stderr?.toString() || result.error?.message);
  return result.stdout;
}
function clean() { git('diff', '--exit-code', 'HEAD', '--'); }
function canonicalSource(commit, relative) { return git('show', `${commit}:${relative}`); }
function checkSource(commit, relative) {
  const canonical = canonicalSource(commit, relative);
  const checkout = fs.readFileSync(path.join(worktree, relative));
  // Git may convert LF to CRLF. Record both byte hashes and accept only that
  // exact checkout transform; no source fixes or replacements are allowed.
  assert.equal(checkout.toString('utf8').replaceAll('\r\n', '\n'), canonical.toString('utf8').replaceAll('\r\n', '\n'));
  return { path: relative, gitBlob: git('rev-parse', `${commit}:${relative}`).toString().trim(),
    sha256: hash(canonical), checkoutSha256: hash(checkout),
    checkoutTransform: checkout.equals(canonical) ? 'none' : 'line-endings-only' };
}
assert.equal(fs.realpathSync(worktree), path.resolve(worktree));
assert.equal(path.resolve(worktree, git('rev-parse', '--git-common-dir').toString().trim()), path.join(root, 'build/research/excalidraw/.git'));
const originalHead = git('rev-parse', 'HEAD').toString().trim();
assert.ok([caseInfo.parent, caseInfo.head].includes(originalHead), 'Unrecognized worktree revision; refusing to switch it.');
assert.equal(git('branch', '--show-current').toString().trim(), '', 'The fixture worktree must be detached.');
clean();
const changedFiles = git('diff', '--name-only', caseInfo.parent, caseInfo.head).toString().trim().split(/\r?\n/).sort();
assert.deepEqual(changedFiles, [
  'packages/excalidraw/components/LayerUI.tsx',
  'packages/excalidraw/components/MobileMenu.tsx',
  'packages/excalidraw/css/styles.scss',
]);
if (fs.existsSync(installedFixture)) assert.equal(hash(fs.readFileSync(installedFixture)), hash(fixtureBytes), 'Existing upstream fixture differs; inspect it before replacement.');
else fs.writeFileSync(installedFixture, fixtureBytes, { flag: 'wx' });
assert.equal(canonicalSource(caseInfo.parent, 'yarn.lock').toString(), canonicalSource(caseInfo.head, 'yarn.lock').toString());
assert.equal(canonicalSource(caseInfo.parent, 'package.json').toString(), canonicalSource(caseInfo.head, 'package.json').toString());

const directory = path.join(root, 'build/web-review/upstream');
fs.mkdirSync(directory, { recursive: true });
const output = fs.mkdtempSync(path.join(directory, 'run-'));
const results = [];
function write(name, value) { fs.writeFileSync(path.join(output, name), JSON.stringify(value, null, 2) + '\n', { flag: 'wx' }); }
async function execute(revision) {
  const log = fs.openSync(path.join(output, `${revision}.log`), 'wx');
  const args = [vitest, 'run', fixtureRelative, '--maxWorkers=1', '--minWorkers=1', '--reporter=json',
    `--outputFile=${path.join(output, `${revision}-vitest.json`)}`];
  try {
    await new Promise((resolve, reject) => {
      const child = spawn(process.execPath, args, { cwd: worktree, stdio: ['ignore', log, log], windowsHide: true,
        env: { ...process.env, GEUL_REVISION: revision, GEUL_OBSERVATIONS: path.join(output, `${revision}-observations.json`) } });
      const timer = setTimeout(() => { child.kill(); reject(new Error('Upstream test timeout (180 seconds).')); }, 180_000);
      child.once('error', error => { clearTimeout(timer); reject(error); });
      child.once('exit', code => { clearTimeout(timer); code === 0 ? resolve() : reject(new Error(`Upstream ${revision} exited ${code}; inspect ${output}`)); });
    });
  } finally { fs.closeSync(log); }
}

const setupPaths = ['yarn.lock', 'package.json', 'vitest.config.mts', 'setupTests.ts',
  'packages/excalidraw/tests/test-utils.ts', 'packages/excalidraw/tests/helpers/polyfills.ts',
  'packages/excalidraw/components/App.tsx'];
try {
  for (const [revision, commit] of [['before', caseInfo.parent], ['after', caseInfo.head]]) {
    clean();
    git('switch', '--detach', commit);
    const sourceEvidence = [...new Set([...changedFiles, ...setupPaths])].map(relative => checkSource(commit, relative));
    const source = canonicalSource(commit, target.path).toString('utf8');
    const pinned = caseInfo.blobs.find(blob => blob.revision === revision && blob.path === target.path);
    assert.equal(hash(source), pinned.sha256);
    const artifact = liftJsxFlow(source, { ...target.selector, ...(revision === 'after' ? { prefixLine: target.afterPrefixLine } : {}),
      filename: path.join(root, 'build/web-corpus', caseInfo.id, revision, target.path) });
    write(`${revision}-artifact.json`, artifact);
    process.stdout.write(`Running original ${revision} app at ${commit}; log: ${output}\n`);
    await execute(revision);
    clean();
    assert.equal(hash(fs.readFileSync(installedFixture)), hash(fixtureBytes));
    const testResult = read(path.join(output, `${revision}-vitest.json`));
    assert.equal(testResult.success, true);
    assert.equal(testResult.numPassedTests, 8);
    assert.equal(testResult.numFailedTests, 0);
    const captured = read(path.join(output, `${revision}-observations.json`));
    assert.equal(captured.schema, 'geul-upstream-observations-1');
    assert.equal(captured.revision, revision);
    const ids = new Set(captured.observations.map(row => row.id));
    assert.equal(ids.size, 8);
    const modelChecks = captured.observations.map(row => {
      assert.equal(row.formFactor, 'phone');
      assert.ok([0, 1].includes(row.buttonCount));
      const model = observe(artifact.ir, row.input);
      assert.deepEqual(model, { kind: 'value', value: row.buttonCount === 1 }, `${revision} ${row.id} ${row.phase}`);
      return { id: row.id, phase: row.phase, input: row.input, model, buttonCount: row.buttonCount };
    });
    for (const id of ids) {
      const phases = modelChecks.filter(row => row.id === id).map(row => row.phase);
      assert.equal(new Set(phases).size, phases.length);
      for (const phase of ['initial', 'wheel-away', 'injected-menu', 'closed-menu', 'injected-sidebar', 'closed-sidebar']) assert.ok(phases.includes(phase));
    }
    const clickChecks = modelChecks.filter(row => row.phase === 'click-back').length;
    assert.equal(clickChecks, revision === 'before' ? 2 : 4);
    write(`${revision}-model-checks.json`, modelChecks);
    results.push({ revision, commit, tree: git('rev-parse', `${commit}^{tree}`).toString().trim(), sourceEvidence,
      testsPassed: 8, modelChecks: modelChecks.length, clickChecks, checks: modelChecks });
  }
} finally {
  // Only our detached, clean fixture checkout is switched. Keep all experiment
  // logs, failed runs, the copied test, and installed dependencies for inspection.
  clean();
  git('switch', '--detach', originalHead);
}
const paired = [];
for (const before of results[0].checks) {
  const after = results[1].checks.find(row => row.id === before.id && row.phase === before.phase);
  assert.ok(after);
  assert.deepEqual(before.input, after.input);
  paired.push({ id: before.id, phase: before.phase, before: before.buttonCount, after: after.buttonCount });
}
const changed = paired.filter(row => row.before !== row.after);
assert.equal(changed.length, 6);
const report = {
  schema: 'web-upstream-results-1', case: caseInfo.id, engineSha256: ENGINE_SHA256,
  corpusLockSha256: hash(corpusBytes), fixtureSha256: hash(fixtureBytes), runnerSha256: hash(fs.readFileSync(fileURLToPath(import.meta.url))),
  node: process.version, output, changedFiles,
  installedVersions: Object.fromEntries(['react', 'react-dom', 'typescript', 'vitest', 'jsdom'].map(name =>
    [name, read(path.join(worktree, 'node_modules', name, 'package.json')).version])),
  dependencySetup: 'Original Yarn 1.22.22 frozen lock, install scripts ignored; installed package files are not all independently hashed.',
  scope: 'Original Excalidraw app in its original jsdom test environment. Compare the selected mobile button DOM count against the JSX-object-flow model at observed states; click existing controls and check scrolledOutside becomes false.',
  environmentAssumptions: [
    'Original canvas, fonts, storage, matchMedia and throttle test mocks remain; see hash-bound setupTests.ts and imported test helpers.',
    'Mocked 390 x 844 layout; original refreshEditorInterface/refresh called because jsdom does not drive browser layout/ResizeObserver and window resize is edit-mode-only.',
    'Wheel and button click use original event handlers. Menu/sidebar states are injected through the original test API; their user reachability is not established.',
  ],
  notProven: ['CSS layout/visibility/occlusion', 'real browser rendering and hydration', 'all reachable states or event schedules', 'whole change semantics', 'human readability'],
  wholeBehaviorCasesVerified: 0, humanParticipants: 0,
  testsPassed: results.reduce((sum, row) => sum + row.testsPassed, 0),
  modelChecks: results.reduce((sum, row) => sum + row.modelChecks, 0),
  clickChecks: results.reduce((sum, row) => sum + row.clickChecks, 0),
  pairedStates: paired.length, changedStates: changed, results: results.map(({ checks, ...row }) => row),
};
write('report.json', report);
fs.writeFileSync(path.join(root, 'build/web-review/upstream-results.json'), JSON.stringify(report, null, 2) + '\n');
process.stdout.write(JSON.stringify({ output, testsPassed: report.testsPassed, modelChecks: report.modelChecks,
  clickChecks: report.clickChecks, changedStates: changed.length, wholeBehaviorCasesVerified: 0 }) + '\n');
