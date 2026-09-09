import { Unsupported } from './core.mjs';
import { discoverSource } from './discovery.mjs';
import { hash } from './typescript.mjs';
import { ENGINE_SHA256 } from './fingerprint.mjs';
import { inspectUnifiedPatch } from '../scripts/diff-spans.mjs';
import { sourceText } from './report.mjs';

// Source geometry only. The patch parser reconstructs the entire after text;
// no AST correspondence or behavioral equivalence is inferred from overlaps.
export function discoverChange(beforeText, afterText, patch, { beforeFilename = 'before.tsx', afterFilename = 'after.tsx', patchFilename, kind = 'all', limit = 32, beforeOffset = 0, afterOffset = 0, focus = 'all' } = {}) {
  if (!['all', 'changed-lines'].includes(focus)) throw new Unsupported('변경 후보의 focus는 all·changed-lines 중 하나여야 합니다.');
  let diff;
  try { diff = inspectUnifiedPatch(patch, beforeText, afterText); }
  catch (error) {
    if (error.code !== 'ERR_ASSERTION') throw error;
    throw new Unsupported('두 원본과 단일 파일 Git 패치가 일치하지 않습니다: ' + error.message.slice(0, 300));
  }
  const before = discoverSource(beforeText, { filename: beforeFilename, kind, limit, offset: beforeOffset, ...(focus === 'changed-lines' ? { focusSpans: diff.removed } : {}) });
  const after = discoverSource(afterText, { filename: afterFilename, kind, limit, offset: afterOffset, ...(focus === 'changed-lines' ? { focusSpans: diff.added } : {}) });
  const budget = { remaining: 65536 };
  function overlapping(changed, span) {
    let lo = 0, hi = changed.length;
    while (lo < hi) { const mid = (lo + hi) >>> 1; if (changed[mid].end <= span.start) lo = mid + 1; else hi = mid; }
    const lines = [];
    for (let index = lo; index < changed.length && changed[index].start < span.end; index++) {
      if (--budget.remaining < 0) throw new Unsupported('변경 행과 후보의 연결 제한(65536)을 초과했습니다. 부분 목록을 완성본으로 반환하지 않습니다.');
      lines.push(changed[index].line);
    }
    return lines;
  }
  function link(report, changed) {
    const candidates = report.candidates.map(row => {
      const anchorLines = overlapping(changed, row.source), selectionLines = overlapping(changed, row.selectionSource);
      if (focus === 'changed-lines' && row.inFocus !== (selectionLines.length > 0)) throw new Error('검사 대상 선택과 변경 행의 교차 결과가 다릅니다.');
      const analyzedLines = row.status === 'lowered'
        ? [...new Set(row.analyzedSources.flatMap(span => overlapping(changed, span)))].sort((a, b) => a - b) : null;
      return { ...row, sourceChange: { anchorLines, selectionLines, analyzedLines, behaviorImpact: 'not-evaluated' } };
    });
    return { ...report, candidates, changedLines: changed.map(row => row.line), changeCounts: {
      changedLines: changed.length,
      anchorsIntersecting: candidates.filter(row => row.sourceChange.anchorLines.length > 0).length,
      selectionsIntersecting: candidates.filter(row => row.sourceChange.selectionLines.length > 0).length,
      analyzedSpansIntersecting: candidates.filter(row => row.sourceChange.analyzedLines?.length > 0).length,
      unavailableAnalyzedSpans: candidates.filter(row => row.sourceChange.analyzedLines === null).length,
    } };
  }
  const linkedBefore = link(before, diff.removed), linkedAfter = link(after, diff.added);
  return { schema: 'web-change-discovery-1', status: 'source-change-candidates', engineSha256: ENGINE_SHA256, focus,
    patch: { sha256: hash(patch), ...(patchFilename !== undefined ? { file: patchFilename } : {}), reconstructed: true, gitIdentityVerified: false, hunks: diff.hunks.length },
    before: linkedBefore, after: linkedAfter, sourceIntersections: 65536 - budget.remaining,
    nativeExecutions: 0, wholeBehaviorVerified: false, semanticCoverage: null,
    scope: ['지정한 두 파일의 내용과 단일 파일 패치 본문을 대조해 변경 후 전체 내용을 복원했다. Git 커밋·헤더 경로·파일 모드의 동일성을 검증한 것은 아니다.',
      '후보 위치, 추출기가 살펴본 구문, 해석한 계산 구간과 변경 행의 교차를 각각 표시한다. 구간 안의 공백·주석이나 같은 물리적 행의 다른 식 변경도 교차할 수 있다.',
      '교차는 실행 결과가 달라졌다는 증거가 아니며 교차하지 않는다는 사실도 행동이 같다는 증거가 아니다. 주변 의존성·호출 경로·런타임 상태는 별도다.',
      '해석 구간이 없는 거부·미검사 후보의 analyzedLines는 null이다. 빈 배열과 구별한다.',
      ...(focus === 'changed-lines' ? ['changed-lines는 변경 행과 선택 구문이 교차하는 후보만 검사한다. 다른 후보는 미검사로 남는다. 간접 의존성의 변화와 실행 영향은 이 선택 기준으로 판단하지 않는다.'] : []),
      '전후 후보를 같은 행동으로 짝짓지 않는다. 각 파일의 후보 번호와 페이지 시작 위치는 독립적이다.'] };
}

