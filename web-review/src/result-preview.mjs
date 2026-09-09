import path from 'node:path';
import ts from 'typescript';
import { indexFunctionResult } from './function-results.mjs';
import { liftProject } from './project.mjs';
import { observe, inputNames, VERSION, Unsupported } from './core.mjs';
import { parseSource, lowerExpression } from './typescript.mjs';

// A parameter-input experiment plus a source index, not execution of the
// surrounding caller. Preserve the original body's IR when reading its result:
// encoding/decoding it first would erase the constructed-record prototype limit.
function buildFunctionResultModel(source, { functionName, line, filename = 'input.tsx', inputBoundary = 'function-parameters' } = {}) {
  if (!['function-parameters', 'call-arguments'].includes(inputBoundary)) throw new Unsupported('알 수 없는 입력 경계');
  const index = indexFunctionResult(source, { functionName, line, filename });
  const entry = path.basename(filename);
  const body = { ...liftProject({ files: { [entry]: source }, entry, functionName, isolation: 'function-body' }), sourceFile: filename };
  const selected = body.dependencies.find(row => row.function === functionName)?.source;
  if (!selected || selected.start !== index.functionDeclaration.start || selected.end !== index.functionDeclaration.end || body.sources.length !== 1 || body.sources[0].sha256 !== index.source.sha256 || body.engineSha256 !== index.engineSha256) throw new Unsupported('함수 계산과 결과 연결의 원본 선언이 일치하지 않습니다.');
  let executionIR = body.ir;
  if (inputBoundary === 'call-arguments') {
    if (index.arguments.length !== body.parameterInputs.length || index.arguments.length > 64) throw new Unsupported('호출 인수 계산은 매개변수와 정확히 대응하는 인수 0~64개에 한정합니다.');
    if (index.otherFunctionReferences.length) throw new Unsupported('함수의 별칭·대입 등 직접 호출 밖 참조가 있으면 호출 구간으로 연결하지 않습니다.');
    const file = parseSource(source, filename), nodes = new Map();
    const wanted = new Set(index.arguments.map(row => `${row.expression.start}:${row.expression.end}`));
    function visit(node, depth = 0) {
      if (depth > 128) throw new Unsupported('호출 인수 AST 깊이 제한 초과');
      const key = `${node.getStart(file)}:${node.end}`;
      if (wanted.has(key) && ts.isExpressionNode(node)) nodes.set(key, node);
      ts.forEachChild(node, child => visit(child, depth + 1));
    }
    visit(file);
    const bindings = index.arguments.map((argument, i) => {
      const node = nodes.get(`${argument.expression.start}:${argument.expression.end}`);
      if (!node) throw new Unsupported('호출 인수의 원본 식을 찾지 못했습니다.');
      return { name: `검토인수${i + 1}`, label: body.parameterInputs[i].input, value: lowerExpression(node, { records: true }),
        bindingRole: 'call-argument', argumentIndex: i, source: argument.expression };
    });
    const replacements = new Map(body.parameterInputs.map((parameter, i) => [parameter.input,
      { kind: 'local', name: bindings[i].name, source: bindings[i].source }]));
    function substitute(node) {
      if (node?.kind === 'input') {
        const replacement = replacements.get(node.name);
        if (!replacement) throw new Unsupported('함수 매개변수 밖 입력을 호출 인수로 대체할 수 없습니다.');
        return { ...replacement, source: node.source };
      }
      if (Array.isArray(node)) return node.map(substitute);
      if (!node || typeof node !== 'object') return node;
      return Object.fromEntries(Object.entries(node).map(([key, value]) => [key, substitute(value)]));
    }
    // Argument expressions all run left-to-right before parameter binding and
    // destructuring. Replacing parameters by expressions inline would duplicate
    // reads and change both order and errors for unused arguments.
    executionIR = bindings.reduceRight((inner, binding) => ({ kind: 'let', ...binding, body: inner }), substitute(body.ir));
  }
  const resultName = '검토반환값', value = { kind: 'local', name: resultName, source: index.resultDeclaration };
  // The result of an object binding is read once per element, in source order.
  // No property of a returned object is assumed to be frozen at a later use.
  const fields = index.connections.map((connection, i) => ({ name: `binding${i + 1}`,
    value: connection.property === null ? value : { kind: 'access', base: value, steps: [{ key: connection.property, optional: false }], source: connection.declaration },
    source: connection.declaration }));
  const bindingIR = { kind: 'let', name: resultName, value: executionIR,
    body: { kind: 'record', projection: 'binding-values', properties: fields, source: index.resultDeclaration }, source: index.resultDeclaration };
  let nodeCount = 0;
  const pending = [{ node: bindingIR, depth: 0 }];
  while (pending.length) {
    const { node, depth } = pending.pop();
    if (++nodeCount > 65536 || depth > 128) throw new Unsupported('호출·결과 결합 IR의 크기·깊이 제한을 초과했습니다.');
    for (const value of Object.values(node)) {
      if (value?.kind) pending.push({ node: value, depth: depth + 1 });
      if (Array.isArray(value)) for (const item of value) {
        if (item?.kind) pending.push({ node: item, depth: depth + 1 });
        else if (item?.value?.kind) pending.push({ node: item.value, depth: depth + 1 });
      }
    }
  }
  return { index, body, inputBoundary, executionIR, bindingIR };
}

