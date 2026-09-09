import test from 'node:test';
import assert from 'node:assert/strict';
import { indexComponentProps } from '../src/component-props.mjs';
import { Unsupported } from '../src/core.mjs';
import { renderPropertyLinks } from '../src/report.mjs';

const files = {
  'child.tsx': 'import { useExternal } from "not-loaded"; export const Child = ({ busy: pending, user }: Props) => { useExternal(); return <button disabled={pending}/>; };',
  'parent.tsx': 'import { Child as View } from "#child"; export const Parent = () => <View busy={locked} user={currentUser}/>;',
};
const context = { metadata: { 'tsconfig.json': '{"compilerOptions":{"moduleResolution":"Bundler","module":"esnext"}}', 'package.json': '{"imports":{"#child":"./child.tsx"}}' }, inventory: [...Object.keys(files), 'tsconfig.json', 'package.json'], configPath: 'tsconfig.json' };
const index = (sources = files) => indexComponentProps({ files: sources, context, entry: 'parent.tsx', tag: 'View', properties: ['busy', 'user'] });

test('original package mapping connects JSX aliases to destructured child bindings without executing modules', () => {
  const result = index();
  assert.equal(result.mode, 'component-prop-bindings');
  assert.equal(result.component.source.file, '/project/child.tsx');
  assert.deepEqual(result.connections.map(item => [item.property, item.localName]), [['busy', 'pending'], ['user', 'user']]);
  const [busy] = result.connections;
  assert.equal(files['parent.tsx'].slice(busy.expression.start, busy.expression.end), 'locked');
  assert.equal(files['child.tsx'].slice(busy.to.start, busy.to.end), 'busy: pending');
  assert.ok(result.moduleIndex.edges.some(edge => edge.specifier === 'not-loaded' && edge.status !== 'resolved-loaded'));
});

test('shadowing selects the actual local tag declaration rather than matching an import name', () => {
  const source = 'import { Child as View } from "#child"; function Parent() { const View = ({ busy, user }: Props) => <i/>; return <View busy={false} user={null}/>; }';
  const result = index({ ...files, 'parent.tsx': source });
  assert.equal(result.component.source.file, '/project/parent.tsx');
  assert.equal(result.connections[0].localName, 'busy');
});

test('uncertain overwrites, erased bindings and wrappers are not source binding successes', () => {
  for (const parent of [
    'import type { Child as View } from "#child"; const page = <View busy={false} user={null}/>;',
    'import { Child as View } from "#child"; const page = <View {...rest} busy={false} user={null}/>;',
    'import { Child as View } from "#child"; const page = <View busy={false} busy={true} user={null}/>;',
    'import { Child as View } from "#child"; const page = <View user={null}/>;',
  ]) assert.throws(() => index({ ...files, 'parent.tsx': parent }), Unsupported);
  for (const child of [
    'export const Child = memo(({ busy, user }) => <button/>);',
    'export const Child = ({ busy, ...user }) => <button/>;',
    'export const Child = ({ busy, user: { id } }) => <button/>;',
    'export class Child {}',
  ]) assert.throws(() => index({ ...files, 'child.tsx': child }), Unsupported);
  assert.throws(() => indexComponentProps({ files, context: { ...context, metadata: { 'tsconfig.json': context.metadata['tsconfig.json'] } }, entry: 'parent.tsx', tag: 'View', properties: ['busy'] }), Unsupported);
});

test('a type-only barrel cannot be restored into a runtime component by a value import', () => {
  const sources = { ...files, 'barrel.ts': 'export type { Child } from "./child";',
    'parent.tsx': 'import { Child as View } from "./barrel"; const node = <View busy={false} user={null}/>;' };
  const ctx = { ...context, inventory: [...context.inventory, 'barrel.ts'] };
  assert.throws(() => indexComponentProps({ files: sources, context: ctx, entry: 'parent.tsx', tag: 'View', properties: ['busy'] }), /type-only/);
  const result = indexComponentProps({ files: { ...sources, 'barrel.ts': 'export { Child } from "./child";' }, context: ctx, entry: 'parent.tsx', tag: 'View', properties: ['busy'] });
  assert.equal(result.component.source.file, '/project/child.tsx');
  assert.equal(result.component.aliasChain.length, 2);
});

test('default initializers remain source-only while child references distinguish uses, writes and shadowing', () => {
  const child = `export function Child({ busy: pending = externalDefault(), user }) {
    const capture = () => pending;
    const shadow = (pending) => pending;
    pending = true;
    return <Next isLoading={pending} blocked={!pending && user} />;
  }`;
  const result = index({ ...files, 'child.tsx': child }), busy = result.connections[0];
  assert.equal(child.slice(busy.defaultInitializer.start, busy.defaultInitializer.end), 'externalDefault()');
  assert.equal(busy.uses.length, 4); // capture, assignment, two JSX uses; no shadow.
  assert.equal(busy.uses.filter(use => use.nestedFunction).length, 1);
  assert.equal(busy.uses.filter(use => use.kind === 'write-reference').length, 1);
  assert.deepEqual(busy.uses.filter(use => use.kind === 'jsx-attribute').map(use => [use.tag, use.attribute, use.direct]), [['Next', 'isLoading', true], ['Next', 'blocked', false]]);
  const report = renderPropertyLinks(result, { snippets: source => ({ ...files, 'child.tsx': child })[source.file.slice('/project/'.length)].slice(source.start, source.end) });
  assert.match(report, /externalDefault\(\)/);
  assert.match(report, /실행 결과 미확인/);
  assert.match(report, /재대입·증감/);
  assert.match(report, /다른 함수에 캡처됨/);
});

test('writes inside JSX expressions and shorthand symbol uses are not hidden from the child index', () => {
  const child = 'export const Child = ({ busy, user }) => { const record = { busy }; return <Next flag={(busy = false)} />; };';
  const result = index({ ...files, 'child.tsx': child }), uses = result.connections[0].uses;
  assert.deepEqual(uses.map(use => use.kind), ['other-reference', 'write-reference']);
  assert.equal(result.connections[1].uses.length, 0);
});

test('explicit absent-prop indexing records omission without inventing undefined or a default result', () => {
  const sources = { ...files, 'child.tsx': 'export const Child = ({ busy = external(), user }) => <Next busy={busy} />;',
    'parent.tsx': 'import { Child as View } from "#child"; const page = <View user={null} />;' };
  const result = indexComponentProps({ files: sources, context, entry: 'parent.tsx', tag: 'View', properties: ['busy', 'user'], includeAbsent: true });
  const busy = result.connections[0];
  assert.equal(busy.provided, false);
  assert.equal(busy.from, null);
  assert.equal(busy.expression, null);
  assert.ok(busy.defaultInitializer);
  assert.equal(Object.hasOwn(busy, 'value'), false);
  assert.equal(busy.uses[0].attribute, 'busy');
  const report = renderPropertyLinks(result);
  assert.match(report, /부모 JSX에 이 속성이 없음; 런타임 값은 미확인/);
  assert.throws(() => index(sources), Unsupported);
  assert.throws(() => indexComponentProps({ files: { ...sources, 'parent.tsx': sources['parent.tsx'].replace('user={null}', '{...unknown}') }, context, entry: 'parent.tsx', tag: 'View', properties: ['busy'], includeAbsent: true }), Unsupported);
  assert.throws(() => indexComponentProps({ files: sources, context, entry: 'parent.tsx', tag: 'View', properties: ['busy'], includeAbsent: 'true' }), Unsupported);
});
