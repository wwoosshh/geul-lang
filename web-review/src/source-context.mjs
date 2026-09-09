import ts from 'typescript';
import { Unsupported } from './core.mjs';
import { location } from './typescript.mjs';

// Syntactic navigation, deliberately NOT a control-flow or reachability proof.
// In particular, a previous if-return is recorded rather than turned into a
// predicate over a later snapshot. A getter or earlier statement may change it.
export function sourceContext(target, source = location) {
  const guards = [], preceding = [], declarators = [], boundaries = [];
  let owner, current = target, depth = 0;
  const boundary = (kind, node) => boundaries.push({ kind, source: source(node) });
  const guard = (kind, condition, accepts, node) => guards.push({ kind, condition: source(condition), accepts, source: source(node) });
  function immediateExit(statement) {
    const terminal = ts.isBlock(statement) && statement.statements.length === 1 ? statement.statements[0] : statement;
    if (ts.isReturnStatement(terminal) || ts.isThrowStatement(terminal)) return { kind: ts.isReturnStatement(terminal) ? 'return' : 'throw', source: source(terminal) };
    return null;
  }
  function prior(statement) {
    const result = { kind: ts.SyntaxKind[statement.kind], source: source(statement) };
    if (ts.isVariableStatement(statement)) result.declarations = statement.declarationList.declarations.map(source);
    if (ts.isIfStatement(statement)) {
      const yes = immediateExit(statement.thenStatement), no = statement.elseStatement && immediateExit(statement.elseStatement);
      if (yes || no) result.immediateExits = {
        condition: source(statement.expression),
        branches: [...(yes ? [{ accepts: 'truthy', ...yes }] : []), ...(no ? [{ accepts: 'falsy', ...no }] : [])],
      };
    }
    return result;
  }
  while (current.parent) {
    if (++depth > 128) throw new Unsupported('소스 문맥의 깊이 제한(128)을 초과했습니다.', source(current));
    const parent = current.parent;
    if (ts.isFunctionLike(parent)) { owner = parent; break; }
    if (ts.isBlock(parent) || ts.isSourceFile(parent)) {
      const index = parent.statements.indexOf(current);
      if (index >= 0) {
        if (preceding.length + index > 2048) throw new Unsupported('선행 문장의 소스 문맥 제한(2048)을 초과했습니다.', source(parent));
        preceding.unshift(...parent.statements.slice(0, index).map(prior));
      }
    } else if (ts.isVariableDeclarationList(parent)) {
      const index = parent.declarations.indexOf(current);
      if (index > 2048) throw new Unsupported('선행 변수 선언의 소스 문맥 제한(2048)을 초과했습니다.', source(parent));
      if (index > 0) declarators.unshift(...parent.declarations.slice(0, index).map(source));
    } else if (ts.isIfStatement(parent)) {
      if (parent.thenStatement === current) guard('if', parent.expression, 'truthy', parent);
      else if (parent.elseStatement === current) guard('if', parent.expression, 'falsy', parent);
    } else if (ts.isConditionalExpression(parent)) {
      if (parent.whenTrue === current) guard('conditional', parent.condition, 'truthy', parent);
      else if (parent.whenFalse === current) guard('conditional', parent.condition, 'falsy', parent);
    } else if (ts.isBinaryExpression(parent) && parent.right === current) {
      const accepts = { [ts.SyntaxKind.AmpersandAmpersandToken]: 'truthy', [ts.SyntaxKind.BarBarToken]: 'falsy', [ts.SyntaxKind.QuestionQuestionToken]: 'nullish' }[parent.operatorToken.kind];
      if (accepts) guard('logical-right', parent.left, accepts, parent);
      else if ([ts.SyntaxKind.AmpersandAmpersandEqualsToken, ts.SyntaxKind.BarBarEqualsToken, ts.SyntaxKind.QuestionQuestionEqualsToken].includes(parent.operatorToken.kind)) boundary('logical-assignment', parent);
    }
    if (ts.isIterationStatement(parent, false)) boundary('loop', parent);
    else if (ts.isTryStatement(parent)) boundary(parent.tryBlock === current ? 'try-body' : parent.catchClause === current ? 'catch-body' : 'finally-body', parent);
    else if (ts.isCaseClause(parent) || ts.isDefaultClause(parent)) boundary('switch-clause', parent);
    else if (ts.isAwaitExpression(parent)) boundary('await', parent);
    else if (ts.isYieldExpression(parent)) boundary('yield', parent);
    else if (ts.isWithStatement(parent)) boundary('with', parent);
    else if (ts.isCallExpression(parent) && ts.isOptionalChain(parent)) boundary('optional-call', parent);
    // A class field initializer is evaluated when the class/instance is made,
    // not when a surrounding function reaches this class declaration.
    else if (ts.isPropertyDeclaration(parent)) { boundary('class-field', parent); break; }
    current = parent;
  }
  const functions = [];
  for (let node = owner; node; node = node.parent) {
    if (ts.isFunctionLike(node)) functions.push({ kind: ts.SyntaxKind[node.kind], name: node.name?.getText() ?? null, source: source(node) });
  }
  return {
    kind: 'syntactic-source-context',
    owner: owner ? { kind: ts.SyntaxKind[owner.kind], name: owner.name?.getText() ?? null, source: source(owner) } : null,
    guards: guards.reverse(), precedingStatements: preceding, precedingDeclarators: declarators, boundaries: boundaries.reverse(), enclosingFunctions: functions,
    reachabilityProven: false,
  };
}
