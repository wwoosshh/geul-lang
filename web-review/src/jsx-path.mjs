import ts from 'typescript';
import { Unsupported } from './core.mjs';
import { location, lowerExpression } from './typescript.mjs';

export function jsxGuardPath(file, targetNode, terminal) {
  const guards = [], omittedEvaluations = [];
  const fail = (reason, node) => { throw new Unsupported(reason, location(node)); };
  let root = targetNode, current = targetNode;
  const omit = (node, reason) => omittedEvaluations.push({ source: location(node), reason });
  const guard = (condition, accepts, owner) => guards.push({ condition: lowerExpression(condition), accepts, source: location(owner), conditionSource: location(condition) });
  while (current.parent) {
    const parent = current.parent;
    if (ts.isParenthesizedExpression(parent) || ts.isAsExpression(parent) || ts.isNonNullExpression(parent) || ts.isSatisfiesExpression(parent) || ts.isTypeAssertionExpression(parent)) {
      // Transparent TypeScript wrappers preserve this evaluation path.
    } else if (ts.isJsxExpression(parent) && !parent.dotDotDotToken) {
      // Continue through the child expression container.
    } else if (ts.isBinaryExpression(parent) && ['&&', '||', '??'].includes(parent.operatorToken.getText(file))) {
      if (parent.right === current) guard(parent.left, { '&&': 'truthy', '||': 'falsy', '??': 'nullish' }[parent.operatorToken.getText(file)], parent);
      else if (parent.left !== current) fail('연산자 경로를 결정할 수 없습니다.', parent);
    } else if (ts.isConditionalExpression(parent)) {
      if (parent.whenTrue === current) guard(parent.condition, 'truthy', parent);
      else if (parent.whenFalse === current) guard(parent.condition, 'falsy', parent);
      else if (parent.condition !== current) fail('조건식 경로를 결정할 수 없습니다.', parent);
    } else if (ts.isJsxElement(parent) || ts.isJsxFragment(parent)) {
      const index = parent.children.indexOf(current);
      if (index < 0) fail('JSX 속성 안의 노드 경로는 아직 지원하지 않습니다.', parent);
      if (ts.isJsxElement(parent)) omit(parent.openingElement, '상위 태그 바인딩과 속성 평가');
      else omit(parent.openingFragment, '상위 fragment 생성기 바인딩');
      for (const sibling of parent.children.slice(0, index)) if (!ts.isJsxText(sibling) && !(ts.isJsxExpression(sibling) && !sibling.expression)) omit(sibling, '선행 형제의 평가');
    } else if ((ts.isVariableDeclaration(parent) && parent.initializer === current) ||
      (ts.isReturnStatement(parent) && parent.expression === current) ||
      (ts.isArrowFunction(parent) && parent.body === current) ||
      (ts.isExpressionStatement(parent) && parent.expression === current)) {
      root = current; break;
    } else fail(`표현식 경로 밖 또는 미지원 경로: ${ts.SyntaxKind[parent.kind]}`, parent);
    current = parent; root = current;
  }
  guards.reverse();
  const literal = value => ({ kind: 'literal', value, source: location(targetNode) });
  let ir = terminal ?? literal(true);
  for (const item of [...guards].reverse()) {
    const condition = item.accepts === 'nullish' ? { kind: 'binary', op: '==', left: item.condition, right: { kind: 'literal', value: null }, generatedOperation: 'is-nullish', source: item.conditionSource } : item.condition;
    ir = { kind: 'conditional', condition,
      yes: item.accepts === 'falsy' ? literal(false) : ir,
      no: item.accepts === 'falsy' ? ir : literal(false), source: item.source };
  }
  return { root, guards, omittedEvaluations, ir };
}
