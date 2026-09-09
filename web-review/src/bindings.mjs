import ts from 'typescript';
import { parseSource, location } from './typescript.mjs';
import { Unsupported } from './core.mjs';

// A source navigation index. Finding a declaration is NOT proof that its
// initializer's value still equals a later snapshot, or that a use executes.
export function bindLocalSource(original, rootLocation) {
  const filename = original.fileName;
  const file = parseSource(original.text, '/binding/original' + (filename.endsWith('.tsx') ? '.tsx' : '.ts'));
  const host = {
    getSourceFile: name => name === file.fileName ? file : undefined,
    getDefaultLibFileName: () => '/no-lib.d.ts', writeFile() {}, getCurrentDirectory: () => '/binding',
    getDirectories: () => [], fileExists: name => name === file.fileName, readFile: name => name === file.fileName ? file.text : undefined,
    getCanonicalFileName: name => name, useCaseSensitiveFileNames: () => true, getNewLine: () => '\n',
  };
  const program = ts.createProgram([file.fileName], { noLib: true, noEmit: true, noResolve: true, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX }, host);
  const checker = program.getTypeChecker();
  const source = node => ({ ...location(node), file: filename });
  const identifiers = [], bySpan = new Map();
  let root, visited = 0;
  function visit(node, depth = 0) {
    if (++visited > 400000 || depth > 128) throw new Unsupported('바인딩 색인의 AST 크기·깊이 제한 초과');
    if (node.getStart(file) === rootLocation.start && node.end === rootLocation.end) root = node;
    if (ts.isIdentifier(node)) { identifiers.push(node); bySpan.set(`${node.getStart(file)}:${node.end}`, node); }
    ts.forEachChild(node, child => visit(child, depth + 1));
  }
  visit(file);
  const symbol = node => ts.isShorthandPropertyAssignment(node.parent) && node.parent.name === node
    ? checker.getShorthandAssignmentValueSymbol(node.parent)
    : ts.isExportSpecifier(node.parent) ? (node === (node.parent.propertyName ?? node.parent.name) ? checker.getExportSpecifierLocalTargetSymbol(node) : undefined) : checker.getSymbolAtLocation(node);
  function declarationInfo(declaration) {
    const kind = ts.isVariableDeclaration(declaration) ? (declaration.parent.flags & ts.NodeFlags.Const ? 'const' : 'mutable-variable')
      : ts.isParameter(declaration) ? 'parameter' : ts.isBindingElement(declaration) ? 'destructured-binding'
      : [ts.SyntaxKind.ImportSpecifier, ts.SyntaxKind.ImportClause, ts.SyntaxKind.NamespaceImport].includes(declaration.kind) ? 'import-binding'
      : ts.isFunctionDeclaration(declaration) ? 'function' : ts.SyntaxKind[declaration.kind];
    const result = { kind, source: source(declaration), ...(declaration.initializer ? { initializer: source(declaration.initializer),
      initializerRole: ts.isBindingElement(declaration) || ts.isParameter(declaration) ? 'default-value' : 'declaration-initializer' } : {}) };
    if (ts.isBindingElement(declaration)) {
      // A binding element's initializer is its conditional default, not the
      // expression supplying the whole pattern. Keep both source locations.
      let owner = declaration, depth = 0;
      while (ts.isBindingElement(owner)) {
        if (++depth > 64) throw new Unsupported('구조 분해 원본 문맥의 깊이 제한 초과');
        owner = owner.parent.parent;
      }
      if (ts.isVariableDeclaration(owner) || ts.isParameter(owner)) {
        result.destructuringOrigin = {
          kind: ts.isParameter(owner) ? 'parameter-pattern' : ts.isCatchClause(owner.parent) ? 'catch-pattern' : 'variable-pattern',
          declaration: source(owner), pattern: source(owner.name), nestingDepth: depth, runtimeValueProven: false,
          ...(owner.initializer ? { expression: source(owner.initializer),
            expressionRole: ts.isParameter(owner) ? 'parameter-default' : 'declaration-initializer' } : {}),
        };
      }
    }
    return result;
  }
  return { file, checker, source, identifiers, bySpan, root, symbol, declarationInfo };
}

