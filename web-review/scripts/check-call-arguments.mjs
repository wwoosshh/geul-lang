import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { liftCallArguments, liftCallEntry } from '../src/call-entry.mjs';
import { hash } from '../src/typescript.mjs';
import { observe } from '../src/core.mjs';
import { ENGINE_SHA256 } from '../src/fingerprint.mjs';

const pkg = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'), root = path.dirname(pkg), build = path.join(root, 'build/web-review');
const read = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const selection = read(path.join(pkg, 'corpus/call-entries.json'));
const target = selection.targets.find(row => row.id === 'actual-tag-rename-validation'); assert.ok(target);
const nativeReport = read(path.join(build, 'call-entry-results.json'));
assert.equal(nativeReport.engineSha256, ENGINE_SHA256);
assert.equal(nativeReport.producerSha256, hash(fs.readFileSync(path.join(pkg, 'scripts/check-call-entries.mjs'))));
assert.equal(nativeReport.selectionSha256, hash(fs.readFileSync(path.join(pkg, 'corpus/call-entries.json'))));
assert.equal(nativeReport.corpusLockSha256, hash(fs.readFileSync(path.join(pkg, 'corpus/lock.json'))));
const native = nativeReport.results.find(row => row.id === target.id); assert.ok(native);
const sourceFile = path.join(root, 'build/web-corpus', target.case, target.revision, target.path), source = fs.readFileSync(sourceFile, 'utf8');
assert.equal(hash(source), native.sourceSha256);
const origin = path.join(build, 'call-entries', target.id);
const linkedEntry = read(path.join(origin, 'artifact.json'));
assert.deepEqual(linkedEntry, liftCallEntry(source, { callee: target.callee, line: target.line, filename: sourceFile }));
const artifact = liftCallArguments(source, { callee: target.callee, line: target.line, filename: sourceFile });
assert.deepEqual(artifact.preparedCall.argumentNames, ['argument1']);
assert.deepEqual(artifact.sourceLinks, linkedEntry.sourceLinks);
const loadEvidence = (name, digest) => {
  const bytes = fs.readFileSync(path.join(origin, name + '.json'));
  assert.equal(hash(bytes), digest, `Changed native ${name} evidence`); return JSON.parse(bytes);
};
const recorded = loadEvidence('observations', native.observationsSha256);
assert.equal(recorded.length, 117); assert.equal(native.inputChecks, recorded.length);
const counts = { inputChecks: 0, argumentsReady: 0, earlyReturns: 0, typeErrors: 0 }, observations = [];
for (const row of recorded) {
  let expected;
  if (row.original.completion === 'TypeError') {
    assert.equal(row.original.calls.length, 0); expected = { kind: 'throw', name: 'TypeError' }; counts.typeErrors++;
  } else {
    assert.equal(row.original.completion, 'returned'); assert.ok([0, 1].includes(row.original.calls.length));
    expected = { kind: 'value', value: { $record: row.original.calls.length
      ? { argument1: row.original.calls[0], stage: 'arguments-ready' } : { stage: 'early-return' } } };
    if (row.original.calls.length) counts.argumentsReady++; else counts.earlyReturns++;
  }
  const observation = observe(artifact.ir, row.inputs);
  assert.deepEqual(observation, expected); counts.inputChecks++;
  observations.push({ inputs: row.inputs, observation, recordedNative: row.original });
}
assert.deepEqual(counts, { inputChecks: 117, argumentsReady: 37, earlyReturns: 50, typeErrors: 30 });
const boundaries = loadEvidence('counterexamples', native.counterexamplesSha256).map(row => {
  assert.equal(row.original.completion, 'TypeError');
  const observation = observe(artifact.ir, row.inputs);
  assert.equal(observation.value.$record.stage, 'arguments-ready');
  return { fault: row.fault, inputs: row.inputs, observation, recordedNative: row.original, note: row.fault === 'argument-getter'
    ? 'The original getter is outside the plain-record profile; the model receives a plain snapshot instead.'
    : 'An argument snapshot does not establish callability or successful invocation.' };
});
assert.deepEqual(boundaries.map(row => row.fault), ['callee-not-callable', 'callee-throws', 'argument-getter']);
const unsupported = loadEvidence('unsupported', native.unsupportedSha256).map(row => {
  const observation = observe(artifact.ir, row.inputs); assert.equal(observation.kind, 'unsupported');
  return { inputs: row.inputs, observation, recordedNative: row.original };
});
assert.equal(unsupported.length, 3);
const directory = path.join(build, 'call-arguments', target.id); fs.mkdirSync(directory, { recursive: true });
const artifactFile = path.join(directory, 'artifact.json'); fs.writeFileSync(artifactFile, JSON.stringify(artifact, null, 2) + '\n');
let cliReplays = 0;
function cli(...args) {
  const result = spawnSync(process.execPath, [path.join(pkg, 'src/cli.mjs'), ...args], { encoding: 'utf8', timeout: 20_000, maxBuffer: 8 * 1024 * 1024 });
  assert.equal(result.status, 0, result.stderr); cliReplays++; return result.stdout;
}
for (const name of ['empty-name', 'changed-name', 'null-tag']) {
  const inputFile = path.join(origin, name + '.json'), inputs = read(inputFile);
  const expected = observe(artifact.ir, inputs);
  assert.deepEqual(JSON.parse(cli('run', '--file', artifactFile, '--inputs', inputFile, '--json')).observation, expected);
  fs.writeFileSync(path.join(directory, name + '.md'), cli('explain', '--file', artifactFile, '--inputs', inputFile));
}
const reading = JSON.parse(cli('read', '--file', artifactFile, '--json'));
assert.deepEqual(reading.sourceLinks, artifact.sourceLinks);
fs.writeFileSync(path.join(directory, 'reading.json'), JSON.stringify(reading, null, 2) + '\n');
fs.writeFileSync(path.join(directory, 'reading.md'), cli('read', '--file', artifactFile));
for (const [name, value] of Object.entries({ observations, boundaries, unsupported })) fs.writeFileSync(path.join(directory, name + '.json'), JSON.stringify(value, null, 2) + '\n');
const report = { schema: 'web-call-argument-results-1', engineSha256: ENGINE_SHA256, id: target.id, ...counts, cliReplays,
  producerSha256: hash(fs.readFileSync(fileURLToPath(import.meta.url))),
  nativeEvidence: { producerSha256: nativeReport.producerSha256, sourceSha256: native.sourceSha256, callbackSourceSha256: native.callbackSourceSha256,
    nativeWrapperSha256: native.nativeWrapperSha256, observationsSha256: native.observationsSha256,
    counterexamplesSha256: native.counterexamplesSha256, unsupportedSha256: native.unsupportedSha256 },
  observationsSha256: hash(fs.readFileSync(path.join(directory, 'observations.json'))), boundaryChecks: boundaries.length, unsupportedProfiles: unsupported.length,
  additionalNativeExecutions: 0, humanParticipants: 0, wholeBehaviorCasesVerified: 0, directory,
  notes: ['Reuses the 117 recorded original callback runs; these are not 117 additional native executions.',
    'Callee identifier value lookup is assumed to complete normally without effects; the model evaluates pure arguments but does not invoke the callee.',
    'Argument value snapshots do not preserve reference identity or establish downstream mutation, React events or server behavior.'] };
fs.writeFileSync(path.join(build, 'call-argument-results.json'), JSON.stringify(report, null, 2) + '\n');
process.stdout.write(JSON.stringify(report) + '\n');
