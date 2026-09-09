import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { ARRAY_PROFILE, ARRAY_LIMIT, encode, decode, observe, compare, Unsupported } from '../src/core.mjs';
import { liftConstBindings } from '../src/const-bindings.mjs';
import { describe, describeComparison } from '../src/presentation.mjs';
import { renderExecution } from '../src/report.mjs';
import { summarizeChanges, verifyChangeRules } from '../src/change-rules.mjs';

const pack = value => encode(value, 0, undefined, { arrays: true });
const unpack = value => decode(value, 0, { arrays: true });
const lift = expression => liftConstBindings(`const result = ${expression};`, { startLine: 1, endLine: 1, outputs: ['result'], arrayProfile: ARRAY_PROFILE, filename: '/arrays.ts' });
// Observation only: move ordinary, known-pure fixture outputs between realms.
// This converter is never used to qualify unknown upstream arrays or objects.
function tree(value) {
  if (Array.isArray(value)) return Array.from(value, tree);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, tree(item)]));
  return value;
}
function native(expression, inputs) {
  try { return { kind: 'value', value: pack(tree(new vm.Script(`({ result: (${expression}) })`).runInNewContext(Object.fromEntries(Object.entries(inputs).map(([key, value]) => [key, unpack(value)])), { timeout: 100 }))) }; }
  catch (error) { if (error.name !== 'TypeError') throw error; return { kind: 'throw', name: error.name }; }
}
function check(expression, inputs) {
  const artifact = lift(expression), expected = native(expression, inputs);
  assert.deepEqual(observe(artifact.ir, inputs), expected, expression);
  return artifact;
}

test('dense array codec preserves order, undefined and signed zero; malformed and exotic profiles are refused', () => {
  const value = [undefined, null, -0, NaN, Infinity, { id: 'x' }, []];
  assert.deepEqual(pack(unpack(pack(value))), pack(value));
  assert.throws(() => encode(value), Unsupported);
  assert.throws(() => decode(pack(value)), Unsupported);
  let getterCalls = 0;
  const accessor = [1]; Object.defineProperty(accessor, '0', { get() { getterCalls++; return 1; } });
  const nonEnumerable = [1]; Object.defineProperty(nonEnumerable, '0', { enumerable: false });
  const extra = [1]; extra.custom = 2;
  const species = [1]; species.constructor = Array;
  const spreadable = [1]; spreadable[Symbol.isConcatSpreadable] = false;
  class Derived extends Array {}
  for (const bad of [Array(1), extra, accessor, nonEnumerable, species, spreadable, new Derived(1), Object.setPrototypeOf([1], null), Array(ARRAY_LIMIT + 1)]) assert.throws(() => pack(bad), Unsupported);
  assert.equal(getterCalls, 0);
  for (const bad of [Array(1), extra, accessor, nonEnumerable, Array(ARRAY_LIMIT + 1)]) assert.throws(() => unpack({ $array: bad }), Unsupported);
  assert.equal(getterCalls, 0);
  assert.throws(() => unpack({ $array: [undefined] }), Unsupported);
  const old = liftConstBindings('const result = input;', { startLine: 1, endLine: 1, outputs: ['result'] });
  assert.equal(observe(old.ir, { input: pack([]) }).kind, 'unsupported');
});

test('pure filter agrees with native JavaScript for ordered finite transaction lists and abrupt completion', () => {
  const expression = 'rows.filter(t => !t.is_child)', artifact = lift(expression);
  assert.deepEqual(artifact.inputs, ['rows']);
  const elements = [{ id: 'missing' }, { id: 'false', is_child: false }, { id: 'true', is_child: true }, { id: 'zero', is_child: 0 }, { id: 'one', is_child: 1 }, { id: 'empty', is_child: '' }, { id: 'text', is_child: 'yes' }, null];
  for (let seed = 0; seed < 160; seed++) {
    const rows = Array.from({ length: seed % 7 }, (_, index) => elements[(seed * 3 + index * 5) % elements.length]);
    const inputs = { rows: pack(rows) };
    assert.deepEqual(observe(artifact.ir, inputs), native(expression, inputs), `seed ${seed}`);
  }
  const observation = observe(artifact.ir, { rows: pack([{ is_child: false }, null, { is_child: true }]) }, { trace: true });
  assert.equal(observation.kind, 'throw');
  assert.deepEqual(observation.trace.filter(event => event.event === 'filter-item').map(event => event.index), [0]);
  assert.equal(observation.trace.some(event => event.event === 'filter-result'), false);
});

