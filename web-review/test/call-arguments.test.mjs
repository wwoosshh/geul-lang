import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { liftCallArguments, liftCallEntry } from '../src/call-entry.mjs';
import { encode, observe } from '../src/core.mjs';
import { buildArtifactReading, buildReading, renderReading } from '../src/reading.mjs';
import { renderExecution } from '../src/report.mjs';

const inputsFor = input => Object.fromEntries(Object.entries(input).map(([name, value]) => [name, encode(value)]));
function native(body, input) {
  let observed = { stage: 'early-return' }, realmPrototype;
  function bridge(value) {
    if (value === null || typeof value !== 'object') return encode(value);
    assert.ok([null, Object.prototype, realmPrototype].includes(Object.getPrototypeOf(value)));
    assert.equal(Object.getOwnPropertySymbols(value).length, 0);
    return { $record: Object.fromEntries(Object.entries(Object.getOwnPropertyDescriptors(value)).map(([name, descriptor]) => {
      assert.ok(Object.hasOwn(descriptor, 'value') && descriptor.enumerable);
      return [name, bridge(descriptor.value)];
    })) };
  }
  const context = vm.createContext({ ...input, save(...args) {
    observed = Object.fromEntries(args.map((value, index) => [`argument${index + 1}`, bridge(value)]));
    observed.stage = 'arguments-ready';
  } });
  realmPrototype = vm.runInContext('Object.prototype', context, { timeout: 100 });
  try { new vm.Script(`(function(){${body}})();`).runInContext(context, { timeout: 100 }); }
  catch (error) { if (error.name !== 'TypeError') throw error; return { kind: 'throw', name: 'TypeError' }; }
  return { kind: 'value', value: { $record: observed } };
}
const ready = (...values) => ({ kind: 'value', value: { $record: { ...Object.fromEntries(values.map((value, index) => [`argument${index + 1}`, encode(value)])), stage: 'arguments-ready' } } });
const returned = { kind: 'value', value: { $record: { stage: 'early-return' } } };

test('argument observation joins normalization and early returns to the original call payload', () => {
  const body = 'const trimmed = name.trim(); if(!trimmed || trimmed === tag.tag)return; save({id:tag.id,tag:trimmed});';
  const artifact = liftCallArguments(`function f(){${body}}`, { callee: 'save' });
  assert.equal(artifact.mode, 'call-arguments-slice'); assert.equal(artifact.excludedCall, undefined);
  assert.equal(artifact.preparedCall.calleeEvaluatedByIR, false); assert.equal(artifact.preparedCall.invokedByIR, false);
  assert.deepEqual(artifact.preparedCall.argumentNames, ['argument1']);
  for (const name of ['', ' ', 'old', ' old ', 'new', '\tnew\n', null, undefined]) {
    for (const tag of [null, undefined, {}, { tag: 'old', id: 1 }, { tag: 'new' }, { tag: '' }]) {
      assert.deepEqual(observe(artifact.ir, inputsFor({ name, tag })), native(body, { name, tag }));
    }
  }
  assert.deepEqual(observe(artifact.ir, inputsFor({ name: ' new ', tag: { id: 1, tag: 'old' } })), ready({ id: 1, tag: 'new' }));
  assert.deepEqual(observe(artifact.ir, inputsFor({ name: ' ', tag: null })), returned);
});

test('prefixes and arguments keep error order and a later argument error cannot emit readiness', () => {
  const body = 'const first = prefix.value; if(!enabled)return; save(left.value, right.value, later.value);';
  const code = `function f(){${body}}`, artifact = liftCallArguments(code, { callee: 'save' });
  for (const prefix of [null, { value: 1 }]) for (const enabled of [false, true]) for (const right of [null, { value: 3 }]) {
    const values = { prefix, enabled, left: { value: 2 }, right, later: { value: 4 } };
    assert.deepEqual(observe(artifact.ir, inputsFor(values)), native(body, values));
  }
  const values = inputsFor({ prefix: { value: 1 }, enabled: true, left: { value: 2 }, right: null, later: null });
  const result = observe(artifact.ir, values, { trace: true });
  assert.equal(result.kind, 'throw');
  const prepared = result.trace.filter(row => row.event === 'observed-call-preparation');
  assert.deepEqual(prepared.map(row => row.name), ['argument1']);
  assert.equal(code.slice(result.trace.at(-1).source.start, result.trace.at(-1).source.end), 'right.value');
  assert.deepEqual(observe(liftCallEntry(code, { callee: 'save' }).ir, values), { kind: 'value', value: true });
});

