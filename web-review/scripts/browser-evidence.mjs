// This verifies a recorded browser experiment; it never claims to rerun a browser.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { hash } from '../src/typescript.mjs';
import { liftJsxFlow } from '../src/jsx-flow.mjs';
import { observe, encode } from '../src/core.mjs';
import { ENGINE_SHA256 } from '../src/fingerprint.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const packageRoot = path.join(root, 'web-review');
const mode = process.argv[2] ?? 'verify';
assert.ok(['freeze', 'verify'].includes(mode));
const recordPath = path.join(packageRoot, 'evaluation/browser-evidence/2026-09-09-scroll.json');
const lockPath = recordPath.replace(/\.json$/, '.lock.json');
const recordBytes = fs.readFileSync(recordPath), recording = JSON.parse(recordBytes);
const read = filename => JSON.parse(fs.readFileSync(filename, 'utf8'));
const corpusBytes = fs.readFileSync(path.join(packageRoot, 'corpus/lock.json'));
const corpus = JSON.parse(corpusBytes);
const caseInfo = corpus.cases.find(row => row.id === 'excalidraw-scroll-back-view-mode');
const target = read(path.join(packageRoot, 'corpus/flows.json')).targets.find(row => row.case === caseInfo.id);
const repo = path.join(root, 'build/research/excalidraw');
function git(...args) {
  const result = spawnSync('git', ['-C', repo, '-c', `safe.directory=${repo.replaceAll('\\', '/')}`, ...args], {
    maxBuffer: 16 * 1024 * 1024, timeout: 10_000,
  });
  assert.equal(result.status, 0, result.stderr?.toString() || result.error?.message);
  return result.stdout;
}
assert.equal(recording.schema, 'geul-browser-observations-1');
assert.deepEqual(recording.commits, { before: caseInfo.parent, after: caseInfo.head });
const fixtureNames = ['browser.html', 'browser.tsx', 'browser.config.mts'];
const sourcePaths = ['packages/excalidraw/components/LayerUI.tsx', target.path,
  'packages/excalidraw/css/styles.scss', 'vitest.config.mts', 'yarn.lock', 'package.json'];
