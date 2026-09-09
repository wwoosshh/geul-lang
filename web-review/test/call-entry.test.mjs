import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { liftCallEntry } from '../src/call-entry.mjs';
import { encode, observe } from '../src/core.mjs';
import { buildReading, buildArtifactReading, renderReading } from '../src/reading.mjs';
import { renderExecution } from '../src/report.mjs';

const body = `const trimmed = name.trim();
if (!trimmed || trimmed === tag.tag) { return; }
renameTag({ id: tag.id, tag: trimmed });`;
const source = `function rename() {\n${body}\n}`;
const inputsFor = input => Object.fromEntries(Object.entries(input).map(([key, value]) => [key, encode(value)]));
function native(body, input, callee = 'renameTag') {
  let called = false;
  try {
    new vm.Script(`(function() { ${body} })();`).runInNewContext({ ...input, [callee]() { called = true; } }, { timeout: 100 });
    return { kind: 'value', value: called };
  } catch (error) { if (error.name !== 'TypeError') throw error; return { kind: 'throw', name: 'TypeError' }; }
}

test('call entry connects a const and early return while retaining the excluded call arguments', () => {
  const artifact = liftCallEntry(source, { callee: 'renameTag', filename: 'tag.tsx' });
  assert.deepEqual(artifact.inputs, ['name', 'tag']);
  assert.equal(artifact.earlyReturns.length, 1); assert.equal(artifact.entryRegion.bindings[0].name, 'trimmed');
  assert.equal(artifact.excludedCall.evaluated, false);
  assert.equal(source.slice(artifact.excludedCall.arguments[0].start, artifact.excludedCall.arguments[0].end), '{ id: tag.id, tag: trimmed }');
  assert.equal(artifact.entryRegion.end, artifact.excludedCall.source.start);
  assert.equal(source.slice(artifact.earlyReturns[0].start, artifact.earlyReturns[0].end), 'return;');
  assert.ok(artifact.bindings.inputs.some(row => row.name === 'name'));
});

test('native callback and IR agree for trimmed names, short-circuited null tags and TypeErrors', () => {
  const artifact = liftCallEntry(source, { callee: 'renameTag' });
  let checks = 0;
  for (const name of ['', ' ', 'old', ' old ', 'new', '\tnew\n', null, undefined]) {
    for (const tag of [null, undefined, {}, { tag: 'old', id: 1 }, { tag: 'new' }, { tag: '' }]) {
      const input = { name, tag };
      assert.deepEqual(observe(artifact.ir, inputsFor(input)), native(body, input)); checks++;
    }
  }
  assert.equal(checks, 48);
  assert.deepEqual(observe(artifact.ir, inputsFor({ name: '', tag: null })), { kind: 'value', value: false });
  assert.deepEqual(observe(artifact.ir, inputsFor({ name: 'new', tag: null })), { kind: 'throw', name: 'TypeError' });
});

test('nested block bindings, branch-local shadowing and fallthrough preserve the outer continuation', () => {
  const prefix = 'const x = input; { const x = other; if (x) return; } if (x) { const y = last; if (y) return; } sink();';
  const artifact = liftCallEntry(`function f(){${prefix}}`, { callee: 'sink' });
  for (const input of [false, true]) for (const other of [false, true]) for (const last of [false, true]) {
    const values = { input, other, last };
    assert.deepEqual(observe(artifact.ir, values), native(prefix, values, 'sink'));
  }
  assert.deepEqual(artifact.inputs, ['input', 'last', 'other']);
});

test('a target without a prefix reports entry but never evaluates the target or argument', () => {
  const artifact = liftCallEntry('function f(){ save(explode()); }', { callee: 'save' });
  assert.deepEqual(artifact.inputs, []); assert.equal(artifact.entryRegion.source, null);
  assert.deepEqual(observe(artifact.ir, {}), { kind: 'value', value: true });
  assert.deepEqual(native('save(explode());', { explode() { throw new TypeError('argument'); } }, 'save'), { kind: 'throw', name: 'TypeError' });
  assert.match(artifact.contract.notProven.join(' '), /인수 평가/);
});