test('argument lowering uses the outer continuation scope after a shadowed inner block', () => {
  const body = 'const x = outer; {const x = inner; if(x)return;} save(x);';
  const artifact = liftCallArguments(`function f(){${body}}`, { callee: 'save' });
  for (const outer of [0, 7]) for (const inner of [false, true]) {
    assert.deepEqual(observe(artifact.ir, { outer, inner }), native(body, { outer, inner }));
  }
  assert.deepEqual(observe(artifact.ir, { outer: 7, inner: false }), ready(7));
  assert.deepEqual(observe(liftCallArguments('function f(){save();}', { callee: 'save' }).ir, {}), ready());
});

test('unsupported argument expressions and spreads are refused even after an unconditional return', () => {
  for (const code of ['function f(){save(explode());}', 'function f(){return; save(explode());}', 'function f(){save(...items);}',
    'function f(){save([1,2]);}', `function f(){save(${Array(33).fill('1').join(',')});}`]) {
    assert.throws(() => liftCallArguments(code, { callee: 'save' }));
  }
  assert.equal(liftCallEntry('function f(){save(explode());}', { callee: 'save' }).mode, 'call-entry-slice');
});

test('callee read failure and failed invocation remain outside the argument snapshot contract', () => {
  const body = 'save(argument.value);', artifact = liftCallArguments(`function f(){${body}}`, { callee: 'save' });
  const snapshot = observe(artifact.ir, inputsFor({ argument: { value: 7 } }));
  assert.deepEqual(snapshot, ready(7));
  const events = [], sandbox = { argument: { get value() { events.push('argument'); return 7; } } };
  // A lexical TDZ is an explicit callee-read failure. A host-defined global
  // accessor can instead be mediated by Node's contextification machinery.
  const beforeInitialization = `function f(){${body}} f(); let save;`;
  assert.throws(() => new vm.Script(beforeInitialization).runInNewContext(sandbox, { timeout: 100 }), { name: 'ReferenceError' });
  assert.deepEqual(events, []);
  assert.throws(() => new vm.Script(body).runInNewContext({ save: 0, argument: { value: 7 } }, { timeout: 100 }), { name: 'TypeError' });
  assert.match(artifact.contract.assumptions.join(' '), /값 읽기는 순수하게 정상 완료/);
  assert.match(artifact.contract.notProven.join(' '), /호출 가능성/);
});

test('reading and execution describe argument preparation without an actual call or a Boolean return', () => {
  const code = 'function f(){ const value = name.trim(); if(!value)return; save(value, item.value); }';
  const artifact = liftCallArguments(code, { callee: 'save' }), snippets = row => code.slice(row.start, row.end);
  const reading = renderReading(artifact, buildArtifactReading(artifact), { snippets });
  assert.match(reading, /1번째 인수의 값/); assert.match(reading, /모든 인수 계산 완료/);
  assert.match(reading, /값 읽기는 정상 완료한다고 가정/);
  const values = inputsFor({ name: ' new ', item: { value: 3 } });
  const text = renderExecution(artifact, observe(artifact.ir, values, { trace: true }), { inputs: values, snippets });
  assert.match(text, /인수 1: "new"/); assert.match(text, /인수 2: 3/);
  assert.match(text, /실제 호출은 실행하지 않음/);
  const broken = structuredClone(artifact.ir);
  const find = node => node.projection === 'call-argument-values' ? node : node.body ? find(node.body) : node.yes ? find(node.yes) : null;
  find(broken).properties.at(-1).value.value = 'invented-stage';
  assert.throws(() => buildReading(broken), /보고용 레코드 구조/);
});

test('sequential call reading keeps branch-local work nested and distinguishes return from argument preparation', () => {
  const code = 'function f(){const outer = name.trim(); if(enabled){const inner = other.value; if(inner)return;} save(outer);}';
  const artifact = liftCallArguments(code, { callee: 'save' });
  const reading = buildArtifactReading(artifact), text = renderReading(artifact, reading), lines = text.split('\n');
  const inner = lines.find(line => line.includes('「inner」에 아래 계산값'));
  assert.ok(inner?.startsWith('    - '));
  assert.ok(lines.includes('  - 조건이 참으로 취급될 때의 결과:'));
  assert.ok(lines.includes('      - 조건이 참으로 취급될 때의 결과:'));
  const find = node => [node, ...node.children.flatMap(row => find(row.node))];
  const returns = find(reading.tree).filter(row => row.kind === 'record' && row.children.length === 1 && row.children[0].node.text.includes('값 없는 return'));
  assert.equal(returns.length, 1);
  assert.match(returns[0].text, /값 없는 return/);
  assert.doesNotMatch(returns[0].text, /인수를 적힌 순서로 계산한 뒤/);
  assert.deepEqual(observe(artifact.ir, inputsFor({ name: ' x ', enabled: false, other: null })), ready('x'));
  assert.equal(observe(artifact.ir, inputsFor({ name: ' x ', enabled: true, other: null })).kind, 'throw');
});
