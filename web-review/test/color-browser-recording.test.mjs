import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { checkColorBrowserRecording } from '../scripts/color-browser-recording.mjs';

const record = JSON.parse(fs.readFileSync(new URL('../evaluation/browser-evidence/2026-09-09-color.json', import.meta.url)));

test('browser color evidence uses visible commits and keeps the raw label discrepancy', () => {
  const result = checkColorBrowserRecording(record, record.commits);
  assert.equal(result.rows.length, 36); assert.equal(result.pairs.length, 18);
  assert.equal(result.rows.filter(row => row.capturedLabel !== row.revision).length, 18);
  const hash = result.rows.find(row => row.revision === 'after' && row.phase === 'hash-only');
  assert.equal(hash.display, ''); assert.equal(hash.observed.errorText, 'Not a valid color');
  assert.equal(result.rows.filter(row => row.action.key === 'Tab').length, 6);
});

test('browser color evidence rejects unrelated commits, lost phases, altered values and geometry', () => {
  for (const mutate of [
    data => { data.rows[18][0] = data.commits.after; },
    data => data.rows.pop(),
    data => { data.rows[3] = data.rows[2]; },
    data => { data.rows[18][4] = '#ff0000'; },
    data => { data.rows[0][5] = 3; },
    data => { data.profiles[1].errorRect.y = 1000; },
    data => { data.profiles[1].errorStyle.visibility = 'hidden'; },
    data => { data.rows[13][6] = { label: 'Canvas background', tag: 'INPUT' }; },
  ]) {
    const data = structuredClone(record); mutate(data);
    assert.throws(() => checkColorBrowserRecording(data, record.commits));
  }
});
