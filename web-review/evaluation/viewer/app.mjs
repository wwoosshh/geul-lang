import { createPracticeSession } from './session.mjs';

const $ = id => document.getElementById(id);
const titles = { 'starting-balance': '시작 잔액의 기본값', 'ui-mode': '기본 UI 판정', 'filter-loading': '필터 적용과 로딩', 'recording-toggle': '방송 중 녹화 판정' };
let data, current, session, running = false, sourceGeneration = 0;
let lastExport;
const sourceCache = new Map();
const node = (tag, text, className) => { const element = document.createElement(tag); if (text !== undefined) element.textContent = text; if (className) element.className = className; return element; };
const error = message => { $('error').textContent = message; $('error').hidden = !message; };
function code(text) { const pre = node('pre'); pre.append(node('code', text)); return pre; }
function details(label, content) { const element = node('details'); element.append(node('summary', label), content); return element; }
function sourceButton(label, sourceId, line = 1) {
  const button = node('button', label, 'source-link'); button.type = 'button';
  button.addEventListener('click', () => { $('source-file').value = sourceId; $('source-line').value = line; showSource(); });
  return button;
}
function switchTab(source) {
  $('material').hidden = source; $('source-panel').hidden = !source;
  $('source-tab').setAttribute('aria-pressed', String(source)); $('material-tab').setAttribute('aria-pressed', String(!source));
}
function updateClock() {
  if (!session || !running) return;
  try {
    const state = session.snapshot(), seconds = Math.floor(state.elapsedMs / 1000);
    $('clock').textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
    $('session-status').textContent = `예행 검토 진행 중 · 원본 이동 ${state.sourceVisits}회${state.waiting ? ' · AI 응답 대기 중' : ''}`;
  } catch (cause) { error(cause.message); }
}
function requestDownload() {
  if (!lastExport) return;
  const url = URL.createObjectURL(new Blob([lastExport.text], { type: 'application/json' }));
  const link = node('a'); link.href = url; link.download = lastExport.filename;
  document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 10000);
}
async function showSource() {
  const generation = ++sourceGeneration, sourceId = $('source-file').value;
  switchTab(true); error('');
  try {
    let source = sourceCache.get(sourceId);
    if (!source) {
      const response = await fetch('/api/source?id=' + encodeURIComponent(sourceId));
      if (!response.ok) throw new Error(await response.text());
      source = await response.json(); sourceCache.set(sourceId, source);
    }
    if (generation !== sourceGeneration) return;
    const lines = source.text.split('\n'), requested = Number($('source-line').value);
    if (!Number.isSafeInteger(requested) || requested < 1 || requested > lines.length) throw new Error(`1~${lines.length} 사이의 줄을 선택하세요.`);
    const first = Math.max(1, requested - 60), last = Math.min(lines.length, requested + 180);
    $('source-code').textContent = '';
    for (let line = first; line <= last; line++) {
      const row = node('div', undefined, 'source-row' + (line === requested ? ' marked' : ''));
      row.append(node('span', String(line), 'source-number'), node('span', lines[line - 1]));
      $('source-code').append(row);
    }
    $('source-status').textContent = `${source.revision === 'before' ? '변경 전' : '변경 후'} · ${source.label} · 전체 ${lines.length}줄 중 ${first}~${last}줄. 다른 줄은 이동으로 확인할 수 있습니다.`;
    const marked = $('source-code').querySelector('.marked');
    $('source-code').scrollTop = marked.offsetTop - $('source-code').firstElementChild.offsetTop - 90;
    if (running) session.visitSource(sourceId, requested);
    updateClock();
  } catch (cause) { error(cause.message); }
}
function renderTask() {
  if (!running) {
    session = undefined; $('response').reset(); $('answers').disabled = true;
    $('clock').textContent = '00:00'; $('confidence-value').textContent = '50 / 100';
    $('session-status').textContent = '시작하면 답변 시간과 원본 이동을 기록합니다.';
    $('ai-wait').textContent = 'AI 응답 대기 시작'; $('ai-wait').setAttribute('aria-pressed', 'false');
  }
  current = data.tasks.find(task => task.id === $('task').value);
  sourceGeneration++;
  switchTab(false);
  $('project-name').textContent = current.project;
  $('material').textContent = '';
  const material = $('material');
  material.append(node('h2', titles[current.id] ?? current.id), node('p', current.prompt));
  material.append(node('p', '관찰 범위 · ' + current.observation, 'scope'), node('p', current.caveat, 'caveat'));
  for (const [index, original] of current.original.entries()) {
    const title = node('div', undefined, 'code-title');
    title.append(node('h3', index ? '변경 후' : '변경 전'), sourceButton(`원본 ${original.line}줄 ↗`, original.sourceId, original.line));
    material.append(title, code(original.expression));
  }
  const condition = $('condition').value, supplement = current.supplements[condition];
  if (supplement) {
    const section = node('section', undefined, 'supplement');
    section.append(node('h3', { B: '실행 비교에서 얻은 설명', C: '같은 입력 범위의 결정표', D: '구조를 유지한 한국어 풀이' }[condition]));
    if (condition === 'B') for (const text of supplement.paragraphs.filter(Boolean)) section.append(node('p', text.replace(/^- /, ''), text.startsWith('- ') ? 'rule' : text.startsWith('가정:') ? 'qualification' : undefined));
    if (condition === 'C') {
      const wrap = node('div', undefined, 'table-wrap'), table = node('table'), head = node('thead'), heading = node('tr'), body = node('tbody');
      for (const name of supplement.names) heading.append(node('th', name));
      head.append(heading);
      for (const row of supplement.rows) { const tr = node('tr'); for (const text of row) tr.append(node('td', text)); body.append(tr); }
      table.append(head, body); wrap.append(table); section.append(wrap, node('p', '선택한 식과 입력 범위에 한정된 결과입니다. 전체 화면·기획 의도·서버 동작은 보증하지 않습니다.', 'caveat'));
    }
    if (condition === 'D') section.append(node('p', '실행 코드가 아닌 표시용 풀이입니다. 연산·분기 구조와 문자열은 유지했습니다.', 'caveat'), node('h3', '변경 전'), code(supplement.before), node('h3', '변경 후'), code(supplement.after));
    material.append(section);
  }
  const domains = details('공통 입력 범위 확인', code(JSON.stringify(current.domains, null, 2)));
  domains.append(node('p', '호출자가 지정한 후보 값입니다. TypeScript 타입이 실제 입력의 유효성을 증명했다는 뜻은 아닙니다.', 'caveat'));
  const glossary = node('div', undefined, 'glossary');
  for (const [name, label] of Object.entries(current.glossary)) glossary.append(node('div', `${name} → ${label}`));
  const sources = node('div', undefined, 'source-links');
  $('source-file').textContent = '';
  for (const source of current.sources) {
    const label = `${source.revision === 'before' ? '전' : '후'} · ${source.label}`;
    const option = node('option', label); option.value = source.id; $('source-file').append(option);
    sources.append(sourceButton(label, source.id));
  }
  material.append(domains, details('공통 용어 대응', glossary), details('원본 파일과 라이선스', sources));
  const project = node('a', `${current.project} · 원본 커밋 ${current.commit.slice(0, 8)}`);
  const url = new URL(current.projectUrl);
  if (url.protocol === 'https:') { project.href = url.href; project.target = '_blank'; project.rel = 'noopener noreferrer'; }
  const provenance = node('p', undefined, 'caveat'); provenance.append(project); material.append(provenance);
  $('source-file').value = current.original[0].sourceId;
  $('source-line').value = current.original[0].line;
}
$('start').addEventListener('click', () => {
  error('');
  $('response').reset(); $('confidence-value').textContent = '50 / 100';
  $('answers').disabled = false; $('task').disabled = true; $('condition').disabled = true; $('start').disabled = true;
  $('ai-wait').textContent = 'AI 응답 대기 시작'; $('ai-wait').setAttribute('aria-pressed', 'false');
  session = createPracticeSession({ task: current.id, condition: $('condition').value, materialSha256: data.materialSha256 });
  running = true; if (document.hidden) session.setHidden(true); updateClock(); $('answer-0').focus();
});
$('task').addEventListener('change', renderTask); $('condition').addEventListener('change', renderTask);
$('material-tab').addEventListener('click', () => switchTab(false)); $('source-tab').addEventListener('click', showSource);
$('source-go').addEventListener('click', showSource);
$('source-file').addEventListener('change', () => { $('source-line').value = 1; showSource(); });
$('source-line').addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); showSource(); } });
$('confidence').addEventListener('input', () => { $('confidence-value').textContent = $('confidence').value + ' / 100'; });
$('ai-wait').addEventListener('click', () => {
  const waiting = !session.snapshot().waiting; session.setWaiting(waiting);
  $('ai-wait').textContent = waiting ? 'AI 응답 대기 종료' : 'AI 응답 대기 시작'; $('ai-wait').setAttribute('aria-pressed', String(waiting)); updateClock();
});
document.addEventListener('visibilitychange', () => { if (running) session.setHidden(document.hidden); });
$('response').addEventListener('submit', event => {
  event.preventDefault(); error('');
  try {
    const result = session.finish({ answers: [0, 1, 2, 3].map(index => $('answer-' + index).value), confidence: Number($('confidence').value), familiar: $('familiar').checked, aiModel: $('ai-model').value, aiRequests: Number($('ai-count').value) });
    lastExport = { text: JSON.stringify(result, null, 2) + '\n', filename: `geul-practice-${current.id}-${Date.now()}.json` };
    $('export-json').value = lastExport.text; $('export-result').hidden = false;
    requestDownload();
    running = false; $('answers').disabled = true; $('task').disabled = false; $('condition').disabled = false; $('start').disabled = false; $('start').textContent = '새 예행 검토 시작';
    $('session-status').textContent = '예행 검토 응답을 준비했습니다. 다운로드 목록을 확인하거나 아래 JSON을 복사하세요. 실제 참가자 결과로 집계하지 않습니다.';
  } catch (cause) { error(cause.message); }
});
$('select-json').addEventListener('click', () => { $('export-json').focus(); $('export-json').select(); });
$('download-again').addEventListener('click', requestDownload);
window.addEventListener('beforeunload', event => { if (running) { event.preventDefault(); event.returnValue = ''; } });
setInterval(updateClock, 1000);
try {
  const response = await fetch('/api/data'); if (!response.ok) throw new Error(await response.text()); data = await response.json();
  if (data.status !== 'practice-only' || data.participants !== 0) throw new Error('예행 검토 자료가 아닙니다.');
  for (const task of data.tasks) { const option = node('option', titles[task.id] ?? task.id); option.value = task.id; $('task').append(option); }
  $('task').disabled = false; $('start').disabled = false; renderTask();
} catch (cause) { error(cause.message); }
