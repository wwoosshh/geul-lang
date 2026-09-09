import { decode, encode, Unsupported } from './core.mjs';

const valueKey = value => JSON.stringify(encode(decode(value, 0, { arrays: true }), 0, undefined, { input: true, arrays: true }));
const pairKey = row => JSON.stringify([row.before, row.after]);
function domainIndex(domains) {
  if (!domains || typeof domains !== 'object' || Array.isArray(domains)) throw new Unsupported('규칙 도메인은 이름에서 값 목록으로 가는 객체여야 합니다.');
  const names = Object.keys(domains).sort();
  if (names.length > 16) throw new Unsupported('규칙 생성은 입력 이름 16개 이하만 지원합니다.');
  let size = 1;
  const indices = names.map(name => {
    if (!Array.isArray(domains[name]) || !domains[name].length) throw new Unsupported('규칙 도메인이 비어 있습니다.');
    size *= domains[name].length;
    if (size > 65536) throw new Unsupported('규칙 도메인 조합 제한 초과');
    const keys = domains[name].map(valueKey);
    if (new Set(keys).size !== keys.length) throw new Unsupported('같은 관찰 값을 중복한 도메인은 규칙 생성에서 제외합니다.');
    return new Map(keys.map((key, index) => [key, index]));
  });
  const tuple = inputs => {
    if (!inputs || names.join('\0') !== Object.keys(inputs).sort().join('\0')) throw new Unsupported('규칙 입력 이름이 도메인과 일치하지 않습니다.');
    return names.map((name, axis) => {
      const index = indices[axis].get(valueKey(inputs[name]));
      if (index === undefined) throw new Unsupported('규칙 입력이 도메인 밖에 있습니다.');
      return index;
    });
  };
  return { names, size, tuple };
}

// Verify by expanding every produced rectangle and comparing it to the
// ORIGINAL changed-row map. This is separate from the grouping algorithm.
function verifyRules(rules, comparison, domains, conditionsOnly) {
  const domain = domainIndex(domains), expected = new Map(), covered = new Set();
  if (comparison.checked !== domain.size || !Number.isSafeInteger(comparison.unchanged) || comparison.unchanged < 0 || comparison.changes.length + comparison.unknown.length + comparison.unchanged !== domain.size) throw new Unsupported('원본 비교의 입력 개수가 도메인과 맞지 않습니다.');
  for (const row of comparison.changes) {
    if (![row.before?.kind, row.after?.kind].every(kind => ['value', 'throw'].includes(kind))) throw new Unsupported('변경 행은 확인된 관찰만 포함해야 합니다.');
    const key = domain.tuple(row.inputs).join(',');
    if (expected.has(key)) throw new Unsupported('변경 입력이 중복됐습니다.');
    expected.set(key, pairKey(row));
  }
  const unknown = new Set();
  for (const row of comparison.unknown) {
    const key = domain.tuple(row.inputs).join(',');
    if (expected.has(key) || unknown.has(key)) throw new Unsupported('미확인 입력이 변경 행 또는 다른 미확인 행과 겹칩니다.');
    unknown.add(key);
  }
  for (const rule of rules) {
    if (!Array.isArray(rule.axes) || rule.axes.length !== domain.names.length) throw new Unsupported('규칙 축이 도메인과 일치하지 않습니다.');
    for (const [axis, values] of rule.axes.entries()) {
      if (!Array.isArray(values) || !values.length || new Set(values).size !== values.length || values.some(index => !Number.isSafeInteger(index) || index < 0 || index >= domains[domain.names[axis]].length)) throw new Unsupported('규칙 값 인덱스 오류');
    }
    let rows = 0;
    const outcomes = new Set();
    function expand(axis, tuple) {
      if (axis < rule.axes.length) { for (const value of rule.axes[axis]) expand(axis + 1, [...tuple, value]); return; }
      const key = tuple.join(',');
      if (covered.has(key) || !expected.has(key) || (!conditionsOnly && expected.get(key) !== pairKey(rule))) throw new Unsupported('규칙이 미변경·미확인 입력을 포함하거나 결과가 다르거나 겹칩니다.');
      outcomes.add(expected.get(key));
      covered.add(key); rows++;
    }
    expand(0, []);
    if (rows !== rule.matchedRows) throw new Unsupported('규칙의 입력 개수가 일치하지 않습니다.');
    if (conditionsOnly && (Object.hasOwn(rule, 'before') || Object.hasOwn(rule, 'after') || rule.distinctOutcomePairs !== outcomes.size)) throw new Unsupported('변경 조건은 단일 결과를 주장할 수 없으며 결과 쌍 개수가 맞아야 합니다.');
  }
  if (covered.size !== expected.size) throw new Unsupported('규칙이 일부 변경 입력을 빠뜨렸습니다.');
  return { coveredChangedRows: covered.size, overlaps: 0, extraRows: 0 };
}

export const verifyChangeRules = (rules, comparison, domains) => verifyRules(rules, comparison, domains, false);
export const verifyChangeConditions = (rules, comparison, domains) => verifyRules(rules, comparison, domains, true);

