import test from 'node:test';
import assert from 'node:assert/strict';
import { ARRAY_PROFILE, encode, observe } from '../src/core.mjs';
import { liftConstBindings } from '../src/const-bindings.mjs';
import { buildExecutionReading, renderExecution } from '../src/report.mjs';

const lift = expression => {
  const text = `const result = ${expression};`;
  return { artifact: liftConstBindings(text, { filename: '/original.ts', startLine: 1, endLine: 1, outputs: ['result'], arrayProfile: ARRAY_PROFILE }),
    snippets: source => text.slice(source.start, source.end) };
};
const pack = value => encode(value, 0, undefined, { arrays: true });

test('entered short-circuit operands can still throw, with no fabricated completed binding', () => {
  const { artifact, snippets } = lift('enabled && object.value');
  const result = observe(artifact.ir, { enabled: true, object: null }, { trace: true });
  const reading = buildExecutionReading(result, { snippets });
  assert.equal(reading.status, 'recorded-ir-execution'); assert.equal(reading.outcome, 'throw');
  assert.deepEqual(reading.rows.map(row => row.event), ['short-circuit', 'throw']);
  assert.match(reading.rows[0].text, /오른쪽 계산을 시작한다/);
  assert.match(reading.rows[0].text, /정상 완료됐다고 판단하지 않는다/);
  assert.equal(snippets(reading.rows[0].references[0].source), 'enabled');
  assert.equal(reading.rows[1].sequence, 2);
  assert.match(reading.rows[1].text, /TypeError/);
  assert.doesNotMatch(reading.rows.map(row => row.text).join('\n'), /result에 .*저장했다/);
  const skipped = buildExecutionReading(observe(artifact.ir, { enabled: false, object: null }, { trace: true }), { snippets });
  assert.equal(skipped.outcome, 'value'); assert.match(skipped.rows[0].text, /오른쪽 계산을 생략했다/);
  assert.equal(skipped.rows.some(row => row.event === 'throw'), false);
  assert.match(renderExecution(artifact, result, { snippets }), /오른쪽 계산을 시작한다/);
});

test('selected branch, ordered filter decisions and concat copying stay in recorded order', () => {
  const { artifact, snippets } = lift('enabled ? preview.concat(rows.filter(t => !t.is_child)) : rows');
  const inputs = { enabled: true, preview: pack([{ id: 'p' }]), rows: pack([{ id: 'a', is_child: false }, { id: 'b', is_child: true }, { id: 'a' }]) };
  const observation = observe(artifact.ir, inputs, { trace: true });
  const reading = buildExecutionReading(observation, { snippets });
  assert.deepEqual(reading.rows.map(row => row.event), ['branch', 'filter-start', 'filter-item', 'filter-item', 'filter-item', 'filter-result', 'concat-part', 'concat-part', 'concat-result', 'bind', 'observed-binding']);
  assert.deepEqual(reading.rows.map(row => row.source), observation.trace.map(row => row.source));
  assert.deepEqual(reading.rows.map(row => row.sequence), Array.from({ length: 11 }, (_, i) => i + 1));
  assert.equal(snippets(reading.rows[0].references[0].source), 'enabled');
  for (const [i, expected] of [[2, /1번째 원소 .*남겼다/], [3, /2번째 원소 .*제외했다/], [4, /3번째 원소 .*남겼다/]]) assert.match(reading.rows[i].text, expected);
  assert.match(reading.rows[5].text, /3개 중 2개를 원래 순서로/);
  assert.match(reading.rows[6].text, /앞 목록의 원소 1개/);
  assert.match(reading.rows[7].text, /1번째 인수 목록의 원소 2개/);
  assert.match(reading.rows[8].text, /새 목록은 3개/);
  const other = buildExecutionReading(observe(artifact.ir, { ...inputs, enabled: false }, { trace: true }), { snippets });
  assert.deepEqual(other.rows.map(row => row.event), ['branch', 'bind', 'observed-binding']);
  assert.match(other.rows[0].text, /그렇지 않은 분기/);
  assert.ok(reading.notes.some(note => note.includes('실제 앱이 이 구간에 도달했다는 증거가 아니다')));
});

test('missing records, truncated records and unsupported outcomes have distinct coverage', () => {
  const { artifact } = lift('rows.filter(t => t)');
  const inputs = { rows: pack(Array(600).fill(true)) };
  assert.equal(buildExecutionReading(observe(artifact.ir, inputs)).status, 'not-generated');
  const truncated = buildExecutionReading(observe(artifact.ir, inputs, { trace: true }));
  assert.equal(truncated.eventCount, 512); assert.equal(truncated.truncated, true);
  assert.equal(truncated.outcome, 'value');
  assert.ok(truncated.notes.some(note => note.includes('마지막 표시가 실행 종료 위치')));
  assert.equal(truncated.rows.some(row => row.event === 'filter-result'), false);
  const unsupported = buildExecutionReading(observe(artifact.ir, { rows: 1 }, { trace: true }));
  assert.equal(unsupported.outcome, 'unsupported'); assert.equal(unsupported.eventCount, 0);
  assert.ok(unsupported.notes.some(note => note.includes('성공한 실행이라고 판단하지 않는다')));
  const noEvents = buildExecutionReading({ kind: 'value', value: 1, trace: [], traceTruncated: false });
  assert.equal(noEvents.status, 'recorded-ir-execution'); assert.equal(noEvents.eventCount, 0);
  assert.ok(noEvents.notes.some(note => note.includes('모든 연산의 개별 기록은 아니다')));
});

test('unknown events and oversized descriptions refuse the whole reading', () => {
  const raw = { kind: 'value', value: 1, trace: [{ event: 'future-operation' }], traceTruncated: false };
  assert.equal(buildExecutionReading(raw).status, 'not-generated');
  assert.equal(buildExecutionReading({ ...raw, trace: Array(513).fill({ event: 'array', length: 1 }) }).status, 'not-generated');
  assert.equal(buildExecutionReading({ ...raw, trace: [{ event: 'array', length: 1 }] }, { textLimit: 1 }).status, 'not-generated');
  for (const textLimit of [0, -1, 1.5, 1048577, Infinity]) assert.equal(buildExecutionReading(raw, { textLimit }).status, 'not-generated');
  const { artifact } = lift('enabled && value');
  const observation = observe(artifact.ir, { enabled: true, value: 2 }, { trace: true });
  const long = buildExecutionReading(observation, { snippets: () => 'x'.repeat(4096), textLimit: 1024 });
  assert.equal(long.status, 'not-generated'); assert.equal(Object.hasOwn(long, 'rows'), false);
});
