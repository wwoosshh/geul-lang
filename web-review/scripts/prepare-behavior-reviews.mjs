import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
import { ENGINE_SHA256 } from '../src/fingerprint.mjs';
import { hash } from '../src/typescript.mjs';
import { compare, observe, decode, encode } from '../src/core.mjs';
import { summarizeChangeConditions } from '../src/change-rules.mjs';
import { describeChangeSummary, describeBooleanChange } from '../src/presentation.mjs';
import { buildScrollBehavior, verifyScrollBehavior, probeScrollChanges } from './scroll-behavior.mjs';

// Two behavior views of existing models: one source-derived finite view and
// one curated view. Neither is general inference of arbitrary UI behavior.
const pkg = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const root = path.dirname(pkg), build = path.join(root, 'build/web-review');
const output = path.join(root, 'build/web-behaviors');
const read = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const link = (title, file) => `[${title}](<${file.replaceAll('\\', '/')}>)`;
const evidenceHashes = {}, materialHashes = {};
let cliReplays = 0, viewObservationChecks = 0, additionalNativeExecutions = 0;
function evidence(relative) {
  const file = path.join(build, relative), bytes = fs.readFileSync(file);
  evidenceHashes[relative] = hash(bytes); return JSON.parse(bytes);
}
function write(relative, text) {
  const file = path.join(output, relative); fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, text); materialHashes[relative] = hash(text); return file;
}
function checkedArtifact(relative, command = 'read') {
  const file = path.join(build, relative);
  const replay = spawnSync(process.execPath, [path.join(pkg, 'src/cli.mjs'), command, '--file', file, '--json'],
    { encoding: 'utf8', timeout: 20000, maxBuffer: 16 * 1024 * 1024 });
  assert.equal(replay.status, 0, replay.stderr); cliReplays++;
  const artifact = evidence(relative); assert.equal(artifact.engineSha256, ENGINE_SHA256); return artifact;
}
const definitions = [
  { id: 'excalidraw-scroll-back-view-mode', title: '돌아가기 버튼: 부모 설정에서 자식 전달까지',
    automatic: true,
    scope: 'LayerUI의 휴대폰 경로와 속성 전달을 MobileMenu의 버튼 생성·자식 자리 전달에 결합한 모델. 실제 표시·클릭·배치는 별도 실행 근거와 구분합니다.',
    questions: ['변경 후 버튼 전달에 필요한 조건을 설명하세요. 기본 UI를 끄면 이 조건이 달라지나요?', '보기 모드와 편집 모드에서 각각 무엇이 달라지나요? 메뉴를 열면 어떻게 되나요?', '버튼 존재가 같으면 위치와 클릭 후 동작도 같다고 말할 수 있나요? 근거와 미확인을 구분하세요.'],
    facets: [{ title: '버튼 전달 조건', directory: 'flows/excalidraw-mobile-scroll-flow', before: 'before/artifact.json', after: 'after/artifact.json' }],
    connections: ['LayerUI의 JSX 조건 → 선택 속성 식 → MobileMenu 매개변수 → 버튼 전달: 원본에서 재추출해 결합', '중간 속성은 별도 자유 입력으로 받지 않음. 입력 경계는 부모 JSX 식의 UI 설정·상태·화면 형식 스냅샷', '실제 버튼 수·클릭·배치: 별도로 수행한 원본 앱·브라우저 관찰'],
    related: ['prop-projects/excalidraw-scroll-back-view-mode/after/prop-bindings.md', 'browser-comparison.md', 'upstream-results.json'],
    unknown: ['UI 설정이 만들어지는 호출과 모든 상태의 도달 가능성을 통합 해석하지 않음', '휴대폰 MobileMenu 경로만 대상으로 함. 데스크톱의 다른 돌아가기 버튼 경로는 이 결합 모델 밖임', '생략한 선행 helper·JSX 생성이 정상 완료하고 전달한 값을 바꾸지 않는다는 실행 계약이 필요함', '브라우저 기록에는 편집 모드의 한 UI 설정에서 버튼 y 위치가 80px 달라진 관찰이 있음. 현재 IR은 CSS 배치를 설명하지 않음', '클릭 후 복귀는 고정된 실행 경로의 근거이며 모든 장면·이벤트 순서의 보장이 아님'] },
  { id: 'actual-mobile-report-filter', title: '모바일 필터: 거래 목록과 로딩 출처가 함께 바뀌는 조건',
    headline: '검색하지 않고 필터를 적용한 경우, 거래 목록은 미리보기 결합 대신 조회 목록을 선택하고 로딩 값도 거래 조회 쪽을 따릅니다. 실제 값이 같을 수 있는 예외가 있습니다.',
    scope: '동일한 이름의 상태 스냅샷을 전제로 한 두 계산 관점. route→비동기 조회→렌더링을 하나의 실행으로 재구성한 결과는 아닙니다.',
    questions: ['검색을 끄고 필터를 켰을 때 거래 목록과 로딩 출처가 각각 어떻게 바뀌나요?', '같은 조건에서도 관찰 결과가 바뀌지 않을 수 있는 예외를 목록과 로딩에서 하나씩 제시하세요.', '필터 입력부터 화면 갱신까지 검증됐나요? route 전달·오래된 응답·자식 렌더링 중 남아 있는 확인을 설명하세요.'],
    conditions: ['`isSearching`이 거짓이고 `isFiltered`가 참인 범위가 변경의 중심', '변경 전 목록: 미리보기 뒤에 자식 거래를 제외한 조회 목록을 결합', '변경 후 목록: 조회한 `transactions`를 그대로 선택', '변경 전 로딩: `isPreviewTransactionsLoading`. 변경 후: `isTransactionsLoading`', '이미 검색 중이면 두 버전 모두 조회 목록·거래 조회 로딩을 선택. 검색과 필터가 모두 꺼져 있으면 기존 경로 유지'],
    facets: [
      { title: '거래 목록 선택', directory: 'arrays/actual-filter-transaction-selection', before: 'before.json', after: 'after.json',
        expected: (i, revision) => ({ transactionsToDisplay: !i.isSearching && (revision === 'before' || !i.isFiltered)
          ? i.previewTransactions.concat(i.transactions.filter(t => !t.is_child)) : i.transactions }) },
      { title: '자식 TransactionList에 전달하는 로딩 값', directory: 'prop-equations/actual-filter-loading-delivery', before: 'before/artifact.json', after: 'after/artifact.json',
        expected: (i, revision) => (i.isSearching || (revision === 'after' && i.isFiltered)) ? i.isTransactionsLoading : i.isPreviewTransactionsLoading },
    ],
    connections: ['AccountsPage의 route 필터 → AllAccountTransactions의 상태: 원본을 찾아보는 경로, 실행 결합 미완료', '목록 선택 → TransactionListWithBalances 매개변수·사용처: 계산 결과와 원본 참조 연결', '부모 isLoading → 자식 TransactionList.isLoading: 명시적 속성 전달 가정 아래 결합한 계산'],
    related: ['output-props/actual-transaction-selection-destinations/after-reading.md', 'prop-projects/actual-mobile-report-filter/after/prop-bindings.md', 'prop-equations/actual-filter-pullable-delivery/unsupported.md'],
    unknown: ['필터 설정의 유효성·비동기 쿼리 구성·stale 응답 처리를 실행 모델로 연결하지 않음', '조회 목록과 미리보기 결합 결과가 같으면 선택 경로가 달라도 목록 관찰값은 같음', '두 로딩 값이 같으면 출처가 달라도 로딩 관찰값은 같음', 'PullToRefresh 경로는 async 콜백 캡처 때문에 미지원. 실제 목록 렌더링·이벤트 실행도 미확인'] },
];
const lock = read(path.join(pkg, 'corpus/lock.json'));
const glossary = { isSearching: '검색중', isFiltered: '필터적용', isTransactionsLoading: '거래조회중', isPreviewTransactionsLoading: '미리보기조회중',
  scrollBackToContentUIEnabled: '복귀UI활성', defaultUIEnabled: '기본UI활성', viewModeEnabled: '보기모드', scrolledOutside: '콘텐츠화면밖', openMenu: '열린메뉴', openSidebar: '열린사이드바' };