if (mode === 'freeze') {
  assert.ok(!fs.existsSync(lockPath), 'Existing recording provenance must not be overwritten.');
  const lock = {
    schema: 'geul-browser-recording-lock-1', recordedOn: '2026-09-09',
    browser: 'Codex in-app browser; viewport 1280 x 1000; not a mobile device emulation',
    collection: 'Observed through CUA UI actions and read-only DOM queries; JSON transcribed from the tool output. Hashes bind the retained evidence, not independent authentication of the recording.',
    case: caseInfo.id, recordingSha256: hash(recordBytes), corpusLockSha256: hash(corpusBytes),
    fixtures: fixtureNames.map(name => ({ path: `upstream-tests/${name}`, sha256: hash(fs.readFileSync(path.join(packageRoot, 'upstream-tests', name))) })),
    revisions: Object.entries(recording.commits).map(([revision, commit]) => ({ revision, commit,
      tree: git('rev-parse', `${commit}^{tree}`).toString().trim(),
      sources: sourcePaths.map(relative => ({ path: relative,
        gitBlob: git('rev-parse', `${commit}:${relative}`).toString().trim(), sha256: hash(git('show', `${commit}:${relative}`)) })),
    })),
    installedDependencyBasis: 'Same Yarn 1.22.22 frozen install as the upstream jsdom experiment; install scripts ignored. Vite 5.0.12, React/React DOM 19.0.0; package files are not all independently hashed.',
    limitations: [
      'A host API supplies scrollX/scrollY = -10000; this browser experiment does not establish user-gesture reachability of that starting state.',
      'The original button receives a browser click. Original CSS, fonts and ResizeObserver run; no jsdom setup or component helper mocks.',
      'Center hit-testing and rectangle measurements concern this viewport and this sample; other positions, styles, devices, schedules and flows are untested.',
      'The harness uses source aliases from original vitest.config.mts with Vite/React development rendering, not the production excalidraw.com entrypoint or bundle.',
      'Screenshots were inspected in the CUA tool; the JSON retains DOM measurements, not screenshot files.',
    ],
  };
  fs.writeFileSync(lockPath, JSON.stringify(lock, null, 2) + '\n', { flag: 'wx' });
}
const lockBytes = fs.readFileSync(lockPath), lock = JSON.parse(lockBytes);
assert.equal(lock.schema, 'geul-browser-recording-lock-1');
assert.equal(lock.recordingSha256, hash(recordBytes));
assert.equal(lock.corpusLockSha256, hash(corpusBytes));
for (const fixture of lock.fixtures) assert.equal(hash(fs.readFileSync(path.join(packageRoot, fixture.path))), fixture.sha256);
const artifacts = {};
for (const revision of lock.revisions) {
  assert.equal(revision.commit, recording.commits[revision.revision]);
  assert.equal(git('rev-parse', `${revision.commit}^{tree}`).toString().trim(), revision.tree);
  for (const source of revision.sources) {
    const data = git('show', `${revision.commit}:${source.path}`);
    assert.equal(hash(data), source.sha256);
    assert.equal(git('rev-parse', `${revision.commit}:${source.path}`).toString().trim(), source.gitBlob);
  }
  const source = git('show', `${revision.commit}:${target.path}`).toString('utf8');
  artifacts[revision.revision] = liftJsxFlow(source, { ...target.selector,
    ...(revision.revision === 'after' ? { prefixLine: target.afterPrefixLine } : {}),
    filename: path.join(root, 'build/web-corpus', caseInfo.id, revision.revision, target.path) });
}
assert.deepEqual(recording.columns, ['revision', 'ui', 'viewModeEnabled', 'phase', 'buttonCount', 'scrolledOutside', 'scrollX', 'scrollY', 'button']);
assert.deepEqual(recording.common, { mobile: true, openMenu: null, openSidebar: null });
assert.deepEqual(recording.viewport, { width: 1280, height: 1000 });
assert.deepEqual(recording.appSize, { width: 390, height: 650 });
assert.equal(recording.observations.length, 18);
const rows = recording.observations.map(values => {
  assert.equal(values.length, recording.columns.length);
  const row = Object.fromEntries(recording.columns.map((key, index) => [key, values[index]]));
  assert.ok(['before', 'after'].includes(row.revision));
  assert.ok(['default', 'scroll-only', 'disabled'].includes(row.ui));
  assert.ok(['host-api-away', 'native-button-click'].includes(row.phase));
  assert.equal(typeof row.viewModeEnabled, 'boolean');
  assert.equal(typeof row.scrolledOutside, 'boolean');
  assert.ok([0, 1].includes(row.buttonCount));
  const inputs = { appState: encode({ viewModeEnabled: row.viewModeEnabled,
    scrolledOutside: row.scrolledOutside, openMenu: null, openSidebar: null }),
    defaultUIEnabled: row.ui === 'default', scrollBackToContentUIEnabled: row.ui !== 'disabled' };
  assert.deepEqual(observe(artifacts[row.revision].ir, inputs), { kind: 'value', value: row.buttonCount === 1 });
  if (row.buttonCount) {
    const { rect } = row.button;
    assert.equal(row.button.centerHit, true);
    assert.equal(row.button.display, 'block');
    assert.equal(row.button.visibility, 'visible');
    assert.equal(row.button.opacity, '1');
    assert.ok(rect.width > 0 && rect.height > 0 && rect.x >= 0 && rect.y >= 0);
    assert.ok(rect.x + rect.width <= recording.viewport.width && rect.y + rect.height <= recording.viewport.height);
  } else assert.equal(row.button, null);
  if (row.phase === 'native-button-click') {
    assert.equal(row.buttonCount, 0);
    assert.equal(row.scrolledOutside, false);
    assert.deepEqual([row.scrollX, row.scrollY], [25, 100]);
  } else {
    assert.equal(row.scrolledOutside, true);
    assert.deepEqual([row.scrollX, row.scrollY], [-10000, -10000]);
  }
  return row;
});
assert.equal(new Set(rows.map(row => `${row.revision}/${row.ui}/${row.viewModeEnabled}/${row.phase}`)).size, rows.length);
const pairs = [];
for (const ui of ['default', 'scroll-only', 'disabled']) for (const view of [false, true]) {
  const before = rows.find(row => row.revision === 'before' && row.ui === ui && row.viewModeEnabled === view && row.phase === 'host-api-away');
  const after = rows.find(row => row.revision === 'after' && row.ui === ui && row.viewModeEnabled === view && row.phase === 'host-api-away');
  assert.ok(before && after);
  for (const row of [before, after]) if (row.buttonCount) assert.ok(rows.some(other => other.revision === row.revision && other.ui === ui && other.viewModeEnabled === view && other.phase === 'native-button-click'));
  pairs.push({ ui, viewModeEnabled: view, beforeButtonCount: before.buttonCount, afterButtonCount: after.buttonCount,
    beforeY: before.button?.rect.y ?? null, afterY: after.button?.rect.y ?? null,
    positionChangedWithSamePresence: Boolean(before.button && after.button && before.button.rect.y !== after.button.rect.y) });
}
const presenceChanges = pairs.filter(row => row.beforeButtonCount !== row.afterButtonCount);
const unmodeledLayoutChanges = pairs.filter(row => row.positionChangedWithSamePresence);
assert.equal(presenceChanges.length, 2);
assert.equal(unmodeledLayoutChanges.length, 1);
const result = { schema: 'web-browser-recording-check-1', engineSha256: ENGINE_SHA256,
  recordingSha256: hash(recordBytes), provenanceSha256: hash(lockBytes),
  operation: 'Verify retained browser observations against current model; browser was not rerun by this command.',
  recordedStatesChecked: rows.length, recordedClicksChecked: rows.filter(row => row.phase === 'native-button-click').length,
  pairs, unmodeledLayoutChanges, wholeBehaviorCasesVerified: 0, humanParticipants: 0, limitations: lock.limitations };
