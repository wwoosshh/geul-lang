import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { buildReading, renderReading } from '../src/reading.mjs';
import { liftExpression } from '../src/typescript.mjs';
import { liftConstBindings } from '../src/const-bindings.mjs';
import { liftProject } from '../src/project.mjs';
import { liftJsxProperty } from '../src/jsx-property.mjs';
import { ARRAY_PROFILE, observe, Unsupported } from '../src/core.mjs';

const lift = text => liftExpression(`const result = ${text};`, text, '/original.ts');
const nodes = reading => [reading, ...reading.children.flatMap(row => nodes(row.node))];

test('sequential reading keeps eager initializers ordered without nesting every later declaration', () => {
  const code = 'const unused = other.value;\nconst lowered = name.toLowerCase();\nconst result = enabled ? lowered : fallback;';
  const artifact = liftConstBindings(code, { filename: '/sequence.ts', startLine: 1, endLine: 3, outputs: ['result'] });
  const reading = buildReading(artifact.ir), saved = structuredClone(reading);
  const text = renderReading(artifact, reading), lines = text.split('\n');
  const declarations = ['unused', 'lowered', 'result'].map(name => lines.find(line => line.includes(`「${name}」에 아래 계산값을 저장한 뒤`)));
  assert.ok(declarations.every(line => line?.startsWith('- ')), 'Sequential declarations should stay in one flow');
  assert.ok(text.indexOf('입력 「other」') < text.indexOf('「lowered」에'));
  assert.ok(text.indexOf('소문자 변환') < text.indexOf('「result」에'));
  const conditional = lines.find(line => line.includes('저장할 값: 먼저 조건을 계산'));
  assert.ok(conditional.startsWith('  - '), 'The conditional initializer must stay inside the result declaration');
  assert.deepEqual(reading, saved, 'Rendering must retain the complete original reading tree and source links');
  assert.equal(observe(artifact.ir, { other: null, name: 'A', enabled: false, fallback: 1 }).kind, 'throw');
});

test('static reading retains both lazy branches and an eager unused initializer that can throw', () => {
  const artifact = liftConstBindings('const unused = other.value;\nconst result = enabled ? left : right;', { filename: '/original.ts', startLine: 1, endLine: 2, outputs: ['result'] });
  const reading = buildReading(artifact.ir), all = nodes(reading.tree), text = renderReading(artifact, reading);
  assert.match(text, /「unused」에 아래 계산값을 저장한 뒤/);
  assert.match(text, /선택하지 않은 갈래는 계산하지 않습니다/);
  assert.match(text, /입력 「left」/); assert.match(text, /입력 「right」/);
  assert.match(text, /기록이 아니라 가능한 계산과 분기 구조/);
  assert.equal(all.length, reading.nodeCount);
  assert.equal(new Set(all.map(row => row.path)).size, all.length);
  for (const row of all) {
    // Resolve each recorded IR path in the original immutable artifact.
    const original = row.path.slice(2).replace(/\[(\d+)\]/g, '.$1').split('.').filter(Boolean).reduce((node, key) => node[key], artifact.ir);
    assert.equal(row.kind, original.kind);
    assert.deepEqual(row.source, original.source);
  }
  assert.equal(observe(artifact.ir, { other: null, enabled: false, left: 1, right: 2 }).kind, 'throw');
});

test('short circuits describe returning operand values and conditionally evaluating the right side', () => {
  for (const [op, phrase, left, expected] of [['&&', '거짓으로 취급되면', 0, 0], ['||', '참으로 취급되면', 'yes', 'yes'], ['??', 'null·undefined가 아니면', false, false]]) {
    const artifact = lift(`left ${op} right.value`), reading = buildReading(artifact.ir);
    assert.match(reading.tree.text, new RegExp(phrase));
    assert.match(reading.tree.text, /앞값 자체를 결과로 사용/);
    assert.match(reading.tree.children[1].role, /앞값만으로 끝나지 않을 때/);
    assert.deepEqual(observe(artifact.ir, { left, right: null }), { kind: 'value', value: expected });
  }
});

test('computed access keys are rendered at their own step, with optional skip and null error order', () => {
  const artifact = lift('value?.[first.key][second.key]');
  const reading = buildReading(artifact.ir), text = renderReading(artifact, reading);
  assert.match(text, /이 키 계산과 남은 읽기를 모두 생략/);
  assert.match(text, /정상 접근의 null 오류보다 키 식 계산이 먼저/);
  assert.ok(text.indexOf('1번째:') < text.indexOf('입력 「first」'));
  assert.ok(text.indexOf('입력 「first」') < text.indexOf('2번째:'));
  assert.ok(text.indexOf('2번째:') < text.indexOf('입력 「second」'));
  assert.deepEqual(observe(artifact.ir, { value: null, first: null, second: null }), { kind: 'value', value: { $value: 'undefined' } });
});

test('only Boolean-producing operands receive a compact conjunction or disjunction', () => {
  for (const op of ['&&', '||']) {
    const raw = buildReading(lift(`left ${op} right`).ir);
    assert.equal(raw.tree.fragment, undefined);
    assert.equal(raw.tree.booleanResult, false);
    const artifact = lift(`!left ${op} !right`), reading = buildReading(artifact.ir);
    assert.equal(reading.tree.booleanResult, true);
    assert.match(reading.tree.fragment, /앞 조건이 .* 때만 뒷조건을 계산/);
    for (const left of [null, 0, '', 'x', false, true]) for (const right of [null, 0, '', 'x', false, true]) {
      const expected = op === '&&' ? !left && !right : !left || !right;
      assert.deepEqual(observe(artifact.ir, { left, right }), { kind: 'value', value: expected });
    }
  }
});

