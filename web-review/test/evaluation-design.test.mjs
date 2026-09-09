import test from 'node:test';
import assert from 'node:assert/strict';
import { plannedAllocation } from '../evaluation/design.mjs';

test('planned slots balance task, condition and position without fabricating participants', () => {
  const plan = plannedAllocation(['one', 'two', 'three', 'four']);
  assert.equal(plan.participants, 0);
  assert.equal(plan.slots.length, 8);
  assert.ok(plan.slots.every(s => s.assignedParticipant === null));
  for (const row of [...plan.byCondition, ...plan.byPosition]) assert.deepEqual(row, [2, 2, 2, 2]);
  for (const slot of plan.slots) {
    assert.equal(new Set(slot.tasks.map(t => t.task)).size, 4);
    assert.equal(new Set(slot.tasks.map(t => t.condition)).size, 4);
  }
  assert.throws(() => plannedAllocation(['same', 'same', 'three', 'four']));
});