test('prefix lowering refuses forward and self references even behind an earlier return', () => {
  for (const prefix of ['const x = x;', 'if (x) return; const x = false;', 'return; const x = x;', 'if (flag) { if(x) return; const x = false; }']) {
    assert.throws(() => liftCallEntry(`function f(){${prefix} sink();}`, { callee: 'sink' }), /초기화 전/);
  }
});

test('unsupported statements, valued returns, async and generators cannot silently become pure entry conditions', () => {
  for (const prefix of ['log();', 'let x = 1;', 'return bad();', 'return 1;', 'throw new Error();', 'while (flag) {}', 'try {} finally {}', 'const { x } = obj;', 'const x = fetch();', 'return; mutate();']) {
    assert.throws(() => liftCallEntry(`function f(){${prefix} sink();}`, { callee: 'sink' }));
  }
  for (const code of ['async function f(){sink();}', 'function* f(){sink();}', 'function f(){sink?.();}', 'sink();', 'function f(){if(flag){sink();}}', 'function f(){sink(); return;}']) {
    assert.throws(() => liftCallEntry(code, { callee: 'sink' }));
  }
});

test('ambiguous call sites require their exact line and resource bounds precede serialization', () => {
  const multiple = 'function a(){ sink(); }\nfunction b(){ sink(); }';
  assert.throws(() => liftCallEntry(multiple, { callee: 'sink' }), /2곳/);
  assert.equal(liftCallEntry(multiple, { callee: 'sink', line: 2 }).target.line, 2);
  for (const line of [0, -1, 1.5, NaN]) assert.throws(() => liftCallEntry(multiple, { callee: 'sink', line }));
  assert.throws(() => liftCallEntry('function f(){' + 'if (flag) {} '.repeat(16) + 'sink();}', { callee: 'sink' }), /IR 크기/);
  assert.throws(() => liftCallEntry('function f(){' + ';'.repeat(129) + 'sink();}', { callee: 'sink' }), /문장 수/);
});

test('Korean reading and execution distinguish reaching a call from invoking it or returning a Boolean', () => {
  const artifact = liftCallEntry(source, { callee: 'renameTag' }), input = inputsFor({ name: '', tag: null });
  const snippets = row => source.slice(row.start, row.end);
  const reading = renderReading(artifact, buildReading(artifact.ir), { snippets });
  assert.match(reading, /함수가 true·false를 반환한다는 뜻이 아니다/);
  assert.match(reading, /이 호출은 실행하지 않았다/); assert.match(reading, /인수 1/);
  const text = renderExecution(artifact, observe(artifact.ir, input, { trace: true }), { inputs: input, snippets });
  assert.match(text, /조기 반환으로 호출 식에 도달하지 않음/);
  assert.match(text, /trimmed에/); assert.match(text, /값 없는 return/);
});

test('call entry reading labels only control-flow results and retains ordinary Boolean initializers and conditions', () => {
  const code = 'function f(){ const x = flag ? true : false; if(x){ if(other) return; } else {return;} save(); }';
  const artifact = liftCallEntry(code, { callee: 'save' });
  const generic = buildReading(artifact.ir), reading = buildArtifactReading(artifact);
  const flatten = node => [node, ...node.children.flatMap(row => flatten(row.node))];
  const nodes = flatten(reading.tree), terminals = nodes.filter(node => node.observationRole);
  assert.equal(terminals.length, 3);
  assert.deepEqual(terminals.map(node => node.reached), [false, true, false]);
  const values = nodes.filter(node => node.kind === 'literal' && !node.observationRole);
  assert.equal(values.length, 2); assert.deepEqual(values.map(node => node.fragment), ['참', '거짓']);
  assert.equal(flatten(generic.tree).filter(node => node.observationRole).length, 0);
  assert.equal(nodes.length, generic.nodeCount);
  assert.deepEqual(nodes.map(node => [node.path, node.source]), flatten(generic.tree).map(node => [node.path, node.source]));
  const text = renderReading(artifact, generic);
  assert.match(text, /값 없는 return으로 이 본문을 빠져나갑니다/);
  assert.match(text, /호출 대상·인수는 아직 계산하지 않았습니다/);
  assert.equal(text, renderReading(artifact, reading));
  for (const flag of [false, true]) for (const other of [false, true]) {
    assert.deepEqual(observe(artifact.ir, { flag, other }), native(code.slice(code.indexOf('{') + 1, -1), { flag, other }, 'save'));
  }
  const altered = structuredClone(artifact); altered.earlyReturns = [];
  assert.throws(() => buildArtifactReading(altered), /경계에 연결/);
});

