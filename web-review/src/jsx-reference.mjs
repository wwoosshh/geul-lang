import ts from 'typescript';
import { Unsupported, VERSION, inputNames } from './core.mjs';
import { parseSource, location, lowerExpression, hash } from './typescript.mjs';
import { jsxGuardPath } from './jsx-path.mjs';
import { indexSliceBindings } from './bindings.mjs';
import { ENGINE_SHA256 } from './fingerprint.mjs';

export function liftJsxReference(source, { name, line, column, filename = 'input.tsx' }) {
  for (const value of [line, column]) if (value !== undefined && (!Number.isSafeInteger(value) || value < 1)) throw new Unsupported('선택 줄·열은 양의 정수여야 합니다.');
  const file = parseSource(source, filename), matches = [];
  function visit(node, depth = 0) {
    if (depth > 128) throw new Unsupported('AST 깊이 제한 초과');
    if (ts.isIdentifier(node) && node.text === name && ts.isJsxExpression(node.parent) && !node.parent.dotDotDotToken &&
      (ts.isJsxElement(node.parent.parent) || ts.isJsxFragment(node.parent.parent))) {
      const at = location(node);
      if ((line === undefined || at.line === line) && (column === undefined || at.column === column)) matches.push(node);
    }
    ts.forEachChild(node, child => visit(child, depth + 1));
  }
  visit(file);
  if (matches.length !== 1) throw new Unsupported(`직접 JSX 자식으로 읽는 식별자는 정확히 한 곳이어야 합니다: ${matches.length}곳`);
  const node = matches[0];
  const terminal = { kind: 'object-child', value: lowerExpression(node), source: location(node) };
  const { root, guards, omittedEvaluations, ir } = jsxGuardPath(file, node, terminal);
  return { schema: VERSION, mode: 'jsx-reference-slice', typescript: ts.version, engineSha256: ENGINE_SHA256,
    source: { file: filename, sha256: hash(source), ...location(node) },
    target: { name, line: location(node).line, column: location(node).column }, root: location(root),
    guards, omittedEvaluations, bindings: indexSliceBindings(file, [{ condition: ir }], location(root)), ir, inputs: inputNames(ir),
    contract: { observation: '명시한 표현식 안에서 선택한 식별자의 객체 값을 직접 JSX 자식 자리에 전달하는지 여부',
      assumptions: ['식별자들은 선택한 표현식의 스냅샷 입력', '생략한 선행 태그·속성·형제 평가가 정상 완료하고 입력을 바꾸지 않음', '불투명 객체 입력은 null이 아니며 참으로 취급되고 typeof가 object인 값이라는 가정'],
      notProven: ['그 객체가 앞서 선택한 JSX 생성 결과와 동일하다는 사실', '실제 React 요소인지와 내부 props·이벤트', '표현식 도달 조건·나중의 return·렌더링 성공', '생략된 선행 평가의 무효과성·라이프사이클·서버 동작'] } };
}