function changedEnvelope(comparison, domain) {
  if (!comparison.changes.length) return null;
  const axes = domain.names.map(() => new Set());
  for (const row of comparison.changes) domain.tuple(row.inputs).forEach((index, axis) => axes[axis].add(index));
  const unknownRows = comparison.unknown.filter(row => domain.tuple(row.inputs).every((index, axis) => axes[axis].has(index))).length;
  const matchedRows = axes.reduce((size, values) => size * values.size, 1);
  return { axes: axes.map(values => [...values].sort((a, b) => a - b)), matchedRows,
    changedRows: comparison.changes.length, unknownRows, unchangedRows: matchedRows - comparison.changes.length - unknownRows,
    scope: '변경 입력을 모두 포함하는 축별 공통 범위; 내부의 모든 입력에서 변경된다는 뜻은 아님' };
}

function summarize(comparison, domains, { rowLimit = 8192, workLimit = 2000000 } = {}, conditionsOnly = false) {
  try {
    if (!Number.isSafeInteger(rowLimit) || rowLimit < 0 || !Number.isSafeInteger(workLimit) || workLimit < 0) throw new Unsupported('규칙 생성 제한은 0 이상의 정수여야 합니다.');
    const domain = domainIndex(domains);
    if (comparison.checked !== domain.size || comparison.changes.length + comparison.unknown.length + comparison.unchanged !== domain.size) throw new Unsupported('원본 비교의 입력 개수가 도메인과 맞지 않습니다.');
    if (comparison.changes.length > rowLimit) throw new Unsupported('규칙 생성의 변경 행 제한 초과');
    let cubes = comparison.changes.map(row => ({ axes: domain.tuple(row.inputs).map(index => [index]), before: row.before, after: row.after, matchedRows: 1 }));
    cubes.sort((a, b) => { const x = JSON.stringify(a.axes), y = JSON.stringify(b.axes); return x < y ? -1 : x > y ? 1 : 0; });
    let work = 0, limited = false, changed = true;
    while (changed) {
      changed = false;
      for (let axis = 0; axis < domain.names.length; axis++) {
        const groups = new Map();
        for (const cube of cubes) {
          work += 1 + cube.axes.reduce((sum, values) => sum + values.length, 0);
          if (work > workLimit) { limited = true; break; }
          const key = JSON.stringify([conditionsOnly ? null : pairKey(cube), cube.axes.map((values, index) => index === axis ? null : values)]);
          if (!groups.has(key)) groups.set(key, []);
          groups.get(key).push(cube);
        }
        if (limited) break;
        const merged = [];
        for (const group of groups.values()) {
          const first = group[0], values = [...new Set(group.flatMap(cube => cube.axes[axis]))].sort((a, b) => a - b);
          if (values.length !== group.reduce((sum, cube) => sum + cube.axes[axis].length, 0)) throw new Unsupported('겹치는 변경 입력은 합칠 수 없습니다.');
          merged.push({ axes: first.axes.map((items, index) => index === axis ? values : items),
            before: first.before, after: first.after, matchedRows: group.reduce((sum, cube) => sum + cube.matchedRows, 0) });
          if (group.length > 1) changed = true;
        }
        cubes = merged;
      }
      if (limited) break;
    }
    if (conditionsOnly) {
      // Count distinct observations using the original rows. The condition
      // projection deliberately carries no representative before/after pair.
      const outcomes = new Map(comparison.changes.map(row => [domain.tuple(row.inputs).join(','), pairKey(row)]));
      cubes = cubes.map(cube => {
        const pairs = new Set();
        function expand(axis, tuple) {
          if (axis < cube.axes.length) { for (const value of cube.axes[axis]) expand(axis + 1, [...tuple, value]); return; }
          pairs.add(outcomes.get(tuple.join(',')));
        }
        expand(0, []);
        return { axes: cube.axes, matchedRows: cube.matchedRows, distinctOutcomePairs: pairs.size };
      });
    }
    const verification = verifyRules(cubes, comparison, domains, conditionsOnly);
    return { status: conditionsOnly ? 'verified-finite-change-conditions' : 'verified-finite-cover', names: domain.names,
      optimization: limited ? 'work-limit' : 'greedy-fixed-point', rules: cubes, verification,
      ...(conditionsOnly ? { envelope: changedEnvelope(comparison, domain) } : {}),
      scope: conditionsOnly ? '명시한 유한 도메인 안에서 차이가 생긴 입력만 정확히 덮는 조건; 같은 결과·변경 원인·도메인 밖 일반화를 주장하지 않음' : '명시한 유한 도메인 안의 변경 입력만 정확히 덮는 규칙; 최소 규칙 수나 도메인 밖 일반화는 보증하지 않음' };
  } catch (error) {
    if (!(error instanceof Unsupported)) throw error;
    return { status: 'not-generated', reason: error.message };
  }
}

export const summarizeChanges = (comparison, domains, options) => summarize(comparison, domains, options, false);
export const summarizeChangeConditions = (comparison, domains, options) => summarize(comparison, domains, options, true);
