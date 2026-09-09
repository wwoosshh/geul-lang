import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import ts from 'typescript';
import { fileURLToPath } from 'node:url';
import { liftExpression, hash, parseSource } from '../src/typescript.mjs';
import { liftJsxAttribute } from '../src/jsx.mjs';
import { compare, observe, decode, encode } from '../src/core.mjs';
import { describeComparison } from '../src/presentation.mjs';
import { summarizeChanges } from '../src/change-rules.mjs';
import { caseChangeScope } from './inventory-scope.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const pkg = path.join(root, 'web-review');
const read = file => JSON.parse(fs.readFileSync(path.join(pkg, 'corpus', file), 'utf8'));
const lock = read('lock.json'), selection = read('selection.json'), slices = read('slices.json');
const audit = read('dependency-audit.json');
assert.equal(lock.selectionSha256, hash(fs.readFileSync(path.join(pkg, 'corpus/selection.json'))));
assert.equal(lock.cases.length, 12);
assert.equal(new Set(lock.cases.map(c => c.project)).size, 3);
// Validate the entire denominator, including hard unsupported cases.
let verifiedBlobs = 0;
for (const item of lock.cases) for (const blob of item.blobs) {
  const file = path.join(root, 'build/web-corpus', item.id, blob.revision, blob.path);
  assert.equal(hash(fs.readFileSync(file)), blob.sha256, file);
  verifiedBlobs++;
}
assert.ok(new Set(audit.cases.map(c => c.case)).size >= 5);
for (const edge of audit.cases) {
  const item = lock.cases.find(c => c.id === edge.case);
  for (const file of [edge.from, edge.to]) assert.ok(item.blobs.some(b => b.revision === 'after' && b.path === file));
  const source = fs.readFileSync(path.join(root, 'build/web-corpus', edge.case, 'after', edge.from), 'utf8');
  const file = parseSource(source, edge.from);
  assert.ok(file.statements.some(s => ts.isImportDeclaration(s) && s.moduleSpecifier.text === edge.specifier));
  for (const evidence of edge.evidence) assert.ok(source.includes(evidence), evidence);
}
const results = [];
let differentialChecks = 0;
for (const target of slices.targets) {
  const artifacts = ['before', 'after'].map(revision => {
    const filename = path.join(root, 'build/web-corpus', target.case, revision, target.path);
    const source = fs.readFileSync(filename, 'utf8');
    const selector = target[revision + 'Selector'] ?? target.selector;
    return selector ? liftJsxAttribute(source, { ...selector, filename }) : liftExpression(source, target[revision], filename, { container: target.container });
  });
  const comparison = compare(artifacts[0].ir, artifacts[1].ir, target.domains);
  const result = { ...comparison, domains: target.domains, changeRules: summarizeChanges(comparison, target.domains) };
  assert.equal(result.changeRules.status, 'verified-finite-cover');
  assert.equal(result.unknown.length, 0);
  assert.equal(result.changes.length, target.expectedChanged);
  // Human-authored expected predicate is an independent test oracle, not
  // generated from the analysis IR. It describes these finite-domain cases.
  const expected = new vm.Script(target.expectedPredicate);
  const names = Object.keys(target.domains);
  const originals = artifacts.map(artifact => {
    const source = fs.readFileSync(artifact.source.file, 'utf8');
    const expression = artifact.mode === 'jsx-attribute-slice' ? source.slice(artifact.ir.source.start, artifact.ir.source.end) : artifact.source.expression;
    return new vm.Script(`(${expression})`);
  });
  function check(index, inputs) {
    if (index < names.length) {
      for (const value of target.domains[names[index]]) check(index + 1, { ...inputs, [names[index]]: value });
      return;
    }
    const decoded = Object.fromEntries(Object.entries(inputs).map(([k, v]) => [k, decode(v)]));
    const observed = artifacts.map((a, i) => {
      const actual = { kind: 'value', value: encode(originals[i].runInNewContext(decoded, { timeout: 100 })) };
      assert.deepEqual(observe(a.ir, inputs), actual);
      differentialChecks++;
      return actual;
    });
    assert.equal(JSON.stringify(observed[0]) !== JSON.stringify(observed[1]), !!expected.runInNewContext(decoded, { timeout: 100 }));
  }
  check(0, {});
  results.push({ id: target.id, case: target.case, changeScope: caseChangeScope(target.case, [target.path]), artifacts, comparison: result, explanation: describeComparison(result) });
}
const output = {
  schema: 'web-corpus-results-1', sourceCases: lock.cases.length, sourceProjects: Object.keys(selection.projects).length,
  verifiedBlobs, slicesChecked: results.length, differentialChecks,
  manuallyMappedMultiFileCases: audit.cases.length,
  wholeBehaviorCasesVerified: 0,
  notProven: ['선정 사례의 전체 동작', '여러 파일 의존성의 실행 의미', '한국어 설명의 사람 검토 효용'], results,
};
fs.mkdirSync(path.join(root, 'build/web-review'), { recursive: true });
fs.writeFileSync(path.join(root, 'build/web-review/corpus-results.json'), JSON.stringify(output, null, 2) + '\n');
process.stdout.write(JSON.stringify({ ...output, results: results.map(r => ({ id: r.id, explanation: r.explanation })) }, null, 2) + '\n');
