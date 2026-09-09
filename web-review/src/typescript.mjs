import ts from 'typescript';
import { createHash } from 'node:crypto';
import { BINARY, Unsupported, VERSION, encode, inputNames } from './core.mjs';
import { ENGINE_SHA256 } from './fingerprint.mjs';

export const hash = text => createHash('sha256').update(text).digest('hex');
export function parseSource(source, filename = 'input.tsx') {
  if (Buffer.byteLength(source) > 2 * 1024 * 1024) throw new Unsupported('파일 크기 제한(2 MiB)을 초과했습니다.');
  const file = ts.createSourceFile(filename, source, ts.ScriptTarget.ESNext, true,
    filename.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  if (file.parseDiagnostics.length) throw new Unsupported(ts.flattenDiagnosticMessageText(file.parseDiagnostics[0].messageText, '\n'));
  return file;
}
export function location(node) {
  const file = node.getSourceFile();
  const start = node.getStart(file), position = file.getLineAndCharacterOfPosition(start);
  return { file: file.fileName, start, end: node.end, line: position.line + 1, column: position.character + 1 };
}
export function findExpression(file, text, container) {
  const matches = [];
  function visit(node, depth = 0) {
    if (depth > 128) throw new Unsupported('AST 깊이 제한(128)을 초과했습니다.');
    if (ts.isExpressionNode(node) && node.getText(file) === text) {
      let owner = node.parent;
      while (owner && !ts.isFunctionLike(owner)) owner = owner.parent;
      if (!container || owner?.name?.getText(file) === container) matches.push(node);
    }
    ts.forEachChild(node, child => visit(child, depth + 1));
  }
  visit(file);
  if (matches.length !== 1) throw new Unsupported(`선택 식은 정확히 한 곳이어야 합니다: ${matches.length}곳`);
  return matches[0];
}
export function lowerExpression(root, { resolve, calls, jsx = false, records = false, arrays = false, sourceLocation = location } = {}) {
  let remaining = 8192;
  const callbackScopes = [];
  function lower(node, depth = 0) {
    if (--remaining < 0 || depth > 128) throw new Unsupported('식의 크기·깊이 제한을 초과했습니다.', sourceLocation(node));
    const sub = value => lower(value, depth + 1);
    const fail = reason => { throw new Unsupported(reason, sourceLocation(node)); };
    const wrap = data => ({ ...data, source: sourceLocation(node) });
    if (ts.isParenthesizedExpression(node)) return sub(node.expression);
    // Assertions do not validate a runtime value. Keep the value unchanged.
    if (ts.isAsExpression(node) || ts.isTypeAssertionExpression(node) || ts.isNonNullExpression(node) || ts.isSatisfiesExpression(node)) return sub(node.expression);
    if (ts.isIdentifier(node)) {
      for (let index = callbackScopes.length - 1; index >= 0; index--) {
        const binding = callbackScopes[index];
        if (binding.label === node.text) return wrap({ kind: 'local', name: binding.name, label: binding.label, definition: binding.source });
      }
      const resolved = resolve?.(node);
      if (resolved) return { ...resolved, source: sourceLocation(node), definition: resolved.source };
      return wrap({ kind: 'input', name: node.text });
    }
    if (node.kind === ts.SyntaxKind.TrueKeyword) return wrap({ kind: 'literal', value: true });
    if (node.kind === ts.SyntaxKind.FalseKeyword) return wrap({ kind: 'literal', value: false });
    if (node.kind === ts.SyntaxKind.NullKeyword) return wrap({ kind: 'literal', value: null });
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
      if (ts.isStringLiteral(node) && ts.isJsxAttribute(node.parent) && node.text.includes('&')) fail('JSX 속성 문자열의 HTML entity 해석은 아직 지원하지 않습니다.');
      return wrap({ kind: 'literal', value: node.text });
    }
    if (ts.isNumericLiteral(node)) return wrap({ kind: 'literal', value: encode(Number(node.text)) });
    if (ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) {
      const steps = [];
      let base = node;
      while (ts.isPropertyAccessExpression(base) || ts.isElementAccessExpression(base)) {
        if (steps.length + depth >= 128) fail('속성 접근 경로의 깊이 제한(128)을 초과했습니다.');
        if (ts.isPropertyAccessExpression(base) && !ts.isIdentifier(base.name)) fail('private 필드 접근은 값 레코드의 속성 읽기가 아닙니다.');
        const key = ts.isPropertyAccessExpression(base) ? base.name.text :
          ts.isStringLiteral(base.argumentExpression) ? base.argumentExpression.text : undefined;
        steps.unshift(key === undefined
          ? { value: sub(base.argumentExpression), optional: !!base.questionDotToken }
          : { key, optional: !!base.questionDotToken });
        base = base.expression;
      }
      if (ts.isNonNullExpression(base) && ts.isOptionalChain(node)) fail('선택적 체인 중간의 non-null 단언은 아직 지원하지 않습니다.');
      return wrap({ kind: 'access', base: sub(base), steps });
    }
    if (ts.isPrefixUnaryExpression(node)) {
      const op = ts.tokenToString(node.operator);
      if (!['!', '+', '-'].includes(op)) fail(`미지원 단항 연산: ${op}`);
      return wrap({ kind: 'unary', op, value: sub(node.operand) });
    }
    if (ts.isTypeOfExpression(node)) return wrap({ kind: 'unary', op: 'typeof', value: sub(node.expression) });
    if (ts.isBinaryExpression(node)) {
      const op = ts.tokenToString(node.operatorToken.kind);
      if (!BINARY.has(op)) fail(`미지원 이항 연산: ${op}`);
      if (['==', '!='].includes(op) && node.right.kind !== ts.SyntaxKind.NullKeyword) fail('느슨한 비교는 우변 null만 지원합니다.');
      return wrap({ kind: 'binary', op, left: sub(node.left), right: sub(node.right) });
    }
    if (ts.isConditionalExpression(node)) return wrap({ kind: 'conditional', condition: sub(node.condition), yes: sub(node.whenTrue), no: sub(node.whenFalse) });
    if (arrays && ts.isArrayLiteralExpression(node)) {
      if (node.elements.some(item => ts.isOmittedExpression(item) || ts.isSpreadElement(item))) fail('배열 리터럴의 빈칸·spread는 지원하지 않습니다.');
      return wrap({ kind: 'array', items: node.elements.map(sub) });
    }
    if (records && ts.isObjectLiteralExpression(node)) {
      const properties = [];
      for (const property of node.properties) {
        if (ts.isSpreadAssignment(property)) {
          properties.push({ spread: true, value: sub(property.expression), source: sourceLocation(property) });
          continue;
        }
        const shorthand = ts.isShorthandPropertyAssignment(property) && !property.objectAssignmentInitializer;
        if ((!ts.isPropertyAssignment(property) && !shorthand) || (!ts.isIdentifier(property.name) && !ts.isStringLiteral(property.name))) fail('객체는 고정 이름·단축 속성·값 레코드 spread만 지원합니다.');
        const name = property.name.text;
        if (name === '__proto__' && !shorthand) fail('객체의 prototype 설정은 지원하지 않습니다.');
        properties.push({ name, value: sub(shorthand ? property.name : property.initializer), source: sourceLocation(property) });
      }
      return wrap({ kind: 'record', properties });
    }
    if (jsx && (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node))) {
      const opening = ts.isJsxElement(node) ? node.openingElement : node;
      const tag = opening.tagName.getText();
      if (!/^[a-z][a-z0-9]*$/.test(tag)) fail('기본 태그의 JSX 생성만 지원합니다. 사용자 컴포넌트·fragment는 별도 모델이 필요합니다.');
      const attributes = [], seen = new Set();
      for (const attribute of opening.attributes.properties) {
        if (!ts.isJsxAttribute(attribute)) fail('JSX spread는 지원하지 않습니다.');
        const name = attribute.name.getText();
        if (['key', 'ref', 'children', '__proto__'].includes(name) || seen.has(name)) fail('특수·중복 JSX 속성은 지원하지 않습니다.');
        seen.add(name);
        let value;
        if (!attribute.initializer) value = { kind: 'literal', value: true, source: sourceLocation(attribute) };
        else if (ts.isStringLiteral(attribute.initializer)) value = sub(attribute.initializer);
        else if (ts.isJsxExpression(attribute.initializer) && attribute.initializer.expression) value = sub(attribute.initializer.expression);
        else fail('미지원 JSX 속성 초기화');
        attributes.push({ name, value, source: sourceLocation(attribute) });
      }
      const children = [];
      for (const child of ts.isJsxElement(node) ? node.children : []) {
        if (ts.isJsxText(child)) {
          if (child.text.includes('&')) fail('JSX 텍스트 entity는 아직 지원하지 않습니다.');
          if (/[\r\n\u2028\u2029]/.test(child.text)) {
            if (child.text.trim()) fail('여러 줄 JSX 텍스트 정규화는 아직 지원하지 않습니다.');
            continue;
          }
          if (child.text) children.push({ kind: 'literal', value: child.text, source: sourceLocation(child) });
        } else if (ts.isJsxExpression(child)) {
          if (child.dotDotDotToken) fail('JSX 자식 spread는 지원하지 않습니다.');
          if (child.expression) children.push(sub(child.expression));
        } else children.push(sub(child));
      }
      return wrap({ kind: 'jsx', tag, attributes, children });
    }
    if (arrays && ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) && ['filter', 'concat'].includes(node.expression.name.text)) {
      if (ts.isOptionalChain(node) || ts.isOptionalChain(node.expression)) fail('배열 메서드의 선택적 호출은 지원하지 않습니다.');
      const base = sub(node.expression.expression);
      if (node.expression.name.text === 'concat') {
        if (node.arguments.some(ts.isSpreadElement)) fail('concat 호출의 인수 spread는 지원하지 않습니다.');
        return wrap({ kind: 'array-concat', base, arguments: node.arguments.map(sub) });
      }
      const callback = node.arguments[0];
      if (node.arguments.length !== 1 || !ts.isArrowFunction(callback) || callback.parameters.length !== 1 || ts.isBlock(callback.body) || callback.modifiers?.length) fail('filter는 인수 하나·매개변수 하나·식 본문의 동기 화살표 함수만 지원합니다.');
      const parameter = callback.parameters[0];
      if (!ts.isIdentifier(parameter.name) || parameter.initializer || parameter.dotDotDotToken || parameter.questionToken || parameter.modifiers?.length) fail('filter 매개변수의 구조 분해·기본값·rest는 지원하지 않습니다.');
      // NUL cannot appear in a source identifier. Source span disambiguates
      // nested callbacks with the same spelling without capturing outer locals.
      const binding = { name: `\u0000filter:${callback.getStart()}:${parameter.name.text}`, label: parameter.name.text, source: sourceLocation(parameter.name) };
      callbackScopes.push(binding);
      let predicate;
      try { predicate = sub(callback.body); } finally { callbackScopes.pop(); }
      return wrap({ kind: 'array-filter', base, parameter: binding.name, parameterLabel: binding.label, parameterSource: binding.source, predicate });
    }
    if (ts.isCallExpression(node) && calls) return calls(node, sub);
    fail(`미지원 구문: ${ts.SyntaxKind[node.kind]}`);
  }
  return lower(root);
}
export function liftExpression(source, expression, filename = 'input.tsx', { container } = {}) {
  const file = parseSource(source, filename), node = findExpression(file, expression, container);
  const ir = lowerExpression(node);
  return {
    schema: VERSION, mode: 'expression-slice', typescript: ts.version, engineSha256: ENGINE_SHA256,
    source: { file: filename, sha256: hash(source), ...location(node), expression, ...(container ? { container } : {}) },
    ir, inputs: inputNames(ir),
    contract: {
      observation: '선택한 식을 해당 지점에서 평가한 값 또는 TypeError 발생',
      binding: '각 식별자의 값은 해당 프로그램 지점의 명시적 입력; 선언·도달 조건은 아직 추적하지 않음',
      records: 'null 프로토타입의 비순환 값 트리; 객체 별칭·배열·getter·Proxy 제외; 계산한 속성 키는 평가 시 원시 문자열에 한정',
      assumptions: ['불투명 객체 태그를 쓴 입력은 null이 아니고 참으로 취급되며 typeof가 object라는 가정'],
      notProven: ['전체 함수 또는 컴포넌트의 동작', '프로젝트 모듈 초기화', '입력 가정의 실제 충족'],
    },
  };
}
