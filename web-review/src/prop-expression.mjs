import ts from 'typescript';
import { indexComponentProps } from './component-props.mjs';
import { liftJsxAttribute } from './jsx.mjs';
import { parseSource, lowerExpression, location } from './typescript.mjs';
import { bindLocalSource } from './bindings.mjs';
import { Unsupported, VERSION, inputNames } from './core.mjs';

// This is a source-bound equation model with an explicit delivery assumption.
// It never invokes React or the selected component, and is not a claim that
// omitted attributes/initializers/body statements complete successfully.
export function liftPropExpression({ files, entry, tag, line, properties, context, includeAbsent = false, assumePlainProps, sink } = {}) {
  if (assumePlainProps !== true) throw new Unsupported('속성 식 결합은 assumePlainProps: true라는 명시적 전달 가정이 필요합니다.');
  if (!sink || typeof sink.tag !== 'string' || typeof sink.attribute !== 'string') throw new Unsupported('자식의 sink 태그와 속성을 지정해야 합니다.');
  const index = indexComponentProps({ files, entry, tag, line, properties, context, includeAbsent });
  const componentFile = index.component.source.file, childText = files[componentFile.slice('/project/'.length)];
  const child = liftJsxAttribute(childText, { ...sink, filename: componentFile });
  const childFile = parseSource(childText, componentFile);
  let selectedChild;
  function findChild(node, depth = 0) {
    if (depth > 128) throw new Unsupported('자식 속성 AST 깊이 제한 초과');
    if (node.getStart() === child.target.element.start && node.end === child.target.element.end) selectedChild = node;
    ts.forEachChild(node, value => findChild(value, depth + 1));
  }
  findChild(childFile);
  let owner = selectedChild?.parent;
  while (owner && !ts.isFunctionLike(owner)) owner = owner.parent;
  if (!owner || owner.parameters[0]?.getStart() !== index.component.parameter.start || owner.parameters[0]?.end !== index.component.parameter.end) throw new Unsupported('sink는 연결된 자식 함수 자체의 JSX 속성이어야 합니다. 중첩 함수는 결합하지 않습니다.');
  for (const connection of index.connections) {
    if (connection.defaultInitializer) throw new Unsupported('선택 매개변수의 기본값은 이 결합 모델에서 아직 실행하지 않습니다.', connection.to);
    const uncertainUse = connection.uses.find(use => use.nestedFunction || !['jsx-attribute', 'jsx-expression', 'type-only'].includes(use.kind));
    if (uncertainUse) throw new Unsupported('선택 매개변수의 재대입·캡처·기타 사용이 있으면 속성 식으로 결합하지 않습니다.', uncertainUse.source);
  }
  const parentFile = parseSource(files[entry], '/project/' + entry);
  const bound = bindLocalSource(parentFile, index.target.source), nodes = new Map();
  let opening;
  function findParent(node, depth = 0) {
    if (depth > 128) throw new Unsupported('부모 속성 AST 깊이 제한 초과');
    if (node.getStart() === index.target.source.start && node.end === index.target.source.end) opening = node;
    if (ts.isExpressionNode(node)) nodes.set(`${node.getStart()}:${node.end}`, node);
    ts.forEachChild(node, value => findParent(value, depth + 1));
  }
  findParent(parentFile);
  if (!opening?.attributes) throw new Unsupported('부모 JSX 위치를 다시 찾지 못했습니다.');
  const ordered = [...index.connections].sort((a, b) => (a.from?.start ?? Infinity) - (b.from?.start ?? Infinity));
  const bindings = ordered.map((connection, i) => {
    let value;
    if (!connection.provided) value = { kind: 'literal', value: { $value: 'undefined' }, source: index.target.source };
    else if (!connection.expression) value = { kind: 'literal', value: true, source: connection.from };
    else {
      const node = nodes.get(`${connection.expression.start}:${connection.expression.end}`);
      if (!node) throw new Unsupported('부모 속성의 원본 식을 찾지 못했습니다.');
      value = lowerExpression(node, { records: true, resolve: identifier => {
        const original = bound.bySpan.get(`${identifier.getStart()}:${identifier.end}`);
        return identifier.text === 'undefined' && !bound.symbol(original)?.declarations?.length
          ? { kind: 'literal', value: { $value: 'undefined' }, source: location(identifier) } : undefined;
      } });
    }
    return { name: `전달속성${i + 1}`, label: connection.localName, value,
      bindingRole: 'prop-equation', provided: connection.provided, source: connection.from ?? index.target.source, connection };
  });
  function substitute(node) {
    if (node?.kind === 'input') {
      const binding = bindings.find(row => row.connection.localName === node.name && row.connection.uses.some(use => use.source.start === node.source.start && use.source.end === node.source.end));
      if (!binding) throw new Unsupported('자식 식의 모든 입력이 선택한 매개변수 바인딩에 대응해야 합니다.', node.source);
      return { kind: 'local', name: binding.name, source: node.source, definition: binding.connection.to };
    }
    if (Array.isArray(node)) return node.map(substitute);
    if (!node || typeof node !== 'object') return node;
    return Object.fromEntries(Object.entries(node).map(([key, value]) => [key, substitute(value)]));
  }
  const ir = bindings.reduceRight((body, { connection, ...binding }) => ({ kind: 'let', ...binding, body }), substitute(child.ir));
  let count = 0;
  const queue = [{ node: ir, depth: 0 }];
  while (queue.length) {
    const { node, depth } = queue.pop();
    if (++count > 65536 || depth > 128) throw new Unsupported('속성 결합 IR 크기·깊이 제한 초과');
    for (const value of Object.values(node)) {
      if (value?.kind) queue.push({ node: value, depth: depth + 1 });
      if (Array.isArray(value)) for (const item of value) {
        if (item?.kind) queue.push({ node: item, depth: depth + 1 });
        else if (item?.value?.kind) queue.push({ node: item.value, depth: depth + 1 });
      }
    }
  }
  const selectedStarts = new Set(index.connections.filter(row => row.provided).map(row => row.from.start));
  const omittedAttributes = opening.attributes.properties.filter(node => !selectedStarts.has(node.getStart())).map(location);
  return {
    schema: VERSION, mode: 'prop-expression-slice', engineSha256: index.engineSha256, typescript: index.typescript,
    sources: index.sources, target: child.target, ir, inputs: inputNames(ir), index, child,
    propPath: { assumption: '선택한 부모 속성값을 바꾸지 않고 해당 자식 매개변수에 전달하며, 생략한 속성은 이 모델 안에서 undefined로 둠',
      bindings: bindings.map(({ connection }) => connection), omittedAttributes, sink: child.source },
    contract: {
      observation: '명시한 전달 가정 아래 선택한 부모 속성 식을 계산하고 자식의 선택 속성 식에 대입한 값 또는 TypeError; React 실행 결과가 아님',
      assumptions: ['선택한 JSX 속성은 일반 속성값으로 전달되고 생략 속성은 undefined인 모델',
        '전달한 값이 자식의 선택 식까지 유지됨', '부모 식별자는 명시한 평가 지점의 스냅샷',
        '객체 입력은 모든 자체 속성이 열거 가능한 null 프로토타입 값 트리'],
      notProven: ['다른 부모 속성·자식의 매개변수 초기화·본문·hooks의 정상 완료와 부수 효과',
        'React 생성기·defaultProps·wrapper·실제 함수 바인딩 및 호출', '자식 식의 도달과 최종 DOM·이벤트·상태·서버 동작',
        '일반 객체 별칭·getter·Proxy·prototype', '전체 변경·사람 검토 개선'],
    },
  };
}
