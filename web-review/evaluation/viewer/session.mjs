export function createPracticeSession({ task, condition, materialSha256, now = () => performance.now(), wall = () => new Date().toISOString() }) {
  const start = now(), startedAt = wall(), events = [];
  let last = start, waiting = false, hidden = false, waitMs = 0, hiddenMs = 0, finished = false;
  const tick = () => {
    if (finished) return last - start;
    const value = now();
    if (!Number.isFinite(value) || value < last) throw new Error('시간 기록이 역행했습니다. 예행 검토를 새로 시작하세요.');
    if (waiting) waitMs += value - last;
    if (hidden) hiddenMs += value - last;
    last = value;
    return value - start;
  };
  const record = (kind, detail = {}) => {
    if (finished) return;
    if (events.length >= 4096) throw new Error('기록 한도에 도달했습니다. 현재 응답을 내보내세요.');
    events.push({ kind, elapsedMs: tick(), ...detail });
  };
  record('start');
  return {
    visitSource(sourceId, line) { record('source-open', { sourceId, line }); },
    setWaiting(value) { if (!finished) { record(value ? 'ai-wait-start' : 'ai-wait-end'); waiting = Boolean(value); } },
    setHidden(value) { if (!finished) { record(value ? 'window-hidden' : 'window-visible'); hidden = Boolean(value); } },
    snapshot() { return { elapsedMs: tick(), aiWaitingMs: waitMs, hiddenMs, waiting, sourceVisits: events.filter(event => event.kind === 'source-open').length }; },
    finish({ answers, confidence, familiar, aiModel, aiRequests = 0 }) {
      if (finished) throw new Error('이미 내보낸 예행 검토입니다.');
      if (!Array.isArray(answers) || answers.length !== 4 || answers.some(answer => typeof answer !== 'string' || !answer.trim() || answer.length > 8000)) throw new Error('네 문항에 8,000자 이내로 답해주세요.');
      if (!Number.isFinite(confidence) || confidence < 0 || confidence > 100) throw new Error('확신도는 0~100 사이여야 합니다.');
      if (typeof aiModel !== 'string' || aiModel.length > 200) throw new Error('AI 도구·모델 기록은 200자 이내여야 합니다.');
      if (!Number.isInteger(aiRequests) || aiRequests < 0 || aiRequests > 1000) throw new Error('AI 질문 횟수는 0~1000 정수여야 합니다.');
      record('finish');
      const timing = this.snapshot();
      finished = true;
      return { schema: 'geul-review-practice-response-1', mode: 'practice-only', participant: null, task, condition, materialSha256,
        startedAt, finishedAt: wall(), timing, answers, confidence, familiar: Boolean(familiar), aiModel, selfReportedAiRequests: aiRequests, previewAvailableBeforeStart: true, events: [...events],
        timingNote: '경과 시간은 AI 대기와 창 비활성 시간을 포함한다. 두 보조 시간은 겹칠 수 있으므로 합산해 빼지 않는다. 실제 참가자 관측값으로 집계하지 않는다.' };
    },
  };
}
