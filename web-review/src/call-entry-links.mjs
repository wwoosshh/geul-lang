import ts from 'typescript';
import { Unsupported } from './core.mjs';
import { sourceContext } from './source-context.mjs';

const wrapped = node => ts.isParenthesizedExpression(node) || ts.isAsExpression(node) || ts.isTypeAssertionExpression(node)
  || ts.isNonNullExpression(node) || ts.isSatisfiesExpression(node);
function outer(node) { while (node.parent && wrapped(node.parent) && node.parent.expression === node) node = node.parent; return node; }
const fieldName = node => ts.isIdentifier(node) || ts.isStringLiteral(node) ? node.text : null;

// Link source symbols only. A reference to a function does not establish when
// it runs, which value an alias holds, or which callback React will deliver.
export function indexCallEntryLinks(bound, owner, call) {
  const { source, symbol, declarationInfo, identifiers, checker } = bound;
  function declaration(name) {
    const binding = symbol(name), declarations = binding?.declarations ?? [];
    return { name: name.text, source: source(name), status: declarations.length === 1 ? 'declaration-found' : declarations.length ? 'ambiguous-declaration' : 'unresolved-in-file',
      declarations: declarations.slice(0, 32).map(declarationInfo), declarationsTruncated: declarations.length > 32 };
  }
  const callee = declaration(call.expression), assigned = outer(owner).parent;
  const name = ts.isFunctionDeclaration(owner) ? owner.name
    : ts.isVariableDeclaration(assigned) && assigned.initializer === outer(owner) && ts.isIdentifier(assigned.name)
      && (assigned.parent.flags & ts.NodeFlags.Const) ? assigned.name : undefined;
  let entry;
  if (!name) entry = { status: 'not-indexed', source: source(owner), reason: '직접 const에 저장한 함수 또는 이름 있는 함수 선언의 참조만 색인한다.' };
  else {
    const declared = declaration(name), binding = symbol(name);
    const unique = declared.status === 'declaration-found' && checker.resolveName(name.text, name, ts.SymbolFlags.Value, false) === binding;
    const references = unique ? identifiers.filter(identifier => identifier !== name && symbol(identifier) === binding) : [];
    let contextBytes = 0;
    entry = { ...declared, source: source(owner), referenceCount: unique ? references.length : null, referencesTruncated: references.length > 128,
      references: references.slice(0, 128).map(identifier => {
        const expression = outer(identifier), parent = expression.parent;
        let kind = 'other-reference', container = expression, details = {};
        if (ts.isCallExpression(parent) && parent.expression === expression) {
          kind = ts.isOptionalChain(parent) ? 'optional-call' : 'direct-call'; container = parent;
          details.arguments = parent.arguments.map(source);
        } else if (ts.isJsxExpression(parent) && ts.isJsxAttribute(parent.parent)) {
          const attribute = parent.parent; kind = 'jsx-attribute';
          details = { tag: attribute.parent.parent.tagName.getText(), attribute: attribute.name.getText() };
        } else if ((ts.isPropertyAssignment(parent) && parent.initializer === expression) || ts.isShorthandPropertyAssignment(parent)) {
          kind = ts.isShorthandPropertyAssignment(parent) ? 'object-shorthand' : 'object-property'; container = parent;
          details.property = fieldName(parent.name);
          const object = outer(parent.parent), jsxExpression = object.parent;
          if (ts.isObjectLiteralExpression(parent.parent) && ts.isJsxExpression(jsxExpression) && ts.isJsxAttribute(jsxExpression.parent)) {
            const attribute = jsxExpression.parent;
            details.jsxContainer = { tag: attribute.parent.parent.tagName.getText(), attribute: attribute.name.getText(), source: source(attribute) };
          }
        } else if (ts.isCallExpression(parent) && parent.arguments.includes(expression)) {
          kind = 'call-argument'; container = parent; details.argumentIndex = parent.arguments.indexOf(expression);
        } else if (ts.isReturnStatement(parent)) kind = 'return-reference';
        else if (ts.isBinaryExpression(parent) && parent.left === expression
          && parent.operatorToken.kind >= ts.SyntaxKind.FirstAssignment && parent.operatorToken.kind <= ts.SyntaxKind.LastAssignment) kind = 'write-reference';
        for (let ancestor = identifier.parent; ancestor && !ts.isStatement(ancestor); ancestor = ancestor.parent) {
          if (ts.isTypeNode(ancestor)) { kind = 'type-only'; container = expression; details = {}; break; }
        }
        const context = sourceContext(container, source);
        contextBytes += Buffer.byteLength(JSON.stringify(context));
        if (contextBytes > 2 * 1024 * 1024) throw new Unsupported('호출 참조의 소스 문맥 제한(2 MiB)을 초과했습니다.', source(identifier));
        return { kind, source: source(identifier), expression: source(container), ...details, context, reachabilityProven: false };
      }) };
    if (!unique) entry.referenceStatus = 'ambiguous-binding';
  }
  return { status: 'source-links-only', callee, entry,
    scope: '동일 원본 파일의 선언·직접 심볼 참조다. 초기화·호출·이벤트·속성 전달을 실행한 결과가 아니다.',
    notProven: ['별칭·다른 파일·객체 경유 참조', '참조 위치의 실제 도달과 호출 순서', '객체 속성 덮어쓰기·spread·React가 실제 받은 콜백', 'hook의 반환값·callee 호출 가능성·인수 평가·후속 효과'] };
}
