import ts from 'typescript';
import { Unsupported, inputNames } from './core.mjs';
import { parseSource, lowerExpression, location } from './typescript.mjs';
import { indexComponentProps } from './component-props.mjs';
import { liftJsxGuards } from './jsx-guards.mjs';
import { liftJsxReference } from './jsx-reference.mjs';
import { bindLocalSource, indexSliceBindings } from './bindings.mjs';
import { prependConstPrefix } from './jsx-prefix.mjs';

const unwrap = node => {
  while (ts.isParenthesizedExpression(node) || ts.isAsExpression(node) || ts.isNonNullExpression(node) || ts.isSatisfiesExpression(node) || ts.isTypeAssertionExpression(node)) node = node.expression;
  return node;
};
const sameSpan = (a, b) => a.getStart() === b.start && a.end === b.end;

// Compose existing flow and prop-binding queries; no new CLI extraction mode.
// This equation starts at the parent expression, under explicit normal/stable
// delivery assumptions. It does not execute a component or its omitted body.
export function linkJsxFlowProps({ files, entry, tag, line, properties, context, sink, assumePlainProps }) {
  if (assumePlainProps !== true) throw new Unsupported('흐름 결합에는 명시적 일반 속성 전달 가정이 필요합니다.');
  const index = indexComponentProps({ files, entry, tag, line, properties, context });
  const childFile = index.component.source.file;
  const child = liftJsxFlow(files[childFile.slice('/project/'.length)], { ...sink, filename: childFile });
  const parent = liftJsxFlow(files[entry], { tag, line: index.target.line, filename: '/project/' + entry });
  if (parent.flow.route !== 'inline-child') throw new Unsupported('부모 호출 자리는 직접 JSX 자식 전달 경로여야 합니다.');
  const originalChild = parseSource(files[childFile.slice('/project/'.length)], childFile);
  let selected;
  function find(node) {
    if (sameSpan(node, child.source)) selected = node;
    ts.forEachChild(node, find);
  }
  find(originalChild);
  let owner = selected?.parent;
  while (owner && !ts.isFunctionLike(owner)) owner = owner.parent;
  if (!owner?.parameters[0] || !sameSpan(owner.parameters[0], index.component.parameter)) throw new Unsupported('버튼은 연결한 자식 함수 자체에 속해야 합니다.');
  for (const row of index.connections) {
    if (row.defaultInitializer || row.uses.some(use => use.kind === 'write-reference')) throw new Unsupported('기본값·매개변수 재대입이 있는 경로는 결합하지 않습니다.', row.to);
  }
  const originalParent = parseSource(files[entry], '/project/' + entry);
  const bound = bindLocalSource(originalParent, index.target.source), nodes = new Map();
  function collect(node) { nodes.set(`${node.getStart()}:${node.end}`, node); ts.forEachChild(node, collect); }
  collect(originalParent);
  const names = new Set();
  function collectNames(node) {
    if (node?.kind === 'let' || node?.kind === 'local') names.add(node.name);
    if (node && typeof node === 'object') for (const value of Object.values(node)) {
      if (Array.isArray(value)) value.forEach(collectNames);
      else if (value && typeof value === 'object') collectNames(value);
    }
  }
  collectNames(child.ir);
  const bindings = [...index.connections].sort((a, b) => a.from.start - b.from.start).map((connection, i) => {
    let name = `부모전달${i + 1}`;
    while (names.has(name)) name += '_';
    names.add(name);
    const expression = connection.expression && nodes.get(`${connection.expression.start}:${connection.expression.end}`);
    if (connection.expression && !expression) throw new Unsupported('부모 속성 식을 찾지 못했습니다.', connection.expression);
    const value = expression ? lowerExpression(expression, { records: true, resolve: identifier => {
      const original = bound.bySpan.get(`${identifier.getStart()}:${identifier.end}`);
      return identifier.text === 'undefined' && !bound.symbol(original)?.declarations?.length
        ? { kind: 'literal', value: { $value: 'undefined' }, source: location(identifier) } : undefined;
    } }) : { kind: 'literal', value: true, source: connection.from };
    return { name, value, connection };
  });
  function substitute(node) {
    if (node?.kind === 'input') {
      const binding = bindings.find(row => row.connection.localName === node.name && row.connection.uses.some(use =>
        !use.nestedFunction && use.source.start === node.source.start && use.source.end === node.source.end));
      if (!binding) throw new Unsupported('자식의 모든 자유 입력이 부모 전달 속성에 연결되어야 합니다.', node.source);
      return { kind: 'local', name: binding.name, source: node.source, definition: binding.connection.to };
    }
    if (Array.isArray(node)) return node.map(substitute);
    if (!node || typeof node !== 'object') return node;
    return Object.fromEntries(Object.entries(node).map(([key, value]) => [key, substitute(value)]));
  }
  const body = bindings.reduceRight((body, binding) => ({ kind: 'let', name: binding.name,
    label: binding.connection.localName, value: binding.value, source: binding.connection.from, body }), substitute(child.ir));
  const ir = { kind: 'conditional', condition: parent.ir, yes: body, no: { kind: 'literal', value: false }, source: parent.source };
  return { schema: 'web-linked-flow-1', engineSha256: index.engineSha256, sources: index.sources, ir, inputs: inputNames(ir),
    index, parent, child, bindings,
    contract: { observation: '부모 JSX 경로 진입 → 선택 속성 식의 순차 계산 → 자식 버튼 생성값의 직접 자식 자리 전달 여부',
      assumptions: ['부모 표현식에 도달하고 생략한 평가가 정상 완료하며 관련 입력을 바꾸지 않음',
        '선택 속성을 일반 값으로 전달하고 자식 분석 구간까지 해당 값을 유지함', ...child.contract.assumptions],
      notProven: ['상위 앱에서 UI 설정·화면 형식·상태가 만들어지는 과정과 도달 가능성',
        '생략한 다른 속성·hooks·본문·React 호출·defaultProps의 실제 효과', '최종 DOM·배치·클릭·상태 전이', '도메인 밖 동작과 전체 행동의 검증'] } };
}

