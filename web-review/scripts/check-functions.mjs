import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import ts from 'typescript';
import { fileURLToPath } from 'node:url';
import { parseSource, hash } from '../src/typescript.mjs';
import { liftProject } from '../src/project.mjs';
import { observe, encode, decode } from '../src/core.mjs';
import { renderExecution } from '../src/report.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const read = name => JSON.parse(fs.readFileSync(path.join(root, 'web-review/corpus', name), 'utf8'));
const selectionFile = path.join(root, 'web-review/corpus/selection.json');
const lock = read('lock.json'), targets = read('functions.json').targets;
assert.equal(lock.selectionSha256, hash(fs.readFileSync(selectionFile)));

// Independently authored examples, not evaluated predicates generated from IR.
// Whitespace-only dates disappear; nonblank dates retain their ORIGINAL text.
// This includes each ECMAScript trim whitespace/line terminator individually,
// and two non-whitespace characters often confused with whitespace.
function startingSettingsCases() {
  const absent = { name: 'absent' }, undef = { $value: 'undefined' };
  const dates = [absent, { value: undefined }, { value: null }, { value: '' },
    ...['\u0009', '\u000a', '\u000b', '\u000c', '\u000d', ' ', '\u00a0', '\u1680',
      '\u2000', '\u2001', '\u2002', '\u2003', '\u2004', '\u2005', '\u2006', '\u2007',
      '\u2008', '\u2009', '\u200a', '\u2028', '\u2029', '\u202f', '\u205f', '\u3000', '\ufeff', '\t \n']
      .map(value => ({ value })),
    ...['2026-09-09', '  2026-09-09  ', '\u200b', '\u0085', 'invalid-date', '오늘']
      .map(value => ({ value, expected: value }))];
  const amounts = [absent, { value: undefined }, { value: null },
    ...[0, -0, 1, -500, NaN, Infinity, -Infinity].map(value => ({ value, expected: value }))];
  const result = [];
  for (const date of dates) for (const amount of amounts) {
    const settings = {};
    if (Object.hasOwn(date, 'value')) settings.date = date.value;
    if (Object.hasOwn(amount, 'value')) settings.amount = amount.value;
    result.push({ inputs: { settings: encode(settings) }, expected: { kind: 'value', value: encode({ startingDate: date.expected, startingBalance: amount.expected }) } });
  }
  for (const settings of [null, undef]) result.push({ inputs: { settings }, expected: { kind: 'value', value: { $record: { startingBalance: undef, startingDate: undef } } } });
  return result;
}

const results = [];
for (const target of targets) {
  assert.equal(target.oracle, 'starting-settings-v1', 'Every target needs an independent oracle.');
  const item = lock.cases.find(item => item.id === target.case);
  const blob = item?.blobs.find(blob => blob.revision === target.revision && blob.path === target.path);
  assert.ok(blob, 'Target must be part of the frozen corpus.');
  const sourceFile = path.join(root, 'build/web-corpus', target.case, target.revision, target.path);
  const bytes = fs.readFileSync(sourceFile);
  assert.equal(hash(bytes), blob.sha256);
  const source = bytes.toString('utf8'), entry = path.basename(sourceFile);
  const artifact = { ...liftProject({ files: { [entry]: source }, entry, functionName: target.functionName, isolation: 'function-body' }), sourceFile };
  // Keep the selected declaration's exact source. Surrounding imports and
  // module initialization are deliberately outside this declared experiment.
  const parsed = parseSource(source, sourceFile);
  const declarations = parsed.statements.filter(node => ts.isFunctionDeclaration(node) && node.name?.text === target.functionName && node.body);
  assert.equal(declarations.length, 1);
  const declaration = declarations[0].getText(parsed);
  const compiled = ts.transpileModule(declaration, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const script = new vm.Script(`${compiled}\nexports.${target.functionName}(settings);`);
  const cases = startingSettingsCases();
  for (const test of cases) {
    const native = script.runInNewContext({ exports: {}, settings: decode(test.inputs.settings) }, { timeout: 100 });
    const actual = { kind: 'value', value: encode(Object.fromEntries(Object.entries(native))) };
    assert.deepEqual(actual, test.expected, JSON.stringify(test.inputs));
    assert.deepEqual(observe(artifact.ir, test.inputs), actual, JSON.stringify(test.inputs));
  }
  // Reject claiming results for invalid receiver kinds instead of replacing
  // a user-provided trim method or running arbitrary coercion.
  let unsupportedChecks = 0;
  for (const date of [5, true, { $record: {} }]) {
    assert.equal(observe(artifact.ir, { settings: { $record: { date } } }).kind, 'unsupported');
    unsupportedChecks++;
  }
  const inputs = { settings: { $record: { date: '  2026-09-09  ', amount: 0 } } };
  const observation = observe(artifact.ir, inputs, { trace: true });
  const report = renderExecution(artifact, observation, { inputs, snippets: loc => loc ? source.slice(loc.start, loc.end) : undefined });
  const directory = path.join(root, 'build/web-review/functions', target.id);
  fs.mkdirSync(directory, { recursive: true });
  fs.writeFileSync(path.join(directory, 'artifact.json'), JSON.stringify(artifact, null, 2) + '\n');
  fs.writeFileSync(path.join(directory, 'inputs.json'), JSON.stringify(inputs, null, 2) + '\n');
  fs.writeFileSync(path.join(directory, 'explanation.md'), report);
  results.push({ id: target.id, case: target.case, revision: target.revision, sourceSha256: blob.sha256,
    functionBodyDifferentialChecks: cases.length, unsupportedChecks, artifact, cases });
}
const output = { schema: 'web-function-results-1', selectedBodyCount: results.length,
  differentialChecks: results.reduce((sum, item) => sum + item.functionBodyDifferentialChecks, 0),
  unsupportedChecks: results.reduce((sum, item) => sum + item.unsupportedChecks, 0),
  wholeBehaviorCasesVerified: 0,
  notProven: ['원본 모듈 초기화와 실제 함수 호출 연결', '날짜·금액의 업무상 유효성', 'React 렌더링과 서버 동작', '입력 계약 밖의 객체·무한 입력 범위', '사람이 설명을 읽고 더 잘 검토한다는 사실'], results };
fs.mkdirSync(path.join(root, 'build/web-review'), { recursive: true });
fs.writeFileSync(path.join(root, 'build/web-review/function-results.json'), JSON.stringify(output, null, 2) + '\n');
process.stdout.write(JSON.stringify({ ...output, results: results.map(({ cases, artifact, ...summary }) => summary) }, null, 2) + '\n');
