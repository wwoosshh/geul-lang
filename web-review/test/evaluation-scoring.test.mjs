import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { makePracticeScoringPacket, inspectPracticeScores, validateRubric, renderRubric } from '../evaluation/scoring.mjs';

const rubric = JSON.parse(fs.readFileSync(new URL('../evaluation/rubric.json', import.meta.url)));
const materialSha256 = 'a'.repeat(64);
const response = {
  schema: 'geul-review-practice-response-1', mode: 'practice-only', participant: null, previewAvailableBeforeStart: true,
  task: 'starting-balance', condition: 'B', materialSha256, confidence: 99,
  answers: ['생략이면 바뀐다.', 'undefined에서 0이 된다.', '-0은 그대로다.', '그러므로 서버에 0이 전송된다.'],
  aiModel: 'synthetic-only', timing: { elapsedMs: 123 }, selfReportedAiRequests: 7,
  events: [{ kind: 'source-open', sourceId: 'private-example' }], unexpectedMetadata: 'Do not copy into the sheet',
};
const prepare = input => makePracticeScoringPacket(input, { rubric, materialSha256, responseId: 'synthetic-example' });

test('practice scoring hides condition metadata, preserves answers and retains the raw private record', () => {
  validateRubric(rubric);
  const { sheet, privateRecord } = prepare(response);
  assert.deepEqual(sheet.answers, response.answers);
  for (const key of ['condition', 'confidence', 'timing', 'aiModel', 'events', 'selfReportedAiRequests', 'unexpectedMetadata', 'materialSha256']) assert.equal(Object.hasOwn(sheet, key), false);
  assert.deepEqual(privateRecord.originalResponse, response);
  privateRecord.originalResponse.answers[0] = 'changed'; assert.notEqual(response.answers[0], 'changed');
  assert.deepEqual(inspectPracticeScores(sheet, sheet), {
    mode: 'practice-only', participant: null, scoredItems: 0, unscoredItems: 4,
    status: 'incomplete-human-scoring', total: null, maximum: 8, boundaryOverclaim: null,
    accuracyOfHumanScoresVerified: false, humanExperimentParticipants: 0,
  });
  const text = renderRubric(rubric);
  assert.ok(text.includes('undefined→0')); assert.ok(text.includes('null→0'));
  assert.equal((text.match(/### /g) ?? []).length, 16);
});

test('scores stay incomplete until every manual item and scope flag is provided', () => {
  const original = prepare(response).sheet, sheet = structuredClone(original);
  sheet.items[0] = { criterion: 'conditions', score: 1, reason: '일부 조건만 답했다.' };
  assert.equal(inspectPracticeScores(sheet, original).total, null);
  for (const item of sheet.items) { item.score = 1; item.reason = '합성 테스트의 점수 입력; 실제 사람의 채점 아님'; }
  assert.equal(inspectPracticeScores(sheet, original).total, null);
  sheet.boundaryOverclaim = true; sheet.boundaryEvidence = '서버에 0이 전송된다';
  const result = inspectPracticeScores(sheet, original);
  assert.equal(result.total, 4); assert.equal(result.accuracyOfHumanScoresVerified, false);
  assert.equal(result.humanExperimentParticipants, 0);
});

test('scoring refuses stale or participant responses, altered answers and unsupported manual claims', () => {
  for (const mutate of [
    value => { value.materialSha256 = 'b'.repeat(64); },
    value => { value.participant = 'person-1'; },
    value => { value.mode = 'experiment'; },
    value => { value.task = 'unknown'; },
    value => { value.answers.pop(); },
  ]) { const input = structuredClone(response); mutate(input); assert.throws(() => prepare(input)); }
  const original = prepare(response).sheet;
  for (const mutate of [
    value => { value.answers[0] = 'edited'; },
    value => { value.items[0].score = 3; value.items[0].reason = 'invalid'; },
    value => { value.items[0].score = 2; },
    value => { value.boundaryOverclaim = true; value.boundaryEvidence = 'invented quote'; },
    value => { value.condition = 'B'; },
  ]) { const input = structuredClone(original); mutate(input); assert.throws(() => inspectPracticeScores(input, original)); }
  const invalid = structuredClone(rubric); invalid.tasks[0].anchors.conditions.pop();
  assert.throws(() => validateRubric(invalid));
});