test('array callbacks preserve lexical bindings and empty-list non-execution', () => {
  const artifact = liftConstBindings('const result = groups.filter(item => item.children.filter(item => item.visible).length > 0).concat(extra);', { filename: '/arrays.ts', startLine: 1, endLine: 1, outputs: ['result'], arrayProfile: ARRAY_PROFILE });
  const reading = buildReading(artifact.ir), all = nodes(reading.tree), filters = all.filter(row => row.kind === 'array-filter');
  assert.equal(filters.length, 2);
  const locals = all.filter(row => row.kind === 'local' && row.binding.label === 'item');
  assert.equal(new Set(locals.map(row => row.binding.id)).size, 2);
  assert.deepEqual(reading.bindingNames.disambiguated, ['item']);
  assert.equal(new Set(locals.map(row => row.binding.displayLabel)).size, 2);
  for (const local of locals) {
    const owner = filters.find(filter => filter.id === local.binding.id);
    assert.deepEqual(owner.bindingDefinition, local.binding);
    assert.ok(owner.text.includes(local.binding.displayLabel));
    assert.ok(local.fragment.includes(local.binding.displayLabel));
  }
  assert.match(renderReading(artifact, reading), /빈 목록이면 조건을 한 번도 계산하지 않습니다/);
  assert.match(renderReading(artifact, reading), /인수 목록을 적힌 순서로 모두 계산/);
  assert.deepEqual(observe(artifact.ir, { groups: { $array: [] }, extra: { $array: [] } }), { kind: 'value', value: { $record: { result: { $array: [] } } } });
});

test('record observations, actual JSX structure and string operations retain their distinct contracts', () => {
  const artifact = liftConstBindings('const text = name.trim();\nconst result = { ...data, text };', { filename: '/original.ts', startLine: 1, endLine: 2, outputs: ['result'] });
  const text = renderReading(artifact, buildReading(artifact.ir));
  assert.match(text, /열거 가능한 자체 속성을 얕게 복사/);
  assert.match(text, /보고용이며 앱에 객체를 생성하는 연산이 아닙니다/);
  assert.match(text, /표준 trim/);
  const jsx = liftProject({ files: { 'screen.tsx': 'export function Screen(busy: boolean) { return <button disabled={busy}>save</button>; }' }, entry: 'screen.tsx', functionName: 'Screen' });
  assert.match(renderReading(jsx, buildReading(jsx.ir)), /React·DOM 렌더링은 별도/);
  const absent = liftJsxProperty('const view = <input/>;', { tag: 'input', attribute: 'aria-invalid', filename: '/original.tsx' });
  assert.match(renderReading(absent, buildReading(absent.ir)), /선택 속성은 원본에 없습니다/);
  assert.match(renderReading(absent, buildReading(absent.ir)), /실제 props 객체·DOM 생성 결과가 아닙니다/);
});

test('reading rejects unknown operations, lost local scope and size limits without a partial success', () => {
  assert.throws(() => buildReading({ kind: 'effect-call' }), Unsupported);
  assert.throws(() => buildReading({ kind: 'binary', op: 'invented' }), Unsupported);
  assert.throws(() => buildReading({ kind: 'local', name: 'lost' }), Unsupported);
  const artifact = lift('x ? y : z');
  for (const options of [{ nodeLimit: 2 }, { depthLimit: 0 }, { textLimit: 10 }, { nodeLimit: Infinity }]) assert.throws(() => buildReading(artifact.ir, options), Unsupported);
  const escaped = lift('flag ? "<img src=x>" : "*not emphasis*"');
  const rendered = renderReading(escaped, buildReading(escaped.ir));
  assert.doesNotMatch(rendered, /<img src=x>/);
  assert.match(rendered, /&lt;img src=x&gt;/);
});

test('normal string evidence joins only known branches and operands without rewriting unknown input falsiness', () => {
  for (const expression of ['!(flag ? "" : "x")', '!("" || "x")', '!("" && "x")', '!("" ?? "x")', '!typeof value']) {
    const artifact = lift(expression), reading = buildReading(artifact.ir);
    const original = new vm.Script(expression);
    assert.equal(reading.tree.readingRule.name, 'string-falsiness-is-empty');
    const operand = reading.tree.children[0].node;
    assert.equal(operand.normalCompletionType, 'string');
    assert.ok(operand.normalCompletionEvidence.rule);
    for (const flag of [false, true]) for (const value of [false, 0, '', ' ', null]) {
      const observed = observe(artifact.ir, { flag, value });
      assert.equal(observed.value, original.runInNewContext({ flag, value }, { timeout: 100 }));
      assert.equal(typeof observe(artifact.ir.value, { flag, value }).value, 'string');
    }
  }
  for (const expression of ['!(flag ? "" : value)', '!(value || "")', '!(value && "")', '!(value ?? "")', '!value']) {
    const reading = buildReading(lift(expression).ir);
    assert.equal(reading.tree.readingRule, undefined);
    assert.equal(reading.tree.children[0].node.normalCompletionType, undefined);
  }
});
