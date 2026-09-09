import ts from 'typescript';
import { Unsupported } from './core.mjs';
import { lowerExpression, location } from './typescript.mjs';

// Execute an explicitly selected contiguous const prefix in source order.
// Never replace a snapshot by re-running its initializer at a later time.
export function prependConstPrefix(ir, line, bound, filename, { rootValue } = {}) {
  const { root, checker, bySpan, symbol, source } = bound;
  const fail = (reason, node) => { throw new Unsupported(reason, node ? source(node) : undefined); };
  if (!Number.isSafeInteger(line) || line < 1) fail('prefix 시작 줄은 양의 정수여야 합니다.');
  let finalStatement = root?.parent;
  if (finalStatement && ts.isVariableDeclaration(finalStatement)) finalStatement = finalStatement.parent.parent;
  if (!finalStatement || !ts.isStatement(finalStatement) || (!ts.isBlock(finalStatement.parent) && !ts.isSourceFile(finalStatement.parent))) fail('prefix는 같은 블록의 변수 초기화 또는 return 식에만 연결할 수 있습니다.', root);
  const block = finalStatement.parent, statements = [...block.statements], end = statements.indexOf(finalStatement);
  const starts = statements.map((node, index) => ({ node, index })).filter(item => source(item.node).line === line && item.index <= end);
  if (starts.length !== 1) fail('prefix 시작 줄은 대상 앞의 문장 하나를 정확히 가리켜야 합니다.');
  const selected = statements.slice(starts[0].index, end + 1), declarations = [];
  for (const statement of selected) {
    if (statement === finalStatement && ts.isReturnStatement(statement)) break;
    if (!ts.isVariableStatement(statement) || !(statement.declarationList.flags & ts.NodeFlags.Const)) fail('prefix 구간은 중간 생략 없는 const 선언만 지원합니다.', statement);
    for (const declaration of statement.declarationList.declarations) {
      if (declaration.initializer === root) break;
      if (!ts.isIdentifier(declaration.name) || !declaration.initializer) fail('prefix는 단순 이름과 초기값이 있는 const만 지원합니다.', declaration);
      declarations.push(declaration);
    }
  }
  if ((!declarations.length && !rootValue) || declarations.length + (rootValue ? 1 : 0) > 64) fail('prefix는 const 1~64개가 필요합니다.');
  const env = new Map(), bindings = [];
  const unique = node => {
    const binding = checker.getSymbolAtLocation(node);
    if (!binding || binding.declarations?.length !== 1 || checker.resolveName(node.text, node, ts.SymbolFlags.Value, false) !== binding) fail('prefix 선언은 하나로 결정되어야 합니다.', node);
    return binding;
  };
  const upcoming = new Set(declarations.map(declaration => unique(declaration.name)));
  if (ts.isVariableDeclaration(root.parent)) {
    if (!ts.isIdentifier(root.parent.name)) fail('대상 표현식의 저장 변수는 단순 이름이어야 합니다.', root.parent);
    upcoming.add(unique(root.parent.name));
  }
  function resolve(node) {
    const binding = symbol(node);
    if (env.has(binding)) return { ...env.get(binding), source: source(node) };
    if (upcoming.has(binding)) fail('초기화 전 지역 값 읽기는 지원하지 않습니다.', node);
    for (const declaration of binding?.declarations ?? []) {
      let statement = declaration;
      while (statement.parent && !ts.isStatement(statement)) statement = statement.parent;
      if (ts.isVariableStatement(statement) && statement.parent === block && declaration.getStart() >= node.getStart()) fail('뒤에 선언된 지역 값을 입력으로 대체할 수 없습니다.', node);
    }
    return { kind: 'input', name: node.text, source: source(node) };
  }
  for (const declaration of declarations) {
    const value = lowerExpression(declaration.initializer, { resolve });
    const name = `선행값${bindings.length + 1}`;
    bindings.push({ name, label: declaration.name.text, value, source: source(declaration), initializer: source(declaration.initializer) });
    env.set(unique(declaration.name), { kind: 'local', name, source: source(declaration.name) });
  }
  function substitute(node) {
    if (node?.kind === 'input') {
      const original = bySpan.get(`${node.source.start}:${node.source.end}`);
      if (!original) fail('조건 입력의 원본 식별자를 찾을 수 없습니다.');
      return resolve(original);
    }
    if (Array.isArray(node)) return node.map(substitute);
    if (!node || typeof node !== 'object') return node;
    return Object.fromEntries(Object.entries(node).map(([key, value]) => [key, substitute(value)]));
  }
  if (rootValue) {
    if (!ts.isVariableDeclaration(root.parent) || !ts.isIdentifier(root.parent.name)) fail('생성 값의 저장 선언이 필요합니다.', root);
    const declaration = root.parent, value = substitute(rootValue), name = `선행값${bindings.length + 1}`;
    bindings.push({ name, label: declaration.name.text, value, source: source(declaration), initializer: source(root), projection: 'jsx-object-or-null' });
    env.set(unique(declaration.name), { kind: 'local', name, source: source(declaration.name) });
  }
  let result = substitute(ir);
  result = bindings.reduceRight((body, binding) => ({ kind: 'let', name: binding.name, label: binding.label, value: binding.value, source: binding.source, body }), result);
  function rebase(node) {
    if (Array.isArray(node)) return node.map(rebase);
    if (!node || typeof node !== 'object') return node;
    return Object.fromEntries(Object.entries(node).map(([key, value]) => [key, key === 'file' && value === bound.file.fileName ? filename : rebase(value)]));
  }
  return { ir: rebase(result), prefix: { line, source: source(starts[0].node), end: location(root).start,
    bindings: bindings.map(({ label, source, initializer, projection }) => ({ name: label, source, initializer, ...(projection ? { projection } : {}) })),
    contract: '명시한 시작 문장부터 const 초기화를 순서대로 실행한다. 다른 입력은 시작 지점의 스냅샷이다. 시작점 이전 실행은 확인하지 않는다.' } };
}
