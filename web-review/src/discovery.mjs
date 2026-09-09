import ts from 'typescript';
import { Unsupported } from './core.mjs';
import { parseSource, location, hash } from './typescript.mjs';
import { liftConstBindings } from './const-bindings.mjs';
import { liftCallEntry, liftCallArguments } from './call-entry.mjs';
import { liftJsxAttribute } from './jsx.mjs';
import { ENGINE_SHA256, ENGINE_RUNTIME } from './fingerprint.mjs';
import { sourceText } from './report.mjs';

const kinds = ['const', 'jsx-attribute', 'call-entry', 'call-arguments'];
const commands = { const: 'lift-const-bindings', 'jsx-attribute': 'lift-jsx-attribute', 'call-entry': 'lift-call-entry', 'call-arguments': 'lift-call-arguments' };
const candidateLimit = 4096, nodeLimit = 100000, workLimit = 16 * 1024 * 1024;

export function liftSourceCandidate(text, kind, target, filename) {
  const options = { ...target, filename };
  if (kind === 'const') return liftConstBindings(text, options);
  if (kind === 'jsx-attribute') return liftJsxAttribute(text, options);
  if (kind === 'call-entry') return liftCallEntry(text, options);
  if (kind === 'call-arguments') return liftCallArguments(text, options);
  throw new Unsupported('알 수 없는 후보 종류입니다.');
}

