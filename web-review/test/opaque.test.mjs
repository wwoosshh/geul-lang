import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { liftExpression } from '../src/typescript.mjs';
import { liftProject } from '../src/project.mjs';
import { observe, compare, encode, decode, Unsupported } from '../src/core.mjs';
import { summarizeChanges } from '../src/change-rules.mjs';

const opaque = { $opaque: 'truthy-object' };
const expression = text => liftExpression(`const result = ${text};`, text).ir;
test('an explicitly opaque object preserves supported observations across different concrete structures', () => {
  const values = [{}, [], new Date(0), new Map(), /abc/];
  const expressions = ['!x', '!!x', 'typeof x', 'x == null', 'x != null', 'x === null', 'x === true', 'x ? 1 : 2', 'x && false', '!x || true'];
  for (const text of expressions) for (const x of values) {
    const expected = new vm.Script(text).runInNewContext({ x }, { timeout: 100 });
    assert.deepEqual(observe(expression(text), { x: opaque }), { kind: 'value', value: encode(expected) });
  }
});

test('opaque data cannot quietly become an empty record or a known return value', () => {
  for (const text of ['x', 'x || false', 'x ?? null', 'x.value', 'x + 1', 'x === other']) {
    assert.equal(observe(expression(text), { x: opaque, other: opaque }).kind, 'unsupported', text);
  }
  const source = 'export function f(x: any) { return { item: x }; }';
  const artifact = liftProject({ files: { 'a.ts': source }, entry: 'a.ts', functionName: 'f' });
  assert.equal(observe(artifact.ir, { x: opaque }).kind, 'unsupported');
  assert.throws(() => encode(decode(opaque)), Unsupported);
  assert.deepEqual(encode(decode({ $record: { item: opaque } }), 0, undefined, { input: true }), { $record: { item: opaque } });
});

test('comparison and finite rules retain unknown opaque returns while describing known Boolean changes', () => {
  const domains = { x: [null, opaque] };
  const result = compare(expression('!x'), expression('x != null'), domains);
  assert.equal(result.unknown.length, 0);
  assert.equal(summarizeChanges(result, domains).status, 'verified-finite-cover');
  const uncertain = compare(expression('x'), expression('x'), domains);
  assert.equal(uncertain.status, 'inconclusive');
  assert.equal(uncertain.unknown.length, 1);
  assert.equal(uncertain.unchanged, 1);
});
