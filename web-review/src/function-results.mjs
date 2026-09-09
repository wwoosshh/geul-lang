import ts from 'typescript';
import { Unsupported, VERSION } from './core.mjs';
import { parseSource, location, hash } from './typescript.mjs';
import { bindLocalSource } from './bindings.mjs';
import { sourceContext } from './source-context.mjs';
import { ENGINE_SHA256 } from './fingerprint.mjs';

const wrapped = node => ts.isParenthesizedExpression(node) || ts.isAsExpression(node) || ts.isTypeAssertionExpression(node) || ts.isNonNullExpression(node) || ts.isSatisfiesExpression(node);
function outer(node) { while (node.parent && wrapped(node.parent) && node.parent.expression === node) node = node.parent; return node; }
const fieldName = node => node && (ts.isIdentifier(node) || ts.isStringLiteral(node)) ? node.text : undefined;
const owner = node => { for (let current = node.parent; current; current = current.parent) if (ts.isFunctionLike(current)) return current; return node.getSourceFile(); };

// This source index connects a direct call's const result to its later uses.
// It does not substitute return values into a later program point or execute
// the callee, its caller, another module, or any external mutation.
export function indexFunctionResult(sourceText, { functionName, line, filename = 'input.tsx' } = {}) {
  if (typeof functionName !== 'string' || !functionName) throw new Unsupported('함수 이름이 필요합니다.');
  if (line !== undefined && (!Number.isSafeInteger(line) || line < 1)) throw new Unsupported('호출 줄은 양의 정수여야 합니다.');
  const original = parseSource(sourceText, filename);
  const declarations = original.statements.filter(node => ts.isFunctionDeclaration(node) && node.name?.text === functionName && node.body);
  if (declarations.length !== 1) throw new Unsupported('이름이 일치하는 최상위 함수 선언 하나가 필요합니다.');
  const bound = bindLocalSource(original, location(declarations[0]));
  const { file, checker, source, symbol, identifiers, root: fn } = bound;
  const fail = (message, node) => { throw new Unsupported(message, node ? source(node) : undefined); };
  const contexts = new Map();
  let contextBytes = 0;
  const contextFor = node => {
    if (!contexts.has(node)) {
      const value = sourceContext(node, source);
      contexts.set(node, { value, bytes: Buffer.byteLength(JSON.stringify(value)) });
    }
    const context = contexts.get(node);
    // Count each occurrence in the eventual JSON, including contexts shared
    // by several result fields, to avoid a small source expanding without bound.
    contextBytes += context.bytes;
    if (contextBytes > 8 * 1024 * 1024) fail('결과 연결의 소스 문맥 출력 제한(8 MiB)을 초과했습니다.', node);
    return context.value;
  };
  const unique = node => {
    const value = symbol(node);
    if (!value || value.declarations?.length !== 1 || checker.resolveName(node.text, node, ts.SymbolFlags.Value, false) !== value) fail('바인딩 선언을 하나로 결정할 수 없습니다.', node);
    return value;
  };
  const targetSymbol = unique(fn.name);
  const directCalls = [], otherReferences = [];
  for (const identifier of identifiers) {
    if (identifier === fn.name || symbol(identifier) !== targetSymbol) continue;
    const expression = outer(identifier);
    if (ts.isCallExpression(expression.parent) && expression.parent.expression === expression && !expression.parent.questionDotToken) directCalls.push(expression.parent);
    else otherReferences.push(source(identifier));
  }
  const matches = directCalls.filter(call => line === undefined || source(call).line === line);
  if (matches.length !== 1) fail(`선택한 직접 호출은 정확히 한 곳이어야 합니다: ${matches.length}곳`);
  const call = matches[0];
  if (call.arguments.some(ts.isSpreadElement)) fail('호출 인수 spread는 위치 대응을 확정할 수 없습니다.', call);
  const initialized = outer(call), declaration = initialized.parent;
  if (!ts.isVariableDeclaration(declaration) || declaration.initializer !== initialized || !(declaration.parent.flags & ts.NodeFlags.Const)) fail('선택한 호출 결과를 직접 받는 const 선언이 필요합니다.', call);
  const bindings = [];
  if (ts.isIdentifier(declaration.name)) bindings.push({ name: declaration.name, property: null });
  else if (ts.isObjectBindingPattern(declaration.name) && declaration.name.elements.length && declaration.name.elements.length <= 64) {
    for (const element of declaration.name.elements) {
      if (!ts.isIdentifier(element.name) || element.initializer || element.dotDotDotToken) fail('결과 구조 분해는 기본값·중첩·나머지 속성 없는 이름이어야 합니다.', element);
      const property = fieldName(element.propertyName ?? element.name);
      if (property === undefined) fail('결과 속성은 고정 이름 또는 문자열이어야 합니다.', element);
      bindings.push({ name: element.name, property });
    }
  } else fail('단순 const 또는 비어 있지 않은 객체 구조 분해만 연결합니다.', declaration);

  function usage(identifier) {
    const result = { source: source(identifier), nestedFunction: owner(identifier) !== owner(declaration) };
    for (let parent = identifier.parent; parent && !ts.isStatement(parent); parent = parent.parent) {
      if (ts.isTypeNode(parent)) return { ...result, kind: 'type-only' };
    }
    const expression = outer(identifier), parent = expression.parent;
    let property;
    if (ts.isShorthandPropertyAssignment(parent) && parent.name === identifier && !parent.objectAssignmentInitializer) property = parent;
    else if (ts.isPropertyAssignment(parent) && parent.initializer === expression) property = parent;
    if (property && ts.isObjectLiteralExpression(property.parent)) {
      const object = property.parent, payloadName = fieldName(property.name), argument = outer(object), receiverCall = argument.parent;
      if (payloadName === '__proto__' && ts.isPropertyAssignment(property)) return { ...result, kind: 'object-prototype-setting', property: source(property) };
      if (payloadName !== undefined && ts.isCallExpression(receiverCall) && receiverCall.arguments.includes(argument)) {
        const overwriteRisk = object.properties.some(node => ts.isSpreadAssignment(node) || fieldName(node.name) === undefined)
          || object.properties.filter(node => fieldName(node.name) === payloadName).length !== 1;
        return { ...result, kind: overwriteRisk ? 'payload-property-overwrite-uncertain' : 'direct-payload-property',
          payloadName, property: source(property), call: source(receiverCall), callee: source(receiverCall.expression),
          argumentIndex: receiverCall.arguments.indexOf(argument), optionalCall: ts.isOptionalChain(receiverCall),
          context: contextFor(receiverCall) };
      }
      return { ...result, kind: 'object-property', property: source(property) };
    }
    if (ts.isCallExpression(parent) && parent.arguments.includes(expression)) return { ...result, kind: 'call-argument', call: source(parent), callee: source(parent.expression), argumentIndex: parent.arguments.indexOf(expression) };
    if (ts.isJsxExpression(parent) && ts.isJsxAttribute(parent.parent)) return { ...result, kind: 'jsx-attribute', attribute: source(parent.parent) };
    if (ts.isReturnStatement(parent)) return { ...result, kind: 'return-value' };
    if (ts.isBinaryExpression(parent) && parent.left === expression && parent.operatorToken.kind >= ts.SyntaxKind.FirstAssignment && parent.operatorToken.kind <= ts.SyntaxKind.LastAssignment) return { ...result, kind: 'write-reference' };
    if ((ts.isPrefixUnaryExpression(parent) || ts.isPostfixUnaryExpression(parent)) && [ts.SyntaxKind.PlusPlusToken, ts.SyntaxKind.MinusMinusToken].includes(parent.operator)) return { ...result, kind: 'write-reference' };
    return { ...result, kind: 'other-reference' };
  }
  const connections = bindings.map(binding => {
    const value = unique(binding.name);
    const uses = identifiers.filter(node => node !== binding.name && symbol(node) === value);
    if (uses.length > 2048) fail('결과 바인딩의 참조 제한(2048)을 초과했습니다.', binding.name);
    return { property: binding.property, localName: binding.name.text, declaration: source(binding.name), uses: uses.map(usage) };
  });
  return {
    schema: VERSION, mode: 'function-result-bindings', typescript: ts.version, engineSha256: ENGINE_SHA256,
    source: { file: filename, sha256: hash(sourceText) },
    target: { functionName, line: source(call).line }, functionDeclaration: source(fn), call: source(call),
    arguments: call.arguments.map((argument, index) => ({ index, expression: source(argument), parameter: fn.parameters[index] ? source(fn.parameters[index]) : null })),
    resultDeclaration: source(declaration), callContext: contextFor(call), connections,
    otherDirectCalls: directCalls.filter(node => node !== call).map(source), otherFunctionReferences: otherReferences,
    contract: {
      observation: '한 원본 파일에서 직접 함수 호출의 const 결과·고정 속성 분해·이후 사용 위치를 TypeScript 심볼로 연결; 분기와 선행 문장은 소스 문맥으로 제시',
      notProven: ['런타임 함수 바인딩이 이 선언으로 유지된다는 사실', '인수 계산과 함수의 실행 결과',
        '이 호출·이후 참조의 도달 조건과 실제 실행', '객체의 이후 변경과 별칭 경유 사용',
        '다른 파일의 사용·외부 호출 내부·서버 반영', 'JSX 렌더링·이벤트·비동기 순서'] },
  };
}
