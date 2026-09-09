import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { hash } from '../src/typescript.mjs';
import { ENGINE_SHA256 } from '../src/fingerprint.mjs';
import { liftConstBindings } from '../src/const-bindings.mjs';
import { liftJsxProperty } from '../src/jsx-property.mjs';
import { inspectUnifiedPatch, intersectChangedLines } from './diff-spans.mjs';
import { caseChangeScope, describeChangeScope } from './inventory-scope.mjs';

const pkg = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'), root = path.dirname(pkg);
const build = path.join(root, 'build/web-review');
const read = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const corpusBytes = fs.readFileSync(path.join(pkg, 'corpus/lock.json')), corpus = JSON.parse(corpusBytes);
const inventoryBytes = fs.readFileSync(path.join(pkg, 'corpus/change-inventory.lock.json'));
const inventory = JSON.parse(inventoryBytes);
assert.equal(corpus.selectionSha256, hash(fs.readFileSync(path.join(pkg, 'corpus/selection.json'))));
assert.equal(inventory.corpusLockSha256, hash(corpusBytes));
const types = [
  { kind: 'const', selection: 'array-slices.json', summary: 'array-results.json', producer: 'check-arrays.mjs', directory: 'arrays' },
  { kind: 'property', selection: 'jsx-properties.json', summary: 'jsx-property-results.json', producer: 'check-jsx-properties.mjs', directory: 'jsx-properties' },
];
const results = [];
const output = path.join(build, 'slice-source-scope'); fs.mkdirSync(output, { recursive: true });
function git(project, ...args) {
  const repo = path.join(root, 'build/research', project);
  const result = spawnSync('git', ['-C', repo, '-c', `safe.directory=${repo.replaceAll('\\', '/')}`, ...args], { maxBuffer: 16 * 1024 * 1024, timeout: 20_000 });
  assert.equal(result.status, 0, result.stderr?.toString() || result.error?.message); return result.stdout;
}
const lineAt = (text, offset) => text.slice(0, offset).split('\n').length;
function ranges(numbers) {
  const result = [];
  for (const value of numbers) {
    const last = result.at(-1);
    if (last && value === last[1] + 1) last[1] = value;
    else result.push([value, value]);
  }
  return result.map(([first, last]) => first === last ? String(first) : `${first}–${last}`).join(', ') || '없음';
}
for (const type of types) {
  const selectionBytes = fs.readFileSync(path.join(pkg, 'corpus', type.selection)), selection = JSON.parse(selectionBytes);
  const summary = read(path.join(build, type.summary));
  assert.equal(summary.engineSha256, ENGINE_SHA256);
  assert.equal(summary.selectionSha256, hash(selectionBytes));
  assert.equal(summary.producerSha256, hash(fs.readFileSync(path.join(pkg, 'scripts', type.producer))));
  for (const target of selection.targets) {
    const entry = corpus.cases.find(row => row.id === target.case); assert.ok(entry);
    const selectedResult = summary.results.find(row => row.id === target.id); assert.ok(selectedResult);
    const changedFile = inventory.cases.find(row => row.case === target.case)?.changedFiles.find(row => row.path === target.path);
    assert.ok(changedFile && !changedFile.binary);
    const sources = {}, revisions = {};
    for (const [revision, commit] of [['before', entry.parent], ['after', entry.head]]) {
      const file = path.join(root, 'build/web-corpus', target.case, revision, target.path);
      const source = fs.readFileSync(file, 'utf8'); sources[revision] = source;
      const pinned = entry.blobs.find(row => row.revision === revision && row.path === target.path);
      assert.equal(hash(source), pinned.sha256); assert.equal(hash(source), selectedResult.sourceSha256[revision]);
      assert.equal(hash(git(entry.project, 'show', `${commit}:${target.path}`)), pinned.sha256);
      const artifactFile = path.join(build, type.directory, target.id, `${revision}.json`);
      const artifactBytes = fs.readFileSync(artifactFile), artifact = JSON.parse(artifactBytes);
      const replay = type.kind === 'const'
        ? liftConstBindings(source, { ...target[revision], outputs: target.outputs, arrayProfile: target.arrayProfile, filename: file })
        : liftJsxProperty(source, { tag: target.tag, attribute: target.attribute, filename: file });
      assert.deepEqual(artifact, replay, 'Selected artifact must replay exactly from its bound source.');
      let spans, absenceAnchor = null;
      if (type.kind === 'const') spans = [{ start: artifact.prefix.source.start, end: artifact.prefix.end, kind: 'const-region' }];
      else if (artifact.target.provided) spans = [{ start: artifact.source.start, end: artifact.source.end, kind: 'jsx-property' }];
      else {
        // The element is an anchor for checking absence, not a span covering
        // every other attribute, callback and child of that element.
        spans = []; absenceAnchor = { tag: target.tag, attribute: target.attribute, provided: false, element: artifact.target.element };
      }
      spans = spans.map(span => ({ ...span, line: lineAt(source, span.start), endLine: lineAt(source, span.end - 1),
        selectedTextSha256: hash(source.slice(span.start, span.end)) }));
      revisions[revision] = { commit, file, sourceSha256: pinned.sha256, artifactSha256: hash(artifactBytes), spans, absenceAnchor };
    }
    const diffArgs = ['diff', '--no-ext-diff', '--no-textconv', '--no-renames', '--no-color', '--unified=0', entry.parent, entry.head, '--', target.path];
    const patch = git(entry.project, ...diffArgs).toString('utf8');
    const diff = inspectUnifiedPatch(patch, sources.before, sources.after);
    assert.equal(diff.removed.length, changedFile.removedLines); assert.equal(diff.added.length, changedFile.addedLines);
    for (const revision of ['before', 'after']) {
      const rows = intersectChangedLines(revision === 'before' ? diff.removed : diff.added, revisions[revision].spans, sources[revision]);
      revisions[revision].changedLines = rows;
      revisions[revision].intersectingLines = rows.filter(row => row.selectedSpanIndices.length).length;
      revisions[revision].outsideLines = rows.filter(row => !row.selectedSpanIndices.length).length;
    }
    const scope = caseChangeScope(target.case, [target.path]);
    const result = { id: target.id, case: target.case, path: target.path,
      status: 'source-overlap-only', semanticCoverage: null, wholeBehaviorVerified: false,
      selectionSha256: hash(selectionBytes), selectedProducerSha256: summary.producerSha256,
      patchSha256: hash(patch), gitDiffArguments: diffArgs, reconstructedEntireAfterFile: diff.reconstructed,
      hunks: diff.hunks, revisions, changeScope: scope };
    results.push(result);
    fs.writeFileSync(path.join(output, target.id + '.patch'), patch);
    fs.writeFileSync(path.join(output, target.id + '.json'), JSON.stringify(result, null, 2) + '\n');
    const lines = [`# ${target.id} · 선택 원본과 변경 줄`, '', describeChangeScope(scope), '',
      '아래 수치는 Git이 바뀌었다고 표시한 텍스트 줄과 선택한 원본 구간의 교차다. 한 줄의 일부만 겹쳐도 포함된다. 동작 해석 성공률이나 누락 없는 검토 비율로 사용하지 않는다. 들여쓰기·이동으로 생긴 변경 줄도 포함된다.', '',
      '| 버전 | 변경 줄 수 | 선택 구간과 겹친 줄 | 선택 구간 밖 변경 줄 |', '|---|---:|---:|---:|',
      ...Object.entries(revisions).map(([revision, row]) => `| ${revision === 'before' ? '전 · 삭제 줄' : '후 · 추가 줄'} | ${row.changedLines.length} | ${row.intersectingLines} | ${row.outsideLines} |`), ''];
    for (const [revision, row] of Object.entries(revisions)) {
      const file = row.file.replaceAll('\\', '/');
      lines.push(`## ${revision === 'before' ? '변경 전' : '변경 후'}`, '',
        `선택 구간: ${row.spans.map(span => `[${span.line}–${span.endLine}줄](<${file}:${span.line}>)`).join(', ') || '텍스트 구간 없음'}.`,
        `겹친 변경 줄: ${ranges(row.changedLines.filter(line => line.selectedSpanIndices.length).map(line => line.line))}.`,
        `선택 밖 변경 줄: ${ranges(row.changedLines.filter(line => !line.selectedSpanIndices.length).map(line => line.line))}.`, '');
      if (row.absenceAnchor) lines.push(`선택 속성 ${row.absenceAnchor.attribute}이 없는지 [${row.absenceAnchor.element.line}줄의 태그](<${file}:${row.absenceAnchor.element.line}>)를 확인한 것이다. 태그의 다른 속성·이벤트 코드를 해석한 구간으로 넓혀 세지 않는다.`, '');
    }
    lines.push('원본 diff의 모든 hunk와 바뀌지 않은 사이 구간으로 변경 후 파일 전체를 다시 구성하고 줄 내용·마지막 개행을 대조했다. 이것은 diff와 원본의 일치 검사이며 앱 실행 검증이 아니다. 전체 행동 완료 0/12, 사람 참가자 0명.', '');
    fs.writeFileSync(path.join(output, target.id + '.md'), lines.join('\n'));
  }
}
const report = { schema: 'web-slice-source-scope-results-1', engineSha256: ENGINE_SHA256,
  producerSha256: hash(fs.readFileSync(fileURLToPath(import.meta.url))),
  parserSha256: hash(fs.readFileSync(path.join(pkg, 'scripts/diff-spans.mjs'))), inventorySha256: hash(inventoryBytes),
  scope: 'Exact selected source spans versus changed text lines; no semantic coverage or new execution claim.',
  reconstructedFiles: results.length, artifactReplays: results.length * 2,
  nativeExecutions: 0, humanParticipants: 0, wholeBehaviorCasesVerified: 0, semanticCoverage: null, output, results };
fs.writeFileSync(path.join(build, 'slice-source-scope-results.json'), JSON.stringify(report, null, 2) + '\n');
process.stdout.write(JSON.stringify({ ...report, results: results.map(row => ({ id: row.id,
  before: { changed: row.revisions.before.changedLines.length, intersects: row.revisions.before.intersectingLines },
  after: { changed: row.revisions.after.changedLines.length, intersects: row.revisions.after.intersectingLines } })) }) + '\n');