// A narrow value-flow query. It observes delivery to JSX child slots, not the
// eventual DOM. Selected construction must succeed under a standard runtime.
export function liftJsxFlow(source, selector) {
  const filename = selector.filename ?? 'input.tsx';
  const creation = liftJsxGuards(source, { ...selector, prefixLine: undefined });
  const original = parseSource(source, filename);
  const bound = bindLocalSource(original, creation.root);
  const fail = (message, node) => { throw new Unsupported(message, node ? bound.source(node) : undefined); };
  let target;
  function find(node) { if (sameSpan(node, creation.source)) target = node; ts.forEachChild(node, find); }
  find(bound.file);
  if (!target) fail('선택한 JSX의 바인딩 노드를 찾지 못했습니다.');
  let current = target, inline = false;
  while (current.parent) {
    const parent = current.parent;
    if ((ts.isJsxElement(parent) || ts.isJsxFragment(parent)) && parent.children.includes(current)) { inline = true; break; }
    if (ts.isJsxExpression(parent) || ts.isParenthesizedExpression(parent) || ts.isAsExpression(parent) || ts.isNonNullExpression(parent) || ts.isSatisfiesExpression(parent) || ts.isTypeAssertionExpression(parent) ||
      (ts.isConditionalExpression(parent) && parent.condition !== current) ||
      (ts.isBinaryExpression(parent) && parent.right === current && ['&&', '||', '??'].includes(parent.operatorToken.getText()))) { current = parent; continue; }
    break;
  }
  const common = { ...creation, mode: 'jsx-object-flow', flow: { route: inline ? 'inline-child' : 'stored-const' } };
  const commonAssumptions = ['선택한 JSX의 태그·속성·자식 평가가 정상 완료되고 표준 생성기가 객체를 반환함',
    '분석 구간과 선택한 참조에 도달하며 생략한 선행 평가가 예외를 내지 않음'];
  if (inline) {
    if (selector.prefixLine !== undefined) fail('인라인 전달 경로의 prefix 결합은 아직 지원하지 않습니다.');
    return { ...common, contract: { observation: '선택한 JSX 생성값을 그 값을 보존하는 표현식을 거쳐 직접 자식 자리에 전달하는지 여부',
      assumptions: [...creation.contract.assumptions, ...commonAssumptions],
      notProven: ['생성된 부모 객체가 최종 반환·렌더링된다는 사실', 'JSX props·스타일·이벤트의 실제 내용', '생략한 선행 평가의 무효과성·실제 React·DOM 동작'] } };
  }
  const root = bound.root, declaration = root?.parent;
  if (!declaration || !ts.isVariableDeclaration(declaration) || !ts.isIdentifier(declaration.name) || !(declaration.parent.flags & ts.NodeFlags.Const)) fail('직접 자식이 아니면 const 저장 선언이 필요합니다.', target);
  if (declaration.parent.declarations.at(-1) !== declaration) fail('선택한 저장 선언은 해당 const 문장의 마지막 선언이어야 합니다.', declaration);
  const initializer = unwrap(root);
  if (!ts.isConditionalExpression(initializer)) fail('저장 경로는 선택 JSX와 null 중 하나를 반환하는 삼항식만 지원합니다.', root);
  const yes = unwrap(initializer.whenTrue), no = unwrap(initializer.whenFalse);
  if (!((sameSpan(yes, creation.source) && no.kind === ts.SyntaxKind.NullKeyword) || (sameSpan(no, creation.source) && yes.kind === ts.SyntaxKind.NullKeyword))) fail('저장 초기화의 두 결과는 선택 JSX와 null이어야 합니다.', initializer);
  const stored = creation.bindings.storedResult;
  if (!stored || stored.status !== 'declaration-found' || stored.usesTruncated || stored.uses.some(use => use.nestedFunction || !['jsx-child', 'condition-value', 'type-only'].includes(use.kind))) fail('저장 값의 별칭·다른 함수 캡처·가변 사용은 아직 연결하지 않습니다.', declaration);
  const uses = stored.uses.filter(use => use.kind === 'jsx-child');
  if (!uses.length || uses.length > 16) fail('직접 자식 참조 1~16개가 필요합니다.', declaration);
  const references = uses.map(use => liftJsxReference(source, { name: stored.name, line: use.source.line, column: use.source.column, filename }));
  // The gap between creation and use can contain arbitrary calls. Only frozen
  // lexical const values are allowed in use guards; object-property re-reads
  // would need a model of intervening mutations.
  const block = declaration.parent.parent.parent;
  const returnStatement = block.statements?.find(statement => ts.isReturnStatement(statement) && statement.expression && sameSpan(statement.expression, references[0].root));
  if (!returnStatement || returnStatement.getStart() <= declaration.getStart() || references.some(reference => !sameSpan(returnStatement.expression, reference.root))) fail('모든 직접 자식 참조는 저장 선언 뒤 같은 블록의 한 return 표현식에 있어야 합니다.', declaration);
  if (stored.uses.some(use => use.kind !== 'type-only' && (use.source.start < returnStatement.expression.getStart() || use.source.end > returnStatement.expression.end))) fail('선택 return 밖의 저장 값 사용은 아직 연결하지 않습니다.', declaration);
  const gap = [...block.statements].filter(statement => statement.getStart() > declaration.parent.parent.getStart() && statement.getStart() < returnStatement.getStart());
  for (const statement of gap) {
    if (!ts.isExpressionStatement(statement)) fail('저장과 return 사이에서는 정상 완료를 가정한 식 문장만 생략합니다.', statement);
    const check = node => {
      if (ts.isAwaitExpression(node) || ts.isYieldExpression(node)) fail('비동기 중단을 가로지르는 흐름은 아직 연결하지 않습니다.', node);
      ts.forEachChild(node, check);
    };
    check(statement);
  }
  for (const reference of references) {
    const pending = [reference.ir];
    while (pending.length) {
      const node = pending.pop();
      if (node.kind === 'access' || node.kind === 'intrinsic') fail('참조 조건에서 객체 내부나 메서드를 다시 읽는 경로는 시점 모델이 필요합니다.');
      if (node.kind === 'input') {
        const identifier = bound.bySpan.get(`${node.source.start}:${node.source.end}`), binding = identifier && bound.symbol(identifier);
        const origin = binding?.valueDeclaration;
        if (!origin || binding.declarations?.length !== 1 || !ts.isVariableDeclaration(origin) || !(origin.parent.flags & ts.NodeFlags.Const) || origin.parent.parent.parent !== block || origin.getStart() > declaration.getStart()) fail('참조 조건은 같은 블록에서 이미 초기화한 const에 한정합니다.', identifier);
      }
      for (const value of Object.values(node)) {
        if (value?.kind) pending.push(value);
        if (Array.isArray(value)) for (const item of value) if (item?.kind) pending.push(item);
      }
    }
  }
  let union = { kind: 'literal', value: false };
  for (let i = references.length - 1; i >= 0; i--) union = { kind: 'binary', op: '||', left: { kind: 'local', name: `참조값${i + 1}` }, right: union };
  // Evaluate every selected reference path eagerly, preserving errors even if
  // an earlier slot has already received the selected object.
  let flowIR = references.reduceRight((body, reference, index) => ({ kind: 'let', name: `참조값${index + 1}`, label: `자식 참조 ${index + 1}`,
    value: reference.ir, source: reference.source, body }), union);
  const projected = { kind: 'conditional', condition: { ...creation.ir, generatedOperation: 'jsx-entry' },
    yes: { kind: 'literal', value: { $opaque: 'truthy-object' }, source: creation.source },
    no: { kind: 'literal', value: null, source: creation.source }, source: creation.source };
  const prefixLine = selector.prefixLine ?? bound.source(declaration.parent.parent).line;
  const prefixed = prependConstPrefix(flowIR, prefixLine, bound, original.fileName, { rootValue: projected });
  flowIR = prefixed.ir;
  return { ...common, prefix: prefixed.prefix, ir: flowIR, inputs: inputNames(flowIR),
    bindings: indexSliceBindings(original, [{ condition: flowIR }], creation.root, bound),
    flow: { route: 'stored-const', storedName: stored.name, declaration: bound.source(declaration),
      returnExpression: bound.source(returnStatement.expression),
      omittedStatements: gap.map(statement => ({ source: bound.source(statement), reason: '정상 완료를 가정한 중간 식 문장; 내부 효과는 실행하지 않음' })),
      references: references.map(reference => ({ source: reference.source, root: reference.root, omittedEvaluations: reference.omittedEvaluations })),
      identity: '초기화와 참조는 같은 함수 활성화의 동일한 const 바인딩이며, 생성 결과는 객체 또는 null로만 투영한다.' },
    contract: { observation: '선택한 JSX를 객체로 투영해 const에 저장한 뒤, 같은 활성화의 직접 JSX 자식 참조 중 하나 이상에 그 객체 값을 전달하는지 여부',
      assumptions: ['외부 입력은 명시한 const 구간 시작점의 스냅샷', ...commonAssumptions],
      notProven: ['선택 JSX의 props·자식·이벤트 내용과 생성 과정의 정상 완료', '생략된 호출·태그·속성 평가의 정상 완료', '같은 이름의 다른 활성화·다른 함수로의 전달', '부모 JSX의 최종 반환·실제 React·DOM 렌더링'] } };
}
