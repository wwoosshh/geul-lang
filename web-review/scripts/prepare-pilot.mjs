import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import ts from 'typescript';
import { hash } from '../src/typescript.mjs';
import { observe } from '../src/core.mjs';
import { ENGINE_SHA256 } from '../src/fingerprint.mjs';
import { plannedAllocation, CONDITIONS } from '../evaluation/design.mjs';
import { validateRubric, renderRubric } from '../evaluation/scoring.mjs';

const pkg = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'), root = path.dirname(pkg);
const read = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const tasks = read(path.join(pkg, 'evaluation/tasks.json'));
const rubric = validateRubric(read(path.join(pkg, 'evaluation/rubric.json')));
assert.deepEqual(rubric.tasks.map(task => task.id), tasks.tasks.map(task => task.id));
const results = read(path.join(root, 'build/web-review/corpus-results.json'));
const slices = read(path.join(pkg, 'corpus/slices.json'));
const selection = read(path.join(pkg, 'corpus/selection.json'));
const lock = read(path.join(pkg, 'corpus/lock.json'));
assert.equal(tasks.participants, 0);
assert.equal(tasks.tasks.length, 4);
const output = path.join(root, 'build/web-pilot');
const glossary = {
  props: '전달값', ui: '화면설정', customStartingDate: '시작설정', amount: '금액',
  isSearching: '검색중', isFiltered: '필터적용됨', isTransactionsLoading: '거래조회중', isPreviewTransactionsLoading: '미리보기조회중',
  _renderRecording: '녹화UI표시플래그', _localRecordingRunning: '로컬녹화중', _isLiveStreamRunning: '방송중',
};
const safe = value => String(value).replaceAll('|', '\\|').replaceAll('\n', ' ');
const shownValue = value => value?.$value ?? JSON.stringify(value);
function lexicalView(expression) {
  const scanner = ts.createScanner(ts.ScriptTarget.Latest, false, ts.LanguageVariant.Standard, expression);
  let output = '';
  for (let token = scanner.scan(); token !== ts.SyntaxKind.EndOfFileToken; token = scanner.scan()) {
    const text = scanner.getTokenText();
    output += token === ts.SyntaxKind.Identifier ? glossary[text] ?? text : token === ts.SyntaxKind.TrueKeyword ? '참' : token === ts.SyntaxKind.FalseKeyword ? '거짓' : text;
  }
  return output;
}
const materialHashes = {};
function write(relative, text) {
  const file = path.join(output, relative);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, text);
  materialHashes[relative] = hash(text);
}
const answerKey = [];
const viewerTasks = [];
for (const task of tasks.tasks) {
  const result = results.results.find(r => r.id === task.corpusSlice);
  assert.ok(result, task.id);
  assert.ok(result.artifacts.every(a => a.engineSha256 === ENGINE_SHA256), '분석기가 변경됐습니다. test:corpus를 다시 실행하세요.');
  const target = slices.targets.find(s => s.id === task.corpusSlice);
  const original = result.artifacts.map(a => {
    const source = fs.readFileSync(a.source.file, 'utf8');
    assert.equal(hash(source), a.source.sha256);
    const span = a.mode === 'jsx-attribute-slice' ? a.ir.source : a.source;
    return { expression: source.slice(span.start, span.end), line: span.line, file: a.source.file };
  });
  const caseInfo = lock.cases.find(c => c.id === target.case);
  const project = selection.projects[caseInfo.project];
  const common = [
    `# ${task.id}: 검토 과제`, '', task.prompt, '',
    `관찰 범위: ${task.observation}`, '', task.caveat, '',
    '아래 입력 도메인을 가정한다. TypeScript 타입이 런타임 입력의 유효성을 증명했다는 뜻은 아니다.', '',
    '```json', JSON.stringify(target.domains, null, 2), '```', '',
    '변경 전:', '', '```tsx', original[0].expression, '```', '',
    '변경 후:', '', '```tsx', original[1].expression, '```', '',
    '공통 원본 자료:', '',
  ];
  for (const revision of ['before', 'after']) {
    for (const blob of caseInfo.blobs.filter(b => b.revision === revision)) {
      const filename = path.join(root, 'build/web-corpus', target.case, revision, blob.path).replaceAll('\\', '/');
      common.push(`- ${revision}: [${blob.path}](<${filename}>)`);
    }
  }
  common.push('', `원본 프로젝트: [${caseInfo.project}](${project.url.replace(/\.git$/, '')}/commit/${caseInfo.head}). 원본의 라이선스 파일도 위 자료에 포함했다.`, '',
    '공통 용어 대응 (표시용이며, 코드의 의미를 바꾸는 규칙이 아니다):', '',
    ...Object.entries(glossary).map(([name, meaning]) => `- ${name}: ${meaning}`), '',
    '네 조건에서 동일한 원본과 AI 도구를 사용할 수 있다. 이 자료의 정답을 아는지와 확신도도 답변에 기록한다.', '');
  const base = common.join('\n');
  const viewer = { id: task.id, prompt: task.prompt, observation: task.observation, caveat: task.caveat, domains: target.domains,
    original, project: caseInfo.project, commit: caseInfo.head, projectUrl: project.url.replace(/\.git$/, '') + '/commit/' + caseInfo.head,
    sources: caseInfo.blobs.map(blob => ({ file: path.join(root, 'build/web-corpus', target.case, blob.revision, blob.path), label: blob.path, revision: blob.revision, sha256: blob.sha256 })),
    supplements: {}, glossary };
  for (const condition of CONDITIONS) {
    let supplement = '';
    if (condition === 'B') {
      supplement = '\n## 실행 비교에서 얻은 설명\n\n' + result.explanation + '\n';
      viewer.supplements.B = { paragraphs: result.explanation.split('\n') };
    }
    if (condition === 'D') supplement = '\n## 구조를 유지한 한국어 이름 표시\n\n다음은 실행 코드가 아닌 표시용 풀이이다. 연산·분기 구조와 문자열 리터럴은 유지했다.\n\n변경 전:\n\n```text\n' + lexicalView(original[0].expression) + '\n```\n\n변경 후:\n\n```text\n' + lexicalView(original[1].expression) + '\n```\n';
    if (condition === 'C') {
      const names = Object.keys(target.domains);
      const rows = [];
      const table = ['\n## 같은 도메인의 결정표\n', `| ${[...names, '변경 전', '변경 후'].join(' | ')} |`, `| ${[...names, '', ''].map(() => '---').join(' | ')} |`];
      function row(index, inputs) {
        if (index < names.length) { for (const value of target.domains[names[index]]) row(index + 1, { ...inputs, [names[index]]: value }); return; }
        const observed = result.artifacts.map(a => observe(a.ir, inputs));
        rows.push([...names.map(n => shownValue(inputs[n])), ...observed.map(o => o.kind === 'value' ? shownValue(o.value) : o.kind === 'throw' ? o.name : '미확인')]);
        table.push(`| ${[...names.map(n => shownValue(inputs[n])), ...observed.map(o => o.kind === 'value' ? shownValue(o.value) : o.kind === 'throw' ? o.name : '미확인')].map(safe).join(' | ')} |`);
      }
      row(0, {});
      supplement = table.join('\n') + '\n\n선택한 식·입력 범위에 한정된 결과다. 전체 화면·기획 의도·서버 동작은 보증하지 않는다.\n';
      viewer.supplements.C = { names: [...names, '변경 전', '변경 후'], rows };
    }
    write(`materials/${task.id}/${condition}.md`, base + supplement);
  }
  viewer.supplements.D = { before: lexicalView(original[0].expression), after: lexicalView(original[1].expression) };
  viewerTasks.push(viewer);
  answerKey.push({ task: task.id, slice: target.id, changedInputs: result.comparison.changes, unchangedCount: result.comparison.unchanged,
    scoring: ['변경되는 입력 조건', '변경 전후 값', '바뀌지 않는 예외', '이 관찰만으로 화면·서버 동작을 보장하지 않는다는 범위 인식'], status: 'rubric-requires-human-review' });
}
write('viewer-data.json', JSON.stringify({ schema: 'web-review-practice-data-1', status: 'practice-only', participants: 0, engineSha256: ENGINE_SHA256, tasks: viewerTasks }, null, 2) + '\n');
write('private/allocation.json', JSON.stringify(plannedAllocation(tasks.tasks.map(t => t.id)), null, 2) + '\n');
write('private/answer-key.json', JSON.stringify(answerKey, null, 2) + '\n');
write('private/rubric.json', JSON.stringify(rubric, null, 2) + '\n');
write('private/rubric.md', renderRubric(rubric));
write('README.md', '# 웹 검토 파일럿 준비 자료\n\n**참가자 0명, 실험 미실시.** 자동 생성한 과제 자료와 미배정 슬롯이다.\n\nmaterials에는 네 실제 변경의 A/B/C/D 비교 자료가 있다. 진행자는 배정된 파일만 참가자에게 제공해야 한다. private의 정답·배정 파일은 참가자에게 제공하지 않는다.\n\n원본 파일 링크는 현재 머신의 절대 경로다. 다른 환경에서 시행하려면 원본을 복원하고 자료를 다시 생성한 뒤 링크와 표시를 확인해야 한다. viewer-data.json은 별도 정답·배정표를 제외한 예행 검토 화면용 자료다. 사람 예행 검토·최종 채점표·본 실험의 시간 측정 운영 검증은 남아 있다.\n');
const manifest = { status: 'draft-not-issued', participants: 0, tasks: tasks.tasks.length, conditions: CONDITIONS,
  engineSha256: ENGINE_SHA256, generatorSha256: hash(fs.readFileSync(fileURLToPath(import.meta.url))),
  tasksSha256: hash(fs.readFileSync(path.join(pkg, 'evaluation/tasks.json'))), materialHashes };
manifest.rubricSha256 = hash(fs.readFileSync(path.join(pkg, 'evaluation/rubric.json')));
manifest.scoringHelperSha256 = hash(fs.readFileSync(path.join(pkg, 'evaluation/scoring.mjs')));
fs.writeFileSync(path.join(output, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
process.stdout.write(JSON.stringify({ ...manifest, materialHashes: Object.keys(materialHashes).length }, null, 2) + '\n');
