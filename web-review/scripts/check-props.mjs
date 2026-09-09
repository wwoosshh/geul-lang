import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { indexComponentProps } from '../src/component-props.mjs';
import { hash } from '../src/typescript.mjs';
import { renderPropertyLinks } from '../src/report.mjs';
import { caseChangeScope, describeChangeScope } from './inventory-scope.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const corpusDir = path.join(root, 'web-review/corpus');
const read = name => JSON.parse(fs.readFileSync(path.join(corpusDir, name), 'utf8'));
const lockBytes = fs.readFileSync(path.join(corpusDir, 'lock.json'));
const lock = JSON.parse(lockBytes), contexts = read('context-lock.json'), targets = read('props.json').targets;
assert.equal(hash(lockBytes), contexts.corpusLockSha256);
assert.equal(lock.selectionSha256, hash(fs.readFileSync(path.join(corpusDir, 'selection.json'))));
function originalCopy(base, relative, bytes) {
  const destination = path.resolve(base, relative), check = path.relative(base, destination);
  assert.ok(check && check !== '..' && !check.startsWith('..' + path.sep) && !path.isAbsolute(check));
  if (fs.existsSync(destination)) assert.equal(hash(fs.readFileSync(destination)), hash(bytes), `원본 복사본이 변경됐습니다: ${destination}`);
  else { fs.mkdirSync(path.dirname(destination), { recursive: true }); fs.writeFileSync(destination, bytes, { flag: 'wx' }); }
}
const results = [];
for (const target of targets) for (const revision of ['before', 'after']) {
  const item = lock.cases.find(item => item.id === target.case);
  const context = contexts.contexts.find(item => item.case === target.case && item.revision === revision);
  assert.ok(context);
  const cachedContext = path.join(root, 'build/web-context', target.case, revision);
  const inventoryBytes = fs.readFileSync(path.join(cachedContext, 'inventory.json'));
  assert.equal(hash(inventoryBytes), context.inventorySha256);
  const inventory = JSON.parse(inventoryBytes), files = {}, metadata = {};
  const bundle = path.join(root, 'build/web-review/prop-projects', target.case, revision);
  let licenses = 0;
  for (const blob of item.blobs.filter(blob => blob.revision === revision)) {
    const bytes = fs.readFileSync(path.join(root, 'build/web-corpus', target.case, revision, blob.path));
    assert.equal(hash(bytes), blob.sha256);
    assert.ok(inventory.some(item => item.path === blob.path && item.type === 'blob' && ['100644', '100755'].includes(item.mode)));
    originalCopy(bundle, blob.path, bytes);
    if (/\.tsx?$/.test(blob.path)) files[blob.path] = bytes.toString('utf8');
    if (/^LICENSE(?:\.txt)?$/.test(path.basename(blob.path))) licenses++;
  }
  assert.ok(licenses >= 1);
  for (const blob of context.metadata) {
    const bytes = fs.readFileSync(path.join(cachedContext, 'files', blob.path));
    assert.equal(hash(bytes), blob.sha256);
    originalCopy(bundle, blob.path, bytes);
    metadata[blob.path] = bytes.toString('utf8');
  }
  const expectedFields = target.expected.filter(item => !item.revisions || item.revisions.includes(revision));
  const paths = inventory.map(item => item.path), properties = expectedFields.map(item => item.property);
  const manifest = { files: Object.keys(files), entry: target.entry, tag: target.tag, properties, includeAbsent: target.includeAbsent ?? false,
    context: { metadata: Object.keys(metadata), inventory: 'inventory.json', configPath: context.configPath } };
  const manifestText = JSON.stringify(manifest, null, 2) + '\n', manifestFile = path.join(bundle, 'project.json');
  fs.writeFileSync(path.join(bundle, 'inventory.json'), JSON.stringify(paths, null, 2) + '\n');
  fs.writeFileSync(manifestFile, manifestText);
  const artifact = { ...indexComponentProps({ files, entry: target.entry, tag: target.tag, properties, includeAbsent: target.includeAbsent,
    context: { metadata, inventory: paths, configPath: context.configPath } }),
    manifest: manifestFile, manifestSha256: hash(manifestText) };
  assert.equal(artifact.component.source.file, '/project/' + target.component);
  for (const expected of expectedFields) {
    const connection = artifact.connections.find(item => item.property === expected.property);
    assert.equal(connection.localName, expected.localName);
    assert.equal(connection.provided, expected.provided ?? true);
    if (expected.provided === false) { assert.equal(connection.expression, null); assert.equal(connection.from, null); }
    else assert.equal(files[target.entry].slice(connection.expression.start, connection.expression.end), typeof expected.expression === 'string' ? expected.expression : expected.expression[revision]);
    assert.equal(connection.to.file, '/project/' + target.component);
    if (expected.default) assert.equal(files[target.component].slice(connection.defaultInitializer.start, connection.defaultInitializer.end), expected.default);
    else assert.equal(connection.defaultInitializer, undefined);
    for (const use of expected.uses ?? []) assert.ok(connection.uses.some(actual => Object.entries(use).every(([key, value]) => actual[key] === value)), JSON.stringify(use));
  }
  const artifactFile = path.join(bundle, 'prop-bindings.json');
  fs.writeFileSync(artifactFile, JSON.stringify(artifact, null, 2) + '\n');
  const changeScope = caseChangeScope(target.case, [target.entry, target.component], { kind: 'source-bindings' });
  const report = describeChangeScope(changeScope) + '\n\n' + renderPropertyLinks(artifact, { snippets: source => files[source.file.slice('/project/'.length)].slice(source.start, source.end) });
  fs.writeFileSync(path.join(bundle, 'prop-bindings.md'), report);
  const replay = spawnSync(process.execPath, [path.join(root, 'web-review/src/cli.mjs'), 'explain', '--file', artifactFile, '--json'], { encoding: 'utf8', timeout: 10000, maxBuffer: 4 * 1024 * 1024 });
  assert.equal(replay.status, 0, replay.stderr);
  assert.deepEqual(JSON.parse(replay.stdout), artifact);
  results.push({ case: target.case, revision, propertyConnections: artifact.connections.filter(item => item.provided).length,
    selectedPropBindings: artifact.connections.length,
    absentPropsIndexed: artifact.connections.filter(item => !item.provided).length,
    childReferences: artifact.connections.reduce((sum, item) => sum + item.uses.length, 0),
    defaultsIndexed: artifact.connections.filter(item => item.defaultInitializer).length,
    cliReplayChecks: 1, licensesCopied: licenses, changeScope, artifact });
}
const output = { schema: 'web-prop-results-1', sourceCaseCount: new Set(results.map(item => item.case)).size,
  producerSha256: hash(fs.readFileSync(fileURLToPath(import.meta.url))), selectionSha256: hash(fs.readFileSync(path.join(corpusDir, 'props.json'))),
  contextsChecked: results.length, propertyConnections: results.reduce((sum, item) => sum + item.propertyConnections, 0),
  selectedPropBindings: results.reduce((sum, item) => sum + item.selectedPropBindings, 0),
  childReferences: results.reduce((sum, item) => sum + item.childReferences, 0), defaultsIndexed: results.reduce((sum, item) => sum + item.defaultsIndexed, 0),
  absentPropsIndexed: results.reduce((sum, item) => sum + item.absentPropsIndexed, 0),
  cliReplayChecks: results.length, wholeBehaviorCasesVerified: 0,
  notProven: ['부모·자식의 런타임 호출·값 변경·렌더링', '이 소스 연결을 결합한 동작의 실행 의미'], results };
fs.writeFileSync(path.join(root, 'build/web-review/prop-results.json'), JSON.stringify(output, null, 2) + '\n');
process.stdout.write(JSON.stringify({ ...output, results: results.map(({ artifact, changeScope, ...item }) => item) }, null, 2) + '\n');
