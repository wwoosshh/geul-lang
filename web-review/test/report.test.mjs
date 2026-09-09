import test from 'node:test';
import assert from 'node:assert/strict';
import { liftProject } from '../src/project.mjs';
import { observe } from '../src/core.mjs';
import { renderExecution } from '../src/report.mjs';

test('Korean explanation is derived from actual execution and preserves failures and omitted paths', () => {
  const a = liftProject({ files: { 'screen.tsx': 'export function Screen(visible: boolean, user: any) { if (!visible) return null; return <button disabled={user.blocked}>삭제</button>; }' }, entry: 'screen.tsx', functionName: 'Screen' });
  const hidden = renderExecution(a, observe(a.ir, { visible: false, user: null }, { trace: true }));
  assert.match(hidden, /결과: \*\*null\*\*/);
  assert.doesNotMatch(hidden, /<button> 구조를 만들었다/);
  const failed = renderExecution(a, observe(a.ir, { visible: true, user: null }, { trace: true }));
  assert.match(failed, /TypeError 발생/);
  assert.match(failed, /"blocked" 속성을 읽다가/);
  assert.doesNotMatch(failed, /<button> 구조를 만들었다/);
  const shown = renderExecution(a, observe(a.ir, { visible: true, user: { $record: { blocked: false } } }, { trace: true }));
  assert.match(shown, /disabled = 거짓/);
  assert.match(shown, /&lt;button&gt; 구조를 만들었다/);
  assert.match(shown, /React 렌더러/);
  const focused = renderExecution(a, observe(a.ir, { visible: false, user: null }, { trace: true }), { inputs: { visible: false, user: null }, snippets: () => '!visible' });
  assert.match(focused, /visible: 거짓/);
  assert.match(focused, /조건 !visible은 참/);
  assert.doesNotMatch(focused, /visible에 .*저장했다/);
});