// Discovery calls the same lowerers as explicit selection. It neither executes
// source code nor treats a successful translation as complete behavior coverage.
export function discoverSource(text, { filename = 'input.tsx', kind = 'all', limit = 32, offset = 0, focusSpans } = {}) {
  if (kind !== 'all' && !kinds.includes(kind)) throw new Unsupported('후보 종류는 all·const·jsx-attribute·call-entry·call-arguments 중 하나여야 합니다.');
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 128) throw new Unsupported('한 번의 후보 검사 한도는 1~128이어야 합니다.');
  if (!Number.isSafeInteger(offset) || offset < 0 || offset > candidateLimit) throw new Unsupported('후보 시작 위치는 0~4096 정수여야 합니다.');
  const file = parseSource(text, filename), bytes = Buffer.byteLength(text), candidates = [];
  let focus;
  if (focusSpans !== undefined) {
    if (!Array.isArray(focusSpans) || focusSpans.length > 65536) throw new Unsupported('후보 선택 소스 범위는 최대 65536개 배열이어야 합니다.');
    let previousEnd = 0;
    focus = focusSpans.map(span => {
      if (!span || !Number.isSafeInteger(span.start) || !Number.isSafeInteger(span.end) || span.start < previousEnd || span.start >= span.end || span.end > text.length) throw new Unsupported('후보 선택 소스 범위는 원본 안에서 겹침 없이 순서대로 지정해야 합니다.');
      previousEnd = span.end; return { start: span.start, end: span.end };
    });
  }
  function inFocus(span) {
    if (focus === undefined) return true;
    let lo = 0, hi = focus.length;
    while (lo < hi) { const mid = (lo + hi) >>> 1; if (focus[mid].end <= span.start) lo = mid + 1; else hi = mid; }
    return lo < focus.length && focus[lo].start < span.end;
  }
  let nodes = 0;
  function add(candidate) {
    if (kind !== 'all' && kind !== candidate.kind) return;
    if (candidates.length >= candidateLimit) throw new Unsupported('파일의 구문 후보 제한(4096)을 초과했습니다. 완성된 목록을 반환하지 않습니다.');
    candidates.push(candidate);
  }
  function visit(node, depth = 0) {
    if (++nodes > nodeLimit || depth > 128) throw new Unsupported('후보 탐색의 AST 크기·깊이 제한을 초과했습니다. 완성된 목록을 반환하지 않습니다.');
    if (ts.isVariableStatement(node) && (node.declarationList.flags & ts.NodeFlags.Const)) {
      const declarations = [...node.declarationList.declarations], line = location(node).line;
      const unsupportedBinding = declarations.find(item => !ts.isIdentifier(item.name) || !item.initializer);
      add({ kind: 'const', source: location(node), selectionSource: location(node), target: { startLine: line, endLine: line,
        outputs: declarations.filter(item => ts.isIdentifier(item.name)).map(item => item.name.text) },
        ...(unsupportedBinding ? { syntaxRefusal: '자동 const 후보는 초기값이 있는 단순 이름만 해석합니다. 구조 분해나 초기값 생략을 건너뛰지 않습니다.', refusalSource: location(unsupportedBinding) } : {}) });
    }
    if (ts.isJsxAttribute(node)) {
      const element = node.parent.parent;
      add({ kind: 'jsx-attribute', source: location(node), selectionSource: location(element), target: { tag: element.tagName.getText(file), attribute: node.name.getText(file), line: location(node).line } });
    }
    if ((ts.isFunctionDeclaration(node) || ts.isFunctionExpression(node) || ts.isArrowFunction(node) || ts.isMethodDeclaration(node)) && node.body && ts.isBlock(node.body)) {
      const last = node.body.statements.at(-1);
      if (last && ts.isExpressionStatement(last) && ts.isCallExpression(last.expression) && ts.isIdentifier(last.expression.expression)) {
        for (const mode of ['call-entry', 'call-arguments']) add({ kind: mode, source: location(last.expression), selectionSource: location(node),
          target: { callee: last.expression.expression.text, line: location(last.expression).line }, prefixStatements: node.body.statements.length - 1,
          prefixSource: node.body.statements.length > 1 ? { ...location(node.body.statements[0]), end: node.body.statements.at(-2).end } : null });
      }
    }
    ts.forEachChild(node, child => visit(child, depth + 1));
  }
  visit(file);
  candidates.sort((a, b) => a.source.start - b.source.start || kinds.indexOf(a.kind) - kinds.indexOf(b.kind));
  if (offset > candidates.length) throw new Unsupported('후보 시작 위치가 선택한 종류의 후보 수보다 큽니다.');
  let checked = 0, lowerCalls = 0, chargedBytes = 0, nextOffset = null;
  const results = candidates.map((candidate, index) => {
    const { syntaxRefusal, refusalSource, ...details } = candidate;
    const base = { id: index, ...details, inFocus: inFocus(candidate.selectionSource), nativeVerified: false };
    if (!base.inFocus) return { ...base, status: 'not-checked', reason: '선택한 소스 범위와 구문이 교차하지 않아 이번에는 검사하지 않습니다.' };
    if (index < offset) return { ...base, status: 'not-checked', reason: '이번 검사 시작 위치보다 앞선 후보입니다.' };
    if (checked >= limit || chargedBytes + bytes > workLimit) {
      nextOffset ??= index;
      return { ...base, status: 'not-checked', reason: checked >= limit ? '이번 후보 검사 개수 한도를 넘었습니다.' : '원본 재해석 작업량 한도(16 MiB)를 넘었습니다.' };
    }
    checked++; chargedBytes += bytes;
    try {
      if (syntaxRefusal) throw new Unsupported(syntaxRefusal, refusalSource);
      lowerCalls++;
      const artifact = liftSourceCandidate(text, candidate.kind, candidate.target, filename);
      const selected = candidate.kind === 'const' ? { start: artifact.prefix.source.start, end: artifact.prefix.end }
        : candidate.kind === 'jsx-attribute' ? artifact.source
          : (artifact.excludedCall ?? artifact.preparedCall).source;
      if (selected.start !== candidate.source.start || selected.end !== candidate.source.end) throw new Error('후보와 실제 추출의 원본 범위가 다릅니다.');
      if (['call-entry', 'call-arguments'].includes(candidate.kind)) {
        if (Boolean(candidate.prefixSource) !== Boolean(artifact.entryRegion.source)
          || (candidate.prefixSource && (candidate.prefixSource.start !== artifact.entryRegion.source.start || candidate.prefixSource.end > artifact.entryRegion.end))) throw new Error('후보와 실제 선행 구간의 원본 범위가 다릅니다.');
      }
      const analyzedSources = candidate.kind === 'const' || candidate.kind === 'jsx-attribute'
        ? [{ ...candidate.source, role: candidate.kind === 'const' ? 'const-statement' : 'jsx-attribute' }]
        : [
          // End at the last prefix statement, not the start of the call: that
          // gap can contain the call line's indentation or unrelated comments.
          ...(candidate.prefixSource ? [{ ...candidate.prefixSource, role: 'call-prefix' }] : []),
          ...(candidate.kind === 'call-arguments' ? artifact.preparedCall.arguments.map((source, index) => ({ ...source, role: `argument${index + 1}` })) : []),
        ];
      for (const span of analyzedSources) if (!(span.start >= candidate.selectionSource.start && span.start < span.end && span.end <= candidate.selectionSource.end)) throw new Error('계산 소스 범위가 선택 구문 밖입니다.');
      return { ...base, status: 'lowered', mode: artifact.mode, inputs: artifact.inputs, contract: artifact.contract,
        analyzedSources, artifactSha256: hash(JSON.stringify(artifact)), lift: { command: commands[candidate.kind], file: filename, target: candidate.target } };
    } catch (error) {
      if (!(error instanceof Unsupported)) throw error;
      return { ...base, status: 'refused', reason: error.message, ...(error.location ? { refusalSource: error.location } : {}) };
    }
  });
  const counts = Object.fromEntries(['lowered', 'refused', 'not-checked'].map(status => [status, results.filter(row => row.status === status).length]));
  return { schema: 'web-source-discovery-1', status: 'source-candidates', engineSha256: ENGINE_SHA256, runtime: ENGINE_RUNTIME,
    source: { file: filename, sha256: hash(text), bytes }, selection: { kind, limit, offset, focus: focus === undefined ? 'all' : 'source-spans', ...(focus !== undefined ? { focusSpans: focus } : {}) }, candidates: results,
    counts: { candidates: results.length, sourceSites: new Set(results.map(row => `${row.source.start}:${row.source.end}`)).size, checked, lowerCalls, ...counts,
      emptyPrefixEntries: results.filter(row => row.status === 'lowered' && row.kind === 'call-entry' && row.prefixStatements === 0).length,
      focusCandidates: results.filter(row => row.inFocus).length, outsideFocus: results.filter(row => !row.inFocus).length },
    nextOffset,
    bounds: { astNodes: nodes, astNodeLimit: nodeLimit, candidateLimit, chargedSourceBytes: chargedBytes, sourceWorkLimit: workLimit },
    nativeExecutions: 0, wholeBehaviorVerified: false, semanticCoverage: null,
    scope: ['파일의 const 문장 한 개, 명시된 JSX 속성 한 개, 함수 블록 마지막의 직접 이름 호출을 대상으로 한다.',
      '같은 호출의 진입과 인수 계산은 서로 다른 관찰 모드이므로 후보 수에 각각 포함한다. sourceSites는 중복 소스 범위를 한 번만 센다.',
      '각 const 문장은 별도 입력 스냅샷에서 분석한다. 인접 문장·이벤트·컴포넌트 전체를 연결하지 않는다.',
      'selectionSource는 추출기가 살펴보는 구문 범위다. analyzedSources는 추출한 계산이 포함하는 소스 범위이며 실제 실행한 행이나 그 밖의 변경에 영향받지 않는다는 증거가 아니다.',
      'JSX spread 자체·일반 중간 호출·멤버 호출·return 안 호출·화살표 식 본문 등 이 규칙 밖의 구문은 목록의 분모에 포함하지 않는다.',
      'lowered는 현재 프로필의 IR 추출 성공이며 원본 실행·실제 입력 유효성·의미 보존 증명·사람 이해도의 측정이 아니다.',
      '배열 프로필을 자동 적용하지 않는다. 필요하면 원본과 전제를 확인한 뒤 명시적으로 추출한다.',
      ...(focus !== undefined ? ['지정 소스 범위와 선택 구문이 교차하는 후보만 검사한다. 범위 밖 후보도 목록에 미검사로 남기며 후보 번호는 전체 목록에서 바꾸지 않는다. 간접 의존성의 영향 여부를 판단한 것이 아니다.'] : []),
      'not-checked는 지원 여부 미확인이다. 목록 자체는 실행할 수 있는 분석 파일이 아니며 lowered 후보도 명시한 lift 명령으로 다시 추출해야 한다.'] };
}

