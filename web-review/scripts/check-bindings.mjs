import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import ts from 'typescript';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { liftConstBindings } from '../src/const-bindings.mjs';
import { liftCallBindings } from '../src/result-preview.mjs';
import { encode, decode, observe, compare } from '../src/core.mjs';
import { hash } from '../src/typescript.mjs';
import { describeComparison, describeChangeSummary } from '../src/presentation.mjs';
import { caseChangeScope, describeChangeScope } from './inventory-scope.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const pkg = path.join(root, 'web-review');
const read = name => JSON.parse(fs.readFileSync(path.join(pkg, 'corpus', name), 'utf8'));
const corpus = read('lock.json'), selection = read('binding-comparisons.json');
assert.equal(corpus.selectionSha256, hash(fs.readFileSync(path.join(pkg, 'corpus/selection.json'))));
const dates = [
  [undefined, undefined], [null, undefined], ['', undefined], [' \t\n', undefined],
  [' 2026-09-09 ', ' 2026-09-09 '], ['invalid-date', 'invalid-date'], ['\u200b', '\u200b'],
];
const amounts = [[undefined, undefined], [null, undefined], [0, 0], [-0, -0], [5, 5], [-5, -5], [NaN, NaN], [Infinity, Infinity]];
const rows = [];
for (const [date, expectedDate] of dates) for (const [amount, expectedAmount] of amounts) rows.push({ records: { chosen: { date, amount } }, expected: [expectedDate, expectedAmount] });
rows.push({ records: { chosen: undefined }, expected: [undefined, undefined] }, { records: { chosen: null }, expected: [undefined, undefined] },
  { records: {}, expected: [undefined, undefined] }, { records: null, throws: true }, { records: undefined, throws: true });
