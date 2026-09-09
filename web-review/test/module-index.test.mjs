import test from 'node:test';
import assert from 'node:assert/strict';
import { indexModules } from '../src/module-index.mjs';
import { Unsupported } from '../src/core.mjs';

test('tsconfig extends, paths and package imports select real module paths', () => {
  const files = {
    'tsconfig.json': JSON.stringify({ compilerOptions: { moduleResolution: 'Bundler', module: 'esnext', baseUrl: '.', paths: { '@lib/*': ['lib/*'] } } }),
    'web/tsconfig.json': JSON.stringify({ extends: '../tsconfig.json', compilerOptions: { customConditions: ['browser'], plugins: [{ name: 'never-execute-this' }] } }),
    'web/package.json': JSON.stringify({ imports: { '#view': { browser: './view.tsx', default: './fallback.ts' } } }),
    'web/main.ts': 'import { test } from "@lib/logic"; import { View } from "#view";',
    'web/view.tsx': 'export const View = () => null;',
    'web/fallback.ts': 'export const View = false;',
    'lib/logic.ts': 'export const test = true;',
  };
  const result = indexModules({ files, inventory: Object.keys(files), configPath: 'web/tsconfig.json' });
  assert.deepEqual(result.edges.map(e => e.target), ['/project/lib/logic.ts', '/project/web/view.tsx']);
  assert.ok(result.edges.every(e => e.status === 'resolved-loaded'));
  assert.ok(result.configReads.includes('/project/tsconfig.json'));
});
test('an unloaded web suffix is not mistaken for a nonexistent file', () => {
  const files = {
    'tsconfig.json': JSON.stringify({ compilerOptions: { moduleResolution: 'Bundler', module: 'esnext', moduleSuffixes: ['.web', ''] } }),
    'main.ts': 'import { value } from "./value";',
    'value.ts': 'export const value = false;',
  };
  const result = indexModules({ files, inventory: [...Object.keys(files), 'value.web.ts'], configPath: 'tsconfig.json' });
  assert.equal(result.edges[0].target, '/project/value.web.ts');
  assert.equal(result.edges[0].status, 'resolved-unloaded');
});
test('unloaded package metadata never becomes a confirmed path choice', () => {
  const files = { 'tsconfig.json': '{"compilerOptions":{"moduleResolution":"Bundler","module":"esnext"}}', 'src/main.ts': 'import { value } from "#value";' };
  const result = indexModules({ files, inventory: [...Object.keys(files), 'package.json'], configPath: 'tsconfig.json' });
  assert.equal(result.edges[0].status, 'unconfirmed-metadata');
  assert.ok(result.edges[0].metadataMissing.includes('/project/package.json'));
});
test('missing extended config, malformed metadata and paths outside the root are rejected', () => {
  const files = { 'tsconfig.json': '{"extends":"./base.json"}', 'main.ts': 'export const x = true;' };
  assert.throws(() => indexModules({ files, inventory: [...Object.keys(files), 'base.json'], configPath: 'tsconfig.json' }), Unsupported);
  assert.throws(() => indexModules({ files, inventory: [...Object.keys(files), '../escape.ts'], configPath: 'tsconfig.json' }), Unsupported);
  const malformed = { 'tsconfig.json': '{"compilerOptions":{"moduleResolution":"Bundler","module":"esnext"}}', 'package.json': '{broken', 'main.ts': 'import { x } from "#x";' };
  assert.throws(() => indexModules({ files: malformed, inventory: Object.keys(malformed), configPath: 'tsconfig.json' }), Unsupported);
});