test('a shadowed name in the reading distinguishes the inner branch from the resumed outer continuation', () => {
  const prefix = 'const x = first; { const x = second; if(x) return; } if(x) return; sink();';
  const artifact = liftCallEntry(`function f(){${prefix}}`, { callee: 'sink' });
  const reading = buildArtifactReading(artifact), all = [];
  function visit(node) { all.push(node); node.children.forEach(row => visit(row.node)); } visit(reading.tree);
  const declarations = all.filter(node => node.kind === 'let'), references = all.filter(node => node.kind === 'local');
  assert.deepEqual(reading.bindingNames.disambiguated, ['x']);
  assert.equal(declarations.length, 2); assert.equal(references.length, 2);
  assert.deepEqual(references.map(node => node.binding.id), [declarations[1].id, declarations[0].id]);
  assert.notEqual(references[0].fragment, references[1].fragment);
  for (const reference of references) {
    const declaration = declarations.find(node => node.id === reference.binding.id);
    assert.ok(declaration.text.includes(reference.binding.displayLabel));
    assert.ok(reference.fragment.includes(reference.binding.displayLabel));
  }
  const text = renderReading(artifact, reading);
  assert.match(text, /실행 횟수가 아니다/);
  for (const first of [false, true]) for (const second of [false, true]) {
    assert.deepEqual(observe(artifact.ir, { first, second }), native(prefix, { first, second }, 'sink'));
  }
  const simple = liftCallEntry('function f(){const x = first; if(x) return; sink();}', { callee: 'sink' });
  assert.equal(buildArtifactReading(simple).bindingNames, undefined);
  assert.doesNotMatch(renderReading(simple, buildArtifactReading(simple)), /저장 \d/);
});

test('callback source links preserve hook declaration, direct call context and object-contained JSX references', () => {
  const code = `function Screen(){
 const {mutate: save} = useSave();
 const rename = (name) => { const value = name.trim(); if(!value)return; save(value); };
 const onKey = e => { if(e.key === 'Enter'){ e.preventDefault(); rename(e.currentTarget.value); finish(); } };
 function unrelated(){ const rename = x => x; rename('shadow'); }
 const alias = rename;
 type Callback = typeof rename;
 return <Input inputProps={{onUpdate: rename, ...overrides}} onKey={onKey}/>;
}`;
  const artifact = liftCallEntry(code, { callee: 'save' }), links = artifact.sourceLinks;
  assert.equal(links.status, 'source-links-only'); assert.deepEqual(artifact.inputs, ['name']);
  assert.equal(links.callee.status, 'declaration-found');
  assert.equal(code.slice(links.callee.declarations[0].destructuringOrigin.expression.start, links.callee.declarations[0].destructuringOrigin.expression.end), 'useSave()');
  assert.equal(links.entry.name, 'rename'); assert.equal(links.entry.referenceCount, 4);
  assert.deepEqual(links.entry.references.map(row => row.kind), ['direct-call', 'other-reference', 'type-only', 'object-property']);
  const direct = links.entry.references[0];
  assert.equal(code.slice(direct.expression.start, direct.expression.end), 'rename(e.currentTarget.value)');
  assert.deepEqual(direct.context.precedingStatements.map(row => code.slice(row.source.start, row.source.end)), ['e.preventDefault();']);
  assert.deepEqual(direct.context.guards.map(row => [code.slice(row.condition.start, row.condition.end), row.accepts]), [["e.key === 'Enter'", 'truthy']]);
  const property = links.entry.references[3];
  assert.equal(property.jsxContainer.tag, 'Input'); assert.equal(property.jsxContainer.attribute, 'inputProps');
  assert.equal(property.property, 'onUpdate'); assert.equal(property.reachabilityProven, false);
  assert.match(links.notProven.join(' '), /덮어쓰기·spread/);
  const text = renderReading(artifact, buildArtifactReading(artifact), { snippets: row => code.slice(row.start, row.end) });
  assert.match(text, /실행하지 않은 초기화 문맥: useSave/);
  assert.match(text, /앞에 적힌 문장: e.preventDefault/);
  assert.match(text, /실제 전달값은 미확인/);
  assert.match(text, /타입 문맥의 참조/);
});

