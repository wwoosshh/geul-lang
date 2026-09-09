import assert from 'node:assert/strict';

// These are declared example expectations, not a parser for arbitrary colors or
// a model of React event/state scheduling. In particular, never derive an IR
// input from the error DOM that will subsequently be used as its oracle.
export function expectedColorObservations(spec, revision) {
  assert.ok(['before', 'after'].includes(revision));
  assert.equal(spec.schema, 'web-color-scenarios-1');
  assert.equal(spec.case, 'excalidraw-color-error');
  assert.equal(spec.initialColor, '#ffffff');
  assert.deepEqual(Object.keys(spec.messages).sort(), ['hex-length', 'invalid-color']);
  for (const text of Object.values(spec.messages)) assert.ok(typeof text === 'string' && text.length > 0 && text.length < 256);
  assert.ok(Array.isArray(spec.scenarios) && spec.scenarios.length > 0 && spec.scenarios.length <= 32);
  const ids = new Set(), rows = [];
  for (const scenario of spec.scenarios) {
    assert.match(scenario.id, /^[a-z][a-z0-9-]*$/);
    assert.ok(!ids.has(scenario.id)); ids.add(scenario.id);
    assert.ok(typeof scenario.label === 'string' && scenario.label.length > 0);
    assert.ok(Array.isArray(scenario.steps) && scenario.steps.length > 0 && scenario.steps.length <= 64);
    const phases = new Set(['initial']);
    const add = (phase, action, display, saved, error) => {
      assert.ok(typeof display === 'string' && display.length < 256);
      assert.ok(typeof saved === 'string' && saved.length > 0 && saved.length < 256);
      assert.ok(error === null || Object.hasOwn(spec.messages, error));
      const declaredMessage = revision === 'after' && error !== null ? spec.messages[error] : null;
      rows.push({ id: scenario.id, phase, action, declaredInput: { errorMessage: declaredMessage },
        actual: { display, saved, ariaPresent: revision === 'after',
          ariaInvalid: revision === 'after' ? String(declaredMessage !== null) : null,
          errorText: declaredMessage, errorRole: declaredMessage !== null ? 'alert' : null,
          errorCount: declaredMessage !== null ? 1 : 0, hasErrorClass: declaredMessage !== null } });
    };
    add('initial', { kind: 'open-menu-and-picker' }, 'ffffff', spec.initialColor, null);
    for (const step of scenario.steps) {
      assert.match(step.id, /^[a-z][a-z0-9-]*$/);
      assert.ok(!phases.has(step.id)); phases.add(step.id);
      assert.ok(Object.keys(step).every(key => ['id', 'change', 'blur', 'display', 'beforeDisplay', 'saved', 'error'].includes(key)));
      assert.notEqual(Object.hasOwn(step, 'change'), Object.hasOwn(step, 'blur'));
      const change = Object.hasOwn(step, 'change');
      if (change) assert.ok(typeof step.change === 'string' && step.change.length < 256);
      else assert.equal(step.blur, true);
      if (Object.hasOwn(step, 'beforeDisplay')) assert.equal(typeof step.beforeDisplay, 'string');
      const display = revision === 'before' && Object.hasOwn(step, 'beforeDisplay') ? step.beforeDisplay : step.display;
      add(step.id, change ? { kind: 'change', value: step.change } : { kind: 'blur' }, display, step.saved, step.error);
    }
  }
  return rows;
}

export function checkColorCapture(spec, revision, captured) {
  assert.equal(captured.schema, 'geul-upstream-color-observations-1');
  assert.equal(captured.revision, revision);
  const expected = expectedColorObservations(spec, revision);
  assert.deepEqual(captured.observations, expected.map(({ declaredInput, ...row }) => row),
    'The entire ordered action/observation sequence must match the declared examples.');
  return expected.map((row, i) => ({ ...row, actual: captured.observations[i].actual }));
}

export function pairColorObservations(before, after) {
  assert.equal(before.length, after.length);
  return before.map((left, i) => {
    const right = after[i];
    for (const key of ['id', 'phase', 'action']) assert.deepEqual(left[key], right[key]);
    assert.deepEqual(Object.keys(left.actual).sort(), Object.keys(right.actual).sort());
    return { id: left.id, phase: left.phase, action: left.action,
      before: left.actual, after: right.actual,
      changedFields: Object.keys(left.actual).filter(key => left.actual[key] !== right.actual[key]) };
  });
}