test('filter callback lexical scopes preserve same-name shadowing and outer captures', () => {
  const expression = 'rows.filter(t => t.children.filter(t => t > limit).length > 0 && t.id === wanted)';
  const inputs = { rows: pack([{ id: 'a', children: [1, 3] }, { id: 'b', children: [5] }, { id: 'a', children: [] }]), limit: 2, wanted: 'a' };
  const artifact = check(expression, inputs);
  assert.deepEqual(artifact.inputs, ['limit', 'rows', 'wanted']);
  assert.ok(artifact.bindings.inputs.every(input => input.name !== 't'));
  assert.doesNotMatch(describe(artifact.ir), /\\u0000/);
  check('rows.filter(undefined => undefined === marker)', { rows: pack([1, 2, undefined]), marker: 2 });
  check('rows.filter(t => ({ t }).t > limit)', { rows: pack([1, 3]), limit: 1 });
  check('rows.filter(t => t.children.filter(u => u > t.limit).length)', { rows: pack([{ children: [1, 3], limit: 2 }, { children: [1], limit: 2 }]) });
});

test('concat keeps duplicates and shallow element order, evaluates every argument before copying', () => {
  check('first.concat(second, third)', { first: pack([1, 1, -0]), second: pack([null, undefined]), third: pack([[2], { id: 'x' }]) });
  check('first.concat()', { first: pack([1]) });
  check('[1, 2].concat([3]).filter(t => t > 1)', {});
  // Argument 1 is outside concat's accepted profile, but argument 2 throws
  // before the algorithm may reject/copy argument 1.
  const artifact = check('first.concat(bad, later.value)', { first: pack([]), bad: 1, later: null });
  const observation = observe(artifact.ir, { first: pack([1]), bad: 1, later: null }, { trace: true });
  assert.equal(observation.trace.some(event => event.event === 'concat-part'), false);
  const nullReceiver = lift('first.concat(missing.unknown)');
  assert.deepEqual(observe(nullReceiver.ir, { first: null }), { kind: 'throw', name: 'TypeError' });
  assert.deepEqual(observe(lift('first.filter(t => t)').ir, { first: null }), { kind: 'throw', name: 'TypeError' });
  assert.equal(observe(lift('first.concat(bad)').ir, { first: pack([]), bad: 3 }).kind, 'unsupported');
});

test('branch short circuit skips unselected collection operations without inventing array identity', () => {
  const expression = 'selected ? rows : preview.concat(rows.filter(t => !t.is_child))';
  check(expression, { selected: true, rows: pack([null, 1]), preview: null });
  check('rows.length === 0 ? [] : rows["0"]', { rows: pack([]) });
  check('rows["0"]', { rows: pack([undefined]) });
  for (const expression of ['rows === rows', 'rows + 1', 'rows["1"]', 'rows.constructor', '({ ...rows })']) assert.equal(observe(lift(expression).ir, { rows: pack([1]) }).kind, 'unsupported', expression);
  assert.equal(observe(lift('rows[0]').ir, { rows: pack([1]) }).kind, 'unsupported');
  assert.equal(observe(lift('[{}].filter(t => t.missing)').ir, {}).kind, 'unsupported');
  assert.equal(observe(lift('[{}].concat([])["0"].missing').ir, {}).kind, 'unsupported');
  check('[{ field: 1 }].concat([])["0"].field', {});
});

test('array operation syntax and profile opt-in remain narrow and explicit', () => {
  for (const expression of ['rows.filter(t => { return t; })', 'rows.filter(async t => t)', 'rows.filter((t, i) => i)', 'rows.filter(({ id }) => id)', 'rows.filter((t = 1) => t)', 'rows.filter((...t) => t)', 'rows.filter(t => t, thisArg)', 'rows.filter(callback)', 'rows.filter(t => t++)', 'rows.filter(t => unknown(t))', 'rows?.filter(t => t)', 'rows.filter?.(t => t)', 'rows.concat(...other)', '[, 1]', '[...rows]', 'rows.map(t => t)']) assert.throws(() => lift(expression), Unsupported, expression);
  assert.throws(() => liftConstBindings('const result = rows.filter(t => t);', { startLine: 1, endLine: 1, outputs: ['result'] }), Unsupported);
  assert.throws(() => liftConstBindings('const result = [];', { startLine: 1, endLine: 1, outputs: ['result'], arrayProfile: 'any-array' }), Unsupported);
});