test('source links handle direct JSX, shorthand, optional calls and unsupported binding owners explicitly', () => {
  const code = 'const callback = () => { save(); }; const settings = { callback }; callback?.(); use(callback); const view = <X onUpdate={callback}/>;';
  const links = liftCallEntry(code, { callee: 'save' }).sourceLinks;
  assert.deepEqual(links.entry.references.map(row => row.kind), ['object-shorthand', 'optional-call', 'call-argument', 'jsx-attribute']);
  assert.equal(links.callee.status, 'unresolved-in-file');
  assert.equal(links.entry.references.at(-1).attribute, 'onUpdate');
  assert.equal(liftCallEntry('register(() => { save(); });', { callee: 'save' }).sourceLinks.entry.status, 'not-indexed');
  assert.equal(liftCallEntry('class X{ method(){ save(); } }', { callee: 'save' }).sourceLinks.entry.status, 'not-indexed');
  const repeated = 'function callback(){save();}\n' + 'consume(callback);\n'.repeat(129);
  const indexed = liftCallEntry(repeated, { callee: 'save' }).sourceLinks.entry;
  assert.equal(indexed.referenceCount, 129); assert.equal(indexed.references.length, 128); assert.equal(indexed.referencesTruncated, true);
});

test('string-normalization evidence permits empty-string wording while preserving prefix errors and unsupported values', () => {
  const prefix = 'const clean = name.trim(); const alias = clean; if(!alias)return; save();';
  const artifact = liftCallEntry(`function f(){${prefix}}`, { callee: 'save' }), reading = buildArtifactReading(artifact);
  const all = [], visit = node => { all.push(node); node.children.forEach(row => visit(row.node)); }; visit(reading.tree);
  const rule = all.find(node => node.readingRule);
  assert.equal(rule.readingRule.name, 'string-falsiness-is-empty');
  assert.equal(rule.children[0].node.normalCompletionType, 'string');
  assert.equal(rule.children[0].node.normalCompletionEvidence.rule, 'stored-string');
  assert.match(rule.fragment, /빈 문자열인지/);
  assert.equal(all.filter(node => node.kind === 'input')[0].normalCompletionType, undefined);
  for (const name of ['', ' ', '\t\n', '\u00a0', '\ufeff', '\u200b', '\u0000', '0', 'false', ' a ', '한글', '😀', '\ud800', null, undefined]) {
    assert.deepEqual(observe(artifact.ir, { name: encode(name) }), native(prefix, { name }, 'save'));
  }
  for (const name of [0, false, {}]) assert.equal(observe(artifact.ir, { name: encode(name) }).kind, 'unsupported');
  const text = renderReading(artifact, reading);
  assert.match(text, /null·undefined이면 TypeError/);
  assert.match(text, /다른 값 종류는 미지원/);
});

test('static parameter annotations and identically named inner values cannot acquire string evidence', () => {
  const code = "function f(value: string){const outer = 'saved'; {const outer = value; if(!outer)return;} if(!outer)return; save();}";
  const artifact = liftCallEntry(code, { callee: 'save' }), reading = buildArtifactReading(artifact), all = [];
  function visit(node){all.push(node);node.children.forEach(row=>visit(row.node));} visit(reading.tree);
  const negatives = all.filter(node => node.kind === 'unary');
  assert.equal(negatives.length, 2);
  assert.equal(negatives[0].readingRule, undefined); assert.match(negatives[0].fragment, /거짓으로 취급/);
  assert.equal(negatives[1].readingRule.name, 'string-falsiness-is-empty'); assert.match(negatives[1].fragment, /빈 문자열/);
  assert.notEqual(negatives[0].children[0].node.binding.id, negatives[1].children[0].node.binding.id);
  for (const value of [false, 0, '', ' ', 'text', null, undefined]) {
    assert.deepEqual(observe(artifact.ir, { value: encode(value) }), native(code.slice(code.indexOf('{') + 1, -1), { value }, 'save'));
  }
});
