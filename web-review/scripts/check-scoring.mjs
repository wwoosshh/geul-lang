import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { hash } from '../src/typescript.mjs';
import { createPracticeSession } from '../evaluation/viewer/session.mjs';
import { loadPracticeData } from '../evaluation/viewer/server.mjs';

const pkg = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'), root = path.dirname(pkg);
const { publicData } = loadPracticeData();
const base = path.join(root, 'build/web-review/scoring-checks'); fs.mkdirSync(base, { recursive: true });
const output = fs.mkdtempSync(path.join(base, 'run-'));
const response = createPracticeSession({ task: 'starting-balance', condition: 'B', materialSha256: publicData.materialSha256,
  now: () => 0, wall: () => '2026-09-09T00:00:00.000Z' }).finish({
  answers: ['합성 입력: amount 생략일 때 바뀐다.', '합성 입력: undefined에서 0으로 바뀐다.', '합성 입력: -0은 유지된다.', '합성 오답: 서버에 0이 전송된다고 확정할 수 있다.'],
  confidence: 99, familiar: false, aiModel: 'synthetic-cli-test', aiRequests: 0,
});
const responseFile = path.join(output, 'synthetic-response.json');
fs.writeFileSync(responseFile, JSON.stringify(response, null, 2) + '\n', { flag: 'wx' });
let commands = 0;
function cli(name, args, expectedStatus = 0) {
  const result = spawnSync(process.execPath, [path.join(pkg, 'scripts/score-practice.mjs'), ...args], { encoding: 'utf8', timeout: 20_000 });
  commands++;
  fs.writeFileSync(path.join(output, name + '.log'), result.stdout + result.stderr, { flag: 'wx' });
  assert.equal(result.status, expectedStatus, result.stderr);
  return expectedStatus === 0 ? JSON.parse(result.stdout) : undefined;
}
const prepared = cli('prepare', ['prepare', '--response', responseFile, '--id', 'synthetic-cli-example']);
const sheetFile = path.join(prepared.directory, 'score-sheet.json');
const original = JSON.parse(fs.readFileSync(sheetFile, 'utf8'));
for (const field of ['condition', 'confidence', 'timing', 'aiModel', 'events']) assert.equal(Object.hasOwn(original, field), false);
assert.deepEqual(original.answers, response.answers);
const empty = cli('empty', ['inspect', '--packet', prepared.directory]);
assert.equal(empty.total, null); assert.equal(empty.unscoredItems, 4);
const partial = structuredClone(original);
partial.items[0] = { criterion: 'conditions', score: 1, reason: '합성 점수: 일부 조건만 제시한 상황을 시험한다.' };
fs.writeFileSync(sheetFile, JSON.stringify(partial, null, 2) + '\n');
assert.equal(cli('partial', ['inspect', '--packet', prepared.directory]).total, null);
const complete = structuredClone(partial);
for (const item of complete.items) { item.score = item.criterion === 'boundary' ? 0 : 1; item.reason = '합성 입력의 합계 계산 시험이며 실제 사람이 채점한 점수가 아니다.'; }
complete.boundaryOverclaim = true; complete.boundaryEvidence = '서버에 0이 전송된다고 확정';
fs.writeFileSync(sheetFile, JSON.stringify(complete, null, 2) + '\n');
const inspected = cli('complete', ['inspect', '--packet', prepared.directory]);
assert.equal(inspected.total, 3); assert.equal(inspected.humanExperimentParticipants, 0);
assert.equal(inspected.accuracyOfHumanScoresVerified, false);
const tampered = structuredClone(complete); tampered.answers[0] = 'changed answer';
fs.writeFileSync(path.join(output, 'tampered-sheet.json'), JSON.stringify(tampered, null, 2) + '\n', { flag: 'wx' });
fs.writeFileSync(sheetFile, JSON.stringify(tampered, null, 2) + '\n');
cli('tampered-answer-refused', ['inspect', '--packet', prepared.directory], 1);
fs.writeFileSync(sheetFile, JSON.stringify(complete, null, 2) + '\n');
const stale = structuredClone(response); stale.materialSha256 = '0'.repeat(64);
const staleFile = path.join(output, 'stale-response.json'); fs.writeFileSync(staleFile, JSON.stringify(stale, null, 2) + '\n', { flag: 'wx' });
cli('stale-material-refused', ['prepare', '--response', staleFile, '--id', 'synthetic-stale-example'], 1);
const report = { schema: 'geul-practice-scoring-checks-1', mode: 'synthetic-tool-check-only', output,
  commands, syntheticResponses: 1, humanParticipants: 0, humanScoresVerified: 0,
  producerSha256: hash(fs.readFileSync(fileURLToPath(import.meta.url))),
  cliSha256: hash(fs.readFileSync(path.join(pkg, 'scripts/score-practice.mjs'))),
  helperSha256: hash(fs.readFileSync(path.join(pkg, 'evaluation/scoring.mjs'))),
  rubricSha256: hash(fs.readFileSync(path.join(pkg, 'evaluation/rubric.json'))),
  materialSha256: publicData.materialSha256,
  packet: prepared.directory, checks: ['metadata hidden', 'raw answers retained', 'unscored remains null', 'manual integer sum', 'altered answer refused', 'stale materials refused'] };
fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n', { flag: 'wx' });
fs.writeFileSync(path.join(root, 'build/web-review/scoring-results.json'), JSON.stringify(report, null, 2) + '\n');
process.stdout.write(JSON.stringify(report) + '\n');
