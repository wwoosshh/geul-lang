// Validate retained browser evidence. This script never drives a browser.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { hash } from '../src/typescript.mjs';
import { ENGINE_SHA256 } from '../src/fingerprint.mjs';
import { observe, encode } from '../src/core.mjs';
import { liftJsxProperty } from '../src/jsx-property.mjs';
import { checkColorBrowserRecording } from './color-browser-recording.mjs';

const pkg = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'), root = path.dirname(pkg);
const mode = process.argv[2] ?? 'verify';
assert.ok(['freeze', 'verify'].includes(mode));
const recordPath = path.join(pkg, 'evaluation/browser-evidence/2026-09-09-color.json');
const lockPath = recordPath.replace(/\.json$/, '.lock.json');
const recordBytes = fs.readFileSync(recordPath), record = JSON.parse(recordBytes);
const corpusBytes = fs.readFileSync(path.join(pkg, 'corpus/lock.json')), corpus = JSON.parse(corpusBytes);
assert.equal(corpus.selectionSha256, hash(fs.readFileSync(path.join(pkg, 'corpus/selection.json'))));
const caseInfo = corpus.cases.find(row => row.id === 'excalidraw-color-error');
const selectionBytes = fs.readFileSync(path.join(pkg, 'corpus/jsx-properties.json'));
const target = JSON.parse(selectionBytes).targets.find(row => row.case === caseInfo.id);
const checks = checkColorBrowserRecording(record, { before: caseInfo.parent, after: caseInfo.head });
const repo = path.join(root, 'build/research/excalidraw');
function git(...args) {
  const result = spawnSync('git', ['-C', repo, '-c', `safe.directory=${repo.replaceAll('\\', '/')}`, ...args], { maxBuffer: 16 * 1024 * 1024, timeout: 15_000 });
  assert.equal(result.status, 0, result.stderr?.toString() || result.error?.message); return result.stdout;
}
const sourcePaths = git('diff', '--no-renames', '--name-only', caseInfo.parent, caseInfo.head).toString().trim().split(/\r?\n/);
assert.equal(sourcePaths.length, 5);
sourcePaths.push('vitest.config.mts', 'yarn.lock', 'package.json', 'packages/common/src/colors.ts');
const fixtures = ['color-browser.html', 'color-browser.tsx', 'color-browser.config.mts'].map(name => ({
  path: `upstream-tests/${name}`, sha256: hash(fs.readFileSync(path.join(pkg, 'upstream-tests', name))),
}));
const revisions = Object.entries(record.commits).map(([revision, commit]) => ({ revision, commit,
  tree: git('rev-parse', `${commit}^{tree}`).toString().trim(),
  sources: sourcePaths.map(relative => git('ls-tree', commit, '--', relative).length === 0
    ? { path: relative, present: false }
    : { path: relative, present: true, gitBlob: git('rev-parse', `${commit}:${relative}`).toString().trim(),
      sha256: hash(git('show', `${commit}:${relative}`)) }),
}));
const provenance = {
  schema: 'geul-color-browser-recording-lock-1', recordingSha256: hash(recordBytes), corpusLockSha256: hash(corpusBytes),
  selectionSha256: hash(selectionBytes), fixtures, revisions,
  browser: 'Codex in-app browser, 1280 x 1000; original app content 798 x 648; desktop viewport, not mobile emulation.',
  dependencies: 'Separate original Yarn 1.22.22 frozen-lock install, scripts ignored; React/React DOM 19.0.0 and Vite 5.0.12. Installed dependency files are not all independently hashed.',
  scope: 'Two original app mounts; original click/change/keyboard handlers, CSS and observers, without jsdom setup. Harness uses original workspace aliases and source components, not the production app entrypoint.',
  collection: 'CUA observations transcribed from tool output. Hashes bind retained evidence and fixtures; they do not independently authenticate the recording.',
};
if (mode === 'freeze') {
  assert.equal(fs.existsSync(lockPath), false, 'Existing evidence must be versioned, not overwritten.');
  fs.writeFileSync(lockPath, JSON.stringify(provenance, null, 2) + '\n', { flag: 'wx' });
}
assert.deepEqual(JSON.parse(fs.readFileSync(lockPath, 'utf8')), provenance);
const artifacts = Object.fromEntries(revisions.map(({ revision, commit }) => {
  const source = git('show', `${commit}:${target.path}`).toString('utf8');
  const pinned = caseInfo.blobs.find(row => row.revision === revision && row.path === target.path);
  assert.equal(hash(source), pinned.sha256);
  return [revision, liftJsxProperty(source, { tag: target.tag, attribute: target.attribute,
    filename: path.join(root, 'build/web-corpus', caseInfo.id, revision, target.path) })];
}));
for (const row of checks.rows) {
  const model = observe(artifacts[row.revision].ir, row.declaredInput);
  const property = row.observed.ariaPresent ? { 'aria-invalid': row.observed.ariaInvalid === 'true' } : {};
  assert.deepEqual(model, { kind: 'value', value: encode(property) });
}
const result = {
  schema: 'web-color-browser-results-1', engineSha256: ENGINE_SHA256, producerSha256: hash(fs.readFileSync(fileURLToPath(import.meta.url))),
  validatorSha256: hash(fs.readFileSync(path.join(pkg, 'scripts/color-browser-recording.mjs'))),
  recordingSha256: hash(recordBytes), lockSha256: hash(fs.readFileSync(lockPath)),
  observations: checks.rows.length, pairedStates: checks.pairs.length,
  displayChanges: checks.pairs.filter(row => row.displayChanged).length,
  errorAddedStates: checks.pairs.filter(row => row.errorAdded).length,
  propertyAddedStates: checks.pairs.filter(row => row.propertyAdded).length,
  tabExits: checks.rows.filter(row => row.action.key === 'Tab').length,
  conditionalPropertyChecks: checks.rows.length, browserRerun: false,
  scope: 'Retained CUA browser record replay. JSX property IR receives independently declared example messages, not observed error DOM or hook state.',
  notProven: ['General React event/hook semantics', 'Screen-reader announcement', 'All colors, layouts, input methods or schedules', 'Whole behavior or human review improvement'],
  wholeBehaviorCasesVerified: 0, humanParticipants: 0, pairs: checks.pairs,
};
fs.writeFileSync(path.join(root, 'build/web-review/color-browser-results.json'), JSON.stringify(result, null, 2) + '\n');
const lines = [
  '# 색상 입력의 실제 브라우저 기록', '',
  '원본 전후 앱에서 같은 조작을 한 기록이다. 이 파일을 생성하는 검증 명령은 브라우저를 다시 실행하지 않는다.', '',
  '| 단계 | 변경 전 입력 표시 | 변경 후 입력 표시 | 양쪽 저장 색 | 오류 안내 추가 |', '|---|---|---|---|---|',
  ...checks.pairs.map(row => `| ${row.phase} | \`${JSON.stringify(row.beforeDisplay)}\` | \`${JSON.stringify(row.afterDisplay)}\` | \`${row.saved}\` | ${row.errorAdded ? '있음' : '없음'} |`), '',
  '같은 색 재입력에서 공백 표시가 달라지는 네 상태, 오류 안내가 추가되는 여섯 상태를 확인했다. 입력이 빈 문자열로 보이는 hash-only 단계에서도 후 버전은 오류를 표시한다. 입력 표시만으로 유효한 색 여부나 저장값을 대신 판단할 수 없다.', '',
  '여섯 Backspace와 세 Tab을 각 버전에서 보냈다. Tab 이후 초점은 원본 팝업의 SPAN으로 이동하고 마지막 유효 색이 다시 표시됐다. 오류 텍스트의 DOM role과 계산 스타일·사각형을 기록했지만 실제 스크린리더를 실행한 것은 아니다.', '',
  '글 모델은 주어진 오류 메시지에서 선택 속성만 계산한다. 콜백·hook의 자동 해석이나 전체 의미 보존·사람 평가가 완료됐다는 결과가 아니다. 전체 행동 0/12, 참가자 0명.', '',
];
fs.writeFileSync(path.join(root, 'build/web-review/color-browser-comparison.md'), lines.join('\n'));
process.stdout.write(JSON.stringify({ ...result, pairs: undefined }) + '\n');
