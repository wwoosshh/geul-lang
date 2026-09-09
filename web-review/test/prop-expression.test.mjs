import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import ts from 'typescript';
import { liftPropExpression } from '../src/prop-expression.mjs';
import { observe, encode, decode, Unsupported } from '../src/core.mjs';
import { renderExecution } from '../src/report.mjs';

const files = {
  'parent.tsx': 'import { Child as View } from "#child"; export function Parent() { return <View busy={search ? query : preview} />; }',
  'child.tsx': 'export function Child({ busy, onRefresh }) { return <Next enabled={!busy && !!onRefresh} />; }',
};
const context = { metadata: { 'tsconfig.json': '{"compilerOptions":{"moduleResolution":"Bundler","module":"esnext"}}', 'package.json': '{"imports":{"#child":"./child.tsx"}}' }, inventory: [...Object.keys(files), 'tsconfig.json', 'package.json'], configPath: 'tsconfig.json' };
const model = (sources = files, extra = {}) => liftPropExpression({ files: sources, context, entry: 'parent.tsx', tag: 'View', properties: ['busy', 'onRefresh'], includeAbsent: true, assumePlainProps: true, sink: { tag: 'Next', attribute: 'enabled' }, ...extra });

// A small synchronous JSX factory for test fixtures, not a React oracle. It
// evaluates all original JSX arguments and the original child body, exposing
// exceptions in regions deliberately excluded by the equation model.
function native(sources, inputs, extra = {}) {
  const modules = new Map();
  function load(name) {
    if (modules.has(name)) return modules.get(name);
    const exports = {};
    modules.set(name, exports);
    const code = ts.transpileModule(sources[name], { fileName: name, compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React } }).outputText;
    new vm.Script(code).runInNewContext({ ...Object.fromEntries(Object.entries(inputs).map(([key, value]) => [key, decode(value)])), ...extra,
      exports, require: specifier => { assert.equal(specifier, '#child'); return load('child.tsx'); }, Next: 'next',
      React: { createElement: (tag, props) => typeof tag === 'function' ? tag(props) : props } }, { timeout: 100 });
    return exports;
  }
  return load('parent.tsx').Parent();
}

test('parent conditions and child property equations preserve missing delivery under the explicit profile', () => {
  const artifact = model();
  assert.deepEqual(artifact.inputs, ['preview', 'query', 'search']);
  for (const search of [false, true]) for (const query of [false, true]) for (const preview of [false, true]) {
    const inputs = { search, query, preview };
    assert.deepEqual(observe(artifact.ir, inputs), { kind: 'value', value: false });
    assert.equal(native(files, inputs).enabled, false);
  }
  const explained = renderExecution(artifact, observe(artifact.ir, { search: false, query: true, preview: false }, { trace: true }));
  assert.match(explained, /생략을 이 모델에서 undefined/);
  assert.match(explained, /전체 React 실행의 성공으로 읽으면 안 된다/);
});

test('provided refresh values preserve all parent evaluations before child short circuit', () => {
  const sources = { ...files, 'parent.tsx': files['parent.tsx'].replace(' />', ' onRefresh={refresh} />') }, artifact = model(sources);
  for (const busy of [false, true]) for (const refresh of [undefined, null, false, true, 0, '', 'refresh']) {
    const inputs = { search: false, query: true, preview: busy, refresh: encode(refresh) };
    assert.equal(observe(artifact.ir, inputs).value, native(sources, inputs).enabled);
  }
  const throwing = { ...files, 'parent.tsx': files['parent.tsx'].replace(' />', ' onRefresh={broken.value} />') };
  const inputs = { search: true, query: true, preview: true, broken: null };
  assert.deepEqual(observe(model(throwing).ir, inputs), { kind: 'throw', name: 'TypeError' });
  assert.throws(() => native(throwing, inputs), error => error.name === 'TypeError');
});

test('source defaults, writes, captures and unmatched child inputs cannot become a delivery equation', () => {
  assert.throws(() => model(files, { assumePlainProps: false }), Unsupported);
  assert.throws(() => model(files, { includeAbsent: false }), Unsupported);
  for (const child of [
    'export function Child({ busy, onRefresh = fallback() }) { return <Next enabled={!busy && !!onRefresh} />; }',
    'export function Child({ busy, onRefresh }) { busy = false; return <Next enabled={!busy && !!onRefresh} />; }',
    'export function Child({ busy, onRefresh }) { const later = () => busy; return <Next enabled={!busy && !!onRefresh} />; }',
    'export function Child({ busy, onRefresh }) { return <Next enabled={unmatched} />; }',
    'export function Child({ busy, onRefresh }) { const later = () => <Next enabled={true} />; return null; }',
  ]) assert.throws(() => model({ ...files, 'child.tsx': child }), Unsupported);
  const spread = { ...files, 'parent.tsx': files['parent.tsx'].replace(' />', ' {...rest} />') };
  assert.throws(() => model(spread), Unsupported);
});

test('constructed parent records keep prototype uncertainty through the child use', () => {
  const sources = { ...files, 'parent.tsx': files['parent.tsx'].replace('search ? query : preview', '{ present: 1 }'),
    'child.tsx': 'export function Child({ busy, onRefresh }) { return <Next enabled={busy.missing} />; }' };
  assert.equal(observe(model(sources).ir, {}).kind, 'unsupported');
});

test('omitted JSX evaluations and child body errors remain explicit counterexamples to whole execution', () => {
  const inputs = { search: true, query: true, preview: true };
  const parent = { ...files, 'parent.tsx': files['parent.tsx'].replace(' />', ' noise={fail()} />') };
  const artifact = model(parent);
  assert.equal(observe(artifact.ir, inputs).value, false);
  assert.equal(artifact.propPath.omittedAttributes.length, 1);
  assert.throws(() => native(parent, inputs, { fail: () => { throw Error('other parent attribute'); } }), /other parent attribute/);
  const child = { ...files, 'child.tsx': files['child.tsx'].replace('return <Next', 'fail(); return <Next') };
  assert.equal(observe(model(child).ir, inputs).value, false);
  assert.throws(() => native(child, inputs, { fail: () => { throw Error('child body'); } }), /child body/);
});

test('manifest property order does not reorder the parent expressions or hide unused selected arguments', () => {
  const sources = { ...files,
    'parent.tsx': files['parent.tsx'].replace('search ? query : preview', 'first.value').replace(' />', ' onRefresh={second.value} />'),
    'child.tsx': 'export function Child({ busy, onRefresh }) { return <Next enabled={true} />; }' };
  const artifact = model(sources, { properties: ['onRefresh', 'busy'] });
  const observed = observe(artifact.ir, { first: null, second: null }, { trace: true });
  assert.equal(observed.kind, 'throw');
  assert.equal(observed.trace[0].source.start, sources['parent.tsx'].indexOf('first.value'));
  assert.deepEqual(artifact.propPath.bindings.map(row => row.property), ['busy', 'onRefresh']);
  assert.throws(() => native(sources, { first: null, second: null }), error => error.name === 'TypeError');
});
