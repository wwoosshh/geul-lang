import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { liftRecord } from '../src/record-slice.mjs';
import { liftJsxAttribute } from '../src/jsx.mjs';
import { encode, decode, observe, compare } from '../src/core.mjs';
import { hash } from '../src/typescript.mjs';
import { caseChangeScope, describeChangeScope } from './inventory-scope.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..'), pkg = path.join(root, 'web-review');
const read = name => JSON.parse(fs.readFileSync(path.join(pkg, 'corpus', name), 'utf8'));
const corpus = read('lock.json'), selection = read('record-slices.json');
assert.equal(corpus.selectionSha256, hash(fs.readFileSync(path.join(pkg, 'corpus/selection.json'))));
const drafts = [{}, { date: 'old' }, ...[undefined, null, 0, -0, 23, NaN, Infinity].map(amount => ({ date: 'old', amount })), null, undefined];
const dateValues = ['2026-09-09', '', undefined, null], amountValues = [undefined, null, 0, -0, 23, NaN];
const domains = {
  date: { customStartingDate: drafts.map(value => encode(value)), e: dateValues.map(value => encode({ target: { value } })) },
  amount: { customStartingDate: drafts.map(value => encode(value)), amount: amountValues.map(value => encode(value)) },
  value: { customStartingDate: drafts.map(value => encode(value)) },
};
const results = [];
for (const target of selection.targets) {
  assert.equal(target.oracle, 'starting-settings-records-v1');
  const entry = corpus.cases.find(row => row.id === target.case), artifacts = {}, files = {}, sources = {}, checks = [];
  const directory = path.join(root, 'build/web-review/records', target.id);
  fs.mkdirSync(directory, { recursive: true });
  for (const revision of ['before', 'after']) {
    const blob = entry.blobs.find(row => row.path === target.path && row.revision === revision);
    assert.ok(blob);
    files[revision] = path.join(root, 'build/web-corpus', target.case, revision, target.path);
    sources[revision] = fs.readFileSync(files[revision], 'utf8');
    assert.equal(hash(sources[revision]), blob.sha256);
    artifacts[revision] = {};
    for (const kind of ['date', 'amount', 'value']) {
      artifacts[revision][kind] = target[revision][kind + 'Lines'].map((line, layout) => {
        const artifact = kind === 'value'
          ? liftJsxAttribute(sources[revision], { tag: 'AmountInput', attribute: 'value', line, filename: files[revision] })
          : liftRecord(sources[revision], { line, filename: files[revision] });
        const expression = kind === 'value' ? sources[revision].slice(artifact.ir.source.start, artifact.ir.source.end)
          : sources[revision].slice(artifact.root.start, artifact.root.end);
        const native = new vm.Script(`(${expression})`);
        let nativeChecks = 0, thrownChecks = 0, unsupportedChecks = 0;
        function check(inputs, expected) {
          assert.deepEqual(observe(artifact.ir, inputs), expected);
          const environment = Object.fromEntries(Object.entries(inputs).map(([name, value]) => [name, decode(value)]));
          if (expected.kind === 'throw') {
            assert.throws(() => native.runInNewContext(environment, { timeout: 100 }), error => error.name === 'TypeError');
            thrownChecks++;
          } else {
            const result = native.runInNewContext(environment, { timeout: 100 });
            assert.deepEqual(encode(result && typeof result === 'object' ? Object.fromEntries(Object.entries(result)) : result), expected.value);
          }
          nativeChecks++;
        }
        for (const draft of drafts) {
          const base = { customStartingDate: encode(draft) };
          if (kind === 'value') {
            const amount = draft?.amount;
            check(base, draft == null ? { kind: 'throw', name: 'TypeError' }
              : { kind: 'value', value: encode(revision === 'after' && amount == null ? 0 : amount) });
          } else for (const replacement of kind === 'date' ? dateValues : amountValues) {
            // Independent expected field construction: carry each existing own
            // field, replace the selected field, never fill a missing amount.
            const expectedFields = new Map(Object.entries(draft ?? {}));
            expectedFields.set(kind === 'date' ? 'date' : 'amount', replacement);
            const input = kind === 'date' ? { e: encode({ target: { value: replacement } }) } : { amount: encode(replacement) };
            check({ ...base, ...input }, { kind: 'value', value: encode(Object.fromEntries(expectedFields)) });
          }
        }
        if (kind === 'date') for (const e of [undefined, null, { target: null }]) check({ customStartingDate: encode({}), e: encode(e) }, { kind: 'throw', name: 'TypeError' });
        if (kind !== 'value') for (const draft of ['', 'abc', { $opaque: 'truthy-object' }]) {
          const inputs = { customStartingDate: draft, ...(kind === 'date' ? { e: encode({ target: { value: 'new' } }) } : { amount: 0 }) };
          assert.equal(observe(artifact.ir, inputs).kind, 'unsupported');
          unsupportedChecks++;
        }
        const name = `${revision}-${kind}-${layout}`;
        fs.writeFileSync(path.join(directory, `${name}.json`), JSON.stringify(artifact, null, 2) + '\n');
        checks.push({ name, nativeChecks, thrownChecks, unsupportedChecks });
        return artifact;
      });
    }
  }
  const comparisons = [];
  for (const kind of ['date', 'amount', 'value']) for (const layout of [0, 1]) {
    const comparison = compare(artifacts.before[kind][layout].ir, artifacts.after[kind][layout].ir, domains[kind]);
    assert.equal(comparison.unknown.length, 0);
    assert.equal(comparison.changes.length, kind === 'value' ? 4 : 0);
    comparisons.push({ kind, layout, ...comparison });
  }
  fs.writeFileSync(path.join(directory, 'comparisons.json'), JSON.stringify({ domains, comparisons }, null, 2) + '\n');
  const sample = { customStartingDate: encode({ date: 'old' }), e: encode({ target: { value: '2026-09-09' } }), amount: 0 };
  const inputFile = path.join(directory, 'inputs.json');
  fs.writeFileSync(inputFile, JSON.stringify(sample, null, 2) + '\n');
  const changeScope = caseChangeScope(target.case, [target.path]);
  for (const kind of ['date', 'amount', 'value']) {
    const run = spawnSync(process.execPath, [path.join(pkg, 'src/cli.mjs'), 'explain', '--file', path.join(directory, `after-${kind}-0.json`), '--inputs', inputFile], { encoding: 'utf8', timeout: 10_000 });
    assert.equal(run.status, 0, run.stderr);
    fs.writeFileSync(path.join(directory, `${kind}-example.md`), describeChangeScope(changeScope) + '\n\n' + run.stdout);
  }
  const textValue = encoded => encoded?.$value ?? JSON.stringify(encoded);
  const rows = drafts.filter(value => value !== null && value !== undefined).map(draft => {
    const inputs = { ...sample, customStartingDate: encode(draft) };
    const value = observe(artifacts.after.value[0].ir, inputs).value;
    const date = observe(artifacts.after.date[0].ir, inputs).value.$record;
    const amount = observe(artifacts.after.amount[0].ir, inputs).value.$record;
    return `| ${Object.hasOwn(draft, 'amount') ? textValue(encode(draft.amount)) : '속성 없음'} | ${textValue(value)} | ${Object.hasOwn(date, 'amount') ? textValue(date.amount) : '속성 없음'} | ${textValue(amount.amount)} |`;
  });
  const link = (label, revision, line) => `[${label}](<${files[revision].replaceAll('\\', '/')}:${line}>)`;
  fs.writeFileSync(path.join(directory, 'review.md'), `${describeChangeScope(changeScope)}\n\n# 입력값 0과 잔액 속성 없음의 차이\n\n` +
    '같은 설정 스냅샷에서 AmountInput에 전달할 값과 날짜·잔액 수정용 객체 식을 각각 계산했다. 아래 열들은 독립된 지점의 계산이며, 실제 이벤트를 순서대로 실행한 기록이 아니다.\n\n' +
    '| 입력 설정의 amount | 변경 후 AmountInput.value | 날짜만 바꿀 때 생성 객체의 amount | 잔액 0을 지정할 때 생성 객체의 amount |\n|---|---|---|---|\n' + [...new Set(rows)].join('\n') + '\n\n' +
    '날짜 수정용 객체는 기존 자체 속성을 복사하고 date를 덮어쓴다. 설정에 amount가 없으면 추가하지 않는다. 잔액 수정용 객체는 amount를 직접 지정하므로, 입력에 없던 속성도 새로 생긴다. AmountInput에 0이 전달된다는 사실만으로 잔액 0이 설정에 저장됐다고 해석할 수 없다.\n\n' +
    '같은 입력을 넣은 전후 객체 식은 모든 지정 조합에서 동일했다. AmountInput의 value 식은 amount가 null·undefined인 경우 0을 대신 전달하도록 바뀌었다. 위젯이 실제로 표시하는 문자열·이벤트 발생·React 상태 갱신·최종 요청 및 서버 반영은 여기서 확인하지 않았다.\n\n' +
    `원본: ${link('변경 전 value', 'before', target.before.valueLines[0])}, ${link('변경 후 value', 'after', target.after.valueLines[0])}, ${link('날짜 수정 인자', 'after', target.after.dateLines[0])}, ${link('잔액 수정 인자', 'after', target.after.amountLines[0])}.\n\n` +
    'e 입력은 값 레코드로 제공한 스냅샷이다. 실제 DOM Event의 getter를 실행하거나 이벤트의 도달 가능성을 확인한 것이 아니다. 객체의 자체 속성 생략과 값 undefined는 구별하며, 원래 객체의 프로토타입·열거 순서는 이 표의 관찰 대상이 아니다.\n');
  results.push({ id: target.id, case: target.case, engineSha256: artifacts.after.date[0].engineSha256,
    sourceSha256: Object.fromEntries(Object.entries(sources).map(([revision, source]) => [revision, hash(source)])),
    sites: checks.length, nativeChecks: checks.reduce((sum, row) => sum + row.nativeChecks, 0),
    thrownChecks: checks.reduce((sum, row) => sum + row.thrownChecks, 0), unsupportedChecks: checks.reduce((sum, row) => sum + row.unsupportedChecks, 0),
    cliReplayChecks: 3, checks, comparisons: comparisons.map(({ changes, unknown, ...row }) => ({ ...row, changedInputs: changes.length, unknownInputs: unknown.length })), changeScope, directory });
}
const result = { schema: 'web-record-results-1', producerSha256: hash(fs.readFileSync(fileURLToPath(import.meta.url))),
  selectionSha256: hash(fs.readFileSync(path.join(pkg, 'corpus/record-slices.json'))), domainsSha256: hash(JSON.stringify(domains)),
  scope: selection.scope, wholeBehaviorCasesVerified: 0, results };
fs.writeFileSync(path.join(root, 'build/web-review/record-results.json'), JSON.stringify(result, null, 2) + '\n');
process.stdout.write(JSON.stringify({ ...result, results: results.map(({ changeScope, comparisons, checks, ...row }) => row) }, null, 2) + '\n');
