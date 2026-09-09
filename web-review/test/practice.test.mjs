import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createPracticeSession } from '../evaluation/viewer/session.mjs';
import { createPracticeServer } from '../evaluation/viewer/server.mjs';
import { hash } from '../src/typescript.mjs';

test('practice clock preserves total time and overlapping AI wait/hidden time without creating participants', () => {
  let now = 0;
  const session = createPracticeSession({ task: 'test', condition: 'B', materialSha256: 'test-hash', now: () => now, wall: () => 'fixed-test-time' });
  now = 100; session.visitSource('0-1', 25);
  now = 200; session.setWaiting(true);
  now = 300; session.setHidden(true);
  now = 500; session.setWaiting(false);
  now = 600; session.setHidden(false);
  now = 800;
  const result = session.finish({ answers: ['condition', 'before/after', 'exception', 'scope'], confidence: 60, familiar: false, aiModel: '' });
  assert.equal(result.participant, null);
  assert.equal(result.mode, 'practice-only');
  assert.equal(result.timing.elapsedMs, 800);
  assert.equal(result.timing.aiWaitingMs, 300);
  assert.equal(result.timing.hiddenMs, 300);
  assert.equal(result.timing.sourceVisits, 1);
  now = 2000;
  session.setWaiting(true);
  assert.equal(session.snapshot().elapsedMs, 800);
  assert.equal(session.snapshot().waiting, false);
  assert.throws(() => session.finish({}), /이미/);
});

test('practice read server serves only listed source and detects changed source without exposing private files', async t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'geul-practice-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const file = path.join(directory, 'source.ts'); fs.writeFileSync(file, 'const value = 1;');
  const server = createPracticeServer({ loaded: { publicData: { status: 'practice-only', participants: 0 }, sources: new Map([['0-0', { file, sha256: hash(fs.readFileSync(file)), label: 'source.ts', revision: 'before' }]]) } });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const base = `http://127.0.0.1:${server.address().port}`;
  assert.equal((await fetch(base + '/api/source?id=0-0')).status, 200);
  for (const route of ['/private/answer-key.json', '/api/source?id=../../private/answer-key.json', '/../../package.json']) assert.equal((await fetch(base + route)).status, 404);
  assert.equal((await fetch(base + '/api/data', { method: 'POST', body: 'answers' })).status, 405);
  assert.equal((await fetch(base + '/api/data', { headers: { Origin: 'https://elsewhere.invalid' } })).status, 403);
  const data = await (await fetch(base + '/api/data')).json();
  assert.equal(data.participants, 0);
  fs.writeFileSync(file, 'changed');
  assert.equal((await fetch(base + '/api/source?id=0-0')).status, 409);
});
