import ts from 'typescript';
import { Unsupported, VERSION } from './core.mjs';
import { parseSource, location, hash } from './typescript.mjs';
import { indexModules } from './module-index.mjs';
import { ENGINE_SHA256 } from './fingerprint.mjs';

// Resolve source bindings across a JSX boundary without executing React,
// a module initializer, hooks or any imported package.
export function indexComponentProps({ files, entry, tag, line, properties, context, includeAbsent = false }) {
  if (typeof includeAbsent !== 'boolean') throw new Unsupported('includeAbsent는 불리언이어야 합니다.');
  if (!files || typeof files !== 'object' || Array.isArray(files) || Object.keys(files).length > 32) throw new Unsupported('코드 파일은 32개 이하의 경로 매핑이어야 합니다.');
  if (!context || typeof context.configPath !== 'string' || !Array.isArray(context.inventory)) throw new Unsupported('원본 configPath와 전체 inventory 문맥이 필요합니다.');
  if (Object.keys(files).some(name => !/\.tsx?$/.test(name))) throw new Unsupported('코드 목록에는 TypeScript 원본만 지정해야 합니다.');
  if (!Array.isArray(properties) || !properties.length || properties.length > 64 || properties.some(name => typeof name !== 'string' || !name.length) || new Set(properties).size !== properties.length) throw new Unsupported('연결할 속성 이름 1~64개를 중복 없이 지정해야 합니다.');
  if (line !== undefined && (!Number.isSafeInteger(line) || line < 1)) throw new Unsupported('선택 줄은 양의 정수여야 합니다.');
  if (Object.keys(context?.metadata ?? {}).some(name => Object.hasOwn(files, name))) throw new Unsupported('코드와 설정 파일이 중복됩니다.');
  const moduleIndex = indexModules({ files: { ...(context?.metadata ?? {}), ...files },
    inventory: context?.inventory ?? Object.keys(files), configPath: context?.configPath });
  const sources = new Map(Object.entries(files).map(([name, text]) => ['/project/' + name, parseSource(text, '/project/' + name)]));
  const options = { ...moduleIndex.compilerOptions, noLib: true, noEmit: true, jsx: ts.JsxEmit.ReactJSX };
  const host = {
    getSourceFile: name => sources.get(name), getDefaultLibFileName: () => '/no-lib.d.ts', writeFile() {},
    getCurrentDirectory: () => '/project', getDirectories: () => [], fileExists: name => sources.has(name), readFile: name => sources.get(name)?.text,
    getCanonicalFileName: name => name, useCaseSensitiveFileNames: () => true, getNewLine: () => '\n',
    resolveModuleNames: (names, from) => names.map(name => {
      const edge = moduleIndex.edges.find(edge => edge.source.file === from && edge.specifier === name);
      return edge?.status === 'resolved-loaded' && sources.has(edge.target) ? {
        resolvedFileName: edge.target, extension: edge.target.endsWith('.tsx') ? ts.Extension.Tsx : ts.Extension.Ts, isExternalLibraryImport: false,
      } : undefined;
    }),
  };
  const checker = ts.createProgram([...sources.keys()], options, host).getTypeChecker();
  const file = sources.get('/project/' + entry);
  if (!file) throw new Unsupported('부모 JSX 파일이 제공되지 않았습니다.');
  const fail = (message, node) => { throw new Unsupported(message, node ? location(node) : undefined); };
  const matches = [];
  function visit(node, depth = 0) {
    if (depth > 128) fail('AST 깊이 제한 초과', node);
    if ((ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) && node.tagName.getText(file) === tag && (line === undefined || location(node).line === line)) matches.push(node);
    ts.forEachChild(node, child => visit(child, depth + 1));
  }
  visit(file);
  if (matches.length !== 1) fail(`부모 JSX 태그는 정확히 한 곳이어야 합니다: ${matches.length}곳`);
  const element = matches[0];
  if (!ts.isIdentifier(element.tagName) || /^[a-z]/.test(element.tagName.text)) fail('이름 있는 사용자 함수 컴포넌트만 연결합니다.', element.tagName);
  const tagSymbol = checker.getSymbolAtLocation(element.tagName);
  let resolved = tagSymbol;
  const seenAliases = new Set(), aliasChain = [];
  while (resolved?.flags & ts.SymbolFlags.Alias) {
    if (seenAliases.has(resolved) || seenAliases.size >= 32) fail('별칭 연결의 순환·깊이 제한 초과', element.tagName);
    seenAliases.add(resolved);
    for (const declaration of resolved.declarations ?? []) {
      if (ts.isTypeOnlyImportOrExportDeclaration(declaration)) fail('type-only import·export는 JSX 실행 값의 연결로 취급할 수 없습니다.', declaration);
      aliasChain.push(location(declaration));
    }
    resolved = checker.getImmediateAliasedSymbol(resolved);
  }
  const declaration = resolved?.valueDeclaration;
  if (!declaration || resolved.declarations?.length !== 1 || !sources.has(declaration.getSourceFile().fileName)) fail('제공된 원본에서 컴포넌트 선언을 하나로 결정할 수 없습니다.', element.tagName);
  let fn;
  if (ts.isFunctionDeclaration(declaration) && declaration.body) fn = declaration;
  else if (ts.isVariableDeclaration(declaration) && (declaration.parent.flags & ts.NodeFlags.Const) &&
    declaration.initializer && (ts.isArrowFunction(declaration.initializer) || ts.isFunctionExpression(declaration.initializer))) fn = declaration.initializer;
  else fail('직접 선언된 함수 컴포넌트만 지원합니다. wrapper·클래스·가변 함수는 미확인입니다.', declaration);
  if (fn.parameters.length !== 1 || !ts.isObjectBindingPattern(fn.parameters[0].name) || fn.parameters[0].initializer || fn.parameters[0].dotDotDotToken) fail('하나의 객체 구조 분해 매개변수만 지원합니다.', fn);
  const fields = fn.parameters[0].name.elements;
  const attributes = element.attributes.properties;
  if (attributes.some(ts.isJsxSpreadAttribute)) fail('spread가 속성을 추가·덮어쓸 수 있어 연결을 확정하지 못했습니다.', element);
  const connections = [];
  const identifiers = [];
  function collect(node, depth = 0) {
    if (depth > 128) fail('자식 참조 AST 깊이 제한 초과', node);
    if (ts.isIdentifier(node)) identifiers.push(node);
    ts.forEachChild(node, child => collect(child, depth + 1));
  }
  collect(fn);
  const owner = node => { for (let parent = node.parent; parent; parent = parent.parent) if (ts.isFunctionLike(parent)) return parent; return null; };
  function useOf(identifier) {
    const result = { source: location(identifier), nestedFunction: owner(identifier) !== fn };
    let expression = identifier;
    while (expression.parent && (ts.isParenthesizedExpression(expression.parent) || ts.isAsExpression(expression.parent) || ts.isNonNullExpression(expression.parent) || ts.isTypeAssertionExpression(expression.parent) || ts.isSatisfiesExpression(expression.parent))) expression = expression.parent;
    const writeParent = expression.parent;
    if ((ts.isBinaryExpression(writeParent) && writeParent.left === expression && writeParent.operatorToken.kind >= ts.SyntaxKind.FirstAssignment && writeParent.operatorToken.kind <= ts.SyntaxKind.LastAssignment) ||
        ((ts.isPrefixUnaryExpression(writeParent) || ts.isPostfixUnaryExpression(writeParent)) && [ts.SyntaxKind.PlusPlusToken, ts.SyntaxKind.MinusMinusToken].includes(writeParent.operator))) return { ...result, kind: 'write-reference', expression: location(writeParent) };
    let enclosingExpression = identifier;
    for (let parent = identifier.parent; parent && parent !== fn; parent = parent.parent) {
      if (ts.isTypeNode(parent)) return { ...result, kind: 'type-only' };
      if (ts.isJsxExpression(parent)) {
        if (ts.isJsxAttribute(parent.parent)) {
          const attribute = parent.parent, opening = attribute.parent.parent;
          return { ...result, kind: 'jsx-attribute', attribute: attribute.name.getText(),
            tag: opening.tagName.getText(), expression: location(parent.expression),
            direct: parent.expression === identifier };
        }
        return { ...result, kind: 'jsx-expression', expression: location(parent.expression) };
      }
      if (ts.isStatement(parent) || ts.isFunctionLike(parent)) break;
      if (ts.isExpressionNode(parent)) enclosingExpression = parent;
    }
    return { ...result, kind: 'other-reference', expression: location(enclosingExpression) };
  }
  let totalUses = 0;
  for (const name of properties) {
    if (['key', 'ref', 'children', '__proto__'].includes(name)) fail('React 특수 속성은 일반 매개변수 연결로 취급하지 않습니다.', element);
    const selectedAttributes = attributes.filter(attribute => ts.isJsxAttribute(attribute) && attribute.name.getText(file) === name);
    const selectedFields = fields.filter(field => ts.isIdentifier(field.name) &&
      (!field.propertyName ? field.name.text === name : (ts.isIdentifier(field.propertyName) || ts.isStringLiteral(field.propertyName)) && field.propertyName.text === name));
    if ((selectedAttributes.length !== 1 && !(includeAbsent && selectedAttributes.length === 0)) || selectedFields.length !== 1) fail(`속성 ${name}은 선택 가능한 JSX 속성과 단순 매개변수 바인딩에 각각 한 번 있어야 합니다.`, element);
    const attribute = selectedAttributes[0], field = selectedFields[0];
    if (field.dotDotDotToken) fail('rest 바인딩은 개별 속성 연결로 취급하지 않습니다.', field);
    const binding = checker.getSymbolAtLocation(field.name);
    if (!binding || binding.declarations?.length !== 1 || checker.resolveName(field.name.text, field.name, ts.SymbolFlags.Value, false) !== binding) fail('매개변수 바인딩이 모호합니다.', field);
    const uses = identifiers.filter(node => node !== field.name && (ts.isShorthandPropertyAssignment(node.parent) && node.parent.name === node
      ? checker.getShorthandAssignmentValueSymbol(node.parent) : checker.getSymbolAtLocation(node)) === binding);
    totalUses += uses.length;
    if (uses.length > 2048 || totalUses > 16384) fail('자식 매개변수의 참조 수 제한 초과', field);
    connections.push({ property: name, localName: field.name.text, provided: !!attribute, from: attribute ? location(attribute) : null,
      expression: attribute?.initializer ? location(ts.isJsxExpression(attribute.initializer) && attribute.initializer.expression ? attribute.initializer.expression : attribute.initializer) : null,
      to: location(field), status: attribute ? 'source-binding-linked' : 'source-omission-linked',
      ...(field.initializer ? { defaultInitializer: location(field.initializer), defaultScope: '받은 속성값이 undefined일 때 평가할 기본값 식의 소스; 실행 결과 미확인' } : {}),
      uses: uses.map(useOf) });
  }
  return { schema: VERSION, mode: 'component-prop-bindings', typescript: ts.version, engineSha256: ENGINE_SHA256,
    entry, target: { tag, line: location(element).line, source: location(element) }, properties, includeAbsent,
    component: { source: location(declaration), parameter: location(fn.parameters[0]), tagBinding: (tagSymbol.declarations ?? []).map(location), aliasChain },
    connections, moduleIndex, sources: [...sources.values()].map(file => ({ file: file.fileName, sha256: hash(file.text) })),
    contract: { observation: '고정된 프로젝트 설정으로 찾은 JSX 태그 선언과 선택 속성·매개변수의 소스 연결; 생략된 속성은 런타임 값으로 치환하지 않음',
      notProven: ['모듈 초기화와 런타임 태그 바인딩의 유지', 'JSX 속성 식의 실행 결과와 평가 순서', '매개변수 기본값 식의 실행·부수 효과', 'React 생성기·기본 속성·wrapper·실제 호출', 'hooks 이후의 입력 변경·재대입·캡처 참조의 실행 시점', '컴포넌트의 실행·반환·렌더링·상태 전이'] } };
}
