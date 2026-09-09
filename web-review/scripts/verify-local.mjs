import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import assert from 'node:assert/strict';
import { ENGINE_RUNTIME } from '../src/fingerprint.mjs';

const pkg = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const root = path.dirname(pkg);
const args = process.argv.slice(2);
assert.ok(args.every(arg => arg === '--upstream') && new Set(args).size === args.length, 'Usage: node scripts/verify-local.mjs [--upstream]');
const includeUpstream = args.includes('--upstream');
const directory = path.join(root, 'build/web-review/verification');
fs.mkdirSync(directory, { recursive: true });
const output = fs.mkdtempSync(path.join(directory, 'run-'));
function fingerprint() {
  const url = pathToFileURL(path.join(pkg, 'src/fingerprint.mjs')).href;
  const result = spawnSync(process.execPath, ['--input-type=module', '-e', `import { ENGINE_SHA256 } from ${JSON.stringify(url)}; process.stdout.write(ENGINE_SHA256);`], { encoding: 'utf8', timeout: 10_000 });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /^[a-f0-9]{64}$/);
  return result.stdout;
}
const engineSha256 = fingerprint(), results = [];
// Bound parser/VM worker contention instead of relaxing native oracle timeouts.
const coreTestConcurrency = 4;
const nodeJob = (name, relative, argv = []) => ({ name, command: process.execPath, args: [path.join(pkg, relative), ...argv] });
const pythonJob = (name, relative, argv = []) => ({ name, command: 'python', args: [path.join(pkg, relative), ...argv] });
const coreTests = fs.readdirSync(path.join(pkg, 'test')).filter(name => name.endsWith('.test.mjs')).sort().map(name => path.join(pkg, 'test', name));

async function run(job) {
  const started = Date.now(), logPath = path.join(output, job.name + '.log'), log = fs.openSync(logPath, 'wx');
  process.stdout.write(`Start ${job.name}\n`);
  let status, error;
  try {
    status = await new Promise((resolve, reject) => {
      const child = spawn(job.command, job.args, { cwd: pkg, stdio: ['ignore', log, log], windowsHide: true });
      const timer = setTimeout(() => { child.kill(); reject(new Error('180 second timeout')); }, 180_000);
      child.once('error', reason => { clearTimeout(timer); reject(reason); });
      child.once('exit', code => { clearTimeout(timer); resolve(code); });
    });
  } catch (reason) { error = reason.message; }
  finally { fs.closeSync(log); }
  const result = { name: job.name, status: status === 0 ? 'passed' : 'failed', exitCode: status ?? null,
    durationMs: Date.now() - started, log: logPath, ...(error ? { error } : {}) };
  results.push(result);
  process.stdout.write(`${result.status}: ${job.name}\n`);
  return result;
}
async function phase(jobs) {
  let cursor = 0;
  await Promise.all(Array.from({ length: Math.min(4, jobs.length) }, async () => {
    while (cursor < jobs.length) await run(jobs[cursor++]);
  }));
  assert.ok(results.every(row => row.status === 'passed'), `A check failed; inspect ${output}`);
  assert.equal(fingerprint(), engineSha256, 'Engine source changed during verification; results are not one stable checkpoint.');
}
let error;
try {
  if (includeUpstream) {
    for (const port of [56678, 56680]) {
      const listening = await new Promise(resolve => {
        const socket = net.createConnection({ host: '127.0.0.1', port });
        const done = value => { socket.destroy(); resolve(value); };
        socket.once('connect', () => done(true)); socket.once('error', () => done(false)); socket.setTimeout(1000, () => done(true));
      });
      assert.equal(listening, false, `Stop the original-app browser fixture on port ${port} before a verification that switches its checkout.`);
    }
  }
  await phase([
    { name: 'core', command: process.execPath, args: ['--test', `--test-concurrency=${coreTestConcurrency}`, ...coreTests] },
    { name: 'inventory-parser', command: 'python', args: ['-m', 'unittest', 'discover', '-s', 'inventory-tests'] },
    pythonJob('corpus-blobs', 'scripts/corpus.py', ['verify']),
    pythonJob('runtime-blobs', 'scripts/runtime.py', ['verify']),
    pythonJob('change-inventory', 'scripts/change_inventory.py', ['verify']),
  ]);
  await phase([
    ...['corpus', 'context', 'functions', 'destructuring', 'guards', 'references', 'flows', 'react', 'props', 'result-links', 'bindings', 'records', 'prop-equations', 'arrays', 'jsx-properties'].map(name => nodeJob(name, `scripts/check-${name}.mjs`)),
    nodeJob('browser-recording', 'scripts/browser-evidence.mjs', ['verify']),
    nodeJob('color-browser-recording', 'scripts/color-browser-evidence.mjs', ['verify']),
    nodeJob('recording-guards', 'scripts/check-recording-guards.mjs'),
    nodeJob('call-entries', 'scripts/check-call-entries.mjs'),
    nodeJob('call-entry-candidates', 'scripts/audit-call-entry-candidates.mjs'),
    nodeJob('color-normalization', 'scripts/check-color-normalization.mjs'),
    nodeJob('discovery', 'scripts/check-discovery.mjs'),
    nodeJob('change-discovery', 'scripts/check-change-discovery.mjs'),
  ]);
  await phase([nodeJob('array-traces', 'scripts/check-array-traces.mjs'), nodeJob('slice-source-scope', 'scripts/check-slice-scope.mjs'),
    nodeJob('call-arguments', 'scripts/check-call-arguments.mjs'), ...(includeUpstream ? [
    nodeJob('upstream-jsdom', 'scripts/check-upstream.mjs'),
    nodeJob('upstream-color', 'scripts/check-upstream-color.mjs'),
  ] : [])]);
  await phase([nodeJob('output-props', 'scripts/check-output-props.mjs')]);
  await phase([nodeJob('behavior-materials', 'scripts/prepare-behavior-reviews.mjs')]);
  await phase([nodeJob('inspector-materials', 'scripts/prepare-inspector.mjs')]);
  await phase([nodeJob('pilot-materials', 'scripts/prepare-pilot.mjs')]);
  await phase([nodeJob('practice-scoring', 'scripts/check-scoring.mjs')]);
} catch (reason) { error = reason.message; }
const report = {
  schema: 'web-local-verification-1', status: error ? 'failed' : 'passed', engineSha256,
  finishedAt: new Date().toISOString(), node: process.version, runtime: ENGINE_RUNTIME, includeUpstream, coreTestConcurrency,
  checks: results.sort((a, b) => a.name.localeCompare(b.name)), ...(error ? { error } : {}),
  browserRerun: false, humanParticipants: 0, wholeBehaviorCasesVerified: 0,
  notes: ['Browser-recording verification checks retained CUA observations; it does not rerun the browser.',
    'File inventory, source links, native execution comparisons and human evaluation are different measurements.'],
};
fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n', { flag: 'wx' });
if (!error) fs.writeFileSync(path.join(root, 'build/web-review/verification-latest.json'), JSON.stringify(report, null, 2) + '\n');
process.stdout.write(JSON.stringify({ status: report.status, engineSha256, checks: results.length, output, ...(error ? { error } : {}) }) + '\n');
if (error) process.exitCode = 1;
