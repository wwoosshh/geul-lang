import { encode, decode } from './core.mjs';

// Compare encoded observation values, not application object identity or keys.
// Repeated equal values may admit multiple alignments. Choose one deterministically
// and validate the complete resulting sequence; never infer an ID-based move.
function values(before, after, options) {
  const { maxItems = 256, workLimit = 131072, byteLimit = 1024 * 1024 } = options;
  if (![maxItems, workLimit, byteLimit].every(value => Number.isSafeInteger(value) && value >= 0) || maxItems > 512 || workLimit > 1048576 || byteLimit > 8 * 1024 * 1024) throw Error('목록 변경 보기의 제한값 오류');
  const budget = { nodes: workLimit, bytes: byteLimit };
  function canonical(value) {
    if (!value || Object.keys(value).length !== 1 || !Array.isArray(value.$array) || value.$array.length > maxItems) throw Error('목록 변경 보기의 배열 형식·길이 제한');
    return encode(decode(value, 0, { arrays: true }, budget), 0, budget, { arrays: true }).$array;
  }
  return { left: canonical(before), right: canonical(after), budget };
}

function reconstruct(left, right, edits, budget) {
  if (!Array.isArray(edits) || edits.length > left.length + right.length) throw Error('목록 변경 재검사 항목 오류');
  const result = [];
  let cursor = 0;
  const key = value => JSON.stringify(value);
  for (const edit of edits) {
    if (--budget.nodes < 0) throw Error('목록 변경 재검사 작업량 제한');
    if (!Number.isSafeInteger(edit?.beforeStart) || edit.beforeStart < cursor || edit.beforeStart > left.length || !Number.isSafeInteger(edit.afterStart) || !Array.isArray(edit.removed) || !Array.isArray(edit.inserted) || !(edit.removed.length + edit.inserted.length) || edit.beforeStart + edit.removed.length > left.length || edit.inserted.length > right.length) throw Error('목록 변경 재검사 위치 오류');
    const clean = items => encode(decode({ $array: items }, 0, { arrays: true }, budget), 0, budget, { arrays: true }).$array;
    const removed = clean(edit.removed), inserted = clean(edit.inserted);
    for (; cursor < edit.beforeStart; cursor++) result.push(left[cursor]);
    if (result.length !== edit.afterStart || key(left.slice(cursor, cursor + removed.length)) !== key(removed)) throw Error('목록 변경 재검사 이전 값·위치 불일치');
    if (result.length + inserted.length > right.length) throw Error('목록 변경 재검사 결과 길이 초과');
    for (const item of inserted) result.push(item);
    cursor += removed.length;
  }
  for (; cursor < left.length; cursor++) result.push(left[cursor]);
  if (key(result) !== key(right)) throw Error('목록 변경으로 이후 관찰 결과를 복원하지 못함');
}

export function verifyArrayDelta(before, after, edits, options = {}) {
  const { left, right, budget } = values(before, after, options);
  reconstruct(left, right, edits, budget);
  return { reconstructedAfter: true, beforeLength: left.length, afterLength: right.length };
}

export function diffArrayValues(before, after, { maxEdits = 64, ...options } = {}) {
  try {
    if (!Number.isSafeInteger(maxEdits) || maxEdits < 0 || maxEdits > 1024) throw Error('목록 변경 보기의 항목 제한값 오류');
    const { left, right, budget } = values(before, after, options), n = left.length, m = right.length;
    if ((n + 1) * (m + 1) > budget.nodes) throw Error('목록 변경 보기 정렬 작업량 제한');
    budget.nodes -= (n + 1) * (m + 1);
    // Intern whole canonical values once. DP compares small integer IDs rather
    // than repeatedly traversing records or trusting a lossy key/hash projection.
    const ids = new Map();
    const intern = item => { const key = JSON.stringify(item); if (!ids.has(key)) ids.set(key, ids.size); return ids.get(key); };
    const a = left.map(intern), b = right.map(intern);
    const lengths = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) lengths[i][j] = a[i] === b[j] ? lengths[i + 1][j + 1] + 1 : Math.max(lengths[i + 1][j], lengths[i][j + 1]);
    const edits = [];
    let i = 0, j = 0, active;
    const flush = () => {
      if (!active) return;
      if (edits.length >= maxEdits) throw Error('목록 변경 보기 항목 제한');
      edits.push(active); active = undefined;
    };
    while (i < n || j < m) {
      if (i < n && j < m && a[i] === b[j]) { flush(); i++; j++; continue; }
      active ??= { beforeStart: i, afterStart: j, removed: [], inserted: [] };
      if (i < n && (j === m || lengths[i + 1][j] >= lengths[i][j + 1])) active.removed.push(left[i++]);
      else active.inserted.push(right[j++]);
    }
    flush();
    reconstruct(left, right, edits, budget);
    return { status: 'verified-array-observation-delta', edits, reconstructedAfter: true, beforeLength: n, afterLength: m,
      scope: '원소의 전체 관찰 값과 순서; 객체 동일성·ID 기반 이동·앱 상태 변경 제외. 중복 값의 가능한 정렬 중 하나.' };
  } catch (error) {
    return { status: 'not-generated', reason: error.message };
  }
}
