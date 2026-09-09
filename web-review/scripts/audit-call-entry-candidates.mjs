import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { inspectCallEntryCandidates } from './call-entry-candidates.mjs';
import { hash } from '../src/typescript.mjs';
import { ENGINE_SHA256 } from '../src/fingerprint.mjs';

const pkg = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'), root = path.dirname(pkg);
const lockBytes = fs.readFileSync(path.join(pkg, 'corpus/lock.json')), lock = JSON.parse(lockBytes);
assert.equal(lock.selectionSha256, hash(fs.readFileSync(path.join(pkg, 'corpus/selection.json'))));
const files = [], candidates = [];
for (const change of lock.cases) {
  for (const blob of change.blobs.filter(blob => blob.revision === 'after' && /\.[jt]sx?$/.test(blob.path))) {
    const filename = path.join(root, 'build/web-corpus', change.id, 'after', blob.path), bytes = fs.readFileSync(filename);
    assert.equal(hash(bytes), blob.sha256);
    const rows = inspectCallEntryCandidates(bytes.toString('utf8'), filename);
    files.push({ case: change.id, path: blob.path, sha256: blob.sha256, candidateCount: rows.length });
    candidates.push(...rows.map(row => ({ case: change.id, path: blob.path, sourceSha256: blob.sha256, ...row })));
  }
}
const counts = rows => Object.fromEntries(['empty-prefix', 'lowered-prefix', 'refused'].map(status => [status, rows.filter(row => row.status === status).length]));
const unique = [...new Map(candidates.map(row => [`${row.sourceSha256}:${row.source.start}:${row.source.end}`, row])).values()];
const result = {
  schema: 'web-call-entry-candidate-audit-1', status: 'syntactic-subset-audit', engineSha256: ENGINE_SHA256,
  corpusLockSha256: hash(lockBytes), producerSha256: hash(fs.readFileSync(fileURLToPath(import.meta.url))),
  classifierSha256: hash(fs.readFileSync(new URL('./call-entry-candidates.mjs', import.meta.url))),
  sourceFileOccurrences: files.length, candidateOccurrences: candidates.length, counts: counts(candidates),
  uniqueByteRanges: { count: unique.length, counts: counts(unique) },
  nativeExecutions: 0, humanParticipants: 0, wholeBehaviorCasesVerified: 0,
  notes: [
    '고정 사례에 포함된 변경 후 JS·TS·JSX·TSX 파일 전체에서 마지막 직접 문장이 이름 있는 호출인 함수 본문만 조사했다.',
    '후보 밖의 호출·함수·구문을 처리한 것으로 세지 않는다. 호출 위치가 실제 변경 줄인지도 이 조사에서는 판정하지 않았다.',
    '여러 사례의 같은 파일 내용은 occurrence에 반복 집계한다. uniqueByteRanges는 파일 바이트 해시와 호출 구간만으로 별도 중복 제거한 수치다.',
    'empty-prefix는 앞선 문장이 없는 본문이다. 호출 자체를 실행하지 않으므로 이 수를 동작 해석 범위로 사용하지 않는다.',
    'lowered-prefix는 선행 문장을 IR로 추출한 결과다. 독립 원본 실행 대조·의미 보존 증명·실제 앱 실행 성공을 뜻하지 않는다.',
    '미지원은 이유와 원본 위치를 남기며 일부 문장을 생략해 성공으로 처리하지 않는다.',
  ], files, candidates,
};
assert.equal(Object.values(result.counts).reduce((a, b) => a + b, 0), candidates.length);
const output = path.join(root, 'build/web-review/call-entry-candidate-audit.json');
fs.mkdirSync(path.dirname(output), { recursive: true });
fs.writeFileSync(output, JSON.stringify(result, null, 2) + '\n');
process.stdout.write(JSON.stringify({ status: result.status, engineSha256: ENGINE_SHA256, sourceFileOccurrences: files.length,
  candidateOccurrences: candidates.length, counts: result.counts, uniqueByteRanges: result.uniqueByteRanges, nativeExecutions: 0, output }) + '\n');
