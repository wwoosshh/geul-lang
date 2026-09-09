import ts from 'typescript';
import { VERSION, Unsupported, inputNames } from './core.mjs';
import { parseSource, lowerExpression, hash, location } from './typescript.mjs';
import { indexSliceBindings } from './bindings.mjs';
import { sourceContext } from './source-context.mjs';
import { ENGINE_SHA256 } from './fingerprint.mjs';

// Select an ELEMENT first, including when the named prop is absent. Returning
// a record here is an observation projection, not the application's props object.
export function liftJsxProperty(sourceText, { tag, attribute, line, filename = 'input.tsx' } = {}) {
  if (typeof tag !== 'string' || !tag || typeof attribute !== 'string' || !attribute) throw new Unsupported('태그와 속성 이름이 필요합니다.');
  if (['key', 'ref', 'children', '__proto__'].includes(attribute)) throw new Unsupported('특수 JSX 속성은 일반 속성 존재 관찰에서 제외합니다.');
  if (line !== undefined && (!Number.isSafeInteger(line) || line < 1)) throw new Unsupported('선택 줄은 여는 태그의 양의 시작 줄이어야 합니다.');
  const file = parseSource(sourceText, filename), matches = [];
  function visit(node, depth = 0) {
    if (depth > 128) throw new Unsupported('JSX 속성 존재 관찰의 AST 깊이 제한');
    if ((ts.isJsxSelfClosingElement(node) || ts.isJsxOpeningElement(node)) && node.tagName.getText(file) === tag && (line === undefined || location(node).line === line)) matches.push(node);
    ts.forEachChild(node, child => visit(child, depth + 1));
  }
  visit(file);
  if (matches.length !== 1) throw new Unsupported(`여는 JSX 태그를 정확히 하나 선택해야 합니다: ${matches.length}곳`);
  const element = matches[0], properties = element.attributes.properties;
  if (properties.some(ts.isJsxSpreadAttribute)) throw new Unsupported('spread가 속성 존재·값을 바꿀 수 있어 이 관찰을 만들지 않습니다.', location(element));
  const selected = properties.filter(item => ts.isJsxAttribute(item) && item.name.getText(file) === attribute);
  if (selected.length > 1) throw new Unsupported('중복된 선택 JSX 속성은 지원하지 않습니다.', location(element));
  const item = selected[0], fields = [];
  if (item) {
    const initializer = item.initializer;
    let value;
    if (!initializer) value = { kind: 'literal', value: true, source: location(item) };
    else if (ts.isStringLiteral(initializer)) value = lowerExpression(initializer);
    else if (ts.isJsxExpression(initializer) && initializer.expression) value = lowerExpression(initializer.expression);
    else throw new Unsupported('빈 JSX 속성 식은 지원하지 않습니다.', location(item));
    fields.push({ name: attribute, value, source: location(item) });
  }
  const ir = { kind: 'record', projection: 'jsx-property-values', properties: fields, source: location(item ?? element) };
  const { storedResult, ...bindings } = indexSliceBindings(file, [{ condition: ir }], location(element));
  return { schema: VERSION, mode: 'jsx-property-slice', engineSha256: ENGINE_SHA256, typescript: ts.version,
    source: { file: filename, sha256: hash(sourceText), ...location(item ?? element) },
    target: { tag, attribute, line: location(element).line, intrinsic: /^[a-z][a-z0-9]*$/.test(tag), element: location(element), provided: !!item },
    ir, inputs: inputNames(ir), bindings, context: sourceContext(element),
    omittedAttributes: properties.filter(property => property !== item).map(location),
    contract: {
      observation: '선택 JSX에 적힌 속성의 존재와 해당 식만 계산한 값·TypeError. 결과 레코드는 그 속성만 담는 보고용 관찰이며 실제 props 객체가 아님',
      assumptions: ['식별자는 속성 식의 평가 지점에서 주어진 스냅샷', '레코드는 별칭·getter·Proxy 없는 null 프로토타입 값 트리', '불투명 객체 태그는 내부 미확인·참 취급·typeof object 가정'],
      notProven: ['다른 속성·형제 JSX·태그 표현식의 평가와 부수 효과', '선택 JSX의 도달·생성 완료·컴포넌트 전달·기본값', 'React의 HTML 속성 변환·접근성 동작·화면·입력 검증', '실제 사용자 상태와 전체 변경'],
    } };
}