export function liftCallBindings(source, options = {}) {
  const { index, body, bindingIR } = buildFunctionResultModel(source, { ...options, inputBoundary: 'call-arguments' });
  const outputs = index.connections.map(row => row.localName);
  const ir = { ...bindingIR, body: { ...bindingIR.body, projection: 'binding-values',
    properties: bindingIR.body.properties.map((property, i) => ({ ...property, name: outputs[i] })) } };
  return {
    schema: VERSION, mode: 'call-bindings-slice', engineSha256: index.engineSha256, typescript: index.typescript,
    source: index.source, sourceFile: index.source.file, sources: body.sources,
    target: index.target, ir, inputs: inputNames(ir), observationBindings: { schema: 'binding-values-1', names: outputs },
    index, functionBody: body,
    contract: {
      observation: '선택한 직접 호출의 인수·함수 본문·결과 바인딩을 계산한 직후의 변수 값; 결과 레코드는 보고용 관찰',
      assumptions: [...body.contract.assumptions, '외부 식별자는 선택한 호출 지점의 스냅샷 값', '선택된 런타임 함수 바인딩이 원본의 함수 선언과 같음', '객체 입력은 null 프로토타입의 비순환 값 레코드; 계산 키는 원시 문자열'],
      notProven: ['호출 도달·앞선 코드·모듈 초기화', '이후 객체 변경·별칭·프로토타입·getter·Proxy', '외부 요청·React·DOM·이벤트·서버 동작', '실제 tsconfig·타입의 런타임 유효성', '전체 변경과 사람의 이해도'],
    },
  };
}

export function previewFunctionResult(source, options = {}) {
  const { index, body, inputBoundary, executionIR, bindingIR } = buildFunctionResultModel(source, options);
  const { inputs } = options;
  const observation = observe(executionIR, inputs, { trace: true });
  const bindingObservation = observation.kind === 'value' ? observe(bindingIR, inputs, { trace: true }) : null;
  const projections = index.connections.map((connection, i) => {
    if (bindingObservation?.kind !== 'value') return { localName: connection.localName, property: connection.property, status: 'unavailable' };
    const value = bindingObservation.value.$record[`binding${i + 1}`];
    return { localName: connection.localName, property: connection.property,
      status: value && typeof value === 'object' && !value.$value ? 'object-snapshot' : 'scalar-at-binding', value };
  });
  return {
    schema: VERSION, mode: 'function-result-preview', engineSha256: index.engineSha256,
    index, body, inputs, inputBoundary, execution: { inputs: inputNames(executionIR), ir: executionIR }, observation, bindingObservation, projections,
    contract: {
      observation: inputBoundary === 'call-arguments' ? '명시한 호출 지점 스냅샷에서 인수 식·선택 함수 본문·즉시 결과 바인딩을 부분 실행하고 원본 사용 위치와 함께 표시' : '명시한 함수 매개변수 입력으로 반환 데이터와 즉시 결과 바인딩을 부분 실행하고 원본 사용 위치와 함께 표시',
      inputBoundary: inputBoundary === 'call-arguments' ? '입력은 선택한 호출 지점의 식별자 값 스냅샷이다. 인수 식을 먼저 계산한 뒤 같은 원본에서 선택한 함수 선언에 전달한다. 실제 앱이 이 스냅샷에 도달했는지는 미확인이다.' : '입력은 함수 본문 진입점의 값이다. 원래 호출 인수 식을 평가한 값이라는 증거가 아니다.',
      assumptions: inputBoundary === 'call-arguments' ? ['선택한 직접 호출의 런타임 함수 값이 심볼로 연결한 원본 함수 선언과 같음'] : [],
      notProven: [...(inputBoundary === 'function-parameters' ? ['호출 인수 식의 계산'] : []), '함수 호출 도달·런타임 바인딩', '반환 객체의 이후 변경·별칭·객체 동일성',
        '이후 호출 인자 전체의 평가와 요청 실행', '이벤트·비동기 순서·서버 반영', '전체 변경 동작과 사람이 읽기 쉬워졌다는 사실'],
    },
  };
}
