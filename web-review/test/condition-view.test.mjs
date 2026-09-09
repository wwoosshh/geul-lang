import test from 'node:test';
import assert from 'node:assert/strict';
import { encode, compare } from '../src/core.mjs';
import { projectFiniteConditions, finiteBooleanView } from '../src/condition-view.mjs';
import { liftJsxFlow } from '../src/jsx-flow.mjs';
import { describeBooleanConditions, describeBooleanChange } from '../src/presentation.mjs';

test('field projections preserve every selected subset or refuse correlated restrictions', () => {
  const domain = [encode({ a: false, b: false }), encode({ a: false, b: true }), encode({ a: true, b: false }), encode({ a: true, b: true })];
  for (let mask = 1; mask < 15; mask++) {
    const selected = domain.flatMap((_, index) => mask & (1 << index) ? [index] : []);
    const view = projectFiniteConditions(domain, selected);
    if (!view) continue;
    const actual = domain.flatMap((value, index) => view.fields.every(field => field.values.some(candidate => JSON.stringify(candidate) === JSON.stringify(value.$record[field.path[0]]))) ? [index] : []);
    assert.deepEqual(actual, selected);
  }
  assert.equal(projectFiniteConditions(domain, [0, 3]), null);
  assert.deepEqual(projectFiniteConditions(domain, [0, 1]).fields, [{ path: ['a'], values: [false] }]);
  assert.equal(projectFiniteConditions(domain, [0, 1, 2, 3]).kind, 'unrestricted-in-domain');
});

test('projection keeps field presence, nested keys, special numbers and resource bounds explicit', () => {
  assert.equal(projectFiniteConditions([encode({}), encode({ value: undefined })], [0]), null);
  assert.equal(projectFiniteConditions([{ $opaque: 'truthy-object' }, null], [0]), null);
  const domain = [encode({ data: { 'a.b': 0 } }), encode({ data: { 'a.b': -0 } })];
  assert.deepEqual(projectFiniteConditions(domain, [1]).fields, [{ path: ['data', 'a.b'], values: [{ $value: '-0' }] }]);
  assert.equal(projectFiniteConditions(domain, [1], { workLimit: 1 }), null);
  assert.equal(projectFiniteConditions(domain, [1], { maxDepth: 1 }), null);
  assert.equal(projectFiniteConditions(domain, [1, 1]), null);
  assert.equal(projectFiniteConditions(domain, [3]), null);
  const nullable = [encode({ sidebar: null, visible: false }), encode({ sidebar: null, visible: true }), encode({ sidebar: { name: 'library' }, visible: false }), encode({ sidebar: { name: 'library' }, visible: true })];
  assert.deepEqual(projectFiniteConditions(nullable, [0, 1]).fields, [{ path: ['sidebar'], values: [null] }]);
});

test('generated conditions retain disjunctions, source evidence, errors and unknown observations', () => {
  const model = liftJsxFlow('const view = <>{a !== b && <button/>}</>;', { tag: 'button' });
  const domain = [encode({ a: false, b: false }), encode({ a: false, b: true }), encode({ a: true, b: false }), encode({ a: true, b: true })];
  const view = finiteBooleanView(model.ir, { a: [false, true], b: [false, true] });
  assert.equal(view.present, 2); assert.equal(view.absent, 2);
  assert.equal(view.rules.length, 2);
  assert.ok(view.rules.every(rule => rule.conditions.every(condition => condition.sources.length > 0)));
  assert.ok(describeBooleanConditions(view).includes('묶음 중 하나'));
  const domains = { a: [false, true], b: [false, true] };
  const delta = describeBooleanChange({ ...compare({ kind: 'literal', value: false }, model.ir, domains), domains });
  assert.ok(delta.startsWith('# 변경 범위')); assert.ok(delta.includes('전달되지 않음 → 전달됨'));
  const stateModel = liftJsxFlow('const view = <>{state.a !== state.b && <button/>}</>;', { tag: 'button' });
  const boundary = finiteBooleanView(stateModel.ir, { state: [...domain, null] });
  assert.equal(boundary.errors.length, 1); assert.equal(boundary.absent, 2);
  const unknown = finiteBooleanView({ kind: 'input', name: 'x' }, { x: [false, true, 0] });
  assert.equal(unknown.unknown.length, 1); assert.equal(unknown.absent, 1); assert.equal(unknown.present, 1);
  assert.ok(describeBooleanConditions(unknown).includes('미전달로 분류하지 않았습니다'));
  const removed = finiteBooleanView({ kind: 'literal', value: false }, { oldFlag: [false, true] });
  assert.equal(removed.checked, 2); assert.equal(removed.absent, 2); assert.equal(removed.present, 0);
});
