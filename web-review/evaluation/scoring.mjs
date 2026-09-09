import assert from 'node:assert/strict';

const criterionIds = ['conditions', 'values', 'exception', 'boundary'];
const taskIds = ['starting-balance', 'ui-mode', 'filter-loading', 'recording-toggle'];
const sha256 = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const text = (value, maximum = 8000) => typeof value === 'string' && value.trim().length > 0 && value.length <= maximum;

export function validateRubric(rubric) {
  assert.equal(rubric.schema, 'web-review-rubric-draft-1');
  assert.equal(rubric.status, 'requires-human-review'); assert.equal(rubric.participants, 0);
  assert.equal(rubric.scoringMode, 'human-assigned-item-scores');
  assert.deepEqual(rubric.criteria.map(row => row.id), criterionIds);
  for (const criterion of rubric.criteria) { assert.equal(criterion.maximum, 2); assert.ok(text(criterion.label, 100)); }
  assert.ok(Array.isArray(rubric.rules) && rubric.rules.length > 0 && rubric.rules.every(rule => text(rule)));
  assert.deepEqual(rubric.tasks.map(row => row.id), taskIds);
  for (const task of rubric.tasks) {
    assert.deepEqual(Object.keys(task.reference).sort(), [...criterionIds].sort());
    assert.deepEqual(Object.keys(task.anchors).sort(), [...criterionIds].sort());
    for (const id of criterionIds) {
      assert.ok(text(task.reference[id]));
      assert.ok(Array.isArray(task.anchors[id]) && task.anchors[id].length === 3 && task.anchors[id].every(anchor => text(anchor)));
    }
  }
  return rubric;
}

export function makePracticeScoringPacket(response, { rubric, materialSha256, responseId }) {
  validateRubric(rubric);
  assert.ok(sha256(materialSha256)); assert.equal(response.materialSha256, materialSha256, 'The response must refer to the exact prepared practice materials.');
  assert.equal(response.schema, 'geul-review-practice-response-1');
  assert.equal(response.mode, 'practice-only'); assert.equal(response.participant, null);
  assert.equal(response.previewAvailableBeforeStart, true);
  assert.ok(taskIds.includes(response.task)); assert.ok(['A', 'B', 'C', 'D'].includes(response.condition));
  assert.match(responseId, /^[a-z][a-z0-9-]{0,63}$/);
  assert.ok(Array.isArray(response.answers) && response.answers.length === 4 && response.answers.every(answer => text(answer)));
  assert.ok(Number.isFinite(response.confidence) && response.confidence >= 0 && response.confidence <= 100);
  // Explicit allowlist: no condition, timing, confidence, AI metadata, events,
  // or identifiers derived from them enter the reviewer's sheet.
  const sheet = {
    schema: 'geul-practice-score-sheet-1', mode: 'practice-only', participant: null,
    responseId, task: response.task, answers: [...response.answers],
    items: criterionIds.map(id => ({ criterion: id, score: null, reason: '' })),
    boundaryOverclaim: null, boundaryEvidence: '',
    status: 'awaiting-human-scores',
    limitation: '조건 메타데이터를 가린 예행 채점 양식이다. 자유 서술의 내용은 수정하지 않으므로 완전한 눈가림을 보장하지 않는다. 점수는 사람이 입력한다.',
  };
  return { sheet, privateRecord: {
    schema: 'geul-practice-score-private-1', responseId, mode: 'practice-only', participant: null,
    originalResponse: structuredClone(response),
  } };
}

export function inspectPracticeScores(sheet, originalSheet) {
  const stripScores = value => ({ ...value, items: value.items.map(({ score, reason, ...row }) => row),
    boundaryOverclaim: null, boundaryEvidence: '' });
  assert.deepEqual(stripScores(sheet), stripScores(originalSheet), 'Response text and task identity cannot change while scoring.');
  assert.equal(sheet.schema, 'geul-practice-score-sheet-1'); assert.equal(sheet.mode, 'practice-only'); assert.equal(sheet.participant, null);
  assert.deepEqual(sheet.items.map(item => item.criterion), criterionIds);
  for (const item of sheet.items) {
    assert.ok(item.score === null || [0, 1, 2].includes(item.score));
    assert.ok(typeof item.reason === 'string' && item.reason.length <= 8000);
    if (item.score !== null) assert.ok(item.reason.trim().length > 0, 'A human-assigned score needs a reason.');
  }
  assert.ok(sheet.boundaryOverclaim === null || typeof sheet.boundaryOverclaim === 'boolean');
  assert.ok(typeof sheet.boundaryEvidence === 'string' && sheet.boundaryEvidence.length <= 8000);
  if (sheet.boundaryOverclaim === true) assert.ok(text(sheet.boundaryEvidence) && sheet.answers.some(answer => answer.includes(sheet.boundaryEvidence)),
    'A scope overclaim flag must quote an actual statement in the response.');
  const scoredItems = sheet.items.filter(item => item.score !== null).length;
  const complete = scoredItems === criterionIds.length && sheet.boundaryOverclaim !== null;
  return { mode: 'practice-only', participant: null, scoredItems, unscoredItems: criterionIds.length - scoredItems,
    status: complete ? 'entered-scores-not-validated' : 'incomplete-human-scoring',
    total: complete ? sheet.items.reduce((sum, item) => sum + item.score, 0) : null,
    maximum: 8, boundaryOverclaim: sheet.boundaryOverclaim,
    accuracyOfHumanScoresVerified: false, humanExperimentParticipants: 0 };
}

export function renderRubric(rubric) {
  validateRubric(rubric);
  const lines = ['# 사람 채점 기준 초안', '', '**사람 검토 필요 · 참가자 0명 · 본 실험 미실시**', '', ...rubric.rules.map(rule => `- ${rule}`), ''];
  for (const task of rubric.tasks) {
    lines.push(`## ${task.id}`, '');
    for (const criterion of rubric.criteria) {
      lines.push(`### ${criterion.label}`, '', task.reference[criterion.id], '',
        ...task.anchors[criterion.id].map((anchor, score) => `- ${score}점: ${anchor}`), '');
    }
  }
  return lines.join('\n');
}
