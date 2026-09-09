import assert from 'node:assert/strict';

// Declared expectations for this fixed browser action sequence, not a color
// classifier and not a translation of React callbacks into geul.
const fill = value => ({ kind: 'fill', value });
const key = value => ({ kind: 'key', key: value });
const steps = [
  ['initial', { kind: 'open-menu-and-picker' }, 'ffffff', 'ffffff', '#ffffff', null],
  ['same-initial', fill('  #FFFFFF  '), '  #ffffff  ', 'ffffff', '#ffffff', null],
  ['new-color', fill('  #FF0000  '), 'ff0000', 'ff0000', '#ff0000', null],
  ['repeat-color', fill('  #FF0000  '), '  #ff0000  ', 'ff0000', '#ff0000', null],
  ['invalid-spaces', fill('  notacolor  '), '  notacolor  ', 'notacolor', '#ff0000', 'color'],
  ['only-spaces', fill('   '), '   ', '', '#ff0000', null],
  ['six', fill('1e9df0'), '1e9df0', '1e9df0', '#1e9df0', null],
  ['five', key('Backspace'), '1e9df', '1e9df', '#1e9df0', 'length'],
  ['four', key('Backspace'), '1e9d', '1e9d', '#1e9d', null],
  ['three', key('Backspace'), '1e9', '1e9', '#1e9', null],
  ['two', key('Backspace'), '1e', '1e', '#1e9', 'length'],
  ['one', key('Backspace'), '1', '1', '#1e9', 'length'],
  ['empty', key('Backspace'), '', '', '#1e9', null],
  ['finish-empty', key('Tab'), '1e9', '1e9', '#1e9', null],
  ['invalid-text', fill('notacolor'), 'notacolor', 'notacolor', '#1e9', 'color'],
  ['finish-invalid', key('Tab'), '1e9', '1e9', '#1e9', null],
  ['hash-only', fill('#'), '', '', '#1e9', 'color'],
  ['finish-hash', key('Tab'), '1e9', '1e9', '#1e9', null],
];
const messages = { color: 'Not a valid color', length: 'Hex code must be 3, 4, 6, or 8 characters' };

export function checkColorBrowserRecording(record, commits) {
  assert.equal(record.schema, 'geul-color-browser-observations-1');
  assert.deepEqual(record.commits, commits);
  assert.notEqual(commits.before, commits.after);
  assert.deepEqual(record.columns, ['visibleCommit', 'phase', 'action', 'display', 'saved', 'profile', 'focused', 'capturedLabel']);
  assert.deepEqual(record.common, {
    viewport: { height: 1000, width: 1280 }, documentWidth: 1280,
    inputRect: { height: 32, width: 80.109375, x: 255.890625, y: 688 },
    appStateSize: { width: 798, height: 648 },
  });
  assert.deepEqual(record.consoleErrors, { before: [], after: [] });
  assert.equal(record.profiles.length, 4); assert.equal(record.rows.length, steps.length * 2);
  const result = [];
  for (const [revisionIndex, revision] of ['after', 'before'].entries()) {
    for (const [i, [phase, action, beforeDisplay, afterDisplay, saved, error]] of steps.entries()) {
      const values = record.rows[revisionIndex * steps.length + i];
      assert.equal(values.length, record.columns.length);
      const row = Object.fromEntries(record.columns.map((name, n) => [name, values[n]]));
      // Raw helper labels are retained, including their documented stale value.
      // The page's actual commit is authoritative; mismatched commits fail.
      assert.equal(row.visibleCommit, commits[revision]); assert.equal(row.capturedLabel, 'after');
      assert.equal(row.phase, phase); assert.deepEqual(row.action, action);
      assert.equal(row.display, revision === 'before' ? beforeDisplay : afterDisplay);
      assert.equal(row.saved, saved);
      const expectedProfile = revision === 'before' ? 3 : error === 'color' ? 1 : error === 'length' ? 2 : 0;
      assert.equal(row.profile, expectedProfile);
      const profile = record.profiles[row.profile];
      const message = revision === 'after' && error !== null ? messages[error] : null;
      const invalid = message !== null, border = invalid ? 'rgb(219, 105, 101)' : 'rgb(241, 240, 255)';
      assert.deepEqual(profile, {
        ariaPresent: revision === 'after', ariaInvalid: revision === 'after' ? String(invalid) : null,
        errorText: message, errorRole: invalid ? 'alert' : null, hasErrorClass: invalid,
        errorRect: invalid ? { height: error === 'length' ? 35.1875 : 19.59375, width: 184, x: 212, y: 733 } : null,
        labelStyle: { borderColor: border, color: 'rgb(27, 27, 31)', display: 'grid', visibility: 'visible' },
        errorStyle: invalid ? { borderColor: border, color: border, display: 'block', visibility: 'visible' } : null,
      });
      assert.deepEqual(row.focused, phase === 'initial' ? { label: null, tag: 'DIV' }
        : action.key === 'Tab' ? { label: null, tag: 'SPAN' } : { label: 'Canvas background', tag: 'INPUT' });
      if (profile.errorRect) {
        const { x, y, width, height } = profile.errorRect;
        assert.ok(x >= 0 && y >= 0 && x + width <= record.common.viewport.width && y + height <= record.common.viewport.height);
      }
      result.push({ ...row, revision, observed: profile, declaredInput: { errorMessage: message } });
    }
  }
  const pairs = result.filter(row => row.revision === 'before').map(before => {
    const after = result.find(row => row.revision === 'after' && row.phase === before.phase);
    return { phase: before.phase, action: before.action, beforeDisplay: before.display, afterDisplay: after.display,
      saved: before.saved, displayChanged: before.display !== after.display,
      errorAdded: after.observed.errorText !== null, propertyAdded: !before.observed.ariaPresent && after.observed.ariaPresent };
  });
  assert.equal(pairs.filter(row => row.displayChanged).length, 4);
  assert.equal(pairs.filter(row => row.errorAdded).length, 6);
  return { rows: result, pairs };
}
