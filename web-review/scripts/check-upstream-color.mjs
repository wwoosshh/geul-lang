import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { liftJsxProperty } from '../src/jsx-property.mjs';
import { observe, encode } from '../src/core.mjs';
import { hash } from '../src/typescript.mjs';
import { ENGINE_SHA256 } from '../src/fingerprint.mjs';
import { expectedColorObservations, checkColorCapture, pairColorObservations } from './color-observations.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const pkg = path.join(root, 'web-review');
const worktree = path.join(root, 'build/runtime-apps/excalidraw-color-786ab266');
const read = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const corpusBytes = fs.readFileSync(path.join(pkg, 'corpus/lock.json'));
const corpus = JSON.parse(corpusBytes);
assert.equal(corpus.selectionSha256, hash(fs.readFileSync(path.join(pkg, 'corpus/selection.json'))));
const specBytes = fs.readFileSync(path.join(pkg, 'corpus/color-scenarios.json'));
const spec = JSON.parse(specBytes);
expectedColorObservations(spec, 'before'); expectedColorObservations(spec, 'after');
const caseInfo = corpus.cases.find(row => row.id === spec.case);
assert.ok(caseInfo);
const selectionBytes = fs.readFileSync(path.join(pkg, 'corpus/jsx-properties.json'));
const target = JSON.parse(selectionBytes).targets.find(row => row.case === caseInfo.id);
assert.equal(target.attribute, 'aria-invalid'); assert.equal(target.tag, 'input');
const fixtureBytes = fs.readFileSync(path.join(pkg, 'upstream-tests/excalidraw-color.test.tsx'));
const runnerSha256 = hash(fs.readFileSync(fileURLToPath(import.meta.url)));
const comparatorSha256 = hash(fs.readFileSync(path.join(pkg, 'scripts/color-observations.mjs')));
const fixtureRelative = 'packages/excalidraw/tests/geul-color-observation.test.tsx';
const scenarioRelative = 'packages/excalidraw/tests/geul-color-scenarios.json';
const vitest = path.join(worktree, 'node_modules/vitest/vitest.mjs');
assert.ok(fs.existsSync(vitest), 'Prepare the separate color worktree and its frozen dependencies; see upstream-tests/README.md.');

function git(...args) {
  const result = spawnSync('git', ['-c', `safe.directory=${worktree.replaceAll('\\', '/')}`, ...args], {
    cwd: worktree, maxBuffer: 16 * 1024 * 1024, timeout: 30_000,
  });
  assert.equal(result.status, 0, result.stderr?.toString() || result.error?.message);
  return result.stdout;
}
function clean() { git('diff', '--exit-code', 'HEAD', '--'); }
function canonical(commit, relative) { return git('show', `${commit}:${relative}`); }
function sourceEvidence(commit, relative) {
  const exists = git('ls-tree', commit, '--', relative).length !== 0;
  if (!exists) {
    assert.equal(fs.existsSync(path.join(worktree, relative)), false, `Deleted source still present: ${relative}`);
    return { path: relative, present: false };
  }
  const source = canonical(commit, relative), checkout = fs.readFileSync(path.join(worktree, relative));
  assert.equal(checkout.toString('utf8').replaceAll('\r\n', '\n'), source.toString('utf8').replaceAll('\r\n', '\n'));
  return { path: relative, present: true, gitBlob: git('rev-parse', `${commit}:${relative}`).toString().trim(),
    sha256: hash(source), checkoutSha256: hash(checkout),
    checkoutTransform: source.equals(checkout) ? 'none' : 'line-endings-only' };
}
const listening = await new Promise(resolve => {
  const socket = net.createConnection({ host: '127.0.0.1', port: 56680 });
  const done = value => { socket.destroy(); resolve(value); };
  socket.once('connect', () => done(true)); socket.once('error', () => done(false)); socket.setTimeout(1000, () => done(true));
});
assert.equal(listening, false, 'Stop the color browser fixture on port 56680 before switching its checkout.');
assert.equal(fs.realpathSync(worktree), path.resolve(worktree));
assert.equal(path.resolve(worktree, git('rev-parse', '--git-common-dir').toString().trim()), path.join(root, 'build/research/excalidraw/.git'));
const originalHead = git('rev-parse', 'HEAD').toString().trim();
assert.ok([caseInfo.parent, caseInfo.head].includes(originalHead));
assert.equal(git('branch', '--show-current').toString().trim(), '', 'A detached fixture worktree is required.');
clean();
const changedFiles = git('diff', '--name-only', '--no-renames', caseInfo.parent, caseInfo.head).toString().trim().split(/\r?\n/).sort();
assert.deepEqual(changedFiles, [
  'packages/excalidraw/components/ColorPicker/ColorInput.tsx',
  'packages/excalidraw/components/ColorPicker/ColorPicker.scss',
  'packages/excalidraw/locales/en.json',
  'packages/excalidraw/tests/colorInput.test.ts',
  'packages/excalidraw/tests/colorInput.test.tsx',
]);
for (const [relative, bytes] of [[fixtureRelative, fixtureBytes], [scenarioRelative, specBytes]]) {
  const installed = path.join(worktree, relative);
  if (fs.existsSync(installed)) assert.equal(hash(fs.readFileSync(installed)), hash(bytes), `Existing fixture differs: ${relative}`);
  else fs.writeFileSync(installed, bytes, { flag: 'wx' });
}
for (const relative of ['yarn.lock', 'package.json']) assert.equal(canonical(caseInfo.parent, relative).toString(), canonical(caseInfo.head, relative).toString());

