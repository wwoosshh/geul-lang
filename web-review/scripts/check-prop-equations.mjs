import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { liftPropExpression } from '../src/prop-expression.mjs';
import { hash } from '../src/typescript.mjs';
import { observe, compare, Unsupported } from '../src/core.mjs';
import { caseChangeScope, describeChangeScope } from './inventory-scope.mjs';
import { ENGINE_SHA256 } from '../src/fingerprint.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..'), pkg = path.join(root, 'web-review');
const read = name => JSON.parse(fs.readFileSync(path.join(pkg, 'corpus', name), 'utf8'));
const corpusBytes = fs.readFileSync(path.join(pkg, 'corpus/lock.json')), corpus = JSON.parse(corpusBytes);
const contexts = read('context-lock.json'), selection = read('prop-equations.json');
assert.equal(contexts.corpusLockSha256, hash(corpusBytes));
assert.equal(corpus.selectionSha256, hash(fs.readFileSync(path.join(pkg, 'corpus/selection.json'))));
const domains = { isSearching: [false, true], isFiltered: [false, true], isTransactionsLoading: [false, true], isPreviewTransactionsLoading: [false, true] };
const rows = [];
for (const isSearching of domains.isSearching) for (const isFiltered of domains.isFiltered) for (const isTransactionsLoading of domains.isTransactionsLoading) for (const isPreviewTransactionsLoading of domains.isPreviewTransactionsLoading) rows.push({ isSearching, isFiltered, isTransactionsLoading, isPreviewTransactionsLoading });
function copyOriginal(base, relative, bytes) {
  const destination = path.resolve(base, relative), rel = path.relative(base, destination);
  assert.ok(rel && rel !== '..' && !rel.startsWith('..' + path.sep) && !path.isAbsolute(rel));
  if (fs.existsSync(destination)) assert.equal(hash(fs.readFileSync(destination)), hash(bytes), destination);
  else { fs.mkdirSync(path.dirname(destination), { recursive: true }); fs.writeFileSync(destination, bytes, { flag: 'wx' }); }
}
const results = [];
for (const target of selection.targets) {
  assert.ok(['filter-loading-delivery-v1', 'filter-pullable-delivery-v1'].includes(target.oracle));
  const original = corpus.cases.find(row => row.id === target.case), artifacts = {}, artifactFiles = {}, refusals = [];
  const directory = path.join(root, 'build/web-review/prop-equations', target.id);
  let nativeChecks = 0, cliReplayChecks = 0;
  for (const revision of ['before', 'after']) {
    const context = contexts.contexts.find(row => row.case === target.case && row.revision === revision);
    assert.ok(context);
    const cache = path.join(root, 'build/web-context', target.case, revision), bundle = path.join(directory, revision), files = {}, metadata = {};
    const inventoryBytes = fs.readFileSync(path.join(cache, 'inventory.json'));
    assert.equal(hash(inventoryBytes), context.inventorySha256);
    const inventory = JSON.parse(inventoryBytes), inventoryPaths = inventory.map(row => row.path);
    let licenses = 0;
    for (const blob of original.blobs.filter(row => row.revision === revision)) {
      const bytes = fs.readFileSync(path.join(root, 'build/web-corpus', target.case, revision, blob.path));
      assert.equal(hash(bytes), blob.sha256);
      assert.ok(inventory.some(row => row.path === blob.path && row.type === 'blob' && ['100644', '100755'].includes(row.mode)));
      copyOriginal(bundle, blob.path, bytes);
      if (/\.tsx?$/.test(blob.path)) files[blob.path] = bytes.toString('utf8');
      if (/^LICENSE(?:\.txt)?$/.test(path.basename(blob.path))) licenses++;
    }
    assert.ok(licenses > 0);
    for (const blob of context.metadata) {
      const bytes = fs.readFileSync(path.join(cache, 'files', blob.path));
      assert.equal(hash(bytes), blob.sha256);
      copyOriginal(bundle, blob.path, bytes);
      metadata[blob.path] = bytes.toString('utf8');
    }
    fs.writeFileSync(path.join(bundle, 'inventory.json'), JSON.stringify(inventoryPaths, null, 2) + '\n');
    const manifest = { files: Object.keys(files), entry: target.entry, tag: target.tag, properties: target.properties,
      includeAbsent: true, assumePlainProps: true, sink: target.sink,
      context: { metadata: Object.keys(metadata), inventory: 'inventory.json', configPath: context.configPath } };
    const manifestFile = path.join(bundle, 'project.json'), manifestText = JSON.stringify(manifest, null, 2) + '\n';
    fs.writeFileSync(manifestFile, manifestText);
    let lifted;
    try {
      lifted = liftPropExpression({ files, entry: target.entry, tag: target.tag, properties: target.properties,
        includeAbsent: true, assumePlainProps: true, sink: target.sink, context: { metadata, inventory: inventoryPaths, configPath: context.configPath } });
    } catch (error) {
      if (!(error instanceof Unsupported) || !target.expectedUnsupported || !error.message.includes(target.expectedUnsupported)) throw error;
      refusals.push({ revision, reason: error.message, location: error.location, manifest: manifestFile,
        sourceSha256: Object.fromEntries(Object.entries(files).map(([filename, source]) => [filename, hash(source)])) });
      continue;
    }
    assert.equal(target.expectedUnsupported, undefined, '지원 범위가 바뀌었다. 미지원 표지를 지우기 전에 해당 원본 계산의 검증 근거를 작성해야 한다.');
    const artifact = { ...lifted,
      manifest: manifestFile, manifestSha256: hash(manifestText) };
    const snippet = source => files[source.file.slice('/project/'.length)].slice(source.start, source.end);
    const bindings = artifact.propPath.bindings;
    const argumentsText = bindings.map(row => !row.provided ? 'undefined' : row.expression ? `(${snippet(row.expression)})` : 'true').join(', ');
    const expression = files[artifact.child.source.file.slice('/project/'.length)].slice(artifact.child.ir.source.start, artifact.child.ir.source.end);
    const nativeSource = `(function (${bindings.map(row => row.localName).join(', ')}) { return (${expression}); })(${argumentsText})`;
    const native = new vm.Script(nativeSource);
    for (const inputs of rows) {
      const value = target.oracle === 'filter-pullable-delivery-v1' ? false
        : (inputs.isSearching || (revision === 'after' && inputs.isFiltered)) ? inputs.isTransactionsLoading : inputs.isPreviewTransactionsLoading;
      assert.deepEqual(observe(artifact.ir, inputs), { kind: 'value', value });
      assert.equal(native.runInNewContext(inputs, { timeout: 100 }), value);
      nativeChecks++;
    }
    artifactFiles[revision] = path.join(bundle, 'artifact.json');
    fs.writeFileSync(artifactFiles[revision], JSON.stringify(artifact, null, 2) + '\n');
    fs.writeFileSync(path.join(bundle, 'native-selected-expressions.js'), nativeSource + '\n');
    artifacts[revision] = artifact;
  }
  if (refusals.length) {
    assert.equal(refusals.length, 2);
    assert.equal(nativeChecks, 0);
    const result = { id: target.id, case: target.case, status: 'unsupported',
      pairedInputs: null, changedInputs: null, nativeChecks, cliReplayChecks, reason: target.limitation, refusals, directory };
    fs.writeFileSync(path.join(directory, 'unsupported.json'), JSON.stringify(result, null, 2) + '\n');
    fs.writeFileSync(path.join(directory, 'unsupported.md'), '# 속성 식 결합을 완료하지 못한 경로\n\n' + target.limitation + '\n\n' +
      refusals.map(row => `- ${row.revision}: ${row.reason} — [원본 캡처 참조](<${path.resolve(path.dirname(row.manifest), row.location.file.slice('/project/'.length)).replaceAll('\\', '/')}:${row.location.line}>)`).join('\n') + '\n\n원본 두 버전의 거부를 확인했다. 실행 비교·변경 없음·전체 동작 성공으로 세지 않는다.\n');
    results.push(result);
    continue;
  }
  const changeScope = caseChangeScope(target.case, [target.entry, artifacts.after.index.component.source.file.slice('/project/'.length)]);
  const comparison = compare(artifacts.before.ir, artifacts.after.ir, domains);
  assert.equal(comparison.checked, 16);
  assert.equal(comparison.unknown.length, 0);
  assert.equal(comparison.changes.length, target.expectedChanged);
  const domainFile = path.join(directory, 'domains.json'), inputFile = path.join(directory, 'inputs.json');
  fs.writeFileSync(domainFile, JSON.stringify(domains, null, 2) + '\n');
  fs.writeFileSync(inputFile, JSON.stringify({ isSearching: false, isFiltered: true, isTransactionsLoading: true, isPreviewTransactionsLoading: false }, null, 2) + '\n');
  for (const revision of ['before', 'after']) {
    const explained = spawnSync(process.execPath, [path.join(pkg, 'src/cli.mjs'), 'explain', '--file', artifactFiles[revision], '--inputs', inputFile], { encoding: 'utf8', timeout: 10_000 });
    assert.equal(explained.status, 0, explained.stderr);
    fs.writeFileSync(path.join(directory, `${revision}.md`), describeChangeScope(changeScope) + '\n\n' + explained.stdout);
    cliReplayChecks++;
  }
  const compared = spawnSync(process.execPath, [path.join(pkg, 'src/cli.mjs'), 'compare', '--before', artifactFiles.before, '--after', artifactFiles.after, '--domains', domainFile], { encoding: 'utf8', timeout: 10_000 });
  assert.equal(compared.status, 0, compared.stderr);
  fs.writeFileSync(path.join(directory, 'comparison.md'), compared.stdout + `\n\n# ${target.sink.tag}.${target.sink.attribute}에 연결한 조건 비교\n\n` + describeChangeScope(changeScope) + '\n\n이 비교는 선택한 속성 식의 전달 가정 모델이다. 다른 JSX 속성·hooks·자식 본문·실제 React·DOM은 실행하지 않았다.\n');
  cliReplayChecks++;
  fs.writeFileSync(path.join(directory, 'comparison.json'), JSON.stringify(comparison, null, 2) + '\n');
  results.push({ id: target.id, case: target.case, status: 'checked-in-assumed-model', engineSha256: artifacts.after.engineSha256,
    nativeChecks, cliReplayChecks, pairedInputs: comparison.checked, changedInputs: comparison.changes.length,
    nativeScope: '원본에서 선택한 부모 속성 식과 자식 속성 식의 가정된 결합; 전체 컴포넌트 실행 아님',
    changeScope, directory });
}
const result = { schema: 'web-prop-equation-results-1', engineSha256: ENGINE_SHA256, producerSha256: hash(fs.readFileSync(fileURLToPath(import.meta.url))),
  selectionSha256: hash(fs.readFileSync(path.join(pkg, 'corpus/prop-equations.json'))), domainsSha256: hash(JSON.stringify(domains)),
  scope: selection.scope, wholeBehaviorCasesVerified: 0, results };
fs.writeFileSync(path.join(root, 'build/web-review/prop-equation-results.json'), JSON.stringify(result, null, 2) + '\n');
process.stdout.write(JSON.stringify({ ...result, results: results.map(({ changeScope, ...row }) => row) }, null, 2) + '\n');
