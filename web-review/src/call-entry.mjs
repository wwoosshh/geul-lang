import ts from 'typescript';
import { stringIntrinsic, stringAssumptions } from './string-intrinsics.mjs';
import { Unsupported, VERSION, inputNames } from './core.mjs';
import { parseSource, location, lowerExpression, hash } from './typescript.mjs';
import { bindLocalSource, indexSliceBindings } from './bindings.mjs';
import { ENGINE_SHA256 } from './fingerprint.mjs';
import { indexCallEntryLinks } from './call-entry-links.mjs';

// A synchronous function body's pure prefix, ending BEFORE evaluation of a
// selected final call expression. This models input-validation control flow;
// it does not invoke the callee, evaluate its arguments or model an effect.
export function liftCallEntry(sourceText, options) { return liftCallBoundary(sourceText, options, false); }
export function liftCallArguments(sourceText, options) { return liftCallBoundary(sourceText, options, true); }

function liftCallBoundary(sourceText, { callee, line, filename = 'input.tsx' } = {}, includeArguments) {
  if (typeof callee !== 'string' || !callee.length || callee.length > 256) throw new Unsupported('호출 이름을 1~256자로 지정하세요.');
  if (line !== undefined && (!Number.isSafeInteger(line) || line < 1)) throw new Unsupported('호출 줄은 양의 정수여야 합니다.');
  const original = parseSource(sourceText, filename), matches = [];
  function find(node, depth = 0) {
    if (depth > 128) throw new Unsupported('호출 진입 AST 깊이 제한 초과');
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === callee
      && (line === undefined || location(node).line === line)) matches.push(node);
    ts.forEachChild(node, child => find(child, depth + 1));
  }
  find(original);
  if (matches.length !== 1) throw new Unsupported(`호출 지점은 정확히 한 곳이어야 합니다: ${matches.length}곳`);
  const bound = bindLocalSource(original, location(matches[0]));
  const { root: call, source, symbol, checker } = bound;
  const fail = (reason, node = call) => { throw new Unsupported(reason, source(node)); };
  if (!ts.isCallExpression(call) || ts.isOptionalChain(call)) fail('일반 직접 호출 지점만 지원합니다.');
  const targetStatement = call.parent, block = targetStatement?.parent, owner = block?.parent;
  if (!ts.isExpressionStatement(targetStatement) || targetStatement.expression !== call || !ts.isBlock(block)
    || !(ts.isFunctionDeclaration(owner) || ts.isFunctionExpression(owner) || ts.isArrowFunction(owner) || ts.isMethodDeclaration(owner))
    || owner.body !== block) fail('대상은 함수 본문 블록의 직접 호출 문장이어야 합니다.');
  if (owner.asteriskToken || owner.modifiers?.some(item => item.kind === ts.SyntaxKind.AsyncKeyword)) fail('async·generator 함수의 진입은 지원하지 않습니다.', owner);
  if (block.statements.at(-1) !== targetStatement) fail('대상은 본문의 마지막 문장이어야 합니다. 뒤의 코드를 생략하지 않습니다.');
  if (includeArguments && (call.arguments.length > 32 || call.arguments.some(ts.isSpreadElement))) fail('호출 인수 관찰은 spread 없는 인수 32개까지 지원합니다.');
  const prefix = [...block.statements].slice(0, -1), selectedSymbols = new Set(), returns = [], bindings = [];
  let statements = 0, declarations = 0, generated = 0;
  const stringOperations = new Set();
  const unique = name => {
    const binding = symbol(name);
    if (!binding || binding.declarations?.length !== 1 || checker.resolveName(name.text, name, ts.SymbolFlags.Value, false) !== binding) fail('지역 선언은 하나로 결정되어야 합니다.', name);
    return binding;
  };
  function scan(node, depth = 0) {
    if (++statements > 128 || depth > 32) fail('호출 앞 문장 수·중첩 제한 초과', node);
    if (ts.isVariableStatement(node) && (node.declarationList.flags & ts.NodeFlags.Const)) {
      for (const declaration of node.declarationList.declarations) {
        if (++declarations > 64 || !ts.isIdentifier(declaration.name) || !declaration.initializer) fail('초기값 있는 단순 const 이름 64개까지 지원합니다.', declaration);
        selectedSymbols.add(unique(declaration.name));
        bindings.push({ name: declaration.name.text, source: source(declaration), initializer: source(declaration.initializer) });
      }
    } else if (ts.isIfStatement(node)) {
      scan(node.thenStatement, depth + 1); if (node.elseStatement) scan(node.elseStatement, depth + 1);
    } else if (ts.isBlock(node)) for (const item of node.statements) scan(item, depth + 1);
    else if (ts.isReturnStatement(node) && !node.expression) returns.push(source(node));
    else if (!ts.isEmptyStatement(node)) fail('호출 앞은 const·if·블록·값 없는 return만 지원합니다. 문장을 건너뛰지 않습니다.', node);
  }
  prefix.forEach(node => scan(node));
  function expression(node, env) {
    return lowerExpression(node, { records: true, sourceLocation: source, resolve: identifier => {
      const binding = symbol(identifier);
      if (env.has(binding)) return { ...env.get(binding), source: source(identifier) };
      if (selectedSymbols.has(binding)) fail('초기화 전 지역 값을 외부 입력으로 대체할 수 없습니다.', identifier);
      if (identifier.text === 'undefined' && !binding?.declarations?.length) return { kind: 'literal', value: { $value: 'undefined' }, source: source(identifier) };
      return { kind: 'input', name: identifier.text, source: source(identifier) };
    }, calls: (invocation, sub) => {
      if (ts.isPropertyAccessExpression(invocation.expression) && stringIntrinsic(`string.${invocation.expression.name.text}`)
        && !ts.isOptionalChain(invocation) && invocation.arguments.length === 0) {
        const name = `string.${invocation.expression.name.text}`;
        stringOperations.add(name);
        return { kind: 'intrinsic', name, value: sub(invocation.expression.expression), source: source(invocation) };
      }
      fail('선행 식 호출은 원시 문자열의 표준 trim·toLowerCase만 지원합니다.', invocation);
    } });
  }
  const literal = (value, node) => ({ kind: 'literal', value, source: source(node) });
  function argumentObservation(stage, node, argumentsIR = []) {
    return { kind: 'record', projection: 'call-argument-values', source: source(node), properties: [
      ...argumentsIR.map((value, index) => ({ name: `argument${index + 1}`, value, source: source(call.arguments[index]) })),
      // Emit readiness only AFTER all argument values finish. An error in a
      // later argument must not leave a misleading ready event in the trace.
      { name: 'stage', value: literal(stage, node), source: source(node) },
    ] };
  }
  function sequence(items, env, continuation, depth = 0) {
    if (depth > 128) fail('호출 진입 계산 깊이 제한 초과');
    if (!items.length) return typeof continuation === 'function' ? continuation(env) : continuation;
    const [first, ...rest] = items;
    if (ts.isVariableStatement(first)) {
      const updated = new Map(env), bindings = [];
      for (const declaration of first.declarationList.declarations) {
        const value = expression(declaration.initializer, updated), name = `진입값${++generated}`;
        bindings.push({ name, label: declaration.name.text, value, source: source(declaration) });
        updated.set(unique(declaration.name), { kind: 'local', name, source: source(declaration.name) });
      }
      return bindings.reduceRight((body, binding) => ({ kind: 'let', ...binding, body }), sequence(rest, updated, continuation, depth + 1));
    }
    // Validate/lower even unreachable suffixes. A return must not conceal an
    // unsupported call, assignment or an invalid local binding later on.
    const tail = sequence(rest, env, continuation, depth + 1);
    if (ts.isReturnStatement(first)) return includeArguments ? argumentObservation('early-return', first) : literal(false, first);
    if (ts.isBlock(first)) return sequence([...first.statements], new Map(env), tail, depth + 1);
    if (ts.isIfStatement(first)) {
      const branch = node => node ? sequence(ts.isBlock(node) ? [...node.statements] : [node], new Map(env), tail, depth + 1) : tail;
      return { kind: 'conditional', condition: expression(first.expression, env), yes: branch(first.thenStatement), no: branch(first.elseStatement), source: source(first) };
    }
    return tail; // Empty statement; all other statement kinds were refused.
  }
  let ir = sequence(prefix, new Map(), includeArguments
    ? env => argumentObservation('arguments-ready', call, call.arguments.map(argument => expression(argument, env)))
    : literal(true, call));
  function rebase(node) {
    if (Array.isArray(node)) return node.map(rebase);
    if (!node || typeof node !== 'object') return node;
    return Object.fromEntries(Object.entries(node).map(([key, value]) => [key, key === 'file' && value === bound.file.fileName ? filename : rebase(value)]));
  }
  // Count expanded occurrences, not only unique DAG nodes, before serializing
  // continuations copied into several branches.
  let count = 0;
  const pending = [{ node: ir, depth: 0 }];
  while (pending.length) {
    const { node, depth } = pending.pop();
    if (++count > 65536 || depth > 128) fail('호출 진입 IR 크기·깊이 제한 초과');
    for (const value of Object.values(node)) {
      if (value?.kind) pending.push({ node: value, depth: depth + 1 });
      if (Array.isArray(value)) for (const item of value) {
        if (item?.kind) pending.push({ node: item, depth: depth + 1 });
        else if (item?.value?.kind) pending.push({ node: item.value, depth: depth + 1 });
      }
    }
  }
  ir = rebase(ir);
  return {
    schema: VERSION, mode: includeArguments ? 'call-arguments-slice' : 'call-entry-slice', engineSha256: ENGINE_SHA256, typescript: ts.version,
    source: { file: filename, sha256: hash(sourceText) }, target: { callee, line: source(call).line },
    functionBody: source(block), entryRegion: { source: prefix.length ? source(prefix[0]) : null, end: call.getStart(), bindings },
    ...(includeArguments ? { preparedCall: { source: source(call), callee: source(call.expression), arguments: call.arguments.map(source),
      argumentNames: call.arguments.map((_, index) => `argument${index + 1}`), calleeEvaluatedByIR: false, invokedByIR: false } }
      : { excludedCall: { source: source(call), callee: source(call.expression), arguments: call.arguments.map(source), evaluated: false } }),
    earlyReturns: returns, ir, inputs: inputNames(ir),
    sourceLinks: indexCallEntryLinks(bound, owner, call),
    bindings: indexSliceBindings(original, [{ condition: ir }], location(matches[0]), bound),
    contract: {
      observation: includeArguments
        ? '동기 함수 본문 시작 스냅샷에서 순수 선행 구간과 마지막 호출의 순수 인수 식을 계산한다. 조기 반환 또는 준비한 인수별 값 또는 선행·인수 TypeError를 관찰한다. 결과 레코드는 보고용이며 함수의 실제 반환값이 아니다.'
        : '동기 함수 본문 시작 스냅샷에서 순수 선행 문장을 계산해 마지막 호출 식 평가 직전에 도달하는지 여부 또는 선행 TypeError. 참·거짓은 도달 여부이며 함수의 실제 반환값이 아니다.',
      assumptions: ['외부 식별자는 함수 본문 시작 지점의 입력 스냅샷', '레코드 입력은 getter·Proxy·별칭·외부 변경 없는 값 레코드',
        ...(includeArguments ? ['선택 callee 식별자의 값 읽기는 순수하게 정상 완료한다고 가정하며, 그 읽기를 IR에서 실행하지 않는다. 인수는 이 읽기 이후에 평가되는 범위다.'] : []),
        ...stringAssumptions(stringOperations)],
      notProven: ['이 본문을 가진 함수의 호출 여부와 본문 시작 전 인수·매개변수 초기화',
        includeArguments ? '선택 callee 식별자의 실제 값 읽기·호출 가능성·호출 실행·반환' : '선택한 호출의 callee·인수 평가·호출 가능성·실행·반환',
        ...(includeArguments ? ['인수 값 스냅샷 사이의 참조 동일성·별칭과 호출 후 변경 관계'] : []),
        '이벤트·상태 변경·외부 요청·React·DOM', '실제 앱에서 입력의 도달 가능성·전체 변경·사람 검토 성과'],
    },
  };
}
