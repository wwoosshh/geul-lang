import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { ENGINE_SHA256 } from '../src/fingerprint.mjs';
import { hash } from '../src/typescript.mjs';
import { caseChangeScope, describeChangeScope } from './inventory-scope.mjs';

const pkg = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'), root = path.dirname(pkg);
const selectionBytes = fs.readFileSync(path.join(pkg, 'corpus/output-prop-links.json')), selection = JSON.parse(selectionBytes);
assert.equal(selection.schema, 'web-output-prop-selection-1');
// Prerequisite producers must finish first. CLI below still replays both full
// artifacts and original source/config, rather than trusting these summaries.
const arrays = JSON.parse(fs.readFileSync(path.join(root, 'build/web-review/array-results.json')));
const props = JSON.parse(fs.readFileSync(path.join(root, 'build/web-review/prop-results.json')));
assert.equal(arrays.engineSha256, ENGINE_SHA256);
assert.equal(arrays.producerSha256, hash(fs.readFileSync(path.join(pkg, 'scripts/check-arrays.mjs'))));
assert.equal(props.producerSha256, hash(fs.readFileSync(path.join(pkg, 'scripts/check-props.mjs'))));
assert.equal(arrays.selectionSha256, hash(fs.readFileSync(path.join(pkg, 'corpus/array-slices.json'))));
assert.equal(props.selectionSha256, hash(fs.readFileSync(path.join(pkg, 'corpus/props.json'))));
const results = [];
for (const target of selection.targets) for (const revision of ['before', 'after']) {
  assert.ok(arrays.results.some(row => row.id === target.arraySlice && row.case === target.case));
  assert.ok(props.results.some(row => row.case === target.case && row.revision === revision && row.artifact.engineSha256 === ENGINE_SHA256));
  const arrayBase = path.join(root, 'build/web-review/arrays', target.arraySlice);
  const propBase = path.join(root, 'build/web-review/prop-projects', target.case, revision);
  const artifact = path.join(arrayBase, `${revision}.json`), index = path.join(propBase, 'prop-bindings.json'), inputs = path.join(arrayBase, 'inputs.json');
  const args = [path.join(pkg, 'src/cli.mjs'), 'explain', '--file', artifact, '--inputs', inputs, '--props-index', index];
  const json = spawnSync(process.execPath, [...args, '--json'], { encoding: 'utf8', timeout: 15_000, maxBuffer: 8 * 1024 * 1024 });
  assert.equal(json.status, 0, json.stderr);
  const result = JSON.parse(json.stdout), links = result.outputPropLinks;
  assert.equal(links.status, 'source-indexes-linked'); assert.equal(links.links.length, 1);
  const link = links.links[0];
  assert.equal(link.name, target.name); assert.equal(link.property, target.property); assert.equal(link.childUses.length, target.childUses);
  const parent = JSON.parse(fs.readFileSync(artifact)), prop = JSON.parse(fs.readFileSync(index));
  assert.equal(links.sourceAlignment.sha256, parent.source.sha256);
  const other = link.childUses.filter(use => use.kind === 'other-reference');
  assert.equal(other.length, 1);
  const sourcePath = path.join(propBase, other[0].source.file.slice('/project/'.length));
  const source = fs.readFileSync(sourcePath, 'utf8');
  assert.equal(hash(source), prop.sources.find(row => row.file === other[0].source.file).sha256);
  assert.equal(source.slice(other[0].expression.start, other[0].expression.end), target.expectedUseExpression);
  assert.equal(result.observation.kind, 'value');
  assert.equal(Object.hasOwn(link, 'value'), false);
  const report = spawnSync(process.execPath, args, { encoding: 'utf8', timeout: 15_000, maxBuffer: 8 * 1024 * 1024 });
  assert.equal(report.status, 0, report.stderr);
  assert.ok(report.stdout.includes('useSelected')); assert.ok(report.stdout.includes('실행 결과가 아닌 원본 탐색'));
  const sourcePaths = [prop.entry, prop.component.source.file.slice('/project/'.length)];
  const changeScope = caseChangeScope(target.case, sourcePaths, { kind: 'source-bindings' });
  const directory = path.join(root, 'build/web-review/output-props', target.id);
  fs.mkdirSync(directory, { recursive: true });
  fs.writeFileSync(path.join(directory, `${revision}.json`), json.stdout);
  fs.writeFileSync(path.join(directory, `${revision}.md`), describeChangeScope(changeScope) + '\n\n' + report.stdout);
  const readingArgs = [path.join(pkg, 'src/cli.mjs'), 'read', '--file', artifact, '--props-index', index];
  const readingJson = spawnSync(process.execPath, [...readingArgs, '--json'], { encoding: 'utf8', timeout: 15_000, maxBuffer: 8 * 1024 * 1024 });
  assert.equal(readingJson.status, 0, readingJson.stderr);
  const reading = JSON.parse(readingJson.stdout);
  assert.equal(reading.status, 'ir-reading-view');
  assert.equal(Object.hasOwn(reading, 'observation'), false);
  assert.deepEqual(reading.outputPropLinks, links);
  const readingText = spawnSync(process.execPath, readingArgs, { encoding: 'utf8', timeout: 15_000, maxBuffer: 8 * 1024 * 1024 });
  assert.equal(readingText.status, 0, readingText.stderr);
  assert.ok(readingText.stdout.includes('useSelected')); assert.ok(readingText.stdout.includes('실행 결과가 아닌 원본 탐색'));
  fs.writeFileSync(path.join(directory, `${revision}-reading.json`), readingJson.stdout);
  fs.writeFileSync(path.join(directory, `${revision}-reading.md`), describeChangeScope(changeScope) + '\n\n' + readingText.stdout);
  results.push({ id: target.id, case: target.case, revision, links: links.links.length, childReferences: link.childUses.length,
    sourceAlignment: links.sourceAlignment, originalSources: prop.sources, cliReplayChecks: 4, readingNodes: reading.nodeCount,
    nativeChecks: 0, observationScope: result.scope.observation, changeScope, directory });
}
const result = { schema: 'web-output-prop-results-1', engineSha256: ENGINE_SHA256,
  producerSha256: hash(fs.readFileSync(fileURLToPath(import.meta.url))), selectionSha256: hash(selectionBytes), scope: selection.scope,
  wholeBehaviorCasesVerified: 0, results };
fs.writeFileSync(path.join(root, 'build/web-review/output-prop-results.json'), JSON.stringify(result, null, 2) + '\n');
process.stdout.write(JSON.stringify({ ...result, results: results.map(({ originalSources, sourceAlignment, changeScope, ...row }) => row) }, null, 2) + '\n');
