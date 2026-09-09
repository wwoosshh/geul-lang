import ts from 'typescript';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';

// Test-only instrumentation for the fixed Actual selection shape. It does not
// consume IR, replace filter/concat, or provide a general source transformer.
// Wrappers return the very same evaluated value. Native outcomes are compared
// with the untouched statement separately by the caller.
export function instrumentTransactionSelection(source, { sourceOffset = 0 } = {}) {
  assert.equal(typeof source, 'string'); assert.ok(source.length <= 65536);
  assert.ok(Number.isSafeInteger(sourceOffset) && sourceOffset >= 0);
  const file = ts.createSourceFile('original.ts', source, ts.ScriptTarget.ES2022, true, ts.ScriptKind.TS);
  assert.equal(file.parseDiagnostics.length, 0, 'Invalid selected source');
  assert.equal(file.statements.length, 1, 'Expected one original const statement');
  const statement = file.statements[0];
  assert.ok(ts.isVariableStatement(statement) && !statement.modifiers?.length);
  assert.ok(statement.declarationList.flags & ts.NodeFlags.Const);
  assert.equal(statement.declarationList.declarations.length, 1);
  const declaration = statement.declarationList.declarations[0];
  const identifier = (node, name) => ts.isIdentifier(node) && node.text === name;
  const negated = (node, name) => ts.isPrefixUnaryExpression(node) && node.operator === ts.SyntaxKind.ExclamationToken && identifier(node.operand, name);
  assert.ok(identifier(declaration.name, 'transactionsToDisplay') && !declaration.type);
  const choice = declaration.initializer;
  assert.ok(choice && ts.isConditionalExpression(choice));
  assert.ok(identifier(choice.whenFalse, 'transactions'));
  let shortLeft;
  if (!negated(choice.condition, 'isSearching')) {
    const condition = choice.condition;
    assert.ok(ts.isBinaryExpression(condition) && condition.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken);
    assert.ok(negated(condition.left, 'isSearching') && negated(condition.right, 'isFiltered'));
    shortLeft = condition.left;
  }
  const method = (node, receiver, name) => ts.isCallExpression(node) && !node.questionDotToken && !node.typeArguments?.length
    && ts.isPropertyAccessExpression(node.expression) && !node.expression.questionDotToken
    && identifier(node.expression.expression, receiver) && identifier(node.expression.name, name);
  const concat = choice.whenTrue;
  assert.ok(method(concat, 'previewTransactions', 'concat') && concat.arguments.length === 1);
  const filter = concat.arguments[0];
  assert.ok(method(filter, 'transactions', 'filter') && filter.arguments.length === 1);
  const callback = filter.arguments[0];
  assert.ok(ts.isArrowFunction(callback) && !callback.modifiers?.length && !callback.type && !callback.typeParameters?.length && callback.parameters.length === 1);
  const parameter = callback.parameters[0];
  assert.ok(ts.isIdentifier(parameter.name) && !parameter.initializer && !parameter.dotDotDotToken && !parameter.type && !parameter.questionToken);
  const predicate = callback.body;
  assert.ok(ts.isPrefixUnaryExpression(predicate) && predicate.operator === ts.SyntaxKind.ExclamationToken);
  assert.ok(ts.isPropertyAccessExpression(predicate.operand) && !predicate.operand.questionDotToken);
  assert.ok(identifier(predicate.operand.expression, parameter.name.text) && identifier(predicate.operand.name, 'is_child'));

  const probes = [];
  function add(event, node) {
    const start = node.getStart(file), end = node.end;
    probes.push({ id: probes.length, event, start, end, source: { start: sourceOffset + start, end: sourceOffset + end } });
  }
  add('branch', choice.condition);
  if (shortLeft) add('short-left', shortLeft);
  add('filter-item', predicate); add('filter-result', filter); add('concat-result', concat);
  for (const a of probes) for (const b of probes) assert.ok(!(a.start < b.start && b.start < a.end && a.end < b.end), 'Crossing probe spans');
  const name = '__geul_trace_' + createHash('sha256').update(source).digest('hex').slice(0, 16);
  const visit = node => { if (ts.isIdentifier(node)) assert.notEqual(node.text, name, 'Probe name collision'); ts.forEachChild(node, visit); };
  visit(file);
  const positions = [...new Set([0, source.length, ...probes.flatMap(probe => [probe.start, probe.end])])].sort((a, b) => a - b);
  let instrumented = '';
  for (const [index, position] of positions.entries()) {
    for (const probe of probes.filter(probe => probe.end === position).sort((a, b) => b.start - a.start)) instrumented += '))';
    for (const probe of probes.filter(probe => probe.start === position).sort((a, b) => b.end - a.end)) instrumented += `${name}(${probe.id}, (`;
    if (index + 1 < positions.length) instrumented += source.slice(position, positions[index + 1]);
  }
  return { source: instrumented, probeName: name, probes };
}

