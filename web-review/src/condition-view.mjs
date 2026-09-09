import { decode, encode, compare, Unsupported } from './core.mjs';
import { summarizeChangeConditions } from './change-rules.mjs';

const canonical = value => JSON.stringify(encode(decode(value), 0, undefined, { input: true }));

// Factor a record-valued finite input axis into field conditions only when
// expanding those conditions over the ORIGINAL domain selects exactly the
// original indices. Correlated values must not turn into a Cartesian product.
// This is a display projection, never a theorem about unlisted objects.
export function projectFiniteConditions(domain, indices, { maxFields = 64, maxDepth = 8, workLimit = 65536 } = {}) {
  if (!Array.isArray(domain) || !domain.length || !Array.isArray(indices) || !indices.length || new Set(indices).size !== indices.length || indices.some(index => !Number.isInteger(index) || index < 0 || index >= domain.length)) return null;
  if (indices.length === domain.length) return { kind: 'unrestricted-in-domain', verified: true };
  let work = 0;
  try {
    if (domain.some(value => !value || !value.$record)) return null;
    const rows = domain.map(() => []);
    function flatten(values, path = []) {
      work += values.length;
      if (work > workLimit || path.length > maxDepth || rows[0].length >= maxFields) throw new Error('projection limit');
      const keys = values[0]?.$record ? Object.keys(values[0].$record).sort() : null;
      const sameShape = keys && values.every(value => value?.$record && JSON.stringify(Object.keys(value.$record).sort()) === JSON.stringify(keys));
      if (sameShape && keys.length) {
        for (const name of keys) flatten(values.map(value => value.$record[name]), [...path, name]);
      } else {
        if (!path.length) throw new Error('different root fields');
        // A null/object union is an atomic field restriction. Do not split it
        // into missing subfields, which would lose the null distinction.
        for (let index = 0; index < values.length; index++) {
          if (JSON.stringify(values[index]).includes('"$opaque"')) throw new Error('unknown structure');
          rows[index].push({ path, value: values[index], key: canonical(values[index]) });
        }
      }
    }
    flatten(domain);
    const fields = [];
    for (let column = 0; column < rows[0].length; column++) {
      const allowed = new Map(indices.map(index => [rows[index][column].key, rows[index][column].value]));
      const entire = new Set(rows.map(row => row[column].key));
      if (allowed.size !== entire.size) fields.push({ path: rows[0][column].path, values: [...allowed.values()], keys: [...allowed.keys()], column });
    }
    const wanted = new Set(indices);
    for (let index = 0; index < rows.length; index++) {
      const matches = fields.every(field => { if (++work > workLimit) throw new Error('projection limit'); return field.keys.includes(rows[index][field.column].key); });
      if (matches !== wanted.has(index)) return null;
    }
    return { kind: 'record-fields-in-domain', verified: true, fields: fields.map(({ path, values }) => ({ path, values })), selectedCount: indices.length };
  } catch { return null; }
}

// Classify a boolean observation, then reuse the verified finite-cover
// algorithm. The constant false is an internal membership sentinel, NOT a
// previous program revision. Exceptions and unsupported values stay separate.
export function finiteBooleanView(ir, domains) {
  // Keep the declared experiment grid even when an edit removes a free input.
  // Reading these data-only axes in the sentinel does not constrain the IR.
  const sentinel = Object.keys(domains).reduceRight((body, name, i) => ({ kind: 'let', name: `분류축${i}`,
    value: { kind: 'input', name }, body }), { kind: 'literal', value: false });
  const classified = compare(sentinel, ir, domains);
  const positive = classified.changes.filter(row => row.after.kind === 'value' && row.after.value === true);
  const errors = classified.changes.filter(row => row.after.kind === 'throw');
  const other = classified.changes.filter(row => row.after.kind === 'value' && row.after.value !== true);
  const unknown = [...classified.unknown, ...other];
  const cover = summarizeChangeConditions({ checked: classified.checked, changes: positive, unknown: [],
    unchanged: classified.checked - positive.length }, domains);
  if (cover.status !== 'verified-finite-change-conditions') throw new Unsupported(cover.reason);
  const reads = [];
  function pathOf(node, env) {
    if (node?.kind === 'input') return { name: node.name, path: [], sources: node.source ? [node.source] : [] };
    if (node?.kind === 'local') {
      const base = env.get(node.name);
      return base && { ...base, sources: [...base.sources, ...(node.source ? [node.source] : [])] };
    }
    if (node?.kind === 'access' && node.steps.every(step => typeof step.key === 'string')) {
      const base = pathOf(node.base, env);
      return base && { name: base.name, path: [...base.path, ...node.steps.map(step => step.key)],
        sources: [...base.sources, ...(node.source ? [node.source] : [])] };
    }
    return null;
  }
  function walk(node, env = new Map()) {
    if (!node || typeof node !== 'object') return;
    const subject = pathOf(node, env);
    if (subject) reads.push(subject);
    if (node.kind === 'let') {
      walk(node.value, env);
      const next = new Map(env); next.set(node.name, pathOf(node.value, env));
      walk(node.body, next); return;
    }
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) value.forEach(item => walk(item, env));
      else if (value && typeof value === 'object') walk(value, env);
    }
  }
  walk(ir);
  const rules = cover.rules.map(rule => ({ matchedRows: rule.matchedRows, axes: rule.axes,
    conditions: rule.axes.flatMap((indices, axis) => {
      const name = cover.names[axis], domain = domains[name];
      if (indices.length === domain.length) return [];
      const projection = projectFiniteConditions(domain, indices);
      const fields = projection?.kind === 'record-fields-in-domain' ? projection.fields : [{ path: [], values: indices.map(i => domain[i]) }];
      return fields.map(field => {
        const sources = reads.filter(read => read.name === name && JSON.stringify(read.path) === JSON.stringify(field.path)).flatMap(read => read.sources);
        return { name, ...field, sources: [...new Map(sources.map(source => [JSON.stringify(source), source])).values()] };
      });
    }) }));
  return { status: 'verified-finite-boolean-view', checked: classified.checked, present: positive.length,
    absent: classified.unchanged, errors, unknown, rules, names: cover.names, domains,
    verification: cover.verification,
    scope: '명시한 입력집 안에서 참인 입력만 정확히 덮는 조건 목록. 필요한 일반 조건·원인·도메인 밖 충분조건의 증명이 아님' };
}