const output = path.join(root, 'build/web-review');
fs.mkdirSync(output, { recursive: true });
fs.writeFileSync(path.join(output, 'browser-recording-results.json'), JSON.stringify(result, null, 2) + '\n');
const labels = { default: '전체 기본 UI', 'scroll-only': '복귀 버튼만', disabled: '모두 끔' };
const table = pairs.map(row => `| ${labels[row.ui]} | ${row.viewModeEnabled ? '켜짐' : '꺼짐'} | ${row.beforeButtonCount} | ${row.afterButtonCount} | ${row.beforeY ?? '없음'} | ${row.afterY ?? '없음'} |`).join('\n');
fs.writeFileSync(path.join(output, 'browser-comparison.md'), `# 원본 브라우저 관찰과 글 모델\n\n실제 브라우저 기록 18개를 현재 객체 전달 모델과 대조했다. 이 명령은 브라우저를 다시 실행하지 않는다. 기록된 클릭은 6회다.\n\n브라우저 1280 × 1000, 앱 390 × 650. 호스트 API로 콘텐츠 밖 상태를 만들었고 메뉴·사이드바는 닫혀 있다.\n\n| UI | 보기 모드 | 이전 버튼 수 | 이후 버튼 수 | 이전 y(px) | 이후 y(px) |\n|---|---|---:|---:|---:|---:|\n${table}\n\n보기 모드의 두 UI 조건에서는 버튼이 생긴다. 생성된 버튼의 중앙 hit-test와 실제 클릭 후 콘텐츠 복귀를 이 기록에서 확인했다.\n\n복귀 버튼만 켠 편집 모드에서는 전후 모두 버튼이 있지만 y가 659.5에서 739.5로 80px 이동했다. **현재 객체 전달 모델은 이 배치 변화를 설명하지 않는다.** 전달 여부의 동일성을 화면 전체의 동일성으로 확대할 수 없다. 이 배치 결과는 특정 브라우저 실행 관찰이며 CSS의 일반적 의미를 증명한 결과가 아니다.\n\n전체 행동 검증 0/12, 사람 참가자 0명.\n\n기록: [관찰 데이터](${recordPath.replaceAll('\\', '/')}) · [원본과 실행 조건](${lockPath.replaceAll('\\', '/')})\n`);
process.stdout.write(JSON.stringify({ recordedStatesChecked: rows.length, recordedClicksChecked: result.recordedClicksChecked,
  presenceChanges: presenceChanges.length, unmodeledLayoutChanges: unmodeledLayoutChanges.length, browserRerun: false }) + '\n');
