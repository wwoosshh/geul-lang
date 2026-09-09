import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { indexModules } from '../src/module-index.mjs';
import { hash } from '../src/typescript.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const pkg = path.join(root, 'web-review');
const corpusBytes = fs.readFileSync(path.join(pkg, 'corpus/lock.json'));
const corpus = JSON.parse(corpusBytes);
const contexts = JSON.parse(fs.readFileSync(path.join(pkg, 'corpus/context-lock.json'), 'utf8'));
const audit = JSON.parse(fs.readFileSync(path.join(pkg, 'corpus/dependency-audit.json'), 'utf8'));
assert.equal(hash(corpusBytes), contexts.corpusLockSha256);
const results = [];
for (const context of contexts.contexts) {
  const base = path.join(root, 'build/web-context', context.case, context.revision);
  const inventoryBytes = fs.readFileSync(path.join(base, 'inventory.json'));
  assert.equal(hash(inventoryBytes), context.inventorySha256);
  const inventory = JSON.parse(inventoryBytes), files = {};
  const caseEntry = corpus.cases.find(c => c.id === context.case);
  for (const blob of caseEntry.blobs.filter(b => b.revision === context.revision && /\.tsx?$/.test(b.path))) {
    const source = fs.readFileSync(path.join(root, 'build/web-corpus', context.case, context.revision, blob.path));
    assert.equal(hash(source), blob.sha256);
    assert.ok(inventory.some(i => i.path === blob.path && i.type === 'blob' && ['100644', '100755'].includes(i.mode)));
    files[blob.path] = source.toString('utf8');
  }
  for (const blob of context.metadata) {
    const bytes = fs.readFileSync(path.join(base, 'files', blob.path));
    assert.equal(hash(bytes), blob.sha256);
    assert.ok(inventory.some(i => i.path === blob.path && i.type === 'blob' && ['100644', '100755'].includes(i.mode)));
    files[blob.path] = bytes.toString('utf8');
  }
  const index = indexModules({ files, inventory: inventory.map(i => i.path), configPath: context.configPath });
  const expected = audit.cases.find(c => c.case === context.case);
  const edge = index.edges.find(e => e.source.file === '/project/' + expected.from && e.specifier === expected.specifier);
  assert.ok(edge, context.case);
  assert.equal(edge.target, '/project/' + expected.to, context.case);
  assert.equal(edge.status, 'resolved-loaded', JSON.stringify(edge));
  const counts = {};
  for (const item of index.edges) counts[item.status] = (counts[item.status] ?? 0) + 1;
  results.push({ case: context.case, revision: context.revision, index, expectedEdge: edge, counts });
}
const output = { contextsChecked: results.length, observedMultiFileCases: new Set(results.map(r => r.case)).size,
  scope: '고정된 원본 설정으로 수동 선정한 모듈 연결 경로를 재확인함; 전체 실행 의미 검증은 아님', results };
fs.mkdirSync(path.join(root, 'build/web-review'), { recursive: true });
fs.writeFileSync(path.join(root, 'build/web-review/context-results.json'), JSON.stringify(output, null, 2) + '\n');
process.stdout.write(JSON.stringify({ ...output, results: results.map(r => ({ case: r.case, revision: r.revision, expectedTarget: r.expectedEdge.target, counts: r.counts })) }, null, 2) + '\n');