function lexical(source) {
  const scanner = ts.createScanner(ts.ScriptTarget.Latest, false, ts.LanguageVariant.JSX, source); let result = '';
  for (let token = scanner.scan(); token !== ts.SyntaxKind.EndOfFileToken; token = scanner.scan()) result += token === ts.SyntaxKind.Identifier ? glossary[scanner.getTokenText()] ?? scanner.getTokenText() : scanner.getTokenText();
  return result;
}
const cases = [];
function automaticScroll(definition, domains, artifacts) {
  const projects = {}, outputs = {}, checks = {};
  const parentDomains = { ...domains, editorInterface: [encode({ formFactor: 'phone' }), encode({ formFactor: 'desktop' })] };
  function sourceLink(revision, source, probe) {
    const relative = source.file.slice('/project/'.length);
    const file = probe ? path.join(output, definition.id, 'probes', probe, 'files', relative)
      : path.join(build, 'prop-projects', definition.id, revision, relative);
    return link(`${path.basename(relative)}:${source.line}`, `${file}:${source.line}`);
  }
  for (const revision of ['before', 'after']) {
    const directory = path.join(build, 'prop-projects', definition.id, revision);
    const index = checkedArtifact(`prop-projects/${definition.id}/${revision}/prop-bindings.json`, 'explain');
    const tracked = relative => {
      const file = path.join(directory, relative), text = fs.readFileSync(file, 'utf8');
      evidenceHashes[path.relative(build, file)] = hash(text); return text;
    };
    const manifest = JSON.parse(tracked('project.json'));
    assert.equal(hash(fs.readFileSync(path.join(directory, 'project.json'))), index.manifestSha256);
    projects[revision] = { files: Object.fromEntries(manifest.files.map(file => [file, tracked(file)])),
      entry: manifest.entry, tag: manifest.tag, properties: manifest.properties,
      context: { configPath: manifest.context.configPath, inventory: JSON.parse(tracked(manifest.context.inventory)),
        metadata: Object.fromEntries(manifest.context.metadata.map(file => [file, tracked(file)])) } };
    for (const [file, source] of Object.entries(projects[revision].files)) {
      const blob = lock.cases.find(row => row.id === definition.id).blobs.find(blob => blob.revision === revision && blob.path === file);
      assert.ok(blob, '결합 원본이 고정 사례에 있어야 한다.'); assert.equal(hash(source), blob.sha256);
      assert.equal(hash(source), index.sources.find(row => row.file === '/project/' + file).sha256);
    }
    const sink = { ...artifacts[revision].target, ...(artifacts[revision].prefix ? { prefixLine: artifacts[revision].prefix.source.line } : {}) };
    outputs[revision] = buildScrollBehavior(projects[revision], sink, parentDomains, source => sourceLink(revision, source));
    checks[revision] = verifyScrollBehavior(projects[revision], outputs[revision], parentDomains);
    additionalNativeExecutions += checks[revision].nativeExecutions;
    write(`${definition.id}/${revision}-model.json`, JSON.stringify(outputs[revision], null, 2) + '\n');
  }
  const sink = { ...artifacts.after.target, prefixLine: artifacts.after.prefix.source.line };
  const probes = probeScrollChanges(projects.after, sink, parentDomains, (source, probe) => sourceLink('after', source, probe), outputs.after);
  for (const probe of probes) {
    additionalNativeExecutions += probe.nativeExecutions;
    for (const [file, source] of Object.entries(probe.files)) write(`${definition.id}/probes/${probe.id}/files/${file}`, source);
    write(`${definition.id}/probes/${probe.id}/review.md`, '# 합성 원본 수정 실험\n\n실제 PR 변경이 아닌 메모리상의 원본 수정입니다. 고정 사례 원본은 유지됩니다.\n\n' + probe.text + '\n');
    write(`${definition.id}/probes/${probe.id}/result.json`, JSON.stringify(probe, null, 2) + '\n');
  }
  const comparison = { ...compare(outputs.before.model.ir, outputs.after.model.ir, parentDomains), domains: parentDomains };
  const upstream = evidence('upstream-results.json'), observedRows = [];
  assert.equal(upstream.case, definition.id);
  assert.equal(upstream.corpusLockSha256, hash(fs.readFileSync(path.join(pkg, 'corpus/lock.json'))));
  assert.equal(upstream.fixtureSha256, hash(fs.readFileSync(path.join(pkg, 'upstream-tests/excalidraw-scroll.test.tsx'))));
  assert.equal(upstream.runnerSha256, hash(fs.readFileSync(path.join(pkg, 'scripts/check-upstream.mjs'))));
  for (const revision of ['before', 'after']) {
    const recorded = upstream.results.find(row => row.revision === revision);
    for (const source of outputs[revision].model.sources) assert.equal(recorded.sourceEvidence.find(row => '/project/' + row.path === source.file)?.sha256, source.sha256);
    const captured = evidence(path.relative(build, path.join(upstream.output, `${revision}-observations.json`)));
    assert.equal(captured.schema, 'geul-upstream-observations-1'); assert.equal(captured.revision, revision);
    assert.equal(captured.observations.length, recorded.modelChecks);
    for (const row of captured.observations) {
      assert.equal(row.formFactor, 'phone'); assert.ok([0, 1].includes(row.buttonCount));
      const inputs = { ...row.input, editorInterface: encode({ formFactor: row.formFactor }) };
      const observation = observe(outputs[revision].model.ir, inputs);
      assert.deepEqual(observation, { kind: 'value', value: row.buttonCount === 1 });
      observedRows.push({ revision, id: row.id, phase: row.phase, inputs, buttonCount: row.buttonCount, observation });
    }
  }
  const result = { comparison, checks, probes: probes.map(({ id, nativeExecutions, comparison }) => ({ id, nativeExecutions, changed: comparison.changes.length })),
    originalAppObservationReplay: { checks: observedRows.length, originalRun: upstream.output, recordedEngineSha256: upstream.engineSha256,
      newAppExecutionsByThisProducer: 0, rows: observedRows } };
  write(`${definition.id}/automatic-evidence.json`, JSON.stringify(result, null, 2) + '\n');
  return { ...result, headline: describeBooleanChange(comparison),
    conditions: '### 변경 후\n\n' + outputs.after.text + '\n\n<details>\n<summary>변경 전 전달 조건</summary>\n\n' + outputs.before.text + '\n\n</details>',
    probeLinks: probes.map(probe => '- ' + link(probe.id, path.join(output, definition.id, 'probes', probe.id, 'review.md'))).join('\n') };
}
for (const definition of definitions) {
  const pinned = lock.cases.find(row => row.id === definition.id); assert.ok(pinned);
  const comparisons = [], details = [], sourceLinks = []; let automatic;
  for (const facet of definition.facets) {
    const before = checkedArtifact(`${facet.directory}/${facet.before}`), after = checkedArtifact(`${facet.directory}/${facet.after}`);
    const domains = evidence(`${facet.directory}/domains.json`), recorded = evidence(`${facet.directory}/comparison.json`);
    const comparison = compare(before.ir, after.ir, domains);
    for (const key of ['checked', 'unchanged', 'changes', 'unknown']) assert.deepEqual(comparison[key], recorded[key]);
    // Check the curated condition wording's explicit predicate against every
    // observation. This validates this finite view, not a universal formula.
    const names = Object.keys(domains);
    function check(index, inputs) {
      if (index < names.length) { for (const value of domains[names[index]]) check(index + 1, { ...inputs, [names[index]]: value }); return; }
      const values = Object.fromEntries(Object.entries(inputs).map(([key, value]) => [key, decode(value, 0, { arrays: true })]));
      for (const [revision, artifact] of [['before', before], ['after', after]]) {
        const observation = observe(artifact.ir, inputs); assert.equal(observation.kind, 'value');
        assert.deepEqual(observation.value, encode(facet.expected(values, revision), 0, undefined, { arrays: true })); viewObservationChecks++;
      }
    }
    if (facet.expected) check(0, {});
    if (definition.automatic) {
      automatic = automaticScroll(definition, domains, { before, after });
      details.push('### 부모와 자식을 결합한 입력 범위\n\n' + describeBooleanChange(automatic.comparison).replace(/^# 변경 범위\n\n/, '')
        + '\n\n화면 형식 phone·desktop과 기존 UI 설정·상태를 조합했습니다. '
        + link('전체 입력·원본 실행 대조·합성 수정 실험', path.join(output, definition.id, 'automatic-evidence.json'))
        + '\n\n' + ['before', 'after'].map(revision => link(revision + ' 결합 모델·조건 목록', path.join(output, definition.id, `${revision}-model.json`))).join(', '));
    }
    const summary = { ...comparison, domains, changeConditions: summarizeChangeConditions(comparison, domains) };
    comparisons.push({ title: facet.title, checked: comparison.checked, changed: comparison.changes.length, unchanged: comparison.unchanged,
      unknown: comparison.unknown.length, changeConditions: summary.changeConditions });
    details.push(`### ${facet.title}\n\n${describeChangeSummary(summary).replace(/^# 변경 범위\n\n/, '')}\n\n${link('전체 비교', path.join(build, facet.directory, 'comparison.md'))}`);
    for (const [revision, artifact] of [['before', before], ['after', after]]) {
      const source = artifact.source ?? artifact.child.source;
      const file = source.file.startsWith('/project/') ? path.resolve(path.dirname(artifact.manifest), source.file.slice('/project/'.length)) : source.file;
      assert.ok(fs.existsSync(file));
      const line = source.line ?? artifact.target.startLine;
      assert.ok(Number.isSafeInteger(line) && line > 0);
      sourceLinks.push(link(`${facet.title} · ${revision === 'before' ? '변경 전' : '변경 후'} 원본 ${line}행`, `${file}:${line}`));
    }
  }
  const originals = [], lexicalLinks = [];
  for (const blob of pinned.blobs) {
    const file = path.join(root, 'build/web-corpus', definition.id, blob.revision, blob.path);
    const source = fs.readFileSync(file, 'utf8'); assert.equal(hash(source), blob.sha256);
    evidenceHashes[path.relative(build, file)] = blob.sha256;
    originals.push(link(`${blob.revision} · ${blob.path}`, file));
    const relative = `${definition.id}/lexical/${blob.revision}/${blob.path}.md`;
    const fence = '`'.repeat(Math.max(3, ...[...source.matchAll(/`+/g)].map(row => row[0].length + 1)));
    const translated = /\.tsx?$/.test(blob.path) ? lexical(source) : source;
    const translatedFile = write(relative, `# ${blob.path}\n\n${link('같은 원본', file)}\n\n원본 전체의 일부 식별자만 치환한 대조 자료. 실행 가능한 번역 코드가 아닙니다.\n\n${fence}text\n${translated}\n${fence}\n`);
    lexicalLinks.push(link(`${blob.revision} · ${blob.path}`, translatedFile));
  }
  for (const relative of definition.related) {
    const file = path.join(build, relative); assert.ok(fs.existsSync(file)); evidenceHashes[relative] = hash(fs.readFileSync(file));
  }
  const common = `# 공통 과제와 근거\n\n${definition.questions.map((q, i) => `${i + 1}. ${q}`).join('\n')}\n\n두 조건 모두 원본·입력 범위·상세 비교·미확인 목록에 같은 접근을 제공합니다. 아래 상세에는 정답 단서가 있으므로 감추는 시점을 조건마다 다르게 정하지 않습니다.\n\n## 관찰 범위\n\n${definition.scope}\n\n${details.join('\n\n')}\n\n## 미확인과 예외\n\n${definition.unknown.map(x => '- ' + x).join('\n')}\n\n## 관련 근거\n\n${definition.related.map(file => '- ' + link(file, path.join(build, file))).join('\n')}\n\n## 전체 원본\n\n${originals.map(x => '- ' + x).join('\n')}\n`;
  const commonFile = write(`${definition.id}/common.md`, common);
  const expressionStatus = automatic ? '조건 목록·변경 범위는 부모와 자식 원본에서 결합한 모델의 지정 입력 결과로 생성했습니다. 제목·관찰 경계·미확인 설명은 사례별로 작성했습니다. 임의 프로젝트의 행동 자동 재구성이 아닙니다.' : '사람이 정한 행동 제목·조건 이름을 기존 모델의 모든 지정 입력에 대조한 사례별 초안입니다.';
  const body = `${automatic?.headline ?? '# 변경 범위\n\n' + definition.headline}\n\n## ${definition.title}\n\n${definition.scope}\n\n## 조건을 따라 읽기\n\n${automatic?.conditions ?? definition.conditions.map(x => '- ' + x).join('\n')}\n\n## 연결된 경로\n\n${definition.connections.map(x => '- ' + x).join('\n')}\n\n## 결과가 같을 수 있는 경우와 미확인\n\n${definition.unknown.map(x => '- ' + x).join('\n')}\n\n${link('공통 과제·입력 범위·전체 원본', commonFile)}\n\n<details>\n<summary>입력별 변경 범위와 원본 분석</summary>\n\n${details.join('\n\n')}\n\n${sourceLinks.map(x => '- ' + x).join('\n')}\n\n${automatic ? '### 원본 수정에 따른 자동 갱신 실험\n\n' + automatic.probeLinks : ''}\n\n</details>\n\n표현 상태: ${expressionStatus}\n`;
  const file = write(`${definition.id}/B.md`, body);
  write(`${definition.id}/D.md`, `# 식별자 치환 대조 자료\n\n${link('동일한 공통 과제·근거·원본', commonFile)}\n\n${lexicalLinks.map(x => '- ' + x).join('\n')}\n`);
  cases.push({ id: definition.id, title: definition.title, parent: pinned.parent, head: pinned.head, document: file,
    status: automatic ? 'source-derived-finite-behavior-draft' : 'curated-behavior-review-draft', comparisons,
    ...(automatic ? { automatic: { comparison: automatic.comparison, checks: automatic.checks, probes: automatic.probes } } : {}), wholeBehaviorVerified: false });
}
const report = { schema: 'web-behavior-materials-1', engineSha256: ENGINE_SHA256, producerSha256: hash(fs.readFileSync(fileURLToPath(import.meta.url))),
  corpusLockSha256: hash(fs.readFileSync(path.join(pkg, 'corpus/lock.json'))), behaviorReviewDocuments: cases.length,
  wholeBehaviorCasesVerified: 0, humanParticipants: 0, cliReplays, viewObservationChecks, additionalNativeExecutions,
  helperSha256: hash(fs.readFileSync(new URL('./scroll-behavior.mjs', import.meta.url))),
  cases, evidenceHashes, materialHashes };
write('README.md', '# 행동 단위 검토 초안\n\n' + cases.map(row => '- ' + link(row.title, row.document)).join('\n')
  + '\n\n2개 검토 문서를 준비했습니다. 전체 행동 검증 완료는 0/12, 실제 참가자는 0명입니다. 기존 짧은 식 과제와 별도의 표현 예행용 자료입니다.\n');
fs.writeFileSync(path.join(output, 'manifest.json'), JSON.stringify(report, null, 2) + '\n');
process.stdout.write(JSON.stringify({ engineSha256: ENGINE_SHA256, behaviorReviewDocuments: cases.length, cliReplays, viewObservationChecks, wholeBehaviorCasesVerified: 0, output }) + '\n');