export function indexSliceBindings(original, guards, rootLocation, bound = bindLocalSource(original, rootLocation)) {
  const { file, checker, source, identifiers, bySpan, root, symbol, declarationInfo } = bound;
  const inputs = [], seen = new Set();
  function collect(node) {
    if (node.kind === 'input') {
      const key = `${node.source.start}:${node.source.end}`;
      if (seen.has(key)) return;
      seen.add(key);
      const identifier = bySpan.get(key), binding = identifier && symbol(identifier);
      const declarations = binding?.declarations ?? [];
      inputs.push({ name: node.name, use: node.source,
        status: declarations.length === 1 ? 'declaration-found' : declarations.length ? 'ambiguous-declaration' : 'unresolved-in-file',
        declarations: declarations.slice(0, 32).map(declarationInfo), declarationsTruncated: declarations.length > 32 });
    }
    for (const value of Object.values(node)) {
      if (value?.kind) collect(value);
      if (Array.isArray(value)) for (const item of value) {
        if (item?.kind) collect(item);
        else if (item?.value?.kind) collect(item.value);
      }
    }
  }
  for (const guard of guards) collect(guard.condition);
  const owner = node => { for (let parent = node.parent; parent; parent = parent.parent) if (ts.isFunctionLike(parent)) return parent; return file; };
  function useKind(node) {
    for (let parent = node.parent; parent && !ts.isStatement(parent); parent = parent.parent) if (ts.isTypeNode(parent)) return 'type-only';
    const parent = node.parent;
    if (ts.isExportSpecifier(parent)) return 'export-reference';
    if (ts.isJsxExpression(parent) && ts.isJsxAttribute(parent.parent)) return 'jsx-attribute';
    if (ts.isJsxExpression(parent) && (ts.isJsxElement(parent.parent) || ts.isJsxFragment(parent.parent))) return 'jsx-child';
    if (ts.isBinaryExpression(parent)) {
      if ([ts.SyntaxKind.AmpersandAmpersandToken, ts.SyntaxKind.BarBarToken, ts.SyntaxKind.QuestionQuestionToken].includes(parent.operatorToken.kind)) return 'condition-value';
      if (parent.left === node && parent.operatorToken.kind >= ts.SyntaxKind.FirstAssignment && parent.operatorToken.kind <= ts.SyntaxKind.LastAssignment) return 'write-reference';
    }
    if (ts.isPrefixUnaryExpression(parent) || ts.isPostfixUnaryExpression(parent)) {
      if ([ts.SyntaxKind.PlusPlusToken, ts.SyntaxKind.MinusMinusToken].includes(parent.operator)) return 'write-reference';
    }
    if (ts.isReturnStatement(parent)) return 'return-value';
    if (ts.isCallExpression(parent) && parent.arguments.includes(node)) return 'call-argument';
    if (ts.isShorthandPropertyAssignment(parent)) return 'object-shorthand';
    return 'other-reference';
  }
  let storedResult;
  if (root && ts.isVariableDeclaration(root.parent) && root.parent.initializer === root && ts.isIdentifier(root.parent.name)) {
    const declaration = root.parent, binding = checker.getSymbolAtLocation(declaration.name);
    const unambiguous = binding?.declarations?.length === 1;
    const uses = unambiguous ? identifiers.filter(node => node !== declaration.name && symbol(node) === binding) : [];
    storedResult = { name: declaration.name.text, declaration: declarationInfo(declaration),
      status: unambiguous ? 'declaration-found' : 'ambiguous-declaration',
      uses: uses.slice(0, 2048).map(node => {
        const kind = useKind(node);
        const attribute = kind === 'jsx-attribute' ? node.parent.parent : undefined;
        return { source: source(node), kind, nestedFunction: owner(node) !== owner(declaration),
          ...(attribute ? { tag: attribute.parent.parent.tagName.getText(file), attribute: attribute.name.getText(file), direct: true, element: source(attribute.parent.parent) } : {}) };
      }),
      useCount: unambiguous ? uses.length : null, usesTruncated: uses.length > 2048 };
  }
  return { scope: '한 원본 파일의 TypeScript 선언·참조 연결; 실행 경로·값 불변·수정 효과는 미검증', inputs,
    ...(storedResult ? { storedResult } : {}),
    notProven: ['외부 import의 실제 정의', '초기화 이후 객체 변경·시간에 따른 값', '참조 지점의 도달·실제 반환·렌더링'] };
}
