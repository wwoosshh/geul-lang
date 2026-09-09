import test from 'node:test';
import assert from 'node:assert/strict';
import { liftConstBindings } from '../src/const-bindings.mjs';
import { indexComponentProps } from '../src/component-props.mjs';
import { linkOutputProps } from '../src/output-prop-links.mjs';
import { observe, encode, Unsupported } from '../src/core.mjs';
import { renderExecution } from '../src/report.mjs';

function fixture(parent = 'import { Child } from "./child";\nfunction Parent() {\nconst result = input;\nresult.amount = 9;\nreturn <Child data={result} other={false}/>;\n}', child = 'export function Child({ data, other }) { const selected = useSelected(data); return <List rows={data} busy={other}/>; }', target = {}) {
  const files = { 'parent.tsx': parent, 'child.tsx': child };
  const metadata = { 'tsconfig.json': JSON.stringify({ compilerOptions: { moduleResolution: 'bundler', module: 'esnext' } }) };
  const index = indexComponentProps({ files, entry: 'parent.tsx', tag: 'Child', properties: ['data', 'other'],
    context: { metadata, inventory: [...Object.keys(files), 'tsconfig.json'], configPath: 'tsconfig.json' }, ...target });
  const slice = liftConstBindings(parent, { startLine: 3, endLine: 3, outputs: ['result'], filename: '/original/parent.tsx' });
  return { files, index, slice };
}

test('source join reaches a child hook and JSX reference without replacing their values with the earlier observation', () => {
  const { files, index, slice } = fixture(), links = linkOutputProps(slice, index);
  assert.equal(links.status, 'source-indexes-linked'); assert.equal(links.links.length, 1);
  const link = links.links[0];
  assert.equal(link.name, 'result'); assert.equal(link.property, 'data'); assert.equal(link.parameter.name, 'data');
  assert.equal(link.childUses.length, 2);
  const hook = link.childUses.find(use => use.kind === 'other-reference');
  assert.equal(files['child.tsx'].slice(hook.expression.start, hook.expression.end), 'useSelected(data)');
  assert.deepEqual(links.unlinkedProperties, ['other']);
  const inputs = { input: encode({ amount: 1 }) }, observation = observe(slice.ir, inputs, { trace: true });
  assert.equal(observation.value.$record.result.$record.amount, 1);
  const report = renderExecution(slice, observation, { inputs, outputPropLinks: links, propIndex: index,
    propSnippets: source => files[source.file.slice('/project/'.length)].slice(source.start, source.end) });
  assert.match(report, /useSelected\(data\)/); assert.match(report, /List.rows 직접 참조/);
  assert.match(report, /실행 결과가 아닌 원본 탐색/); assert.match(report, /대입하지 않았다/);
  assert.equal(Object.hasOwn(link, 'value'), false);
});

test('source join refuses different source contents, engine versions and transformed prop expressions', () => {
  const { index, slice } = fixture();
  assert.throws(() => linkOutputProps({ ...slice, source: { ...slice.source, sha256: 'wrong' } }, index), Unsupported);
  assert.throws(() => linkOutputProps(slice, { ...index, engineSha256: 'old' }), Unsupported);
  const transformed = fixture('import { Child } from "./child";\nfunction Parent() {\nconst result = input;\nreturn <Child data={result.amount} other={false}/>;\n}');
  assert.throws(() => linkOutputProps(transformed.slice, transformed.index), Unsupported);
  const shadow = fixture('import { Child } from "./child";\nfunction Parent() {\nconst result = input;\nreturn <Child data={result} other={false}/>;\n}\nfunction Other(result) { return <Child data={result} other={false}/>; }', undefined, { line: 6 });
  assert.throws(() => linkOutputProps(shadow.slice, shadow.index), Unsupported);
});

test('Windows CLI source paths align with TypeScript-normalized source index paths', () => {
  const { files, index } = fixture();
  const slice = liftConstBindings(files['parent.tsx'], { startLine: 3, endLine: 3, outputs: ['result'], filename: 'C:\\original\\parent.tsx' });
  assert.notEqual(slice.source.file, slice.outputSources.bindings[0].uses[0].source.file);
  const links = linkOutputProps(slice, index);
  assert.equal(links.status, 'source-indexes-linked');
  assert.equal(links.sourceAlignment.constFile, 'C:\\original\\parent.tsx');
});

test('captured parent uses, child captures and defaults remain source metadata even after a failed observation', () => {
  const { slice, index } = fixture('import { Child } from "./child";\nfunction Parent() {\nconst result = input.value;\nreturn () => <Child data={result} other={false}/>;\n}',
    'export function Child({ data = fallback(), other }) { const later = () => useSelected(data); return <List rows={data} busy={other}/>; }');
  const links = linkOutputProps(slice, index), link = links.links[0];
  assert.equal(link.use.nestedFunction, true); assert.ok(link.defaultInitializer);
  assert.equal(link.childUses.filter(use => use.nestedFunction).length, 1);
  const observation = observe(slice.ir, { input: null }, { trace: true });
  assert.equal(observation.kind, 'throw');
  const report = renderExecution(slice, observation, { outputPropLinks: links, propIndex: index });
  assert.match(report, /기본값 식도 실행하지 않았다/); assert.match(report, /부모 참조도 다른 함수에 캡처/);
});
