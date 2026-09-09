import ts from 'typescript';
import { Unsupported, VERSION, inputNames } from './core.mjs';
import { parseSource, location, lowerExpression, hash } from './typescript.mjs';
import { ENGINE_SHA256 } from './fingerprint.mjs';

// A prop slice has no claim about whether the parent element is reached or
// rendered. Spreads and duplicate props are rejected, rather than obscuring
// JavaScript's property overwrite order.
export function liftJsxAttribute(source, { tag, attribute, line, filename = 'input.tsx' }) {
  if (attribute === '__proto__') throw new Unsupported('__proto__는 일반 JSX 속성으로 취급할 수 없습니다.');
  if (line !== undefined && (!Number.isSafeInteger(line) || line < 1)) throw new Unsupported('선택 줄은 양의 정수여야 합니다.');
  const file = parseSource(source, filename), matches = [];
  function visit(node, depth = 0) {
    if (depth > 128) throw new Unsupported('AST 깊이 제한 초과');
    if ((ts.isJsxSelfClosingElement(node) || ts.isJsxOpeningElement(node)) && node.tagName.getText(file) === tag) {
      const attrs = node.attributes.properties;
      const found = attrs.filter(a => ts.isJsxAttribute(a) && a.name.getText(file) === attribute);
      if (found.length && (line === undefined || found.some(a => location(a).line === line))) {
        if (attrs.some(ts.isJsxSpreadAttribute) || found.length !== 1) throw new Unsupported('대상 JSX의 spread 또는 중복 속성은 지원하지 않습니다.', location(node));
        matches.push({ element: node, attribute: found[0] });
      }
    }
    ts.forEachChild(node, child => visit(child, depth + 1));
  }
  visit(file);
  if (matches.length !== 1) throw new Unsupported(`대상 JSX 속성은 정확히 한 곳이어야 합니다: ${matches.length}곳`);
  const item = matches[0], initializer = item.attribute.initializer;
  let ir;
  if (!initializer) ir = { kind: 'literal', value: true, source: location(item.attribute) };
  else if (ts.isStringLiteral(initializer)) ir = lowerExpression(initializer);
  else if (ts.isJsxExpression(initializer) && initializer.expression) ir = lowerExpression(initializer.expression);
  else throw new Unsupported('빈 JSX 속성 또는 미지원 초기화', location(item.attribute));
  return {
    schema: VERSION, mode: 'jsx-attribute-slice', typescript: ts.version, engineSha256: ENGINE_SHA256,
    source: { file: filename, sha256: hash(source), ...location(item.attribute) },
    target: { tag, attribute, line: location(item.attribute).line, intrinsic: /^[a-z][a-z0-9]*$/.test(tag), element: location(item.element) },
    ir, inputs: inputNames(ir),
    contract: {
      observation: '이 JSX 생성 지점에 도달했다는 전제에서 속성에 전달하는 값',
      assumptions: ['불투명 객체 태그를 쓴 입력은 null이 아니고 참으로 취급되며 typeof가 object라는 가정'],
      notProven: ['이 JSX까지 도달하는 조건', '부모/자식 컴포넌트와 다른 속성의 효과', '실제 DOM 속성으로의 변환', '화면 표시·클릭 가능성·서버 권한'],
    },
  };
}