const domains = { customStartingDates: rows.map(row => encode(row.records)), chosenExternalAccountId: ['chosen', 'missing'] };
assert.equal(new Set(domains.customStartingDates.map(row => JSON.stringify(row))).size, rows.length);
const results = [];
for (const target of selection.targets) {
  assert.equal(target.oracle, 'starting-settings-refactor-v1');
  const entry = corpus.cases.find(row => row.id === target.case), sources = {}, files = {};
  for (const revision of ['before', 'after']) {
    const blob = entry.blobs.find(row => row.path === target.path && row.revision === revision);
    assert.ok(blob);
    files[revision] = path.join(root, 'build/web-corpus', target.case, revision, target.path);
    sources[revision] = fs.readFileSync(files[revision], 'utf8');
    assert.equal(hash(sources[revision]), blob.sha256);
  }
  const before = liftConstBindings(sources.before, { ...target.before, filename: files.before });
  const after = liftCallBindings(sources.after, { ...target.after, filename: files.after });
  assert.deepEqual(before.observationBindings, after.observationBindings);
  assert.equal(before.prefix.bindings.length, 3);
  const beforeText = sources.before.slice(before.prefix.source.start, before.prefix.end);
  const afterFunction = sources.after.slice(after.index.functionDeclaration.start, after.index.functionDeclaration.end);
  const afterDeclaration = sources.after.slice(after.index.resultDeclaration.start, after.index.resultDeclaration.end);
  const native = {
    before: new vm.Script(`${beforeText}\n({ startingDate, startingBalance });`),
    after: new vm.Script(ts.transpileModule(`${afterFunction}\nconst ${afterDeclaration};\n({ startingDate, startingBalance });`, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText),
  };
  let nativeChecks = 0, thrownChecks = 0;
  for (const [i, row] of rows.entries()) for (const key of domains.chosenExternalAccountId) {
    const inputs = { customStartingDates: domains.customStartingDates[i], chosenExternalAccountId: key };
    const expected = row.throws ? { kind: 'throw', name: 'TypeError' } : { kind: 'value', value: encode({
      startingDate: key === 'missing' ? undefined : row.expected[0], startingBalance: key === 'missing' ? undefined : row.expected[1],
    }) };
    for (const [revision, artifact] of [['before', before], ['after', after]]) {
      assert.deepEqual(observe(artifact.ir, inputs), expected);
      const environment = { exports: {}, customStartingDates: decode(inputs.customStartingDates), chosenExternalAccountId: key };
      if (row.throws) {
        assert.throws(() => native[revision].runInNewContext(environment, { timeout: 100 }), error => error.name === 'TypeError');
        thrownChecks++;
      } else {
        const actual = native[revision].runInNewContext(environment, { timeout: 100 });
        assert.deepEqual({ kind: 'value', value: encode(Object.fromEntries(Object.entries(actual))) }, expected);
      }
      nativeChecks++;
    }
  }
  const comparison = { ...compare(before.ir, after.ir, domains), observationBindings: before.observationBindings,
    beforeContract: before.contract, afterContract: after.contract, domains };
  assert.equal(comparison.status, 'equal-in-declared-domain');
  assert.equal(comparison.checked, rows.length * 2);
  let unsupportedChecks = 0;
  for (const date of [5, true, {}]) for (const artifact of [before, after]) {
    assert.equal(observe(artifact.ir, { customStartingDates: encode({ chosen: { date, amount: 0 } }), chosenExternalAccountId: 'chosen' }).kind, 'unsupported');
    unsupportedChecks++;
  }
  const changeScope = caseChangeScope(target.case, [target.path]);
  const directory = path.join(root, 'build/web-review/binding-comparisons', target.id);
  fs.mkdirSync(directory, { recursive: true });
  for (const [name, value] of Object.entries({ before, after, domains, comparison })) fs.writeFileSync(path.join(directory, `${name}.json`), JSON.stringify(value, null, 2) + '\n');
  const inputs = { customStartingDates: encode({ chosen: { date: ' 2026-09-09 ', amount: 0 } }), chosenExternalAccountId: 'chosen' };
  const inputFile = path.join(directory, 'inputs.json');
  fs.writeFileSync(inputFile, JSON.stringify(inputs, null, 2) + '\n');
  for (const revision of ['before', 'after']) {
    const run = spawnSync(process.execPath, [path.join(pkg, 'src/cli.mjs'), 'explain', '--file', path.join(directory, `${revision}.json`), '--inputs', inputFile], { encoding: 'utf8', timeout: 10_000 });
    assert.equal(run.status, 0, run.stderr);
    assert.ok(!run.stdout.includes('/binding/original'));
    fs.writeFileSync(path.join(directory, `${revision}.md`), describeChangeScope(changeScope) + '\n\n' + run.stdout);
  }
  const replay = spawnSync(process.execPath, [path.join(pkg, 'src/cli.mjs'), 'compare', '--before', path.join(directory, 'before.json'), '--after', path.join(directory, 'after.json'), '--domains', path.join(directory, 'domains.json'), '--json'], { encoding: 'utf8', timeout: 10_000 });
  assert.equal(replay.status, 0, replay.stderr);
  assert.equal(JSON.parse(replay.stdout).status, comparison.status);
  assert.equal(JSON.parse(replay.stdout).checked, comparison.checked);
  const sourceLink = (label, revision, line) => `[${label}](<${files[revision].replaceAll('\\', '/')}:${line}>)`;
  fs.writeFileSync(path.join(directory, 'comparison.md'), `${describeChangeSummary(comparison)}\n\n${describeChangeScope(changeScope)}\n\n# 날짜·잔액 계산을 함수로 옮긴 구간의 비교\n\n변경 전 const 세 선언과 변경 후 호출·함수 본문·결과 바인딩을, 구간 끝의 startingDate·startingBalance 값으로 비교했다.\n\n원본 위치: ${sourceLink('변경 전 구간', 'before', target.before.startLine)}, ${sourceLink('변경 후 호출', 'after', after.index.call.line)}, ${sourceLink('분리한 함수 본문', 'after', after.index.functionDeclaration.line)}.\n\n${describeComparison(comparison)}\n\n동일 판정은 명시한 입력과 선택 변수에 한정한다. 이 커밋의 다른 UI 변경이나 다섯 요청의 실행까지 동일하다는 뜻은 아니다.\n`);
  results.push({ id: target.id, case: target.case, engineSha256: before.engineSha256,
    sourceSha256: { before: hash(sources.before), after: hash(sources.after) },
    pairedInputs: comparison.checked, changedInputs: comparison.changes.length, nativeChecks, thrownChecks, unsupportedChecks,
    cliReplayChecks: 3, changeScope, directory });
}
const result = { schema: 'web-binding-comparison-results-1', producerSha256: hash(fs.readFileSync(fileURLToPath(import.meta.url))),
  selectionSha256: hash(fs.readFileSync(path.join(pkg, 'corpus/binding-comparisons.json'))), domainsSha256: hash(JSON.stringify(domains)),
  scope: selection.scope, wholeBehaviorCasesVerified: 0, results };
fs.writeFileSync(path.join(root, 'build/web-review/binding-comparison-results.json'), JSON.stringify(result, null, 2) + '\n');
process.stdout.write(JSON.stringify({ ...result, results: results.map(({ changeScope, ...row }) => row) }, null, 2) + '\n');
