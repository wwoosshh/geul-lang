import test from 'node:test';
import assert from 'node:assert/strict';
import { indexFunctionResult } from '../src/function-results.mjs';
import { renderFunctionResultLinks } from '../src/report.mjs';

const index = source => indexFunctionResult(source, { functionName: 'normalize', filename: '/context.tsx' });
const prelude = 'function normalize(input: any) { return input; }\n';
const snippet = (source, loc) => source.slice(loc.start, loc.end);

test('source context keeps ordered else-if reads and earlier return separate from later values', () => {
  const source = prelude + `function caller(input: any) {
  const before = work();
  if (missing()) { return; }
  const { value } = normalize(input);
  if (provider.kind === 'one') sendOne({ value });
  else if (provider.kind === 'two') sendTwo({ value });
  else sendFallback({ value });
}`;
  const artifact = index(source);
  const ctx = artifact.callContext;
  assert.equal(ctx.kind, 'syntactic-source-context');
  assert.equal(ctx.reachabilityProven, false);
  assert.equal(ctx.guards.length, 0);
  assert.equal(ctx.precedingStatements.length, 2);
  assert.deepEqual(ctx.precedingStatements[1].immediateExits.branches.map(row => [row.accepts, row.kind]), [['truthy', 'return']]);
  assert.equal(snippet(source, ctx.precedingStatements[1].immediateExits.condition), 'missing()');
  const paths = artifact.connections[0].uses.map(use => use.context.guards.map(row => [snippet(source, row.condition), row.accepts]));
  assert.deepEqual(paths, [
    [["provider.kind === 'one'", 'truthy']],
    [["provider.kind === 'one'", 'falsy'], ["provider.kind === 'two'", 'truthy']],
    [["provider.kind === 'one'", 'falsy'], ["provider.kind === 'two'", 'falsy']],
  ]);
  assert.ok(artifact.connections[0].uses.every(use => use.context.precedingStatements.length === 3));
  const report = renderFunctionResultLinks(artifact, { snippets: node => snippet(source, node) });
  assert.match(report, /missing\(\)/);
  assert.match(report, /return 구문/);
  assert.match(report, /반복해서 읽는 속성 값이 같다고 가정/);
  assert.match(report, /완전한 제어 흐름 그래프가 아니다/);
});

test('nested callbacks stop branch inheritance at the function boundary', () => {
  const source = prelude + `function caller(input: any) {
  if (outer) register(() => {
    if (skip) return;
    const { value } = normalize(input);
    if (inner) later(() => { sink({ value }); });
    go && sink({ value });
    go || sink({ value });
    go ?? sink({ value });
    go ? sink({ value }) : sink({ value });
  });
}`;
  const artifact = index(source);
  assert.equal(artifact.callContext.guards.length, 0);
  assert.deepEqual(artifact.callContext.enclosingFunctions.map(row => row.name), [null, 'caller']);
  assert.equal(artifact.connections[0].uses[0].nestedFunction, true);
  assert.deepEqual(artifact.connections[0].uses[0].context.guards, []);
  assert.deepEqual(artifact.connections[0].uses.slice(1).map(use => use.context.guards.map(row => row.accepts)), [['truthy'], ['falsy'], ['nullish'], ['truthy'], ['falsy']]);
  assert.ok(!JSON.stringify(artifact.callContext.guards).includes('outer'));
});

test('loop, exception, switch and class field boundaries are disclosed without inferred predicates', () => {
  const source = prelude + `function caller(input: any) {
  const { value } = normalize(input);
  for (const item of list) { if (item) sink({ value }); }
  try { sink({ value }); } catch (error) { sink({ value }); } finally { sink({ value }); }
  switch (choice) { case 0: noop(); default: sink({ value }); }
  class Field { field = sink({ value }); }
  const optional = receiver?.other(sink({ value }));
}`;
  const uses = index(source).connections[0].uses;
  assert.deepEqual(uses.map(use => use.context.boundaries.map(row => row.kind)), [
    ['loop'], ['try-body'], ['catch-body'], ['finally-body'], ['switch-clause'], ['class-field'], ['optional-call'],
  ]);
  assert.equal(uses[0].context.guards.length, 1);
  assert.ok(uses.slice(1).every(use => use.context.guards.length === 0));
  assert.equal(uses[5].context.owner, null);
});

test('only a directly written sole return or throw is described as an immediate exit', () => {
  const source = prelude + `function caller(input: any) {
  if (first) { return value(); } else { throw error; }
  if (second) { mutate(); return; }
  if (third) { function nested() { return; } }
  const { value } = normalize(input);
  sink({ value });
}`;
  const previous = index(source).callContext.precedingStatements;
  assert.deepEqual(previous[0].immediateExits.branches.map(row => [row.accepts, row.kind]), [['truthy', 'return'], ['falsy', 'throw']]);
  assert.equal(previous[1].immediateExits, undefined);
  assert.equal(previous[2].immediateExits, undefined);
});

test('other declarators in the selected const statement are not hidden from review', () => {
  const source = prelude + `function caller(input: any) {
  const earlier = first(), { value } = normalize(input), later = last();
  sink({ value });
}`;
  const artifact = index(source);
  assert.deepEqual(artifact.callContext.precedingDeclarators.map(row => snippet(source, row)), ['earlier = first()']);
  assert.equal(artifact.connections[0].uses[0].context.precedingStatements[0].declarations.length, 3);
  const report = renderFunctionResultLinks(artifact, { snippets: node => snippet(source, node) });
  assert.match(report, /later = last\(\)/);
  assert.match(report, /같은 선언문 안에서 먼저 적힌/);
});

test('repeated source contexts cannot expand a small source into an unbounded artifact', () => {
  const source = prelude + `function caller(input: any) {
${Array.from({ length: 256 }, (_, i) => `const earlier${i} = unknown();`).join('\n')}
const { value } = normalize(input);
${'sink({ value });\n'.repeat(256)}
}`;
  assert.ok(Buffer.byteLength(source) < 20_000);
  assert.throws(() => index(source), /소스 문맥 출력 제한/);
});
