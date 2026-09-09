export const CONDITIONS = ['A', 'B', 'C', 'D'];
const orders = [[0, 1, 3, 2], [1, 2, 0, 3], [2, 3, 1, 0], [3, 0, 2, 1]];
function permutations(items) {
  if (!items.length) return [[]];
  return items.flatMap((item, index) => permutations(items.filter((_, i) => i !== index)).map(tail => [item, ...tail]));
}
// Design slots are not participants or observations. Eight planned slots give
// two appearances per task/condition and task/position combination.
export function plannedAllocation(taskIds) {
  if (taskIds.length !== 4 || new Set(taskIds).size !== 4) throw new Error('이 배정 초안은 서로 다른 과제 네 개에만 적용합니다.');
  const choices = permutations([0, 1, 2, 3]);
  const byCondition = Array.from({ length: 4 }, () => [0, 0, 0, 0]);
  const byPosition = Array.from({ length: 4 }, () => [0, 0, 0, 0]);
  const rows = [];
  function search(slot) {
    if (slot === 8) return true;
    for (const order of choices) {
      const conditions = orders[slot % 4];
      if (order.some((task, position) => byCondition[task][conditions[position]] >= 2 || byPosition[task][position] >= 2)) continue;
      for (const [position, task] of order.entries()) { byCondition[task][conditions[position]]++; byPosition[task][position]++; }
      rows.push(order);
      if (search(slot + 1)) return true;
      rows.pop();
      for (const [position, task] of order.entries()) { byCondition[task][conditions[position]]--; byPosition[task][position]--; }
    }
    return false;
  }
  if (!search(0)) throw new Error('균형 배정표를 찾지 못했습니다.');
  return {
    status: 'unassigned-planned-slots', participants: 0, plannedSlots: 8,
    byCondition, byPosition,
    slots: rows.map((row, slot) => ({ slot: `slot-${slot + 1}`, assignedParticipant: null,
      tasks: row.map((task, position) => ({ position: position + 1, task: taskIds[task], condition: CONDITIONS[orders[slot % 4][position]] })) })),
  };
}
