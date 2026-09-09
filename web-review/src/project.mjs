import ts from 'typescript';
import { stringIntrinsic, stringAssumptions } from './string-intrinsics.mjs';
import path from 'node:path';
import { Unsupported, VERSION, inputNames, evaluate, encode } from './core.mjs';
import { hash, lowerExpression, location, parseSource } from './typescript.mjs';
import { ENGINE_SHA256 } from './fingerprint.mjs';
import { indexModules } from './module-index.mjs';

const posix = path.posix;
const options = Object.freeze({ target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext,
  moduleResolution: ts.ModuleResolutionKind.Bundler, jsx: ts.JsxEmit.ReactJSX, noLib: true, noEmit: true, allowImportingTsExtensions: true });
const nil = () => ({ kind: 'literal', value: { $value: 'undefined' } });

// Closed, in-memory modules. No package code, module initializer, tsconfig
// plugin or host file is executed to determine the meaning of a name.
export function liftProject({ files, entry, functionName, context, isolation = 'closed-project' }) {
  if (!['closed-project', 'function-body'].includes(isolation)) throw new Unsupported('알 수 없는 함수 격리 범위');
  const bodyOnly = isolation === 'function-body';
  if (bodyOnly && (context || Object.keys(files ?? {}).length !== 1)) throw new Unsupported('함수 본문 모드는 원본 파일 하나만 받습니다.');
  if (!files || typeof files !== 'object' || Array.isArray(files) || Object.keys(files).length > 32) throw new Unsupported('프로젝트 파일 제한(32) 또는 형식 오류');
  const sources = new Map();
  let totalBytes = 0;
  for (const [name, source] of Object.entries(files)) {
    if (typeof source !== 'string' || !/^[^:\\]+\.tsx?$/.test(name) || posix.normalize(name) !== name || name.startsWith('/') || name.startsWith('../')) throw new Unsupported(`잘못된 프로젝트 경로: ${name}`);
    totalBytes += Buffer.byteLength(source);
    if (totalBytes > 4 * 1024 * 1024) throw new Unsupported('프로젝트 크기 제한(4 MiB) 초과');
    const filename = '/project/' + name;
    sources.set(filename, parseSource(source, filename));
  }
  let moduleIndex;
  if (context) {
    const metadata = context.metadata ?? {};
    if (Object.keys(metadata).some(name => Object.hasOwn(files, name))) throw new Unsupported('코드와 설정 파일 경로가 중복됩니다.');
    moduleIndex = indexModules({ files: { ...metadata, ...files }, inventory: context.inventory, configPath: context.configPath });
  }
  const checkerOptions = moduleIndex ? { ...moduleIndex.compilerOptions, noLib: true, noEmit: true } : options;
  const host = {
    getSourceFile: filename => sources.get(filename), getDefaultLibFileName: () => '/no-lib.d.ts',
    writeFile() {}, getCurrentDirectory: () => '/project', getDirectories: () => [],
    fileExists: name => sources.has(name), readFile: name => sources.get(name)?.text,
    getCanonicalFileName: name => name, useCaseSensitiveFileNames: () => true, getNewLine: () => '\n',
    directoryExists: name => [...sources.keys()].some(file => file.startsWith(name + '/')),
    ...(moduleIndex ? { resolveModuleNames: (names, from) => names.map(name => {
      const edge = moduleIndex.edges.find(e => e.source.file === from && e.specifier === name);
      if (edge?.status !== 'resolved-loaded' || !sources.has(edge.target)) return undefined;
      return { resolvedFileName: edge.target, extension: edge.target.endsWith('.tsx') ? ts.Extension.Tsx : ts.Extension.Ts, isExternalLibraryImport: false };
    }) } : {}),
  };
  const program = ts.createProgram([...sources.keys()], checkerOptions, host), checker = program.getTypeChecker();
  const moduleConstants = new Map(), declarations = new Set();
  const moduleEdges = [];
  const fail = (message, node) => { throw new Unsupported(message, node ? location(node) : undefined); };
  const symbol = node => {
    let result = checker.getSymbolAtLocation(node);
    for (const declaration of result?.declarations ?? []) {
      if (ts.isImportSpecifier(declaration) && (declaration.isTypeOnly || declaration.parent.parent.isTypeOnly)) fail('type-only import는 실행 값으로 사용할 수 없습니다.', node);
    }
    if (result?.flags & ts.SymbolFlags.Alias) result = checker.getAliasedSymbol(result);
    return result;
  };
  const uniqueSymbol = name => {
    const result = symbol(name);
    if (!result || result.declarations?.length !== 1 || checker.resolveName(name.text, name, ts.SymbolFlags.Value, false) !== result) fail('선언은 하나로 결정되어야 합니다.', name);
    return result;
  };
  for (const file of sources.values()) {
    for (const statement of file.statements) {
      if (bodyOnly) {
        if (ts.isFunctionDeclaration(statement) && statement.name?.text === functionName && statement.body) {
          uniqueSymbol(statement.name);
          declarations.add(statement);
        }
        continue;
      }
      if (ts.isImportDeclaration(statement)) {
        const clause = statement.importClause;
        if (!clause || clause.name || !clause.namedBindings || !ts.isNamedImports(clause.namedBindings) ||
            !ts.isStringLiteral(statement.moduleSpecifier) || (!moduleIndex && !statement.moduleSpecifier.text.startsWith('.'))) fail('명시한 지역 모듈의 이름 있는 import만 지원합니다.', statement);
        const module = checker.getSymbolAtLocation(statement.moduleSpecifier);
        if (!module?.declarations?.some(d => ts.isSourceFile(d) && sources.has(d.fileName))) fail('제공되지 않은 모듈입니다.', statement);
        for (const binding of clause.namedBindings.elements) {
          if (!clause.isTypeOnly && !binding.isTypeOnly && !symbol(binding.name)?.declarations?.length) fail('import 대상을 결정할 수 없습니다.', binding);
        }
        moduleEdges.push({ from: file.fileName, to: module.declarations[0].fileName, source: location(statement), typeOnly: !!clause.isTypeOnly });
        continue;
      }
      if (ts.isInterfaceDeclaration(statement) || ts.isTypeAliasDeclaration(statement) || ts.isEmptyStatement(statement)) continue;
      if (ts.isFunctionDeclaration(statement) && statement.name && statement.body) {
        const s = uniqueSymbol(statement.name);
        declarations.add(statement);
        if (s.valueDeclaration !== statement) fail('모호한 함수 선언', statement);
        continue;
      }
      if (ts.isVariableStatement(statement) && statement.declarationList.flags & ts.NodeFlags.Const) {
        for (const declaration of statement.declarationList.declarations) {
          if (!ts.isIdentifier(declaration.name) || !declaration.initializer) fail('모듈 상수는 이름과 초기값이 필요합니다.', declaration);
          const value = lowerExpression(declaration.initializer, { resolve: node => fail('모듈 초기화에서는 외부 이름을 읽을 수 없습니다.', node) });
          let constant;
          try { constant = encode(evaluate(value, {})); }
          catch { fail('모듈 상수 초기화는 오류 없는 상수식이어야 합니다.', declaration); }
          moduleConstants.set(uniqueSymbol(declaration.name), { kind: 'literal', value: constant, source: location(declaration) });
        }
        continue;
      }
      fail('모듈 초기화 또는 미지원 최상위 선언', statement);
    }
  }
  // Even pure-looking cycles complicate initialization order; reject them.
  const checkedModules = new Set();
  function checkCycles(file, stack = []) {
    if (stack.includes(file)) throw new Unsupported('순환 import는 지원하지 않습니다.');
    if (checkedModules.has(file)) return;
    for (const edge of moduleEdges.filter(e => e.from === file && !e.typeOnly)) checkCycles(edge.to, [...stack, file]);
    checkedModules.add(file);
  }
  for (const file of sources.keys()) checkCycles(file);
  let serial = 0, expansions = 0;
  const dependencies = [], references = [];
  function bindingElements(pattern) {
    if (!ts.isObjectBindingPattern(pattern) || !pattern.elements.length || pattern.elements.length > 64) fail('비어 있지 않은 객체 구조 분해(최대 64개)만 지원합니다.', pattern);
    return pattern.elements.map(element => {
      if (!ts.isIdentifier(element.name) || element.initializer || element.dotDotDotToken) fail('구조 분해는 기본값·중첩·나머지 속성이 없는 단순 이름만 지원합니다.', element);
      const keyNode = element.propertyName ?? element.name;
      if (!ts.isIdentifier(keyNode) && !ts.isStringLiteral(keyNode)) fail('구조 분해 속성은 고정 이름 또는 문자열이어야 합니다.', element);
      return { node: element, name: element.name, key: keyNode.text };
    });
  }
  function bindProperties(pattern, base, scope, bindings) {
    for (const element of bindingElements(pattern)) {
      const name = `값${++serial}`;
      const value = { kind: 'access', base, steps: [{ key: element.key, optional: false }], source: location(element.node) };
      scope.set(uniqueSymbol(element.name), { kind: 'local', name, source: location(element.name) });
      bindings.push({ name, label: element.name.text, value, bindingRole: 'destructured-property', bindingKey: element.key, source: location(element.node) });
    }
  }
  function expand(fn, argumentsIR, stack = []) {
    if (stack.includes(fn) || stack.length >= 32 || ++expansions > 4096) fail('재귀·호출 깊이·확장 제한을 초과했습니다.', fn);
    if (fn.asteriskToken || fn.modifiers?.some(m => [ts.SyntaxKind.AsyncKeyword, ts.SyntaxKind.DeclareKeyword].includes(m.kind))) fail('generator·async·declare 함수는 지원하지 않습니다.', fn);
    if (fn.parameters.length !== argumentsIR.length) fail('인수 개수가 정확히 일치해야 합니다.', fn);
    const env = new Map(), bindings = [];
    const parameterValues = [];
    // Call arguments are all evaluated before parameter destructuring begins.
    // Interleaving each argument with its property reads changes failure order.
    for (let i = 0; i < fn.parameters.length; i++) {
      const parameter = fn.parameters[i];
      if (parameter.initializer || parameter.dotDotDotToken || (ts.isIdentifier(parameter.name) && parameter.name.text === 'this')) fail('매개변수 기본값·나머지 인수·this 매개변수는 지원하지 않습니다.', parameter);
      if (!ts.isIdentifier(parameter.name)) bindingElements(parameter.name);
      const name = `값${++serial}`;
      const value = { kind: 'local', name, source: location(parameter.name) };
      parameterValues.push(value);
      if (ts.isIdentifier(parameter.name)) env.set(uniqueSymbol(parameter.name), value);
      bindings.push({ name, label: ts.isIdentifier(parameter.name) ? parameter.name.text : `인수 ${i + 1}`, value: argumentsIR[i], source: location(parameter) });
    }
    for (let i = 0; i < fn.parameters.length; i++) {
      if (!ts.isIdentifier(fn.parameters[i].name)) bindProperties(fn.parameters[i].name, parameterValues[i], env, bindings);
    }
    dependencies.push({ function: fn.name.text, source: location(fn) });
    const expr = (node, scope) => lowerExpression(node, {
      jsx: true,
      records: true,
      resolve: name => {
        const s = symbol(name);
        const result = scope.get(s) ?? moduleConstants.get(s);
        if (!result && name.text === 'undefined' && !checker.getSymbolAtLocation(name)?.declarations?.length) return { ...nil(), source: location(name) };
        if (!result) fail('선언되지 않았거나 아직 초기화되지 않은 값 또는 미지원 전역 이름', name);
        references.push({ name: name.text, use: location(name), definition: result.source });
        return result;
      },
      calls: (call, sub) => {
        if (ts.isPropertyAccessExpression(call.expression) && stringIntrinsic(`string.${call.expression.name.text}`) && !ts.isOptionalChain(call) && !call.arguments.length) {
          return { kind: 'intrinsic', name: `string.${call.expression.name.text}`, value: sub(call.expression.expression), source: location(call) };
        }
        if (bodyOnly) fail('함수 본문 밖의 함수 바인딩을 가정할 수 없습니다.', call);
        if (!ts.isIdentifier(call.expression) || call.questionDotToken || call.arguments.some(ts.isSpreadElement)) fail('일반 지역 함수의 직접 호출만 지원합니다.', call);
        const s = symbol(call.expression), target = s?.valueDeclaration;
        if (!target || !declarations.has(target) || s.declarations?.length !== 1) fail('호출 대상을 순수 함수 선언으로 결정할 수 없습니다.', call);
        references.push({ name: call.expression.text, use: location(call), definition: location(target) });
        return expand(target, call.arguments.map(sub), [...stack, fn]);
      },
    });
    function statements(items, scope, continuation, depth = 0) {
      if (depth > 128) fail('문장 중첩 제한을 초과했습니다.', fn);
      if (!items.length) return continuation;
      const [first, ...rest] = items;
      if (ts.isVariableStatement(first) && first.declarationList.flags & ts.NodeFlags.Const) {
        let updated = new Map(scope);
        const localBindings = [];
        for (const declaration of first.declarationList.declarations) {
          if (!declaration.initializer) fail('지역 const는 초기값이 필요합니다.', declaration);
          if (!ts.isIdentifier(declaration.name)) bindingElements(declaration.name);
          const value = expr(declaration.initializer, updated), name = `값${++serial}`;
          if (ts.isIdentifier(declaration.name)) {
            updated.set(uniqueSymbol(declaration.name), { kind: 'local', name, source: location(declaration.name) });
            localBindings.push({ name, label: declaration.name.text, value, source: location(declaration) });
          } else {
            localBindings.push({ name, label: '구조 분해 입력', value, source: location(declaration) });
            bindProperties(declaration.name, { kind: 'local', name, source: location(declaration) }, updated, localBindings);
          }
        }
        return localBindings.reduceRight((body, binding) => ({ kind: 'let', ...binding, body }), statements(rest, updated, continuation, depth + 1));
      }
      // Parse the continuation even after return: unsupported dead code is not
      // silently counted as supported project code.
      const tail = statements(rest, scope, continuation, depth + 1);
      if (ts.isReturnStatement(first)) return first.expression ? expr(first.expression, scope) : nil();
      if (ts.isBlock(first)) return statements([...first.statements], new Map(scope), tail, depth + 1);
      if (ts.isIfStatement(first)) {
        const branch = node => node ? statements(ts.isBlock(node) ? [...node.statements] : [node], new Map(scope), tail, depth + 1) : tail;
        return { kind: 'conditional', condition: expr(first.expression, scope), yes: branch(first.thenStatement), no: branch(first.elseStatement), source: location(first) };
      }
      if (ts.isEmptyStatement(first)) return tail;
      fail('순수 함수에서 미지원 문장입니다.', first);
    }
    const body = statements([...fn.body.statements], env, nil());
    return bindings.reduceRight((inner, binding) => ({ kind: 'let', ...binding, body: inner }), body);
  }
  const entryFile = sources.get('/project/' + entry);
  if (!entryFile) throw new Unsupported('진입 파일이 없습니다.');
  const module = checker.getSymbolAtLocation(entryFile);
  const exported = module && checker.getExportsOfModule(module).find(s => s.name === functionName);
  const fn = bodyOnly ? [...declarations][0] : exported?.valueDeclaration;
  if (!fn || !declarations.has(fn) || (bodyOnly && declarations.size !== 1)) throw new Unsupported(bodyOnly ? '이름이 일치하는 최상위 함수 선언 하나가 필요합니다.' : '진입점은 이름 있는 export 함수여야 합니다.');
  // Reject unsupported helpers as well, including uncalled ones.
  for (const declaration of declarations) expand(declaration, declaration.parameters.map(() => nil()));
  serial = 0; expansions = 0; dependencies.length = 0; references.length = 0;
  const inputLabels = new Set(fn.parameters.filter(p => ts.isIdentifier(p.name)).map(p => p.name.text));
  const parameterInputs = [];
  const args = fn.parameters.map((p, index) => {
    let name;
    if (ts.isIdentifier(p.name)) name = p.name.text;
    else {
      bindingElements(p.name);
      name = `인수${index + 1}`;
      while (inputLabels.has(name)) name += '_';
      inputLabels.add(name);
    }
    parameterInputs.push({ index, input: name, binding: ts.isIdentifier(p.name) ? 'identifier' : 'object-pattern', source: location(p.name) });
    return { kind: 'input', name, source: location(p) };
  });
  const ir = expand(fn, args);
  // Shared continuation subtrees can be small as a graph but enormous when
  // serialized. Bound the expanded tree, not just the number of source nodes.
  let nodeCount = 0;
  let hasJsx = false;
  const stringOperations = new Set();
  const pending = [{ node: ir, depth: 0 }];
  while (pending.length) {
    const { node, depth } = pending.pop();
    if (node.kind === 'jsx') hasJsx = true;
    if (node.kind === 'intrinsic' && stringIntrinsic(node.name)) stringOperations.add(node.name);
    if (++nodeCount > 65536 || depth > 128) throw new Unsupported('전개된 IR 크기·깊이 제한을 초과했습니다.');
    for (const value of Object.values(node)) {
      if (value && typeof value === 'object' && Object.hasOwn(value, 'kind')) pending.push({ node: value, depth: depth + 1 });
      if (Array.isArray(value)) for (const item of value) {
        if (item?.kind) pending.push({ node: item, depth: depth + 1 });
        else if (item?.value?.kind) pending.push({ node: item.value, depth: depth + 1 });
      }
    }
  }
  if (hasJsx) {
    if (checkerOptions.jsxFactory || checkerOptions.jsxFragmentFactory || checkerOptions.jsxImportSource || ![ts.JsxEmit.React, ts.JsxEmit.ReactJSX, ts.JsxEmit.ReactJSXDev].includes(checkerOptions.jsx)) throw new Unsupported('JSX 실행 문맥이 표준 React 생성 프로파일로 고정되지 않았습니다.');
    for (const file of sources.values()) {
      if (['jsx', 'jsxfrag', 'jsximportsource', 'jsxruntime'].some(key => file.pragmas?.has(key))) throw new Unsupported('파일별 JSX 런타임 pragma는 아직 지원하지 않습니다.');
    }
  }
  return {
    schema: VERSION, mode: bodyOnly ? 'function-body-slice' : 'closed-pure-project', typescript: ts.version, engineSha256: ENGINE_SHA256, compilerOptions: checkerOptions,
    entry, functionName, ir, inputs: inputNames(ir), parameterInputs,
    sources: [...sources.values()].map(file => ({ file: file.fileName, sha256: hash(file.text) })),
    dependencies, references, moduleEdges,
    ...(moduleIndex ? { moduleIndex } : {}),
    contract: {
      observation: bodyOnly ? '선택한 선언 본문을 명시한 입력과 표준 연산 환경에서 호출했을 때의 반환 데이터 또는 TypeError 발생' : hasJsx ? '순수 함수에서 생성할 기본 태그 JSX 구조·속성·자식 값 또는 TypeError 발생' : '명시한 모듈 집합의 순수 함수 반환 값 또는 TypeError 발생',
      inputDomain: '직접 전달한 스칼라·모든 자체 속성이 열거 가능한 null 프로토타입 값 레코드·명시한 불투명 객체 프로필; 계산한 속성 키는 원시 문자열; 타입 검사에서 유효성을 추론하지 않음',
      assumptions: ['불투명 객체 태그를 쓴 입력은 null이 아니고 참으로 취급되며 typeof가 object라는 가정', ...stringAssumptions(stringOperations), ...(hasJsx ? ['JSX는 표준 생성기가 정상 제공되는 환경의 구성값만 관찰'] : [])],
      notProven: [...(bodyOnly ? ['원본 모듈 초기화·주변 코드의 실행', '실제 export 바인딩·호출 경로가 이 선언을 사용한다는 사실'] : []), '일반 React 컴포넌트', 'React 렌더러·DOM·이벤트·라이프사이클', '프레임워크·브라우저·서버 동작', '제공되지 않은 외부 패키지·플러그인·배포 문맥', ...(moduleIndex ? [] : ['실제 프로젝트 tsconfig 해석']), '객체 동일성·프로토타입·속성 순서·객체 변환·배열'],
    },
  };
}
