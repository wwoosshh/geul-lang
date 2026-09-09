// An observation delta, not a source patch or proof about unobserved fields.
// Every completed delta is replayed against the before value to ensure that
// field presence, scalar tags, and nested boundaries reconstruct the after.
export function diffRecordValues(before, after, { maxChanges = 64, workLimit = 16384, maxDepth = 32, byteLimit = 1024 * 1024 } = {}) {
  try {
    if (![maxChanges, workLimit, maxDepth, byteLimit].every(value => Number.isSafeInteger(value) && value >= 0) ||
        maxChanges > 1024 || workLimit > 131072 || maxDepth > 64 || byteLimit > 8 * 1024 * 1024) throw Error('속성 변경 보기의 제한값 오류');
    let work = workLimit, bytes = byteLimit;
    const fail = reason => { throw Error(reason); };
    const spend = () => { if (--work < 0) fail('속성 변경 보기 작업량 제한'); };
    const text = value => { if ((bytes -= value.length * 6) < 0) fail('속성 변경 보기 용량 제한'); };
    const isRecord = value => value !== null && typeof value === 'object' && !Array.isArray(value) && Object.hasOwn(value, '$record');
    function canonical(value, depth = 0) {
      spend();
      if (depth > maxDepth) fail('속성 변경 보기 중첩 제한');
      if (value === null || typeof value === 'boolean') return value;
      if (typeof value === 'string') { text(value); return value; }
      if (typeof value === 'number' && Number.isFinite(value) && !Object.is(value, -0)) return value;
      if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).length !== 1) fail('속성 변경 보기의 값 인코딩 오류');
      if (Object.hasOwn(value, '$value') && ['undefined', 'NaN', 'Infinity', '-Infinity', '-0'].includes(value.$value)) return { $value: value.$value };
      if (Object.hasOwn(value, '$array') && Array.isArray(value.$array)) {
        const items = value.$array;
        if (Reflect.ownKeys(items).length !== items.length + 1) fail('속성 변경 보기의 배열 인코딩 오류');
        const array = [];
        for (let index = 0; index < items.length; index++) {
          const descriptor = Object.getOwnPropertyDescriptor(items, String(index));
          if (!descriptor || !Object.hasOwn(descriptor, 'value') || !descriptor.enumerable) fail('속성 변경 보기의 배열 인코딩 오류');
          array.push(canonical(descriptor.value, depth + 1));
        }
        return { $array: array };
      }
      if (!isRecord(value) || !value.$record || typeof value.$record !== 'object' || Array.isArray(value.$record)) fail('속성 변경 보기는 스칼라·값 레코드·인코딩된 배열에 한정');
      return { $record: Object.fromEntries(Object.keys(value.$record).sort().map(key => {
        text(key);
        return [key, canonical(value.$record[key], depth + 1)];
      })) };
    }
    const left = canonical(before), right = canonical(after);
    if (!isRecord(left) || !isRecord(right)) fail('전후 결과가 모두 값 레코드여야 함');
    const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
    const changes = [];
    const push = change => {
      if (changes.length >= maxChanges) fail('속성 변경 보기 항목 제한');
      changes.push(change);
    };
    function walk(a, b, path = []) {
      spend();
      if (equal(a, b)) return;
      if (isRecord(a) && isRecord(b)) {
        for (const key of [...new Set([...Object.keys(a.$record), ...Object.keys(b.$record)])].sort()) {
          spend();
          const here = [...path, key], hasBefore = Object.hasOwn(a.$record, key), hasAfter = Object.hasOwn(b.$record, key);
          if (!hasBefore) push({ kind: 'added', path: here, after: b.$record[key] });
          else if (!hasAfter) push({ kind: 'removed', path: here, before: a.$record[key] });
          else walk(a.$record[key], b.$record[key], here);
        }
      } else push({ kind: 'changed', path, before: a, after: b });
    }
    walk(left, right);
    const reconstructed = structuredClone(left);
    for (const change of changes) {
      let parent = reconstructed;
      for (const key of change.path.slice(0, -1)) {
        if (!isRecord(parent) || !Object.hasOwn(parent.$record, key)) fail('속성 변경 재검사 경로 오류');
        parent = parent.$record[key];
      }
      if (!isRecord(parent)) fail('속성 변경 재검사 부모 오류');
      const key = change.path.at(-1), fields = parent.$record, present = Object.hasOwn(fields, key);
      if (change.kind === 'added' ? present : !present || !equal(fields[key], change.before)) fail('속성 변경 재검사 이전 값 오류');
      if (change.kind === 'removed') delete fields[key];
      else Object.defineProperty(fields, key, { value: change.after, enumerable: true, configurable: true, writable: true });
    }
    // Rebuild keys independently of the insertion order of the delta.
    // This also charges the final verification against the same resource cap.
    if (!equal(canonical(reconstructed), right)) fail('속성 변경으로 원래 관찰 결과를 복원하지 못함');
    return { status: 'verified-observation-delta', changes, reconstructedAfter: true,
      scope: '인코딩된 전후 결과의 자체 속성 값과 존재 여부·배열 원소 순서; 객체 동일성·객체 속성 열거 순서·관찰 밖 동작 제외' };
  } catch (error) {
    return { status: 'not-generated', reason: error.message };
  }
}
