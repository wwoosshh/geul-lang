import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { expectedColorObservations, checkColorCapture, pairColorObservations } from '../scripts/color-observations.mjs';

const spec = JSON.parse(fs.readFileSync(new URL('../corpus/color-scenarios.json', import.meta.url)));
const capture = revision => ({ schema: 'geul-upstream-color-observations-1', revision,
  observations: expectedColorObservations(spec, revision).map(({ declaredInput, ...row }) => row) });

test('color observations retain display versus stored color and missing versus false ARIA', () => {
  const before = checkColorCapture(spec, 'before', capture('before'));
  const after = checkColorCapture(spec, 'after', capture('after'));
  const paired = pairColorObservations(before, after);
  const find = (id, phase) => paired.find(row => row.id === id && row.phase === phase);
  const same = find('whitespace-repeat', 'same-initial');
  assert.equal(same.before.display, '  #ffffff  '); assert.equal(same.after.display, 'ffffff');
  assert.equal(same.before.saved, same.after.saved);
  assert.equal(same.before.ariaPresent, false); assert.equal(same.before.ariaInvalid, null);
  assert.equal(same.after.ariaPresent, true); assert.equal(same.after.ariaInvalid, 'false');
  const cleared = find('delete-to-empty', 'empty');
  assert.equal(cleared.after.display, ''); assert.equal(cleared.after.saved, '#1e9');
  assert.equal(find('delete-to-empty', 'finish').after.display, '1e9');
  assert.deepEqual(after.find(row => row.id === 'invalid-blur' && row.phase === 'invalid').declaredInput,
    { errorMessage: 'Not a valid color' });
});

test('color capture refuses missing, reordered, extra, stale or fabricated observations', () => {
  const mutations = [
    data => data.observations.pop(),
    data => data.observations.reverse(),
    data => data.observations.push(data.observations[0]),
    data => { data.revision = 'after'; },
    data => { data.observations[0].actual.saved = '#ff0000'; },
    data => { data.observations[0].actual.ariaPresent = true; },
    data => { data.observations[0].action.kind = 'api-injection'; },
    data => { data.observations[0].actual.extra = true; },
  ];
  for (const mutate of mutations) {
    const data = capture('before'); mutate(data);
    assert.throws(() => checkColorCapture(spec, 'before', data));
  }
  assert.throws(() => pairColorObservations(
    expectedColorObservations(spec, 'before'), expectedColorObservations(spec, 'after').slice(1)));
});

test('color scenarios refuse ambiguous actions and unrecognized expected states', () => {
  const mutations = [
    data => { data.scenarios[0].steps[0].blur = true; },
    data => { delete data.scenarios[0].steps[0].change; },
    data => { data.scenarios[0].steps[0].error = 'unknown'; },
    data => { data.scenarios[0].steps[0].guessed = true; },
    data => { data.scenarios[0].steps[0].id = 'initial'; },
    data => { data.scenarios.push(data.scenarios[0]); },
    data => { data.scenarios[0].steps[0].beforeDisplay = false; },
  ];
  for (const mutate of mutations) {
    const data = structuredClone(spec); mutate(data);
    assert.throws(() => expectedColorObservations(data, 'after'));
  }
});