export function createTransactionProbe(instrumentation, { limit = 1024 } = {}) {
  assert.ok(Number.isSafeInteger(limit) && limit >= 1 && limit <= 65536);
  const events = [], counts = new Map();
  const probe = (id, value) => {
    assert.ok(events.length < limit, 'Native probe event limit exceeded');
    const description = instrumentation.probes[id]; assert.ok(description);
    const event = { event: description.event, source: description.source };
    if (['branch', 'short-left', 'filter-item'].includes(description.event)) {
      assert.equal(typeof value, 'boolean', 'This fixed oracle accepts Boolean predicate results only');
      event.value = value;
      if (description.event === 'filter-item') { event.index = counts.get(id) ?? 0; counts.set(id, event.index + 1); }
    } else { assert.ok(Array.isArray(value)); event.length = value.length; }
    events.push(event);
    return value;
  };
  return { probe, events };
}

// Compare only the common recorded operations. Bind/copy bookkeeping and error
// locations are deliberately outside this projection; outcomes are compared too.
export function projectTransactionTrace(observation) {
  assert.ok(['value', 'throw'].includes(observation.kind));
  assert.ok(Array.isArray(observation.trace) && observation.traceTruncated === false);
  const events = [];
  for (const row of observation.trace) {
    let event, source;
    if (row.event === 'branch') {
      assert.equal(row.condition.category, 'scalar');
      assert.equal(typeof row.condition.value, 'boolean'); assert.equal(row.selected, row.condition.value ? 'yes' : 'no');
      event = { event: 'branch', value: row.condition.value }; source = row.conditionSource;
    } else if (row.event === 'short-circuit') {
      assert.equal(row.operator, '&&'); assert.equal(row.left.category, 'scalar');
      assert.equal(typeof row.left.value, 'boolean'); assert.equal(row.evaluatedRight, row.left.value);
      event = { event: 'short-left', value: row.left.value }; source = row.leftSource;
    } else if (row.event === 'filter-item') {
      event = { event: row.event, value: row.selected, index: row.index }; source = row.source;
    } else if (['filter-result', 'concat-result'].includes(row.event)) {
      event = { event: row.event, length: row.length }; source = row.source;
    } else { assert.ok(['bind', 'observed-binding', 'filter-start', 'concat-part', 'throw'].includes(row.event), `Unexpected fixed-case event ${row.event}`); continue; }
    assert.ok(source && Number.isInteger(source.start) && Number.isInteger(source.end));
    event.source = { start: source.start, end: source.end }; events.push(event);
  }
  return events;
}

export function attachNativeTraceEvidence(reading, observation, native, { inputs, key, revision, group = 'fixed-domain' }) {
  assert.ok(native && typeof native === 'object', 'Missing native trace row for the selected revision and input');
  assert.ok(['fixed-domain', 'fault-probe'].includes(group), 'Unknown native input group');
  assert.equal(native.group, group); assert.equal(native.key, key); assert.equal(native.revision, revision);
  assert.deepEqual(native.inputs, inputs);
  const { trace, traceTruncated, ...outcome } = observation;
  assert.deepEqual(native.outcome, outcome);
  const projection = projectTransactionTrace(observation);
  assert.deepEqual(native.events, projection);
  assert.equal(reading.status, 'recorded-ir-execution'); assert.equal(reading.outcome, outcome.kind);
  assert.equal(reading.truncated, false); assert.equal(reading.eventCount, trace.length); assert.equal(reading.rows.length, trace.length);
  const comparedSequences = [];
  for (const [index, row] of reading.rows.entries()) {
    assert.equal(row.sequence, index + 1); assert.equal(row.event, trace[index].event); assert.deepEqual(row.source, trace[index].source);
    if (['branch', 'short-circuit', 'filter-item', 'filter-result', 'concat-result'].includes(row.event)) comparedSequences.push(row.sequence);
  }
  assert.equal(comparedSequences.length, native.events.length);
  return { ...reading, nativeEvidence: {
    status: 'matched-fixed-native-projection', group, comparedSequences,
    scope: '이 고정 입력에서 조건·단락 앞값·필터 판단·완료 길이의 값·순서·원본 구간을 계측본과 대조했다. 계측 전 원본과 계측본의 최종 결과도 따로 비교했다.',
    notCompared: '저장·복사 세부 단계·오류 위치·모든 원시 연산·시간·스택·원본 앱 실행은 이 기록 대조에 포함하지 않았다.',
  } };
}
