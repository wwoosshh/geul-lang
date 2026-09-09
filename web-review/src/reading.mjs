import { BINARY, Unsupported } from './core.mjs';
import { stringIntrinsic } from './string-intrinsics.mjs';
import { describe } from './presentation.mjs';
import { sourceText, renderOutputPropLinks, renderInputBindings, renderCallEntryBoundary } from './report.mjs';

const quote = value => `「${value}」`;
const escape = text => String(text).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replace(/[\\`*_{}\[\]|]/g, '\\$&').replaceAll('\n', ' ↵ ');

// A structured reading of the checked IR, not a second executable language.
// Branches and callback bodies remain nested; they are never flattened into
// an unconditional sequence. CLI callers replay original sources first.
export function buildReading(ir, { nodeLimit = 2048, depthLimit = 64, textLimit = 262144 } = {}) {
  for (const [value, hard] of [[nodeLimit, 8192], [depthLimit, 128], [textLimit, 1048576]]) {
    if (!Number.isSafeInteger(value) || value < 1 || value > hard) throw new Unsupported('읽기 보기의 크기·깊이 제한이 잘못됐습니다.');
  }
  let count = 0, textSize = 0, ambiguousLabels;
  const labelCounts = new Map();
  function bindingFor(label, id) {
    if (!ambiguousLabels) labelCounts.set(label, (labelCounts.get(label) ?? 0) + 1);
    return { id, label, ...(ambiguousLabels?.has(label) ? { displayLabel: `${label} · 저장 ${id}` } : {}) };
  }
  function build(node, locals, path, depth) {
    if (++count > nodeLimit || depth > depthLimit) throw new Unsupported('읽기 보기의 노드·깊이 제한을 초과했습니다. 일부만 완성본으로 표시하지 않습니다.');
    const result = { id: count, path, kind: node.kind, source: node.source, children: [] };
    const child = (role, value, suffix, environment = locals) => {
      const reading = build(value, environment, path + suffix, depth + 1);
      result.children.push({ role, node: reading });
      return reading;
    };
    const short = fragment => { if (fragment.length <= 140) result.fragment = fragment; };
    const stringResult = (rule, evidence = {}) => {
      result.normalCompletionType = 'string';
      result.normalCompletionEvidence = { rule, ...evidence };
    };
    switch (node.kind) {
      case 'literal':
        result.text = `값 ${describe(node)}을 사용합니다.`; short(describe(node)); result.booleanResult = typeof node.value === 'boolean';
        if (typeof node.value === 'string') stringResult('string-literal');
        break;
      case 'input': result.text = `입력 스냅샷의 ${quote(node.name)} 값을 읽습니다.`; short(`입력 ${quote(node.name)}`); break;
      case 'local': {
        const binding = locals.get(node.name);
        if (!binding) throw new Unsupported('읽기 보기에서 지역 값의 저장 범위를 찾지 못했습니다.');
        result.binding = binding;
        if (binding.normalCompletionType === 'string') stringResult('stored-string', { bindingId: binding.id, initializerPath: binding.initializerPath });
        result.text = `이 범위에서 저장한 ${quote(binding.displayLabel ?? binding.label)} 값을 읽습니다.`;
        short(`저장값 ${quote(binding.displayLabel ?? binding.label)}`); break;
      }
      case 'let': {
        const binding = bindingFor(node.label ?? node.name, result.id), label = binding.displayLabel ?? binding.label;
        if (binding.displayLabel) result.bindingDefinition = binding;
        result.text = `${quote(label)}에 아래 계산값을 저장한 뒤 다음 계산으로 진행합니다.`;
        if (node.bindingRole === 'call-argument') result.text = `${node.argumentIndex + 1}번째 호출 인수를 계산해 ${quote(label)}에 보관합니다. 모든 인수를 계산한 뒤 본문으로 진행합니다.`;
        if (node.bindingRole === 'prop-equation') result.text = `명시한 전달 가정 아래 ${quote(label)}에 아래 값을 대응시킵니다. 실제 React 전달을 실행하는 것은 아닙니다.`;
        const initializer = child('저장할 값', node.value, '.value');
        if (initializer.normalCompletionType === 'string') {
          binding.normalCompletionType = 'string'; binding.initializerPath = initializer.path;
        }
        const continuation = child('저장한 뒤 이어지는 계산', node.body, '.body', new Map([...locals, [node.name, binding]]));
        if (continuation.normalCompletionType === 'string') stringResult('continuation-string', { path: continuation.path });
        break;
      }
      case 'conditional': {
        result.text = '먼저 조건을 계산하고 참으로 취급되는지에 따라 두 갈래 중 하나만 계산합니다. 선택하지 않은 갈래는 계산하지 않습니다.';
        child('먼저 판단할 조건', node.condition, '.condition');
        const yes = child('조건이 참으로 취급될 때의 결과', node.yes, '.yes');
        const no = child('그 밖의 경우의 결과', node.no, '.no');
        if (yes.normalCompletionType === 'string' && no.normalCompletionType === 'string') stringResult('both-branches-string', { paths: [yes.path, no.path] });
        break;
      }
      case 'binary': {
        if (!BINARY.has(node.op)) throw new Unsupported('읽기 보기에서 알 수 없는 이항 연산입니다.');
        const a = child('먼저 계산할 앞값', node.left, '.left');
        if (['&&', '||', '??'].includes(node.op)) {
          const condition = node.op === '&&' ? '거짓으로 취급되면' : node.op === '||' ? '참으로 취급되면' : 'null·undefined가 아니면';
          result.text = `앞값이 ${condition} 앞값 자체를 결과로 사용하고 뒷값 계산을 생략합니다. 그 밖의 경우에만 뒷값을 계산해 결과로 사용합니다.`;
          const b = child('앞값만으로 끝나지 않을 때 계산할 뒷값', node.right, '.right');
          if (a.normalCompletionType === 'string' && b.normalCompletionType === 'string') stringResult('both-logical-operands-string', { paths: [a.path, b.path] });
          result.booleanResult = a.booleanResult === true && b.booleanResult === true;
          // Only Boolean-producing operands may be worded as conjunction or
          // disjunction; ordinary JS &&/|| return one of their operand values.
          if (result.booleanResult && a.fragment && b.fragment && node.op !== '??') short(
            node.op === '&&' ? `(${a.fragment}) 그리고 (${b.fragment}) — 앞 조건이 맞을 때만 뒷조건을 계산`
              : `(${a.fragment}) 또는 (${b.fragment}) — 앞 조건이 맞지 않을 때만 뒷조건을 계산`);
        } else {
          const b = child('그다음 계산할 뒷값', node.right, '.right');
          result.text = `앞값과 뒷값을 이 순서로 계산한 뒤 ${quote(node.op)} 연산의 결과를 사용합니다. JavaScript의 값 변환·숫자 의미는 명시한 모델을 따릅니다.`;
          const words = { '===': '엄격히 같음', '!==': '엄격히 다름' };
          result.booleanResult = ['===', '!==', '==', '!=', '<', '<=', '>', '>='].includes(node.op);
          if (a.fragment && b.fragment) short(`(${a.fragment}) ${words[node.op] ?? node.op} (${b.fragment})`);
        }
        break;
      }
      case 'unary': {
        if (!['!', '+', '-', 'typeof'].includes(node.op)) throw new Unsupported('읽기 보기에서 알 수 없는 단항 연산입니다.');
        const value = child('연산할 값', node.value, '.value');
        result.booleanResult = node.op === '!';
        result.text = node.op === '!' ? '아래 값이 참으로 취급되는지를 뒤집어 불리언 결과를 사용합니다.' : `아래 값에 ${quote(node.op)} 연산을 적용합니다.`;
        if (node.op === 'typeof') stringResult('typeof-result');
        if (node.op === '!' && value.normalCompletionType === 'string') {
          result.readingRule = { name: 'string-falsiness-is-empty', operandPath: value.path, requires: 'operand-normal-completion-is-string' };
          result.text = '아래 계산이 정상 완료되면 원시 문자열이다. 그 문자열이 빈 문자열인지 확인해 불리언 결과를 사용합니다.';
          if (value.fragment) short(`(${value.fragment})이 빈 문자열인지`);
        } else if (value.fragment) short(node.op === '!' ? `(${value.fragment})이 거짓으로 취급되는지` : `${node.op}(${value.fragment})`);
        break;
      }
      case 'access': {
        const base = child('먼저 읽을 대상', node.base, '.base');
        result.text = '대상을 계산한 뒤 아래 순서로 속성을 읽습니다. 정상 접근에서 대상이 null·undefined이면 TypeError로 중단합니다.';
        result.steps = node.steps.map((step, index) => {
          const text = `${index + 1}번째: ${step.optional ? '앞값이 null·undefined이면 이 키 계산과 남은 읽기를 모두 생략하고 undefined로 끝냅니다. 그 외에는 ' : ''}${step.value ? '아래 키 식을 먼저 계산하고 원시 문자열 키인지 확인한 뒤 읽습니다. 정상 접근의 null 오류보다 키 식 계산이 먼저입니다.' : `${quote(step.key)} 속성을 읽습니다.`}`;
          if (step.value) child(`${index + 1}번째 속성의 키 식 — 이 단계에 도달했을 때만`, step.value, `.steps[${index}].value`);
          return { text, source: step.source };
        });
        if (base.fragment && node.steps.every(step => !step.value && !step.optional)) short(`${base.fragment}의 ${node.steps.map(step => quote(step.key)).join(' 안의 ')} 값`);
        break;
      }
      case 'array':
        result.text = `아래 ${node.items.length}개 값을 순서대로 계산해 새 목록을 만듭니다.`;
        node.items.forEach((item, index) => child(`${index + 1}번째 원소`, item, `.items[${index}]`)); break;
      case 'array-filter': {
        const binding = bindingFor(node.parameterLabel, result.id);
        if (binding.displayLabel) result.bindingDefinition = binding;
        result.text = `대상 목록의 원소를 앞에서부터 하나씩 ${quote(binding.displayLabel ?? binding.label)}로 받아 조건을 계산합니다. 참으로 취급되는 원소만 원래 순서대로 남긴 새 목록을 사용합니다. 빈 목록이면 조건을 한 번도 계산하지 않습니다. 대상이 null·undefined이면 TypeError로 중단합니다.`;
        child('먼저 계산할 대상 목록', node.base, '.base');
        child('각 원소에 대해 반복할 조건', node.predicate, '.predicate', new Map([...locals, [node.parameter, binding]])); break;
      }
      case 'array-concat':
        result.text = '앞 목록을 계산하고 표준 concat 접근을 확인한 뒤 인수 목록을 적힌 순서로 모두 계산합니다. 그다음 원소를 얕게 복사해 이어 붙입니다. 중복 제거·정렬은 하지 않습니다. 앞 목록이 null·undefined이면 인수 계산 전에 TypeError로 중단합니다.';
        child('앞 목록', node.base, '.base');
        node.arguments.forEach((item, index) => child(`${index + 1}번째 인수 목록`, item, `.arguments[${index}]`)); break;
      case 'record':
        if (node.projection === 'call-argument-values') {
          const stage = node.properties.at(-1);
          if (!stage || stage.spread || stage.name !== 'stage' || stage.value.kind !== 'literal'
            || !['early-return', 'arguments-ready'].includes(stage.value.value)
            || (stage.value.value === 'early-return' && node.properties.length !== 1)
            || node.properties.slice(0, -1).some((property, index) => property.spread || property.name !== `argument${index + 1}`)) {
            throw new Unsupported('호출 인수의 보고용 레코드 구조가 잘못됐습니다.');
          }
        }
        result.text = node.projection === 'binding-values' ? '아래 변수 값들을 구간 끝의 결과로 관찰합니다. 이 레코드는 보고용이며 앱에 객체를 생성하는 연산이 아닙니다.'
          : node.projection === 'call-argument-values' ? node.properties.at(-1).value.value === 'early-return'
            ? '값 없는 return으로 본문을 빠져나갑니다. 이 갈래에서는 호출 인수를 계산하지 않습니다.'
            : '아래 인수를 적힌 순서로 계산한 뒤 준비 상태를 관찰합니다. 이 레코드는 보고용이며 선택한 함수를 호출하거나 앱에 객체를 생성하는 연산이 아닙니다.'
          : node.projection === 'jsx-property-values' ? `선택한 JSX 속성의 존재와 값만 관찰합니다.${node.properties.length ? ' 아래 속성이 명시돼 있습니다.' : ' 선택 속성은 원본에 없습니다.'} 실제 props 객체·DOM 생성 결과가 아닙니다.`
          : '아래 속성을 적힌 순서로 계산해 새 객체를 만듭니다. 뒤에 같은 이름이 나오면 앞의 값을 덮어씁니다. 앞의 계산도 생략하지 않습니다. 값 레코드의 spread는 얕은 복사이며 null·undefined·숫자·불리언의 spread는 복사할 속성이 없습니다. 다른 spread 값 종류는 미지원입니다.';
        node.properties.forEach((property, index) => {
          const preparation = node.projection === 'call-argument-values';
          const row = child(preparation ? property.name === 'stage' ? '이 갈래의 준비 상태' : `${index + 1}번째 인수의 값`
            : property.spread ? '이 값의 열거 가능한 자체 속성을 얕게 복사' : `${quote(property.name)}의 값`, property.value, `.properties[${index}].value`);
          if (preparation && property.name === 'stage') {
            row.fragment = property.value.value === 'arguments-ready' ? '모든 인수 계산 완료. 실제 호출은 실행하지 않습니다.'
              : '값 없는 return으로 본문을 빠져나갑니다. 인수는 계산하지 않습니다.';
            row.text = row.fragment;
          }
        }); break;
      case 'jsx':
        result.text = `${quote(node.tag)} 생성 구조를 계산합니다. 속성들을 먼저 적힌 순서로 계산한 뒤 자식들을 계산합니다. React·DOM 렌더링은 별도입니다.`;
        node.attributes.forEach((attribute, index) => child(`속성 ${quote(attribute.name)}`, attribute.value, `.attributes[${index}].value`));
        node.children.forEach((item, index) => child(`${index + 1}번째 자식`, item, `.children[${index}]`)); break;
      case 'object-child':
        result.text = '아래 값을 직접 JSX 자식 자리에서 읽고 null이 아닌 객체 값인지 관찰합니다. 화면 표시나 React 렌더링 성공을 판단하지 않습니다.';
        child('읽을 값', node.value, '.value'); break;
      case 'intrinsic': {
        const operation = stringIntrinsic(node.name);
        if (!operation) throw new Unsupported('읽기 보기에서 알 수 없는 내장 연산입니다.');
        stringResult(operation.evidence);
        result.text = operation.reading + ' null·undefined이면 TypeError이며 다른 값 종류는 미지원입니다.';
        const value = child('원래 문자열', node.value, '.value');
        const prior = value.stringPipeline ?? (['input', 'local', 'literal'].includes(value.kind) && value.fragment
          ? { inputPath: value.path, inputFragment: value.fragment, operations: [] } : undefined);
        if (prior && prior.operations.length < 8) {
          result.stringPipeline = { inputPath: prior.inputPath, inputFragment: prior.inputFragment,
            operations: [...prior.operations, { name: node.name, path, source: node.source }] };
          const actions = result.stringPipeline.operations.map(row => stringIntrinsic(row.name).action);
          short(`${prior.inputFragment}을 읽어 ${actions.join('하고, ')}한 결과. 원시 문자열만 지원; null·undefined는 TypeError, 다른 값 종류는 미지원.`);
        }
        break;
      }
      default: throw new Unsupported(`읽기 보기에서 지원하지 않는 연산: ${node.kind}`);
    }
    textSize += result.text.length + (result.fragment?.length ?? 0) + result.children.reduce((sum, row) => sum + row.role.length, 0) + (result.steps ?? []).reduce((sum, step) => sum + step.text.length, 0);
    if (textSize > textLimit) throw new Unsupported('읽기 보기의 텍스트 제한을 초과했습니다. 일부만 완성본으로 표시하지 않습니다.');
    return result;
  }
  let tree = build(ir, new Map(), '$', 0);
  ambiguousLabels = new Set([...labelCounts].filter(([, occurrences]) => occurrences > 1).map(([label]) => label));
  if (ambiguousLabels.size) {
    // A second bounded pass keeps compact fragments and declarations in sync.
    // IDs and paths are stable; this changes names shown to readers, not IR.
    count = 0; textSize = 0;
    tree = build(ir, new Map(), '$', 0);
  }
  return { schema: 'web-ir-reading-1', status: 'ir-reading-view', nodeCount: count, tree,
    ...(ambiguousLabels.size ? { bindingNames: { disambiguated: [...ambiguousLabels].sort(), scope: '저장 번호는 이 보기의 IR 노드 ID다. 같은 이름의 서로 다른 저장을 구분하며 실행 횟수가 아니다.' } } : {}),
    scope: '재검사한 IR의 계산 구조를 설명하는 한국어 보기; 자연어 자체의 실행 문법·의미 보존 증명·입력 실행 결과는 아님' };
}

// Only the result continuations carry call-entry meaning. Boolean constants
// inside conditions or const initializers remain ordinary JavaScript values.
function applyCallEntryMeaning(artifact, reading) {
  if (artifact.mode !== 'call-entry-slice') return reading;
  const terminals = new Map();
  const sameSource = (a, b) => a && b && a.file === b.file && a.start === b.start && a.end === b.end;
  function visit(ir, path) {
    if (ir.kind === 'let') return visit(ir.body, path + '.body');
    if (ir.kind === 'conditional') { visit(ir.yes, path + '.yes'); visit(ir.no, path + '.no'); return; }
    if (ir.kind !== 'literal' || typeof ir.value !== 'boolean'
      || !(ir.value ? sameSource(ir.source, artifact.excludedCall.source) : artifact.earlyReturns.some(source => sameSource(ir.source, source)))) {
      throw new Unsupported('호출 진입 결과를 원본 호출·return 경계에 연결하지 못했습니다.');
    }
    terminals.set(path, { reached: ir.value, source: ir.source });
  }
  visit(artifact.ir, '$');
  let linked = 0;
  function annotate(node) {
    const terminal = terminals.get(node.path);
    if (terminal) {
      if (node.kind !== 'literal' || !sameSource(node.source, terminal.source)) throw new Unsupported('읽기 보기의 호출 진입 결과 위치가 다릅니다.');
      linked++;
      const text = terminal.reached ? '선택한 호출 식을 평가하기 직전에 도달합니다. 호출 대상·인수는 아직 계산하지 않았습니다.'
        : '값 없는 return으로 이 본문을 빠져나갑니다. 선택한 호출 식에 도달하지 않습니다.';
      return { ...node, text, fragment: text, observationRole: 'call-entry-terminal', reached: terminal.reached };
    }
    return { ...node, children: node.children.map(row => ({ ...row, node: annotate(row.node) })) };
  }
  const tree = annotate(reading.tree);
  if (linked !== terminals.size) throw new Unsupported('읽기 보기에서 호출 진입 결과 일부가 빠졌습니다.');
  return { ...reading, tree, observationMeaning: { mode: 'call-entry-slice', callee: artifact.target.callee,
    boundary: 'before-callee-and-arguments', executed: false } };
}

export function buildArtifactReading(artifact, limits) {
  return applyCallEntryMeaning(artifact, buildReading(artifact.ir, limits));
}

export function renderReading(artifact, reading, { snippets, outputPropLinks, propIndex, propSnippets } = {}) {
  reading = applyCallEntryMeaning(artifact, reading);
  const lines = ['# 선택한 코드의 계산 구조', '', `관찰 범위: ${escape(artifact.contract.observation)}`, '',
    '입력값을 실행한 기록이 아니라 가능한 계산과 분기 구조를 읽는 보기입니다. 각 단계는 앞선 계산이 정상 완료됐을 때만 진행합니다. 실제 도달 가능성은 별도입니다.', '',
    '입력은 각 분석의 계약에 적힌 스냅샷·매개변수 경계에서 읽으며, 저장값은 그 계산 범위에서만 참조합니다. 일반 속성 읽기의 대상이 null·undefined이면 TypeError입니다. 간단한 연산은 한 문장으로 묶었습니다. 모든 하위 연산·위치는 JSON 트리에 남습니다.', ''];
  function render(node, depth, role, sequence = false) {
    const indent = '  '.repeat(depth);
    lines.push(`${indent}- ${role ? escape(role) + ': ' : ''}${escape(node.fragment ?? node.text)} (${sourceText(node.source, artifact)})`);
    if (node.fragment) return;
    if (sequence && node.kind === 'let') {
      // Only a continuation is a subsequent step. Initializers keep their
      // expression tree, including eager work that may throw even if unused.
      render(node.children[0].node, depth + 1, node.children[0].role);
      render(node.children[1].node, depth, '그다음', true);
    } else if (sequence && node.kind === 'conditional') {
      render(node.children[0].node, depth + 1, node.children[0].role);
      // Explicit branch containers keep their local sequence inside the
      // condition; do not flatten it into unconditional sibling statements.
      for (const branch of node.children.slice(1)) {
        lines.push(`${indent}  - ${escape(branch.role)}:`);
        render(branch.node, depth + 2, undefined, true);
      }
    } else if (node.kind === 'access') {
      // Keep computed keys next to their access step: listing all keys before
      // all reads would imply the wrong evaluation order for chained access.
      render(node.children[0].node, depth + 1, node.children[0].role);
      for (const [index, step] of node.steps.entries()) {
        lines.push(`${indent}  - ${escape(step.text)}`);
        const key = node.children.find(row => row.node.path === node.path + `.steps[${index}].value`);
        if (key) render(key.node, depth + 2, key.role);
      }
    } else for (const row of node.children) render(row.node, depth + 1, row.role);
  }
  if (reading.bindingNames) lines.push(escape(reading.bindingNames.scope), '');
  render(reading.tree, 0, undefined, true);
  if (['call-entry-slice', 'call-arguments-slice'].includes(artifact.mode)) lines.push('', renderCallEntryBoundary(artifact, { snippets }), '');
  if (artifact.bindings?.inputs?.length) lines.push('', renderInputBindings(artifact, { snippets }));
  if (outputPropLinks) lines.push('', renderOutputPropLinks(artifact, outputPropLinks, propIndex, { propSnippets }));
  lines.push('', `IR 연산 ${reading.nodeCount}개를 포함합니다. 이 개수는 원본 프로젝트의 처리율이나 사람의 이해도를 뜻하지 않습니다.`, '',
    '실행 가정:', '', ...artifact.contract.assumptions.map(item => `- ${escape(item)}`), '',
    '아직 확인하지 않은 범위:', '', ...artifact.contract.notProven.map(item => `- ${escape(item)}`), '',
    escape(reading.scope));
  return lines.join('\n') + '\n';
}
