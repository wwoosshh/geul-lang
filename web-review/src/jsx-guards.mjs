import ts from 'typescript';
import { Unsupported, VERSION, inputNames } from './core.mjs';
import { parseSource, location, hash } from './typescript.mjs';
import { ENGINE_SHA256 } from './fingerprint.mjs';
import { bindLocalSource, indexSliceBindings } from './bindings.mjs';
import { prependConstPrefix } from './jsx-prefix.mjs';
import { jsxGuardPath } from './jsx-path.mjs';

// This is a conditional path through ONE expression, not a renderer or a
// program slicer that has established purity of everything it leaves out.
export function liftJsxGuards(source, { tag, attribute, equals, line, prefixLine, filename = 'input.tsx' }) {
  if (line !== undefined && (!Number.isSafeInteger(line) || line < 1)) throw new Unsupported('선택 줄은 양의 정수여야 합니다.');
  if ((attribute === undefined) !== (equals === undefined)) throw new Unsupported('속성 선택에는 attribute와 equals가 모두 필요합니다.');
  const file = parseSource(source, filename), matches = [];
  const fail = (reason, node) => { throw new Unsupported(reason, node ? location(node) : undefined); };
  function visit(node, depth = 0) {
    if (depth > 128) fail('AST 깊이 제한 초과', node);
    if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node)) {
      const opening = ts.isJsxElement(node) ? node.openingElement : node;
      if (opening.tagName.getText(file) === tag && (line === undefined || location(opening).line === line)) {
        const found = attribute === undefined ? [] : opening.attributes.properties.filter(item => ts.isJsxAttribute(item) && item.name.getText(file) === attribute);
        if (attribute === undefined || (found.length === 1 && ts.isStringLiteral(found[0].initializer) && found[0].initializer.text === equals)) matches.push(node);
      }
    }
    ts.forEachChild(node, child => visit(child, depth + 1));
  }
  visit(file);
  if (matches.length !== 1) fail(`대상 JSX 노드는 정확히 한 곳이어야 합니다: ${matches.length}곳`);
  const targetNode = matches[0];
  let { root, guards, omittedEvaluations, ir } = jsxGuardPath(file, targetNode);
  const opening = ts.isJsxElement(targetNode) ? targetNode.openingElement : targetNode;
  const bound = bindLocalSource(file, location(root));
  let prefix;
  if (prefixLine !== undefined) ({ ir, prefix } = prependConstPrefix(ir, prefixLine, bound, file.fileName));
  return {
    schema: VERSION, mode: 'jsx-guard-slice', typescript: ts.version, engineSha256: ENGINE_SHA256,
    source: { file: filename, sha256: hash(source), ...location(targetNode) },
    target: { tag, ...(attribute !== undefined ? { attribute, equals } : {}), line: location(opening).line,
      intrinsic: /^[a-z][a-z0-9]*$/.test(tag), element: location(targetNode) },
    root: location(root), ...(prefix ? { prefix } : {}), guards, omittedEvaluations,
    bindings: indexSliceBindings(file, [{ condition: ir }], location(root), bound), ir, inputs: inputNames(ir),
    contract: {
      observation: `${prefix ? '지정한 const 구간을 순서대로 실행한 뒤 ' : ''}지정한 표현식 평가를 시작하고 생략된 선행 평가가 정상 완료된다는 가정에서 대상 JSX 노드의 평가로 진입하는지 여부`,
      assumptions: [prefix ? '외부 입력은 지정한 const 구간의 시작 지점 스냅샷' : '각 식별자는 선택 경로의 명시한 스냅샷 입력', 'JSX 변환기가 사용하는 표준 생성기 참조가 정상 제공됨', '생략된 선행 평가가 예외를 내거나 이후 조건의 입력을 바꾸지 않음'],
      notProven: ['이 표현식 자체에 도달하는 조건과 앞선 return', '생략한 태그·속성·형제 평가의 정상 완료와 무효과성', '대상 노드 자신의 속성·자식 평가와 생성 성공', '생성된 요소가 실제로 반환·사용되는 경로', 'React 렌더링·실제 화면 표시·클릭 가능성·서버 권한'],
    },
  };
}