const directory = path.join(root, 'build/web-review/upstream-color');
fs.mkdirSync(directory, { recursive: true });
const output = fs.mkdtempSync(path.join(directory, 'run-'));
const write = (name, value) => fs.writeFileSync(path.join(output, name), JSON.stringify(value, null, 2) + '\n', { flag: 'wx' });
const results = [];
let checkoutMayBeInUse = false;
async function execute(revision) {
  const log = fs.openSync(path.join(output, `${revision}.log`), 'wx');
  try {
    await new Promise((resolve, reject) => {
      const child = spawn(process.execPath, [vitest, 'run', fixtureRelative, '--maxWorkers=1', '--minWorkers=1', '--reporter=json',
        `--outputFile=${path.join(output, `${revision}-vitest.json`)}`], {
        cwd: worktree, stdio: ['ignore', log, log], windowsHide: true,
        env: { ...process.env, GEUL_REVISION: revision, GEUL_OBSERVATIONS: path.join(output, `${revision}-observations.json`) },
      });
      const timer = setTimeout(() => {
        // Do not switch a checkout possibly still used by a test worker. Keep
        // the failed run and current detached revision available for inspection.
        checkoutMayBeInUse = true; child.kill();
        reject(new Error(`Color test timeout; inspect child process ${child.pid} before restoring ${originalHead}. Logs: ${output}`));
      }, 180_000);
      child.once('error', error => { clearTimeout(timer); reject(error); });
      child.once('exit', code => { clearTimeout(timer); code === 0 ? resolve() : reject(new Error(`Color ${revision} exited ${code}; inspect ${output}`)); });
    });
  } finally { fs.closeSync(log); }
}

const setupPaths = ['yarn.lock', 'package.json', '.npmrc', 'vitest.config.mts', 'setupTests.ts',
  'packages/excalidraw/tests/test-utils.ts', 'packages/excalidraw/tests/helpers/polyfills.ts',
  'packages/excalidraw/tests/helpers/mocks.ts', 'packages/excalidraw/components/App.tsx',
  'packages/common/src/colors.ts', 'packages/excalidraw/components/ColorPicker/ColorPicker.tsx'];
