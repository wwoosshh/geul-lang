import test from 'node:test';
import assert from 'node:assert/strict';
import { inspectCallEntryCandidates } from '../scripts/call-entry-candidates.mjs';

test('candidate audit separates empty bodies from lowered prefixes and keeps unsupported prefix reasons', () => {
  const source = [
    'function empty(){save();}',
    'function validated(){const x = value.trim(); if(!x)return; save();}',
    'function effects(){changeState(); save();}',
    'async function asynchronous(){save();}',
    'function optional(){save?.();}',
    'function valued(){return save();}',
    'function member(){object.save();}',
    'function later(){save(); return;}',
    'const expression = () => save();',
    'save();',
  ].join('\n');
  const rows = inspectCallEntryCandidates(source, 'candidate.tsx');
  assert.equal(rows.length, 5);
  assert.deepEqual(rows.map(row => row.status), ['empty-prefix', 'lowered-prefix', 'refused', 'refused', 'refused']);
  assert.deepEqual(rows[0].inputs, []); assert.deepEqual(rows[1].inputs, ['value']);
  assert.deepEqual(rows.map(row => row.prefixStatements), [0, 2, 1, 0, 0]);
  assert.match(rows[2].reason, /문장을 건너뛰지/);
  assert.equal(source.slice(rows[2].refusalSource.start, rows[2].refusalSource.end), 'changeState();');
  assert.match(rows[3].reason, /async/); assert.match(rows[4].reason, /일반 직접 호출/);
  for (const row of rows) {
    assert.equal(row.nativeVerified, false);
    assert.match(source.slice(row.source.start, row.source.end), /^save/);
    assert.ok(row.body.start < row.source.start && row.body.end > row.source.end);
  }
});

test('nested functions are discovered independently and same-line ambiguity is not silently resolved', () => {
  const source = 'function f(){ const g = () => { sink(); }; outer(); }\nfunction a(){save();} function b(){save();}';
  const rows = inspectCallEntryCandidates(source, 'candidate.tsx');
  assert.equal(rows.length, 4);
  assert.deepEqual(rows.map(row => row.status), ['refused', 'empty-prefix', 'refused', 'refused']);
  assert.equal(rows[1].callee, 'sink');
  assert.match(rows[2].reason, /2곳/); assert.match(rows[3].reason, /2곳/);
  assert.notEqual(rows[2].source.start, rows[3].source.start);
});
