import ts from 'typescript';
import { stringIntrinsic, stringAssumptions } from './string-intrinsics.mjs';
import { Unsupported, VERSION, inputNames, ARRAY_PROFILE } from './core.mjs';
import { parseSource, lowerExpression, location, hash } from './typescript.mjs';
import { bindLocalSource, indexSliceBindings } from './bindings.mjs';
import { sourceContext } from './source-context.mjs';
import { ENGINE_SHA256 } from './fingerprint.mjs';

// Evaluate every declaration in a contiguous const region. The final record is
// an explicit observation of local values, not a generated object in the app.
export function liftConstBindings(sourceText, { startLine, endLine, outputs, filename = 'input.tsx', arrayProfile } = {}) {
  if (arrayProfile !== undefined && arrayProfile !== ARRAY_PROFILE) throw new Unsupported('알 수 없는 배열 의미 프로필');
  const arrays = arrayProfile === ARRAY_PROFILE;
  if (![startLine, endLine].every(value => Number.isSafeInteger(value) && value > 0) || endLine < startLine) throw new Unsupported('구간의 시작·끝은 순서에 맞는 양의 문장 시작 줄이어야 합니다.');
  if (!Array.isArray(outputs) || !outputs.length || outputs.length > 64 || outputs.some(name => typeof name !== 'string') || new Set(outputs).size !== outputs.length) throw new Unsupported('관찰할 변수 이름 1~64개를 중복 없이 지정해야 합니다.');
  const original = parseSource(sourceText, filename), matches = [];
  function find(node, depth = 0) {
    if (depth > 128) throw new Unsupported('const 구간 AST 깊이 제한 초과');
    if (ts.isVariableStatement(node) && location(node).line === startLine) matches.push(node);
    ts.forEachChild(node, child => find(child, depth + 1));
  }
  find(original);
  if (matches.length !== 1) throw new Unsupported('시작 줄은 const 문장 하나를 선택해야 합니다.');
  const bound = bindLocalSource(original, location(matches[0]));
  const { root: first, source, checker, symbol } = bound;
  const fail = (reason, node) => { throw new Unsupported(reason, node ? source(node) : undefined); };
  const block = first.parent;
  if (!ts.isBlock(block) && !ts.isSourceFile(block)) fail('const 구간은 한 블록의 직접 문장이어야 합니다.', first);
  const statements = [...block.statements], begin = statements.indexOf(first);
  const ends = statements.map((node, index) => ({ node, index })).filter(row => row.index >= begin && source(row.node).line === endLine);
  if (ends.length !== 1) fail('끝 줄은 같은 블록의 마지막 문장 시작 줄이어야 합니다.');
  const selected = statements.slice(begin, ends[0].index + 1), declarations = [];
  for (const statement of selected) {
    if (!ts.isVariableStatement(statement) || !(statement.declarationList.flags & ts.NodeFlags.Const)) fail('const 구간에 중간 문장을 생략하거나 다른 종류의 문장을 포함할 수 없습니다.', statement);
    for (const declaration of statement.declarationList.declarations) {
      if (!ts.isIdentifier(declaration.name) || !declaration.initializer) fail('이 구간은 초기값이 있는 단순 const 이름만 지원합니다.', declaration);
      if (declarations.length >= 64) fail('const 구간 선언 제한(64)을 초과했습니다.', declaration);
      declarations.push(declaration);
    }
  }
  const unique = name => {
    const binding = symbol(name);
    if (!binding || binding.declarations?.length !== 1 || checker.resolveName(name.text, name, ts.SymbolFlags.Value, false) !== binding) fail('const 선언의 바인딩을 하나로 결정할 수 없습니다.', name);
    return binding;
  };
  const selectedSymbols = new Set(declarations.map(declaration => unique(declaration.name)));
  const env = new Map(), names = new Map(), bindings = [];
  const stringOperations = new Set();
  function resolve(node) {
    const binding = symbol(node);
    if (env.has(binding)) return env.get(binding);
    if (selectedSymbols.has(binding)) fail('초기화 전 const를 입력으로 대체할 수 없습니다.', node);
    if (node.text === 'undefined' && !binding?.declarations?.length) return { kind: 'literal', value: { $value: 'undefined' }, source: source(node) };
    for (const declaration of binding?.declarations ?? []) {
      let statement = declaration;
      while (statement.parent && !ts.isStatement(statement)) statement = statement.parent;
      if (ts.isVariableStatement(statement) && (statement.declarationList.flags & ts.NodeFlags.BlockScoped) && statement.parent === block && declaration.getStart() >= node.getStart()) fail('뒤에 선언된 지역 값을 구간 입력으로 대신할 수 없습니다.', node);
    }
    return { kind: 'input', name: node.text, source: source(node) };
  }
  for (const declaration of declarations) {
    const value = lowerExpression(declaration.initializer, { resolve, records: true, arrays, sourceLocation: source, calls: (call, sub) => {
      if (ts.isPropertyAccessExpression(call.expression) && stringIntrinsic(`string.${call.expression.name.text}`) && !ts.isOptionalChain(call) && call.arguments.length === 0) {
        const name = `string.${call.expression.name.text}`;
        stringOperations.add(name);
        return { kind: 'intrinsic', name, value: sub(call.expression.expression), source: source(call) };
      }
      fail('const 구간의 호출은 원시 문자열의 표준 trim·toLowerCase에 한정합니다.', call);
    } });
    const name = `구간값${bindings.length + 1}`, label = declaration.name.text;
    bindings.push({ name, label, value, source: source(declaration), initializer: source(declaration.initializer) });
    const local = { kind: 'local', name, source: source(declaration.name) };
    env.set(unique(declaration.name), local);
    names.set(label, local);
  }
  for (const output of outputs) if (!names.has(output)) fail(`선택한 구간에서 초기화한 변수가 아닙니다: ${output}`);
  let remainingUses = 4096;
  const outputSources = outputs.map(name => {
    const declaration = declarations.find(item => item.name.text === name);
    const stored = indexSliceBindings(original, [], source(declaration.initializer), { ...bound, root: declaration.initializer }).storedResult;
    if (!stored) fail('관찰 변수의 선언을 소스 색인에서 찾지 못했습니다.', declaration);
    const uses = stored.uses.slice(0, remainingUses);
    remainingUses -= uses.length;
    return { ...stored, uses, usesTruncated: stored.usesTruncated || stored.useCount > uses.length };
  });
  let ir = { kind: 'record', projection: 'binding-values', properties: outputs.map(name => ({ name, value: names.get(name), source: names.get(name).source })), source: source(ends[0].node) };
  ir = bindings.reduceRight((body, binding) => ({ kind: 'let', ...binding, body }), ir);
  function rebase(node) {
    if (Array.isArray(node)) return node.map(rebase);
    if (!node || typeof node !== 'object') return node;
    return Object.fromEntries(Object.entries(node).map(([key, value]) => [key, key === 'file' && value === bound.file.fileName ? filename : rebase(value)]));
  }
  ir = rebase(ir);
  if (arrays) ir.valueProfile = ARRAY_PROFILE;
  let count = 0;
  const pending = [{ node: ir, depth: 0 }];
  while (pending.length) {
    const { node, depth } = pending.pop();
    if (++count > 65536 || depth > 128) fail('const 구간 IR의 크기·깊이 제한을 초과했습니다.');
    for (const value of Object.values(node)) {
      if (value?.kind) pending.push({ node: value, depth: depth + 1 });
      if (Array.isArray(value)) for (const item of value) {
        if (item?.kind) pending.push({ node: item, depth: depth + 1 });
        else if (item?.value?.kind) pending.push({ node: item.value, depth: depth + 1 });
      }
    }
  }
  return {
    schema: VERSION, mode: 'const-bindings-slice', engineSha256: ENGINE_SHA256, typescript: ts.version,
    source: { file: filename, sha256: hash(sourceText) }, target: { startLine, endLine, outputs, ...(arrays ? { arrayProfile } : {}) },
    ir, inputs: inputNames(ir), observationBindings: { schema: 'binding-values-1', names: outputs },
    outputSources: { scope: '관찰 변수의 선언·같은 원본 파일의 심볼 참조 색인; 사용 시점의 값·도달·부수 효과는 미검증', bindings: outputSources },
    prefix: { line: startLine, source: source(first), end: ends[0].node.end,
      bindings: bindings.map(({ label, source, initializer }) => ({ name: label, source, initializer })),
      contract: '선택한 const 구간을 중간 생략 없이 실행한 끝에서 명시한 변수 값을 관찰한다.' },
    context: sourceContext(first, source), bindings: indexSliceBindings(original, [{ condition: ir }], location(matches[0]), bound),
    contract: {
      observation: '선택한 const 구간 끝에서 명시한 변수들의 값 또는 구간 계산 중 TypeError; 결과 레코드는 보고용 관찰',
      assumptions: ['외부 식별자는 선택 구간 시작 지점의 스냅샷 값', '레코드 입력은 모든 자체 속성이 열거 가능한 null 프로토타입의 비순환 값 레코드; 계산 키는 원시 문자열', ...(arrays ? ['dense-standard-array-1: 비순환 값 트리의 배열은 빈칸·추가 속성·접근자·Proxy·하위 클래스 없는 표준 배열이며 Array와 Object의 프로토타입·filter·concat·species·isConcatSpreadable을 변경하지 않음', 'filter 콜백은 값을 변경하지 않는 동기식이며 외부 참조는 같은 입력 스냅샷; concat은 배열 인수만 지원; 원소 순서와 값은 관찰하지만 객체 동일성은 관찰하지 않음'] : []), ...stringAssumptions(stringOperations)],
      notProven: ['구간 도달·앞선 코드·모듈 초기화', '이후 객체 변경·별칭·프로토타입·getter·Proxy', '외부 요청·React·DOM·이벤트·서버 동작', '실제 tsconfig·타입의 런타임 유효성', '전체 변경과 사람의 이해도'],
    },
  };
}