test('bounded collection evaluation truncates traces explicitly and refuses excessive result or work', () => {
  const input = pack(Array.from({ length: 700 }, () => true));
  const artifact = lift('rows.filter(t => t)'), result = observe(artifact.ir, { rows: input }, { trace: true });
  assert.equal(result.kind, 'value'); assert.equal(result.trace.length, 512); assert.equal(result.traceTruncated, true);
  const large = pack(Array.from({ length: ARRAY_LIMIT }, () => true));
  assert.equal(observe(lift('rows.concat(rows)').ir, { rows: large }).kind, 'unsupported');
  const work = observe(lift('rows.filter(t => rows.filter(u => u).length)').ir, { rows: input });
  assert.equal(work.kind, 'unsupported'); assert.match(work.reason, /단계 제한/);
});

test('finite comparison shares a dynamic work cap across both revisions and all rows', () => {
  const artifact = lift('rows.filter(t => rows.filter(u => u).length)');
  const inputs = { rows: pack(Array.from({ length: 30 }, () => true)) };
  assert.equal(observe(artifact.ir, inputs).kind, 'value');
  const domains = { rows: [inputs.rows, pack(Array.from({ length: 31 }, () => true))] };
  const completed = compare(artifact.ir, artifact.ir, domains, { workLimit: 20000 });
  assert.equal(completed.status, 'equal-in-declared-domain');
  assert.ok(completed.executionWork.charged > 3000);
  // Static IR-node count is tiny; callback repetition must still consume the
  // global comparison budget. No partial comparison object is returned.
  assert.throws(() => compare(artifact.ir, artifact.ir, domains, { workLimit: 3000 }), /비교 전체의 실행 작업량 제한/);
  const copy = lift('rows.concat(rows)');
  assert.throws(() => compare(copy.ir, copy.ir, { rows: [pack(Array.from({ length: 300 }, () => 1))] }, { workLimit: 500 }), /비교 전체의 실행 작업량 제한/);
  const spread = lift('({ ...record })');
  const record = pack(Object.fromEntries(Array.from({ length: 300 }, (_, index) => [String(index), index])));
  assert.throws(() => compare(spread.ir, spread.ir, { record: [record] }, { workLimit: 500 }), /비교 전체의 실행 작업량 제한/);
});

test('array comparison and Korean explanation preserve ordering changes and finite-rule reconstruction', () => {
  const before = lift('a.concat(b)'), after = lift('b.concat(a)');
  const domains = { a: [pack([]), pack([1])], b: [pack([]), pack([2])] };
  const comparison = compare(before.ir, after.ir, domains), changeRules = summarizeChanges(comparison, domains);
  assert.equal(comparison.checked, 4); assert.equal(comparison.changes.length, 1);
  assert.equal(changeRules.status, 'verified-finite-cover');
  assert.equal(verifyChangeRules(changeRules.rules, comparison, domains).coveredChangedRows, 1);
  const reordered = describeComparison({ ...comparison, domains, changeRules });
  assert.match(reordered, /이전 1번째부터 1개 제외 \[1\]/);
  assert.match(reordered, /이후 2번째부터 1개 추가 \[1\]/);
  const expression = 'preview.concat(rows.filter(t => !t.is_child))', artifact = lift(expression);
  const inputs = { preview: pack([{ id: 'p' }]), rows: pack([{ id: 'a', is_child: false }, { id: 'b', is_child: true }]) };
  const observation = observe(artifact.ir, inputs, { trace: true });
  const report = renderExecution(artifact, observation, { inputs, snippets: loc => `const result = ${expression};`.slice(loc.start, loc.end) });
  assert.match(report, /2개 중 1개를 원래 순서로/); assert.match(report, /중복 제거·정렬을 하지 않았다/);
  assert.match(report, /배열.*표준/s); assert.match(report, /arrays.ts:1/);
});