const escape = text => String(text).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replace(/[\\`*_[\]|]/g, '\\$&').replaceAll('\n', ' ↵ ');
export function renderDiscovery(report) {
  const c = report.counts;
  const lines = ['# 이 파일의 분석 후보', '', `종류 ${report.selection.kind} · 시작 번호 ${report.selection.offset} · 검사 한도 ${report.selection.limit}개 · ${report.selection.focus === 'all' ? '전체 후보 대상' : `지정 소스 범위와 교차하는 ${c.focusCandidates}개 대상`}`, '',
    `구문 후보 ${c.candidates}개 · 서로 다른 소스 범위 ${c.sourceSites}곳 · 이번 검사 ${c.checked}개`, '',
    `IR 추출 ${c.lowered}개 (선행 계산 없는 호출 진입 ${c.emptyPrefixEntries}개 포함) · 거부 ${c.refused}개 · 이번에 검사하지 않은 후보 ${c['not-checked']}개. 원본 실행 0회.`, '',
    ...report.scope.map(text => `- ${escape(text)}`), '', '| 번호 | 종류·위치 | 검사 결과 | 입력 또는 거부 사유 |', '|---|---|---|---|'];
  for (const row of report.candidates.filter(row => row.status !== 'not-checked')) {
    lines.push(`| ${row.id} | ${escape(row.kind)} · ${sourceText(row.source, report)} | ${row.status === 'lowered' ? 'IR 추출' : '거부'} | ${escape(row.status === 'lowered' ? row.inputs.join(', ') || '외부 입력 없음' : row.reason)} |`);
    if (row.refusalSource) lines.push(`| | 문제 위치: ${sourceText(row.refusalSource, report)} | | |`);
  }
  if (report.nextOffset !== null) lines.push('', `다음 검사는 같은 파일·종류에 --offset ${report.nextOffset}를 지정합니다. --json 출력에는 미검사 후보와 추출 대상의 구조화된 옵션도 포함됩니다.`);
  lines.push('', `엔진: ${report.engineSha256}`, `원본 SHA256: ${report.source.sha256}`);
  return lines.join('\n') + '\n';
}
