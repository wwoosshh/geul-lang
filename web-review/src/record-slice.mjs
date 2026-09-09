import ts from 'typescript';
import { Unsupported, VERSION, inputNames } from './core.mjs';
import { parseSource, lowerExpression, location, hash } from './typescript.mjs';
import { bindLocalSource, indexSliceBindings } from './bindings.mjs';
import { sourceContext } from './source-context.mjs';
import { ENGINE_SHA256 } from './fingerprint.mjs';

// Select the unmodified object literal, including literals inside callbacks.
// The callback/callee is not executed; identifiers are explicit snapshots at
// the literal's evaluation point, just as for an expression slice.
export function liftRecord(sourceText, { line, column, filename = 'input.tsx' } = {}) {
  if (!Number.isSafeInteger(line) || line < 1 || (column !== undefined && (!Number.isSafeInteger(column) || column < 1))) throw new Unsupported('객체의 시작 줄과 선택 열은 양의 정수여야 합니다.');
  const original = parseSource(sourceText, filename), matches = [];
  function find(node, depth = 0) {
    if (depth > 128) throw new Unsupported('객체 선택 AST 깊이 제한 초과');
    if (ts.isObjectLiteralExpression(node)) {
      const loc = location(node);
      if (loc.line === line && (column === undefined || loc.column === column)) matches.push(node);
    }
    ts.forEachChild(node, child => find(child, depth + 1));
  }
  find(original);
  if (matches.length !== 1) throw new Unsupported(`선택 위치에 객체 리터럴이 정확히 하나여야 합니다: ${matches.length}곳`);
  const selected = matches[0], bound = bindLocalSource(original, location(selected));
  const ir = lowerExpression(selected, { records: true, resolve: node => {
    const identifier = bound.bySpan.get(`${node.getStart()}:${node.end}`);
    return node.text === 'undefined' && !bound.symbol(identifier)?.declarations?.length
      ? { kind: 'literal', value: { $value: 'undefined' }, source: location(node) } : undefined;
  } });
  return {
    schema: VERSION, mode: 'record-expression-slice', typescript: ts.version, engineSha256: ENGINE_SHA256,
    source: { file: filename, sha256: hash(sourceText) }, target: { line, ...(column === undefined ? {} : { column }) },
    root: location(selected), ir, inputs: inputNames(ir),
    bindings: indexSliceBindings(original, [{ condition: ir }], location(selected), bound),
    context: sourceContext(selected),
    contract: {
      observation: '선택한 객체 리터럴의 열거 가능한 자체 문자열 속성 값 또는 계산 중 TypeError; 객체 동일성·속성 열거 순서는 관찰하지 않음',
      assumptions: ['식별자는 객체 식을 평가하는 지점의 명시적 스냅샷', '레코드 입력은 모든 자체 속성이 열거 가능한 데이터 속성인 null 프로토타입 값 트리',
        'spread는 값 레코드·null·undefined·숫자·불리언에 한정; 객체 내부 참조는 얕게 복사'],
      notProven: ['객체 식 도달·앞선 인수 계산·콜백 실행·외부 호출', '실제 DOM Event의 getter와 스냅샷의 일치',
        '이후 상태 갱신·공유 객체 변경·서버 반영', '문자열·배열·심볼·getter·Proxy의 spread',
        '새 객체에서 없는 속성을 읽을 때의 프로토타입 값', '전체 변경·사용자 이해도'],
    },
  };
}
