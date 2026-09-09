import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { hash } from '../src/typescript.mjs';

const directory = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../corpus');
export function caseChangeScope(caseId, analyzedPaths, { kind = 'execution-slice' } = {}) {
  assert.ok(['execution-slice', 'source-bindings'].includes(kind));
  const corpusBytes = fs.readFileSync(path.join(directory, 'lock.json'));
  const inventoryBytes = fs.readFileSync(path.join(directory, 'change-inventory.lock.json'));
  const corpus = JSON.parse(corpusBytes), inventory = JSON.parse(inventoryBytes);
  assert.equal(inventory.schema, 'web-change-inventory-lock-1');
  assert.equal(inventory.corpusLockSha256, hash(corpusBytes));
  assert.equal(inventory.selectionSha256, hash(fs.readFileSync(path.join(directory, 'selection.json'))));
  const original = corpus.cases.find(row => row.id === caseId);
  const entry = inventory.cases.find(row => row.case === caseId);
  assert.ok(original && entry);
  assert.equal(entry.parent, original.parent);
  assert.equal(entry.head, original.head);
  const analyzed = new Set(analyzedPaths);
  assert.ok(analyzed.size > 0);
  for (const filename of analyzed) assert.ok(original.blobs.some(blob => blob.path === filename));
  return {
    schema: 'web-change-scope-1', inventorySha256: hash(inventoryBytes),
    producerSha256: hash(fs.readFileSync(fileURLToPath(import.meta.url))),
    case: caseId, parent: entry.parent, head: entry.head, analysisKind: kind,
    changedFileCount: entry.changedFiles.length,
    analyzedSourceFiles: [...analyzed],
    changedFiles: entry.changedFiles.map(row => ({ ...row, relation: analyzed.has(row.path)
      ? kind === 'source-bindings' ? 'contains-source-bindings' : 'contains-analyzed-slice' : row.selectedInCorpus ? 'selected-context-outside-this-analysis' : 'outside-selected-corpus' })),
    semanticCoverage: null, wholeBehaviorVerified: false,
    limitation: 'Reading a source file for a slice does not establish the semantics of every change in that file.',
  };
}

export function describeChangeScope(scope) {
  const outside = scope.changedFiles.filter(row => !['contains-analyzed-slice', 'contains-source-bindings'].includes(row.relation));
  return [
    `원본 커밋에서는 ${scope.changedFileCount}개 파일이 바뀌었다. ` + (scope.analysisKind === 'source-bindings'
      ? `이 색인은 ${scope.analyzedSourceFiles.length}개 원본 파일의 선언·참조를 연결하며, 실행 결과를 해석하지 않는다.`
      : `이 분석은 ${scope.analyzedSourceFiles.length}개 원본 파일의 선택한 구간을 해석하며, 해당 파일의 모든 변경을 해석했다는 뜻은 아니다.`),
    outside.length ? `이 분석에서 다루지 않은 변경 파일: ${outside.map(row => JSON.stringify(row.path)).join(', ')}.` : '다른 변경 파일은 없지만, 선택 구간 밖의 동작은 별도다.',
    '전체 변경의 의미 보존 여부는 미확인이다.',
  ].join(' ');
}