try {
  for (const [revision, commit] of [['before', caseInfo.parent], ['after', caseInfo.head]]) {
    clean(); git('switch', '--detach', commit);
    const sources = [...new Set([...changedFiles, ...setupPaths])].map(relative => sourceEvidence(commit, relative));
    const source = canonical(commit, target.path).toString('utf8');
    const pinned = caseInfo.blobs.find(blob => blob.revision === revision && blob.path === target.path);
    assert.equal(hash(source), pinned.sha256);
    const artifact = liftJsxProperty(source, { tag: target.tag, attribute: target.attribute,
      filename: path.join(root, 'build/web-corpus', caseInfo.id, revision, target.path) });
    assert.equal(artifact.target.provided, target[revision + 'Provided']);
    if (revision === 'after') {
      const span = artifact.ir.properties[0].value.source;
      assert.equal(source.slice(span.start, span.end), target.afterExpression);
    }
    write(`${revision}-artifact.json`, artifact);
    process.stdout.write(`Running original color ${revision} at ${commit}; log: ${output}\n`);
    await execute(revision); clean();
    assert.equal(hash(fs.readFileSync(path.join(worktree, fixtureRelative))), hash(fixtureBytes));
    assert.equal(hash(fs.readFileSync(path.join(worktree, scenarioRelative))), hash(specBytes));
    const tests = read(path.join(output, `${revision}-vitest.json`));
    assert.equal(tests.success, true); assert.equal(tests.numPassedTests, spec.scenarios.length);
    assert.equal(tests.numFailedTests, 0); assert.equal(tests.numPendingTests, 0);
    const captured = read(path.join(output, `${revision}-observations.json`));
    const checks = checkColorCapture(spec, revision, captured).map(row => {
      // Input is the independently declared scenario message, NEVER the error
      // text just read from the DOM. This remains a conditional JSX relation,
      // not automatic interpretation of changeColor/useState/useEffect.
      const model = observe(artifact.ir, row.declaredInput);
      const domProperty = row.actual.ariaPresent ? { 'aria-invalid': row.actual.ariaInvalid === 'true' } : {};
      assert.deepEqual(model, { kind: 'value', value: encode(domProperty) });
      return { ...row, model };
    });
    write(`${revision}-checks.json`, checks);
    results.push({ revision, commit, tree: git('rev-parse', `${commit}^{tree}`).toString().trim(), sources,
      testsPassed: tests.numPassedTests, observations: checks.length, checks });
  }
} finally {
  if (!checkoutMayBeInUse) { clean(); git('switch', '--detach', originalHead); }
}
assert.equal(hash(fs.readFileSync(fileURLToPath(import.meta.url))), runnerSha256);
assert.equal(hash(fs.readFileSync(path.join(pkg, 'scripts/color-observations.mjs'))), comparatorSha256);
assert.equal(hash(fs.readFileSync(path.join(pkg, 'upstream-tests/excalidraw-color.test.tsx'))), hash(fixtureBytes));
assert.equal(hash(fs.readFileSync(path.join(pkg, 'corpus/color-scenarios.json'))), hash(specBytes));
const paired = pairColorObservations(results[0].checks, results[1].checks);
write('paired.json', paired);
const changesByField = Object.fromEntries(Object.keys(paired[0].before).map(field => [field, paired.filter(row => row.changedFields.includes(field)).length]));
const report = {
  schema: 'web-upstream-color-results-1', case: caseInfo.id, engineSha256: ENGINE_SHA256,
  corpusLockSha256: hash(corpusBytes), selectionSha256: hash(selectionBytes), scenariosSha256: hash(specBytes),
  fixtureSha256: hash(fixtureBytes), runnerSha256, comparatorSha256, node: process.version, output, changedFiles,
  installedVersions: Object.fromEntries(['react', 'react-dom', 'typescript', 'vitest', 'jsdom'].map(name =>
    [name, read(path.join(worktree, 'node_modules', name, 'package.json')).version])),
  dependencySetup: 'Separate original Yarn 1.22.22 frozen-lock install with install scripts ignored; installed package files are not all independently hashed.',
  scope: spec.scope,
  modelInputOrigin: 'Hand-specified scenario error message; not read from DOM or private hook state. The JSX property relation is conditional on this supplied input.',
  environmentAssumptions: [
    'Original App, ColorInput, helpers and original Vitest/jsdom canvas/font/storage/matchMedia/throttle mocks. English locale and initial white background are explicit app props.',
    'No-op ResizeObserver follows original colorInput tests. Menu/picker use click handlers; text change and blur use testing-library events, not physical keyboard/browser gestures.',
    'Background color is read from the original window.h test accessor. Local errorMessage state is not inspected or generated by the geul engine.',
  ],
  notProven: ['All colors and reachable states', 'React hook/event/scheduler interpretation by geul', 'CSS geometry and browser paint',
    'Screen reader announcement', 'Whole change equivalence or correct product intent', 'Human review improvement'],
  wholeBehaviorCasesVerified: 0, humanParticipants: 0,
  scenarios: spec.scenarios.length, testsPassed: results.reduce((sum, row) => sum + row.testsPassed, 0),
  originalAppMounts: results.reduce((sum, row) => sum + row.testsPassed, 0),
  observations: results.reduce((sum, row) => sum + row.observations, 0),
  conditionalPropertyChecks: results.reduce((sum, row) => sum + row.observations, 0),
  pairedStates: paired.length, changesByField,
  results: results.map(({ checks, ...row }) => row),
};
write('report.json', report);
const quote = value => '`' + JSON.stringify(value).replaceAll('|', '\\|') + '`';
const changedDisplay = paired.filter(row => row.changedFields.includes('display'));
const lines = [
  '# 원본 색상 입력의 고정 경로 대조', '',
  `원본 전후 앱을 각각 ${report.scenarios}번 열고 ${report.observations}개 상태를 관찰했다. 전후 대응 상태는 ${paired.length}개다. 기존 12개 사례 중 하나를 더 깊게 검사했으며 새 변경 사례로 더하지 않는다.`, '',
  `입력창의 문자열이 달라진 상태 ${changesByField.display}개, 오류 문구·role이 생긴 상태 ${changesByField.errorText}개, aria-invalid 속성의 존재가 달라진 상태 ${changesByField.ariaPresent}개다. 저장된 배경색 문자열의 전후 차이는 ${changesByField.saved}개다. 같은 시나리오의 여러 단계이므로 독립 사용자나 변경 건수로 해석하지 않는다.`, '',
  '## 입력 표시가 달라진 단계', '',
  '| 경로 / 단계 | 보낸 입력 | 변경 전 표시 | 변경 후 표시 | 양쪽 저장 색 |',
  '|---|---|---|---|---|',
  ...changedDisplay.map(row => `| ${row.id} / ${row.phase} | ${quote(row.action.value)} | ${quote(row.before.display)} | ${quote(row.after.display)} | ${quote(row.after.saved)} |`), '',
  '## 읽을 때 구분할 사실', '',
  '- 같은 색을 공백과 함께 다시 입력하면, 관찰한 전 버전에는 공백이 남고 후 버전에는 공백이 제거된다. 유효한 새 색으로 실제 저장값이 바뀌는 단계에서는 이 차이가 관찰되지 않았다.',
  '- 잘못된 값에서 입력을 마치면 양쪽 모두 마지막으로 저장된 색 표시로 돌아온다. 후 버전의 오류 문구와 invalid 표시도 해제되는 경로를 확인했다.',
  '- 유효한 색을 한 글자씩 지우면 중간의 유효한 4자리·3자리 색이 저장된다. 빈 입력은 흰색으로 초기화한다는 뜻이 아니다. 이 경로의 입력 종료 시 마지막 3자리 색이 다시 표시됐다.', '',
  '## 글 모델과의 관계', '',
  '기존 글 IR은 선택한 aria-invalid 속성만 계산한다. 이번 경로는 수동으로 정한 입력과 기대 메시지를 원본 앱에서 시험했다. DOM의 메시지를 다시 모델 입력으로 돌려 정답으로 사용하지 않는다. 전달한 기대 메시지와 원본 DOM 속성을 대조하되 오류 상태를 만드는 hooks·콜백의 자동 해석은 수행하지 않았다.', '',
  'CSS 배치·실제 보조 기술·임의 입력 및 이벤트 순서·기획 의도·사람의 이해도는 미확인이다. 전체 행동 0/12, 사람 참가자 0명이다.', '',
  `상세 관찰·수정 전후 원본·환경·코드 해시: ${output.replaceAll('\\', '/')}`, '',
];
fs.writeFileSync(path.join(output, 'comparison.md'), lines.join('\n'), { flag: 'wx' });
fs.writeFileSync(path.join(root, 'build/web-review/upstream-color-results.json'), JSON.stringify(report, null, 2) + '\n');
process.stdout.write(JSON.stringify({ output, testsPassed: report.testsPassed, observations: report.observations,
  pairedStates: paired.length, changesByField, wholeBehaviorCasesVerified: 0 }) + '\n');