const labels = { const: 'const', 'jsx-attribute': 'JSX 속성', 'call-entry': '호출 진입', 'call-arguments': '호출 인수' };
const shownLines = lines => lines.length ? lines.length <= 10 ? lines.join(', ') : `${lines.slice(0, 10).join(', ')} 외 ${lines.length - 10}개` : '교차 없음';
export function renderChangeDiscovery(report) {
  const lines = ['# 변경 구간과 분석 후보', '', '패치로 변경 후 전체 파일 내용을 복원해 확인했습니다. 아래는 소스 위치의 연결이며 실행 결과의 비교가 아닙니다.', '', ...report.scope.map(text => '- ' + text), ''];
  for (const [revision, name] of [['before', '변경 전'], ['after', '변경 후']]) {
    const side = report[revision], rows = side.candidates.filter(row => row.sourceChange.selectionLines.length);
    lines.push(`## ${name}`, '', `종류 ${side.selection.kind} · 시작 번호 ${side.selection.offset} · 검사 한도 ${side.selection.limit}개 · 검사 대상 ${report.focus === 'changed-lines' ? '변경 행과 선택 구문이 교차하는 후보' : '전체 후보'}`, '',
      `수정된 행 ${side.changedLines.length}개 · 선택 구문과 교차하는 후보 ${rows.length}개. 전체 후보 중 이번 IR 추출 ${side.counts.lowered}개·거부 ${side.counts.refused}개·미검사 ${side.counts['not-checked']}개.`, '',
      '| 번호 | 후보 | 검사 결과 | 후보 위치와 교차한 행 | 선택 구문과 교차한 행 | 해석한 계산 구간과 교차한 행 |', '|---|---|---|---|---|---|');
    for (const row of rows.slice(0, 40)) lines.push(`| ${row.id} | ${labels[row.kind]} · ${sourceText(row.source, side)} | ${{ lowered: 'IR 추출', refused: '거부', 'not-checked': '미검사' }[row.status]} | ${shownLines(row.sourceChange.anchorLines)} | ${shownLines(row.sourceChange.selectionLines)} | ${row.sourceChange.analyzedLines === null ? '해석 구간 미확인' : shownLines(row.sourceChange.analyzedLines)} |`);
    if (rows.length > 40) lines.push('', `표에는 앞 40개를 표시했습니다. JSON에는 교차하는 후보 ${rows.length}개와 교차하지 않는 후보도 포함됩니다.`);
    lines.push('', `다음 페이지: ${side.nextOffset === null ? '없음' : `--${revision}-offset ${side.nextOffset}`}. 특정 후보를 검사하려면 그 번호부터 시작하도록 같은 옵션을 지정합니다.`, '');
  }
  lines.push(`엔진: ${report.engineSha256}`, `패치 SHA256: ${report.patch.sha256}`, '원본 실행 0회 · 행동 영향 미평가');
  return lines.join('\n') + '\n';
}
