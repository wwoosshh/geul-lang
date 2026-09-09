import test from 'node:test';
import assert from 'node:assert/strict';
import { liftProject } from '../src/project.mjs';
import { observe, compare, Unsupported } from '../src/core.mjs';

function fixture(condition = 'browser') {
  const files = {
    'src/main.tsx': 'import { allowed } from "#policy"; export function Button(owner: boolean) { return <button disabled={!allowed(owner)}>삭제</button>; }',
    'src/policy.web.ts': 'export function allowed(owner: boolean) { return owner; }',
    'src/policy.ts': 'export function allowed(owner: boolean) { return true; }',
  };
  const metadata = {
    'tsconfig.json': JSON.stringify({ compilerOptions: { module: 'esnext', moduleResolution: 'Bundler', jsx: 'react-jsx', customConditions: [condition] } }),
    'package.json': JSON.stringify({ imports: { '#policy': { browser: './src/policy.web.ts', default: './src/policy.ts' } } }),
  };
  return { files, entry: 'src/main.tsx', functionName: 'Button', context: { metadata, inventory: [...Object.keys(files), ...Object.keys(metadata)], configPath: 'tsconfig.json' } };
}
test('package import conditions are bound to executed policy and JSX observations', () => {
  const browser = liftProject(fixture('browser')), fallback = liftProject(fixture('other'));
  assert.equal(browser.moduleEdges[0].to, '/project/src/policy.web.ts');
  assert.equal(fallback.moduleEdges[0].to, '/project/src/policy.ts');
  assert.equal(observe(browser.ir, { owner: false }).value.$jsx.attributes.$record.disabled, true);
  assert.equal(observe(fallback.ir, { owner: false }).value.$jsx.attributes.$record.disabled, false);
  const result = compare(browser.ir, fallback.ir, { owner: [false, true] });
  assert.equal(result.changes.length, 1);
  assert.notDeepEqual(browser.moduleIndex.files, fallback.moduleIndex.files);
});
test('a module exists but is not loaded, or metadata is missing, cannot silently select fallback policy', () => {
  const unloaded = fixture(); delete unloaded.files['src/policy.web.ts'];
  assert.throws(() => liftProject(unloaded), /제공되지 않은 모듈/);
  const unknown = fixture(); delete unknown.context.metadata['package.json'];
  assert.throws(() => liftProject(unknown), /제공되지 않은 모듈/);
  const overlap = fixture(); overlap.context.metadata['src/main.tsx'] = 'bad';
  assert.throws(() => liftProject(overlap), Unsupported);
  const custom = fixture();
  const config = JSON.parse(custom.context.metadata['tsconfig.json']); config.compilerOptions.jsxImportSource = 'custom-runtime';
  custom.context.metadata['tsconfig.json'] = JSON.stringify(config);
  assert.throws(() => liftProject(custom), /JSX 실행 문맥/);
});
