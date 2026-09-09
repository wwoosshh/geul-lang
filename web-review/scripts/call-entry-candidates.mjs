import ts from 'typescript';
import { parseSource, location } from '../src/typescript.mjs';
import { liftCallEntry } from '../src/call-entry.mjs';
import { Unsupported } from '../src/core.mjs';

// This deliberately inventories a syntactic subset, not all calls or all
// changed behavior. A one-statement body has no analyzed prefix computation.
export function inspectCallEntryCandidates(text, filename) {
  const source = parseSource(text, filename), candidates = [];
  function visit(node, depth = 0) {
    if (depth > 128) throw new Unsupported('호출 후보 AST 깊이 제한 초과');
    if ((ts.isFunctionDeclaration(node) || ts.isFunctionExpression(node) || ts.isArrowFunction(node) || ts.isMethodDeclaration(node))
      && node.body && ts.isBlock(node.body)) {
      const last = node.body.statements.at(-1);
      if (last && ts.isExpressionStatement(last) && ts.isCallExpression(last.expression) && ts.isIdentifier(last.expression.expression)) {
        candidates.push({ callee: last.expression.expression.text, source: location(last.expression), body: location(node.body),
          prefixStatements: node.body.statements.length - 1 });
      }
    }
    ts.forEachChild(node, child => visit(child, depth + 1));
  }
  visit(source);
  return candidates.map(candidate => {
    try {
      const artifact = liftCallEntry(text, { callee: candidate.callee, line: candidate.source.line, filename });
      if (artifact.excludedCall.source.start !== candidate.source.start || artifact.excludedCall.source.end !== candidate.source.end) {
        throw new Error('Candidate selection reached a different call');
      }
      return { ...candidate, status: candidate.prefixStatements ? 'lowered-prefix' : 'empty-prefix',
        inputs: artifact.inputs, nativeVerified: false };
    } catch (error) {
      if (!(error instanceof Unsupported)) throw error;
      return { ...candidate, status: 'refused', reason: error.message, ...(error.location ? { refusalSource: error.location } : {}), nativeVerified: false };
    }
  });
}
