const $ = id => document.getElementById(id);
const make = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
};
const normalize = file => file.replaceAll('\\', '/');
let data, state, sourceOrigin, view = 'change', revision = 'after';
const versionName = name => name === 'before' ? '변경 전' : '변경 후';
function pretty(value, depth = 0) {
  if (value?.$value) return value.$value;
  if (value?.$array) return '[' + value.$array.map(item => pretty(item, depth + 1)).join(', ') + ']';
  if (value?.$record) {
    const fields = Object.entries(value.$record);
    if (!fields.length) return '{}';
    return '{ ' + fields.map(([key, item]) => `${JSON.stringify(key)}: ${pretty(item, depth + 1)}`).join(', ') + ' }';
  }
  return JSON.stringify(value);
}
function sourceFor(location, side) {
  return data.sources.find(source => source.revision === side && (normalize(source.file) === normalize(location.file) || normalize(source.alias) === normalize(location.file)));
}
function excerpt(location, side) {
  const source = sourceFor(location, side);
  if (!source) return '이 자료에 포함되지 않은 원본';
  const text = source.text.slice(location.start, location.end);
  return text.length > 220 ? text.slice(0, 220) + '… (일부 생략)' : text;
}
function showSource(location, side, selectedId) {
  const source = selectedId ? data.sources.find(item => item.id === selectedId) : sourceFor(location, side);
  if (!source) { $('source-position').textContent = '이 자료에는 해당 위치의 원본이 포함되지 않았습니다.'; return; }
  $('source-file').value = source.id;
  $('source-version').textContent = versionName(source.revision) + (source.role === 'child' ? ' · 자식' : ' · 부모');
  const line = location?.line ?? source.initialLine;
  const lastLine = location?.end !== undefined ? source.text.slice(0, Math.max(location.start ?? 0, location.end - 1)).split('\n').length : line;
  $('source-position').textContent = `${source.name} · ${line}${lastLine !== line ? '–' + lastLine : ''}행 선택`;
  const code = $('source-code'); code.replaceChildren();
  let offset = 0;
  for (const [index, raw] of source.text.split('\n').entries()) {
    const text = raw.replace(/\r$/, ''), selected = index + 1 >= line && index + 1 <= lastLine;
    const row = make('div', undefined, 'code-line' + (selected ? ' selected' : ''));
    const number = make('span', String(index + 1), 'line-number'); number.setAttribute('aria-hidden', 'true');
    const content = make('span', undefined, 'code-text');
    if (selected && location?.start !== undefined) {
      const begin = Math.max(0, Math.min(text.length, location.start - offset));
      const end = Math.max(begin, Math.min(text.length, location.end - offset));
      content.append(document.createTextNode(text.slice(0, begin)), make('mark', text.slice(begin, end)), document.createTextNode(text.slice(end)));
    } else content.textContent = text || ' ';
    row.append(number, content); code.append(row); offset += raw.length + 1;
  }
  const lineHeight = parseFloat(getComputedStyle(code).lineHeight);
  code.scrollTop = Math.max(0, (line - 1) * lineHeight - Math.min(60, code.clientHeight * .2));
}
function sourceButton(location, side, label) {
  const source = sourceFor(location, side);
  const button = make('button', label ?? `${source?.name ?? '원본'}:${location.line} ↗`, 'source-link');
  button.type = 'button'; button.addEventListener('click', () => visitSource(location, side, button)); return button;
}
function visitSource(location, side, origin) {
  showSource(location, side);
  sourceOrigin = origin;
  $('source-return').hidden = false;
  const panel = document.querySelector('.source'), bounds = panel.getBoundingClientRect();
  if (matchMedia('(max-width: 820px)').matches || bounds.top < 0 || bounds.top > innerHeight - 80) {
    panel.scrollIntoView({ block: 'start', behavior: 'instant' });
    $('source-code').focus({ preventScroll: true });
  }
}
function currentState() {
  const key = [Number($('searching').checked), Number($('filtered').checked), Number($('transaction').value), Number($('preview').value)].join(':');
  const found = data.states.find(item => item.key === key);
  if (!found) throw new Error('고정된 입력 예시를 찾을 수 없습니다. 자료를 다시 생성한 뒤 새로고침하세요.');
  return found;
}
function renderResults() {
  const status = $('result-status');
  status.textContent = state.changed ? '이 예시의 관찰값은 다릅니다' : '이 예시의 관찰값은 같습니다';
  status.className = state.changed ? 'different' : '';
  for (const side of ['before', 'after']) {
    const value = state.observations[side].value.$record.transactionsToDisplay;
    const modified = new Set();
    for (const edit of state.delta.edits) {
      const count = side === 'before' ? edit.removed.length : edit.inserted.length, start = side === 'before' ? edit.beforeStart : edit.afterStart;
      for (let index = start; index < start + count; index++) modified.add(index);
    }
    const list = $(side + '-values'); list.replaceChildren();
    if (!value.$array.length) list.append(make('li', '빈 목록', 'empty'));
    for (const [index, item] of value.$array.entries()) {
      const id = item?.$record?.id;
      const label = typeof id === 'string' ? id : `${index + 1}번째 원소`;
      const token = make('li', label, modified.has(index) ? side === 'before' ? 'removed' : 'inserted' : '');
      token.title = pretty(item); list.append(token);
    }
    $(side + '-full').textContent = versionName(side) + '\n' + value.$array.map((item, index) => `${index + 1}. ${pretty(item)}`).join('\n') + (value.$array.length ? '' : '[]');
  }
}
function renderChanges(container) {
  container.append(make('h3', '목록을 고르는 조건이 바뀌었습니다'));
  const envelope = data.comparison.changeConditions.envelope;
  container.append(make('p', `고정된 ${data.comparison.checked}개 예시에서 변경은 검색이 꺼지고 필터가 켜진 범위에 있었습니다. 이 범위 ${envelope.matchedRows}개 중 ${envelope.changedRows}개는 달라지고 ${envelope.unchangedRows}개는 같았습니다.`));
  const pair = make('div', undefined, 'condition-pair');
  const change = data.comparison.structureComparison.changes[0];
  for (const side of ['before', 'after']) {
    const button = make('button', undefined, 'condition-line'); button.type = 'button';
    button.append(make('small', versionName(side) + ' · 원본에서 보기 ↗'), make('code', excerpt(change[side].source, side)));
    button.addEventListener('click', () => visitSource(change[side].source, side, button)); pair.append(button);
  }
  container.append(pair, make('p', '미리보기와 필터링한 거래를 합치는 갈래, 조회 목록을 그대로 고르는 갈래의 IR 구조는 유지됐습니다. 그 둘 중 무엇을 고를지 결정하는 조건이 달라졌습니다.'));
  container.append(make('p', state.changed ? '지금 고른 예시에서는 위의 두 목록이 다릅니다. 전체 관찰값을 열어 제외·추가된 원소를 확인할 수 있습니다.' : '지금 고른 예시에서는 두 관찰 목록이 같습니다. 필터를 켰다는 사실만으로 항상 목록이 달라지는 것은 아닙니다.'));
  container.append(make('p', '같은 갈래 코드도 입력이나 앞선 계산값이 달라지면 다른 결과를 낼 수 있습니다. 구조 비교는 전체 동작 동등성의 증명이 아닙니다.', 'quiet scope-note'));
}
function renderNode(node, depth, role) {
  const item = make('li');
  if (role) item.append(make('span', role, 'node-role'));
  if (node.fragment) {
    item.append(make('div', node.fragment, 'node-leaf'), sourceButton(node.source, revision)); return item;
  }
  const details = make('details'); details.open = depth < 2;
  details.append(make('summary', node.text), sourceButton(node.source, revision));
  const children = make('ol');
  if (node.kind === 'access') {
    children.append(renderNode(node.children[0].node, depth + 1, node.children[0].role));
    for (const [index, step] of node.steps.entries()) {
      children.append(make('li', step.text, 'node-leaf'));
      const key = node.children.find(row => row.node.path === node.path + `.steps[${index}].value`);
      if (key) children.append(renderNode(key.node, depth + 1, key.role));
    }
  } else for (const child of node.children) children.append(renderNode(child.node, depth + 1, child.role));
  details.append(children); item.append(details); return item;
}
function renderCalculation(container) {
  container.append(make('h3', versionName(revision) + '의 가능한 계산'), make('p', '입력 예시 하나의 실행 기록이 아니라 선택 구간의 계산 구조입니다. 선택하지 않은 갈래는 실행하지 않으며, 앞 계산이 정상 완료돼야 다음으로 진행합니다.', 'quiet'));
  const list = make('ol', undefined, 'calculation-tree'); list.append(renderNode(data.readings[revision].tree, 0));
  container.append(list, make('p', '일반 속성 읽기에서 대상이 null·undefined이면 TypeError입니다. 실제 구간 도달·원본 앱의 상태 변화는 별도입니다.', 'quiet scope-note'));
  const bindings = data.readings[revision].inputBindings;
  if (!bindings?.inputs?.length) return;
  const origins = make('details', undefined, 'input-origins'); origins.append(make('summary', '입력이 선언된 곳'));
  origins.append(make('p', '원본에서 입력 이름을 선언한 위치와 그 식을 연결했습니다. 초기화·기본값·hook을 실행하거나 위의 입력 예시와 같은 값이라고 판단하지 않습니다.', 'quiet'));
  const grouped = new Map();
  for (const input of bindings.inputs) {
    const key = JSON.stringify([input.name, input.status, input.declarations, input.declarationsTruncated]);
    if (!grouped.has(key)) grouped.set(key, { ...input, uses: [] });
    grouped.get(key).uses.push(input.use);
  }
  for (const input of grouped.values()) {
    const entry = make('div', undefined, 'input-origin'); entry.append(make('h4', input.name));
    const declaration = input.status === 'declaration-found' ? input.declarations[0] : undefined;
    for (const [i, location] of input.uses.entries()) entry.append(sourceButton(location, revision, `선택 구간의 사용 ${i + 1} ↗`));
    if (input.declarationsTruncated) entry.append(make('p', '선언 목록 일부가 생략됐습니다.', 'quiet'));
    if (!declaration) { entry.append(make('p', '선언을 확정하지 못했습니다.', 'quiet')); origins.append(entry); continue; }
    entry.append(sourceButton(declaration.source, revision, '선언 위치 ↗'));
    const origin = declaration.destructuringOrigin;
    const showExpression = (label, source) => {
      entry.append(make('p', label, 'quiet'), make('pre', excerpt(source, revision), 'origin-expression'), sourceButton(source, revision, label + ' 원본 ↗'));
    };
    if (origin) {
      showExpression('구조 분해 패턴', origin.pattern);
      if (origin.expression) showExpression(origin.expressionRole === 'parameter-default' ? '매개변수 기본값 식' : '패턴을 받는 선언의 초기화 식', origin.expression);
      else entry.append(make('p', origin.kind === 'variable-pattern' ? '이 선언에는 초기화 식이 없습니다. 실제로 받은 값은 확인하지 않았습니다.' : '함수 인수나 예외에서 받은 실제 값은 확인하지 않았습니다.', 'quiet'));
    }
    if (declaration.initializer) showExpression(declaration.initializerRole === 'default-value' ? '조건부 기본값 식' : '초기화 식', declaration.initializer);
    origins.append(entry);
  }
  container.append(origins);
}
function renderUses(container) {
  const links = data.readings[revision].outputPropLinks;
  container.append(make('h3', '계산 다음에, 어디서 참조할까'), make('p', '이 연결은 실행 결과가 아닌 원본 탐색입니다. 위 목록을 아래 자식의 실제 입력값이나 화면 값으로 대입하지 않았습니다.', 'quiet'));
  for (const link of links.links) {
    container.append(make('p', `${link.name}\n→ TransactionListWithBalances.${link.property}\n→ 자식 매개변수 ${link.parameter.name}`, 'binding-chain'));
    container.append(sourceButton(link.use.source, revision, '부모가 속성에 적은 위치 ↗'), make('span', ' · '), sourceButton(link.parameter.source, revision, '자식 매개변수 선언 ↗'));
    if (link.defaultInitializer) container.append(make('p', '기본값 식은 실행하지 않았습니다: ' + excerpt(link.defaultInitializer, revision), 'quiet'));
    const list = make('div', undefined, 'uses-list');
    for (const use of link.childUses) {
      const button = make('button', undefined, 'use-site'); button.type = 'button';
      const source = sourceFor(use.source, revision);
      button.append(make('code', excerpt(use.expression ?? use.source, revision)), make('small', `${source.name}:${use.source.line} ↗`),
        make('span', (use.kind === 'jsx-attribute' ? '속성에 적힌 참조 · 실제 전달은 미확인' : '별도 해석이 필요한 참조') + (use.nestedFunction ? ' · 다른 함수의 캡처' : ''), 'use-kind'));
      button.addEventListener('click', () => visitSource(use.expression ?? use.source, revision, button)); list.append(button);
    }
    container.append(list);
  }
  container.append(make('p', '자식 hook, 이후 객체 변경, 다른 속성의 계산, 실제 React 전달과 렌더링은 여기서 확인하지 않았습니다.', 'quiet scope-note'));
}
function renderExecution(container) {
  const execution = state.executions[revision];
  container.append(make('h3', versionName(revision) + ' · 이 입력의 계산 기록'));
  container.append(make('p', '위에서 고른 입력으로 선택식의 IR을 계산한 기록입니다. 실제 조회나 React 실행 기록은 아닙니다.', 'quiet'));
  renderExecutionRows(container, execution, revision);
}
function renderExecutionRows(container, execution, side) {
  if (execution.status !== 'recorded-ir-execution') { container.append(make('p', execution.reason)); return; }
  const list = make('ol', undefined, 'execution-steps');
  const evidence = execution.nativeEvidence;
  const compared = new Set(evidence?.comparedSequences ?? []);
  for (const row of execution.rows) {
    const item = make('li');
    item.dataset.event = row.event;
    item.dataset.nativeCompared = String(compared.has(row.sequence));
    item.append(make('p', row.text));
    if (compared.has(row.sequence)) item.append(make('span', '원본 계측과 대조한 기록', 'native-match'));
    if (row.source) item.append(sourceButton(row.source, side, row.event === 'throw' ? 'IR의 오류 위치 ↗' : undefined));
    for (const reference of row.references) item.append(sourceButton(reference.source, side, reference.role + ' ↗'));
    list.append(item);
  }
  if (!execution.rows.length) container.append(make('p', '이 입력에서는 기록 대상 연산이 없었습니다. 기록하지 않는 원시 값 읽기·계산이 없었다는 뜻은 아닙니다.'));
  container.append(list, make('p', `기록 ${execution.eventCount}개 · ${execution.truncated ? '뒷부분 생략' : '기록 상한에 의한 생략 없음'}. 모든 연산을 기록하는 것은 아닙니다.`, 'quiet'));
  if (evidence) {
    const details = make('details', undefined, 'trace-evidence');
    details.append(make('summary', `원본 대조 범위 · 표시한 기록 중 ${compared.size}개`), make('p', evidence.scope, 'quiet'), make('p', evidence.notCompared, 'quiet'));
    container.append(details);
  }
  for (const note of execution.notes.slice(2)) container.append(make('p', note, 'quiet scope-note'));
}
function renderReading() {
  sourceOrigin = undefined;
  $('source-return').hidden = true;
  const container = $('reading-content'); container.replaceChildren();
  if (view === 'change') renderChanges(container);
  else if (view === 'calculation') renderCalculation(container);
  else if (view === 'execution') renderExecution(container);
  else renderUses(container);
}
function update() { state = currentState(); renderResults(); renderReading(); }
function error(reason) { $('error').hidden = false; $('error').textContent = reason.message; }
function renderBoundary() {
  const item = data.boundaries.find(row => row.key === $('boundary-case').value);
  if (!item) throw new Error('고정된 경계 입력을 찾을 수 없습니다.');
  const container = $('boundary-results'); container.replaceChildren();
  if (sourceOrigin && !sourceOrigin.isConnected) { sourceOrigin = undefined; $('source-return').hidden = true; }
  const changes = {
    'throw-to-value': '변경 전에는 TypeError, 변경 후에는 목록을 반환합니다.',
    'same-throw-name': '두 버전 모두 TypeError가 발생합니다. 오류 이름의 일치이며 같은 오류 위치라는 판정은 아닙니다.',
    'same-value': '이 입력에서는 두 버전이 같은 목록을 반환합니다.',
  };
  container.append(make('p', changes[item.transition], 'boundary-outcome'));
  const inputs = make('details', undefined, 'boundary-inputs'); inputs.append(make('summary', '이 예시의 입력값'));
  inputs.append(make('pre', Object.entries(item.inputs).map(([key, value]) => `${key} = ${pretty(value)}`).join('\n'))); container.append(inputs);
  const grid = make('div', undefined, 'boundary-grid');
  for (const side of ['before', 'after']) {
    const observation = item.observations[side], execution = item.executions[side];
    const block = make('section', undefined, 'boundary-revision'); block.dataset.boundaryRevision = side;
    block.append(make('h3', versionName(side)));
    const outcome = observation.kind === 'throw' ? 'TypeError 발생 · 반환 목록 없음' : '반환 목록: ' + pretty(observation.value.$record.transactionsToDisplay);
    block.append(make('p', outcome, 'boundary-value'));
    if (observation.kind === 'throw') block.append(make('p', '오류 이름은 원본 실행과 대조했습니다. 아래의 구체적인 오류 위치는 IR 기록이며, 원본 계측으로 따로 대조한 위치가 아닙니다.', 'quiet'));
    else block.append(make('p', '이 선택식의 반환만 확인했습니다. 반환한 원소를 자식이 처리할 때도 오류가 없는지는 확인하지 않았습니다.', 'quiet'));
    const records = make('details', undefined, 'boundary-records');
    records.append(make('summary', '이 버전의 계산 기록'));
    renderExecutionRows(records, execution, side); block.append(records); grid.append(block);
  }
  container.append(grid);
}
function renderSourceScope(scope) {
  const container = $('source-scope-detail');
  container.append(make('p', 'Git의 변경 줄과 선택한 원본 구간이 겹치는지만 센 값입니다. 한 줄의 일부만 겹쳐도 포함되며, 들여쓰기나 코드 이동도 변경 줄로 잡힙니다. 동작 해석 성공률을 뜻하지 않습니다.'));
  const grid = make('div', undefined, 'scope-grid');
  for (const side of ['before', 'after']) {
    const row = scope.revisions[side], block = make('section', undefined, 'scope-revision');
    block.dataset.scopeRevision = side;
    block.append(make('h3', versionName(side)), make('p', `${side === 'before' ? '삭제' : '추가'} ${row.changedLines.length}줄 · 선택과 겹침 ${row.intersectingLines}줄 · 선택 밖 ${row.outsideLines}줄`, 'scope-counts'));
    for (const span of row.spans) block.append(sourceButton({ ...span, file: row.file }, side, `선택한 계산식 ${span.line}–${span.endLine}행 ↗`));
    block.append(make('p', '같은 파일 안의 선택 밖 변경', 'scope-outside-title'));
    const groups = [];
    for (const line of row.changedLines.filter(item => !item.selectedSpanIndices.length)) {
      const last = groups.at(-1);
      if (last && last.lastLine + 1 === line.line) { last.lastLine = line.line; last.end = line.end; }
      else groups.push({ file: row.file, start: line.start, end: line.end, line: line.line, lastLine: line.line });
    }
    const list = make('ul', undefined, 'scope-outside');
    for (const group of groups) {
      const item = make('li');
      item.append(sourceButton(group, side, `${versionName(side)} ${group.line}${group.line === group.lastLine ? '' : '–' + group.lastLine}행 ↗`)); list.append(item);
    }
    block.append(groups.length ? list : make('p', '선택 밖 변경 줄 없음')); grid.append(block);
  }
  container.append(grid, make('p', '선택 밖은 이 계산식 대조에 포함하지 않았다는 뜻입니다. 그 코드가 해석 불가능하거나 실제 동작에 영향이 없다는 판정은 아닙니다.'));
}
async function start() {
  const response = await fetch('/api/data', { cache: 'no-store' });
  if (!response.ok) throw new Error(await response.text());
  data = await response.json();
  if (data.schema !== 'web-review-inspector-1' || data.status !== 'research-demo' || data.states.length !== 160 || data.boundaries.length !== 12 || data.humanParticipants !== 0) throw new Error('이 작업대의 고정된 연구 자료가 아닙니다. 자료를 다시 생성하세요.');
  for (const [index, profile] of data.profiles.transactions.entries()) $('transaction').append(new Option(profile.label, String(index)));
  for (const [index, profile] of data.profiles.previews.entries()) $('preview').append(new Option(profile.$array.length ? `${profile.$array.length}개 · ${profile.$array.map(item => item.$record.id).join(', ')}` : '미리보기 없음', String(index)));
  $('transaction').value = '3'; $('preview').value = '1';
  for (const item of data.boundaries) $('boundary-case').append(new Option(`${item.label} · 검색 ${item.inputs.isSearching ? '켬' : '끔'} / 필터 ${item.inputs.isFiltered ? '켬' : '끔'}`, item.key));
  $('boundary-case').value = '3';
  $('boundary-case').addEventListener('change', () => { try { renderBoundary(); } catch (reason) { error(reason); } });
  renderBoundary();
  for (const source of data.sources) $('source-file').append(new Option(`${versionName(source.revision)} · ${source.role === 'parent' ? '부모' : '자식'} · ${source.name}`, source.id));
  for (const element of document.querySelectorAll('input,select')) element.disabled = false;
  $('controls').addEventListener('submit', event => event.preventDefault());
  $('controls').addEventListener('change', () => { try { update(); } catch (reason) { error(reason); } });
  for (const button of document.querySelectorAll('[data-view]')) button.addEventListener('click', () => {
    view = button.dataset.view;
    for (const sibling of document.querySelectorAll('[data-view]')) sibling.setAttribute('aria-pressed', String(sibling === button));
    renderReading();
  });
  for (const button of document.querySelectorAll('[data-revision]')) button.addEventListener('click', () => {
    revision = button.dataset.revision;
    for (const sibling of document.querySelectorAll('[data-revision]')) sibling.setAttribute('aria-pressed', String(sibling === button));
    renderReading();
    const role = data.sources.find(source => source.id === $('source-file').value)?.role ?? 'parent';
    showSource(undefined, undefined, `${role}-${revision}`);
  });
  $('source-file').addEventListener('change', () => showSource(undefined, undefined, $('source-file').value));
  $('source-return').addEventListener('click', () => {
    if (!sourceOrigin?.isConnected) return;
    sourceOrigin.scrollIntoView({ block: 'center', behavior: 'instant' });
    sourceOrigin.focus({ preventScroll: true });
  });
  const evidence = data.evidence, scope = evidence.changeScope;
  renderSourceScope(evidence.sourceScope);
  $('evidence-summary').textContent = `고정 입력 ${evidence.pairedInputs}개 · 관찰 변화 ${evidence.changedInputs}개 · 원본 선택 구간 실행 대조 ${evidence.nativeChecks}회`;
  const detail = $('evidence-detail');
  detail.append(make('p', `별도 오류 입력 대조 ${evidence.boundaryNativeChecks}회, 미지원 검사 ${evidence.unsupportedChecks}회. 전후 자식 참조 ${evidence.sourceConnections}곳은 소스 연결이며 실행 검증이 아닙니다.`));
  if (evidence.nativeTrace) detail.append(make('p', `계산 기록의 별도 대조: 같은 고정 입력·오류 예시에서 원본 선택식 ${evidence.nativeTrace.originalReexecutions}회와 계측본 ${evidence.nativeTrace.instrumentedExecutions}회를 실행하고 공통 기록 ${evidence.nativeTrace.projectedEvents}개를 대조했습니다. 새 사례나 원본 앱 전체의 실행 횟수가 아닙니다.`));
  detail.append(make('p', `원본 커밋 ${scope.head}. 변경 파일 ${scope.changedFileCount}개 중 선택식 계산에서 제외한 파일:`));
  const list = make('ul');
  for (const file of scope.changedFiles.filter(row => row.relation !== 'contains-analyzed-slice')) list.append(make('li', file.path));
  detail.append(list, make('p', '자식 파일의 사용처 색인과 선택식 실행 범위는 다릅니다. 사용자 평가 0명, 전체 행동 완료 0건입니다.'));
  const generatedDate = new Date(data.generatedAt).toLocaleDateString('ko-KR', { timeZone: 'Asia/Seoul' });
  $('build-stamp').textContent = `자료 ${generatedDate} (KST) · 엔진 ${data.engineSha256.slice(0, 12)}`;
  update(); showSource(data.comparison.structureComparison.changes[0].after.source, 'after');
}
start().catch(error);
