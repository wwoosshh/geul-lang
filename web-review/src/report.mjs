import path from 'node:path';
import { stringIntrinsic } from './string-intrinsics.mjs';

const escape = text => String(text).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
  .replace(/[\\`*_[\]|]/g, match => '\\' + match).replaceAll('\r', '\\r').replaceAll('\n', '\\n');
function valueText(value) {
  if (value === true) return '참';
  if (value === false) return '거짓';
  if (value === null) return 'null';
  if (value?.$value) return value.$value;
  if (value?.$opaque === 'truthy-object') return '내부 미확인 객체(참으로 취급·typeof object)';
  if (value?.$record) return `{ ${Object.entries(value.$record).map(([name, item]) => `${name}: ${valueText(item)}`).join(', ')} }`;
  if (value?.$array) return `[${value.$array.map(valueText).join(', ')}]`;
  if (value?.$jsx) {
    const { tag, attributes, children } = value.$jsx;
    return `<${tag}> (속성 ${valueText(attributes)}, 자식 [${children.map(valueText).join(', ')}])`;
  }
  return JSON.stringify(value);
}
function previewText(value) {
  if (value.category === 'opaque') return '내부 미확인 객체(참으로 취급·typeof object)';
  if (value.category === 'scalar') return valueText(value.value);
  if (value.category === 'record') return `레코드 (속성: ${value.keys.join(', ')}${value.keys.length === 8 ? ', …' : ''})`;
  if (value.category === 'jsx') return `<${value.tag}> 생성 구조`;
  if (value.category === 'array') return `순서 있는 목록 (${value.length}개)`;
  if (value.category === 'string-preview') return `${JSON.stringify(value.prefix)}… (${value.length}자)`;
  return '값 미리보기 없음';
}
export function sourceText(source, artifact) {
  if (!source) return '원본 위치 없음';
  let filename = source.file;
  if (filename.startsWith('/project/')) {
    if (['function-body-slice', 'call-bindings-slice'].includes(artifact.mode) && artifact.sourceFile) filename = artifact.sourceFile;
    else if (artifact.manifest) filename = path.resolve(path.dirname(artifact.manifest), filename.slice('/project/'.length));
    else return `${escape(filename)}:${source.line}`;
  }
  const label = `${path.basename(filename)}:${source.line}`;
  if (!path.isAbsolute(filename)) return escape(label);
  return `[${escape(label)}](<${filename.replaceAll('\\', '/')}:${source.line}>)`;
}
export function renderIRStructure(comparison, before, after, { beforeSnippets, afterSnippets } = {}) {
  if (comparison.status !== 'ir-structural-comparison') return `IR 구조 설명을 생성하지 않았습니다: ${escape(comparison.reason)}`;
  const lines = ['선택 코드의 계산 구조 변화:', ''];
  if (comparison.sameStructure) lines.push('알려진 위치·표시 이름을 제외하고 지역 값의 범위를 유지한 IR 구조는 같습니다. 이것만으로 전체 코드 변경이 동작에 영향을 주지 않는다고 판단하지 않습니다.');
  for (const change of comparison.changes) {
    const a = sourceText(change.before.source, before), b = sourceText(change.after.source, after);
    const oldText = beforeSnippets?.(change.before.source), newText = afterSnippets?.(change.after.source);
    lines.push(`- ${change.kind === 'condition-changed' ? '두 결과 갈래의 IR 구조는 유지되고 갈래를 고르는 조건이 바뀌었습니다.' : '이 지점의 IR 계산 구조가 바뀌었습니다.'} 변경 전 ${a}, 변경 후 ${b}.`);
    if (oldText !== undefined) lines.push(`  - 변경 전 식: ${escape(oldText)}`);
    if (newText !== undefined) lines.push(`  - 변경 후 식: ${escape(newText)}`);
  }
  lines.push('', '같은 갈래 구조도 입력이나 앞선 계산값이 달라지면 다른 결과를 낼 수 있습니다. 별도의 실행 비교 범위·미확인 입력과 함께 판단해야 합니다. 구조 설명이 변경 원인 전체나 기획 의도를 판정하지 않습니다.');
  return lines.join('\n');
}
function eventText(event, snippets) {
  const condition = event.conditionSource ? snippets?.(event.conditionSource) : undefined;
  const left = event.leftSource ? snippets?.(event.leftSource) : undefined;
  switch (event.event) {
    case 'bind': return event.bindingRole === 'destructured-property'
      ? `${JSON.stringify(event.bindingKey)} 속성에서 읽은 ${previewText(event.value)}을 ${event.name}에 저장했다.`
      : event.bindingRole === 'prop-equation' ? `전달 가정 모델에서 ${event.name}에 ${previewText(event.value)}을 대응시켰다.${event.provided ? ' 선택한 부모 속성 식의 계산값이다.' : ' 부모 JSX의 생략을 이 모델에서 undefined로 둔 결과이며 실제 React 전달값의 증거가 아니다.'}`
      : event.bindingRole === 'call-argument' ? `${event.argumentIndex + 1}번째 호출 인수를 ${previewText(event.value)}으로 계산했다. 모든 인수 계산 뒤 ${event.name} 입력에 전달한다.`
      : `${event.name}에 ${previewText(event.value)}을 저장했다.`;
    case 'record-field': return `생성 중인 객체의 ${JSON.stringify(event.name)} 속성을 ${previewText(event.value)}으로 정했다.`;
    case 'record-spread': return `${previewText(event.value)}에서 열거 가능한 자체 속성 ${event.copied}개를 새 객체로 얕게 복사한다. 없는 속성을 만들거나 기본값을 채우지 않는다.`;
    case 'record-copy-field': return `${JSON.stringify(event.name)}${event.nameTruncated ? ' (이름 일부 생략)' : ''} 속성의 ${previewText(event.value)}을 복사했다.${event.replaced ? ' 앞서 같은 이름에 저장한 값을 덮어썼다.' : ''}`;
    case 'record-overwrite': return `${JSON.stringify(event.name)} 속성에 앞서 저장한 값을 이번 계산값으로 덮어썼다.`;
    case 'observed-binding': return `선택 구간 끝에서 ${event.name}의 값은 ${previewText(event.value)}이다. 보고용 관찰이며 앱의 객체 생성이 아니다.`;
    case 'observed-jsx-property': return `선택 JSX 속성 ${JSON.stringify(event.name)}은 원본에 있으며, 그 식의 값은 ${previewText(event.value)}이다. 실제 props 객체·DOM 생성 결과가 아니다.`;
    case 'observed-call-preparation': {
      if (event.name === 'stage' && event.value.category === 'scalar') {
        if (event.value.value === 'arguments-ready') return '모든 인수 계산을 완료했다. callee의 실제 읽기·호출은 실행하지 않았다.';
        if (event.value.value === 'early-return') return '값 없는 return으로 본문을 빠져나갔다. 선택한 호출의 인수를 계산하지 않았다.';
      } else if (/^argument[1-9]\d*$/.test(event.name)) return `${event.name.slice(8)}번째 인수는 ${previewText(event.value)}으로 계산됐다. 아직 뒤의 인수·실제 호출이 완료됐다는 뜻은 아니다.`;
      throw new Error('호출 인수의 관찰 기록을 해석하지 못했습니다.');
    }
    case 'object-child': return `${previewText(event.value)}을 직접 JSX 자식 자리에서 읽었다. ${event.contributed ? '객체 값을 전달했다' : '객체 값은 전달하지 않았다'}. 렌더링 성공 여부는 별도다.`;
    case 'array': return `원소 ${event.length}개의 목록을 적힌 순서대로 만들었다.`;
    case 'filter-start': return `원소 ${event.length}개를 앞에서부터 ${JSON.stringify(event.parameter)}에 대입하며 검사한다.`;
    case 'filter-item': return `${event.index + 1}번째 원소 ${previewText(event.value)}의 필터 조건이 ${event.selected ? '참으로 취급되어 남겼다' : '거짓으로 취급되어 제외했다'}.`;
    case 'filter-result': return `${event.inputLength}개 중 ${event.length}개를 원래 순서로 남겼다. 원본 목록 자체는 바꾸지 않았다.`;
    case 'concat-part': return `${event.part === 0 ? '앞 목록' : `${event.part}번째 인수 목록`}의 원소 ${event.length}개를 결과 위치 ${event.start}부터 이어 붙였다. 중복 제거·정렬을 하지 않았다.`;
    case 'concat-result': return `이어 붙인 새 목록은 ${event.length}개다. 원본 목록과 원소 객체 자체는 바꾸지 않았다.`;
    case 'intrinsic': {
      const operation = stringIntrinsic(event.name);
      if (!operation) throw new Error('알 수 없는 내장 연산');
      return `${operation.label} (${operation.fragment})으로 ${previewText(event.input)}을 계산한 결과는 ${previewText(event.result)}이다. 원본 문자열 자체는 바꾸지 않았다.`;
    }
    case 'access-key': return `속성 키 식 ${snippets?.(event.keySource) ?? '(원본에서 확인)'}을 계산해 문자열 ${previewText(event.key)}을 얻었다.`;
    case 'computed-read': return `계산한 속성 이름 ${previewText(event.key)}에서 ${previewText(event.value)}을 읽었다.`;
    case 'branch':
      if (event.generatedOperation === 'jsx-entry') return `선택 JSX에 진입하는 경로의 계산값은 ${previewText(event.condition)}이다. ${event.selected === 'yes' ? '정상 생성을 가정하여 내부 미확인 객체로 투영했다' : '생성하지 않는 경우의 null을 선택했다'}.`;
      return `${event.generatedOperation === 'is-nullish' ? `${condition ?? '앞값'}이 null·undefined인지 판정한 값` : condition ? `조건 ${condition}` : '조건 값'}은 ${previewText(event.condition)}이다. ${event.selected === 'yes' ? '참으로 취급되는 분기' : '그렇지 않은 분기'}를 선택했다.`;
    case 'short-circuit': return `${left ? `${left}의 값` : `${event.operator}의 앞값`}은 ${previewText(event.left)}이다. ${event.operator} 오른쪽 계산을 ${event.evaluatedRight ? '시작한다. 이 기록만으로 그 계산이 정상 완료됐다고 판단하지 않는다' : '생략했다'}.`;
    case 'jsx': return `<${event.tag}> 구조를 만들었다. ${Object.entries(event.attributes).map(([key, value]) => `${key} = ${previewText(value)}`).join(', ')}. 자식 ${event.childCount}개.`;
    case 'optional-stop': return event.computed
      ? `앞값이 null·undefined여서 속성 키 식 ${snippets?.(event.keySource) ?? '(원본에서 확인)'}의 계산과 이후 속성 읽기를 생략했다.`
      : `앞값이 null·undefined여서 ${JSON.stringify(event.key)} 이후 속성 읽기를 중단했다.`;
    case 'throw': return `${JSON.stringify(event.key)} 속성을 읽다가 ${event.name}가 발생했다.`;
    default: throw new Error(`알 수 없는 실행 기록: ${event.event}`);
  }
}
// Records are emitted only at selected semantic operations. Even an untruncated
// record is not an instruction-by-instruction trace or evidence of app reachability.
export function buildExecutionReading(observation, { snippets, textLimit = 262144 } = {}) {
  const unavailable = reason => ({ status: 'not-generated', reason });
  if (!Number.isSafeInteger(textLimit) || textLimit < 1 || textLimit > 1048576) return unavailable('실행 읽기의 텍스트 제한이 잘못됐습니다.');
  if (!['value', 'throw', 'unsupported'].includes(observation?.kind)) return unavailable('알려진 부분 실행 결과가 아닙니다.');
  if (!Array.isArray(observation.trace) || typeof observation.traceTruncated !== 'boolean') return unavailable('명시적으로 수집한 실행 기록이 없습니다. 기록이 없다는 사실을 계산이 없었다는 뜻으로 읽지 않습니다.');
  if (observation.trace.length > 512) return unavailable('실행 기록의 최대 길이 512개를 초과했습니다.');
  try {
    let size = 0;
    const rows = observation.trace.map((event, index) => {
      const text = eventText(event, snippets);
      size += text.length;
      if (size > textLimit) throw new Error('실행 읽기의 텍스트 제한을 초과했습니다. 일부만 완성본으로 표시하지 않습니다.');
      const references = [];
      for (const [key, role] of [['conditionSource', '판단한 조건'], ['leftSource', '단락 판단의 앞값'], ['keySource', '속성 키 식']]) {
        if (event[key]) references.push({ role, source: event[key] });
      }
      return { sequence: index + 1, event: event.event, text, source: event.source, references };
    });
    return {
      schema: 'web-execution-reading-1', status: 'recorded-ir-execution', outcome: observation.kind,
      eventCount: rows.length, truncated: observation.traceTruncated, rows,
      notes: [
        '명시한 입력으로 IR을 계산할 때 남긴 기록이다. 실제 앱이 이 구간에 도달했다는 증거가 아니다.',
        '분기·저장·목록 처리 등 선택한 연산에서만 기록한다. 모든 연산의 개별 기록은 아니다.',
        '값 미리보기는 객체 내부나 긴 문자열을 생략할 수 있다. 완전한 관찰 결과와 구분한다.',
        ...(observation.traceTruncated ? ['기록 상한 때문에 뒷부분을 생략했다. 마지막 표시가 실행 종료 위치라는 뜻은 아니다.'] : []),
        ...(observation.kind === 'unsupported' ? ['지원 범위를 벗어나 전체 결과를 확정하지 못했다. 앞선 기록만으로 성공한 실행이라고 판단하지 않는다.'] : []),
      ],
    };
  } catch (error) { return unavailable(error.message); }
}
export function renderOutputPropLinks(artifact, outputPropLinks, propIndex, { propSnippets } = {}) {
  const lines = ['선택한 계산에서 자식 파일까지의 소스 연결:', '', escape(outputPropLinks.scope), '',
    '이 연결은 실행 결과가 아닌 원본 탐색이다. 계산 관찰이나 구조 보기를 아래 자식 입력이나 화면 값으로 대입하지 않았다.', ''];
  for (const link of outputPropLinks.links) {
    lines.push(`${escape(link.name)} 선언 (${sourceText(link.declaration, artifact)}) → ${escape(propIndex.target.tag)}.${escape(link.property)}에 직접 적힌 참조 (${sourceText(link.use.source, artifact)}) → 자식 매개변수 ${escape(link.parameter.name)} (${sourceText(link.parameter.source, propIndex)}).`, '');
    if (link.use.nestedFunction) lines.push('부모 참조도 다른 함수에 캡처됐다. 호출 시점은 별도다.', '');
    if (link.defaultInitializer) lines.push(`선택 매개변수의 기본값 식도 실행하지 않았다: ${escape(propSnippets?.(link.defaultInitializer) ?? '원본에서 확인')} (${sourceText(link.defaultInitializer, propIndex)}).`, '');
    lines.push('| 자식의 원본 사용 식 | 위치 | 소스상 용도 | 다른 함수 안인가 |', '|---|---|---|---|');
    for (const use of link.childUses) lines.push(`| ${escape(propSnippets?.(use.expression ?? use.source) ?? '원본에서 확인')} | ${sourceText(use.source, propIndex)} | ${escape(use.kind === 'jsx-attribute' ? `${use.tag}.${use.attribute}${use.direct ? ' 직접 참조' : ' 계산식 일부'}` : use.kind === 'type-only' ? '타입 참조' : use.kind === 'write-reference' ? '대입 구문' : '별도 해석이 필요한 참조')} | ${use.nestedFunction ? '예' : '아니요'} |`);
    if (!link.childUses.length) lines.push('| — | — | 자식 함수에서 참조를 찾지 못함 | — |');
    lines.push('');
  }
  if (outputPropLinks.unlinkedProperties.length) lines.push(`이 const 출력과 연결하지 않은 선택 속성: ${outputPropLinks.unlinkedProperties.map(escape).join(', ')}.`, '');
  lines.push('이 연결에서 미확인인 내용:', '', ...outputPropLinks.notProven.map(item => `- ${escape(item)}`), '');
  return lines.join('\n');
}
export function renderInputBindings(artifact, { snippets } = {}) {
  if (!artifact.bindings?.inputs?.length) return '';
  const lines = ['입력의 원본 선언:', '',
    '소스에 적힌 선언과 식을 연결했다. 초기화·기본값·hook을 실행하지 않았으며 이 값이 현재 입력 스냅샷과 같다는 증거가 아니다.', '',
    '| 입력 이름 | 사용 위치 | 선언 위치 | 선언에 적힌 식 |', '|---|---|---|---|'];
  const expression = source => {
    const text = snippets?.(source);
    return `${text === undefined ? '원본에서 확인' : escape(text.length > 320 ? text.slice(0, 320) + '… (식 일부 생략)' : text)} (${sourceText(source, artifact)})`;
  };
  for (const input of artifact.bindings.inputs) {
    const declaration = input.status === 'declaration-found' ? input.declarations[0] : undefined;
    const origin = declaration?.destructuringOrigin, pieces = [];
    if (origin) {
      pieces.push(`구조 분해 패턴: ${expression(origin.pattern)}`);
      if (origin.expression) pieces.push(`${origin.expressionRole === 'parameter-default' ? '매개변수 기본값 식' : '패턴을 받는 선언의 초기화 식'}: ${expression(origin.expression)}`);
      else pieces.push(origin.kind === 'parameter-pattern' ? '함수 인수에서 받는 패턴; 실제 전달값 미확인' : origin.kind === 'catch-pattern' ? 'catch에서 받는 패턴; 실제 예외값 미확인' : '선언의 입력 식을 찾지 못함');
    }
    if (declaration?.initializer) pieces.push(`${declaration.initializerRole === 'default-value' ? '조건부 기본값 식' : '초기화 식'}: ${expression(declaration.initializer)}`);
    if (input.declarationsTruncated) pieces.push('선언 목록 일부 생략');
    lines.push(`| ${escape(input.name)} | ${sourceText(input.use, artifact)} | ${declaration ? sourceText(declaration.source, artifact) : '미확인·모호함'} | ${pieces.join('; ') || '—'} |`);
  }
  lines.push('', '중첩·나머지 속성·계산 키가 있는 패턴도 여기서는 원본 위치만 연결한다. 그 식의 평가 순서·값·부수 효과를 실행한 것으로 취급하지 않는다.');
  return lines.join('\n');
}
export function renderCallEntrySourceLinks(artifact, { snippets } = {}) {
  const links = artifact.sourceLinks;
  if (!links) return '';
  const excerpt = loc => {
    const text = snippets?.(loc);
    return `${text === undefined ? '원본에서 확인' : escape(text.length > 320 ? text.slice(0, 320) + '… (원본 일부 생략)' : text)} (${sourceText(loc, artifact)})`;
  };
  const lines = ['콜백 앞뒤의 원본 연결:', '', escape(links.scope), '',
    `호출 이름 ${escape(links.callee.name)}의 선언:`, ''];
  for (const declaration of links.callee.declarations) {
    lines.push(`- ${excerpt(declaration.source)}`);
    const initialization = declaration.destructuringOrigin?.expression ?? declaration.initializer;
    if (initialization) lines.push(`  - 실행하지 않은 초기화 문맥: ${excerpt(initialization)}`);
  }
  if (!links.callee.declarations.length) lines.push('이 파일에서 호출 이름의 선언을 찾지 못했다. 외부 입력값이나 함수라고 추정하지 않는다.');
  if (links.callee.status === 'ambiguous-declaration' || links.callee.declarationsTruncated) lines.push('호출 이름의 선언이 모호하거나 목록 일부를 생략했다.');
  const entry = links.entry;
  if (entry.status === 'not-indexed') lines.push('', escape(entry.reason));
  else {
    lines.push('', `이 본문을 가진 ${escape(entry.name)}의 직접 심볼 참조: ${entry.referenceCount === null ? '미확인' : entry.referenceCount + '곳'}.`, '');
    const labels = { 'direct-call': '원본의 직접 호출 식', 'optional-call': '원본의 선택적 호출 식', 'jsx-attribute': 'JSX 속성 식에 적힌 참조',
      'object-property': '객체 속성 값에 적힌 참조', 'object-shorthand': '객체 축약 속성에 적힌 참조', 'call-argument': '다른 호출의 인수에 적힌 참조',
      'return-reference': 'return에 적힌 참조', 'write-reference': '대입 대상 참조', 'type-only': '타입 문맥의 참조', 'other-reference': '별도 해석이 필요한 참조' };
    for (const reference of entry.references) {
      lines.push(`- ${labels[reference.kind]}: ${excerpt(reference.expression)}`);
      if (reference.jsxContainer) lines.push(`  - ${escape(reference.jsxContainer.tag)}의 ${escape(reference.jsxContainer.attribute)} 속성 식 안에 적힌 객체 속성이다. 실제 전달값은 미확인이다.`);
      if (reference.kind === 'jsx-attribute') lines.push(`  - 원본 태그·속성: ${escape(reference.tag)}.${escape(reference.attribute)}. 실제 전달값은 미확인이다.`);
      for (const guard of reference.context.guards.slice(0, 8)) lines.push(`  - 둘러싼 구문 조건: ${excerpt(guard.condition)} — ${escape({ truthy: '참으로 취급되는', falsy: '거짓으로 취급되는', nullish: 'null·undefined인' }[guard.accepts] ?? guard.accepts)} 갈래. 이 조건을 현재 입력으로 계산하지 않았다.`);
      if (reference.context.guards.length > 8) lines.push('  - 나머지 구문 조건은 JSON에 있다.');
      if (['direct-call', 'optional-call'].includes(reference.kind)) {
        for (const previous of reference.context.precedingStatements.slice(-8)) lines.push(`  - 앞에 적힌 문장: ${excerpt(previous.source)}`);
        if (reference.context.precedingStatements.length > 8) lines.push('  - 앞선 문장은 마지막 8개만 표시했다. 전체 원본 위치 목록은 JSON에 있다.');
      }
    }
    if (entry.referencesTruncated) lines.push('직접 참조가 128곳을 넘어 나머지는 색인하지 않았다.');
  }
  lines.push('', ...links.notProven.map(item => `- 미확인: ${escape(item)}`));
  return lines.join('\n');
}

export function renderCallEntryBoundary(artifact, { snippets } = {}) {
  if (artifact.mode === 'call-arguments-slice') {
    const selected = artifact.preparedCall;
    return ['호출 인수 계산의 검토 경계:', '',
      '선행 구간과 인수 식만 계산한다. callee 식별자의 값 읽기는 정상 완료한다고 가정하며 실행하지 않는다. 그 값 읽기는 원래 인수 계산보다 먼저다. 실제 값 읽기가 실패하거나 값을 바꾸면 이 가정은 성립하지 않는다.', '',
      `선택 호출: ${escape(artifact.target.callee)} (${sourceText(selected.source, artifact)}). 실제 호출 가능성·실행·반환은 확인하지 않았다.`, '',
      '계산 대상으로 포함한 인수 식:', '',
      ...selected.arguments.map((row, index) => `- 인수 ${index + 1}: ${escape(snippets?.(row) ?? '원본에서 확인')} (${sourceText(row, artifact)})`),
      ...(selected.arguments.length ? [] : ['선택한 호출에 인수 식이 없다.']), '',
      '조기 반환하면 인수 계산을 건너뛴다. 인수 중 하나가 실패하면 뒤의 인수를 계산하지 않고 준비 완료도 표시하지 않는다. 보고용 레코드는 함수의 반환값이 아니다.', '',
      renderCallEntrySourceLinks(artifact, { snippets })].join('\n');
  }
  const lines = ['호출 앞의 검토 경계:', '',
    '참이면 선택한 호출 식 평가 직전에 도달한다. 거짓이면 앞의 값 없는 return으로 도달하지 않는다. 이는 함수가 true·false를 반환한다는 뜻이 아니다.', '',
    `선택 호출: ${escape(artifact.target.callee)} (${sourceText(artifact.excludedCall.source, artifact)}). 이 호출은 실행하지 않았다.`, '',
    '계산하지 않은 호출 대상·인수:', '',
    `- 호출 대상: ${escape(snippets?.(artifact.excludedCall.callee) ?? artifact.target.callee)} (${sourceText(artifact.excludedCall.callee, artifact)})`,
    ...artifact.excludedCall.arguments.map((row, index) => `- 인수 ${index + 1}: ${escape(snippets?.(row) ?? '원본에서 확인')} (${sourceText(row, artifact)})`), '',
    '원본의 값 없는 return 위치 (목록 자체는 실행 기록이 아니다):', '',
    ...artifact.earlyReturns.map(row => `- ${sourceText(row, artifact)}`), '',
    '호출 대상 읽기나 인수 계산에서 추가 오류가 날 수 있다. 호출 성공·요청 전송·상태 변경을 보장하지 않는다.'];
  if (!artifact.earlyReturns.length) lines.push('이 본문에는 선행 return이 없다. 선행 계산이 완료되면 호출 식 직전에 도달한다.');
  if (artifact.sourceLinks) lines.push('', renderCallEntrySourceLinks(artifact, { snippets }));
  return lines.join('\n');
}
export function renderExecution(artifact, observation, { inputs, snippets, outputPropLinks, propIndex, propSnippets } = {}) {
  const outcome = observation.kind === 'value' ? artifact.mode === 'call-entry-slice' ? observation.value ? '호출 식 평가 직전에 도달' : '조기 반환으로 호출 식에 도달하지 않음'
    : artifact.mode === 'call-arguments-slice' ? observation.value.$record.stage === 'arguments-ready' ? '호출 인수 계산 완료 — 실제 호출은 실행하지 않음' : '조기 반환으로 인수를 계산하지 않음'
    : valueText(observation.value) : observation.kind === 'throw' ? `${observation.name} 발생` : `미확인: ${observation.reason}`;
  const lines = [
    `# ${escape(artifact.functionName ?? artifact.target?.tag ?? artifact.target?.name ?? artifact.target?.callee ?? '선택한 식')}의 실행 설명`, '',
    `결과: **${escape(outcome)}**`, '',
    `관찰 범위: ${artifact.contract.observation}`, '',
    '아래는 주어진 입력에서 독립 실행기가 실제로 선택한 경로다. 기획 의도나 UX 적합성을 판정한 결과는 아니다.', '',
  ];
  if (artifact.contract.assumptions?.length) lines.push('이 실행의 가정:', '', ...artifact.contract.assumptions.map(item => `- ${escape(item)}`), '');
  if (['call-entry-slice', 'call-arguments-slice'].includes(artifact.mode)) lines.push(renderCallEntryBoundary(artifact, { snippets }), '');
  if (artifact.mode === 'call-arguments-slice' && observation.kind === 'value' && observation.value.$record.stage === 'arguments-ready') {
    lines.push('준비한 인수별 값:', '', ...artifact.preparedCall.argumentNames.map((name, index) => `- 인수 ${index + 1}: ${escape(valueText(observation.value.$record[name]))}`), '');
  }
  if (artifact.mode === 'record-expression-slice') lines.push(`객체 식 위치: ${sourceText(artifact.root, artifact)}`, '',
    '객체 식 자체만 실행했다. 이를 둘러싼 콜백·함수 호출·상태 갱신은 실행하지 않았다. 결과에서 속성 생략과 값이 undefined인 속성은 구별한다.', '');
  if (artifact.mode === 'jsx-property-slice') {
    lines.push(`선택한 여는 태그: ${sourceText(artifact.target.element, artifact)}.`, '',
      artifact.target.provided ? `${escape(artifact.target.attribute)} 속성은 원본에 있다. 값이 undefined·null·false여도 속성 생략으로 바꾸지 않는다.` : `${escape(artifact.target.attribute)} 속성은 선택한 원본 태그에 없다. 빈 관찰 레코드는 선택 속성이 없다는 뜻이며 전체 props 객체가 비었다는 뜻은 아니다.`, '',
      '선택 식과 별도로 남겨 둔 다른 속성:', '', ...artifact.omittedAttributes.map(source => `- ${sourceText(source, artifact)}: ${escape(snippets?.(source) ?? '원본에서 확인')}`), '',
      '이 속성들과 태그·형제의 실행, 실제 요소의 생성, HTML 속성 변환을 계산한 결과가 아니다.', '');
  }
  if (artifact.propPath) {
    lines.push('파일 사이에서 결합한 식:', '', escape(artifact.propPath.assumption), '',
      '| 부모에서 고른 속성 | 부모의 원본 값 식 | 자식의 이름 |', '|---|---|---|');
    for (const row of artifact.propPath.bindings) lines.push(`| ${escape(row.property)} | ${escape(!row.provided ? 'JSX에 없음 → 이 모델에서 undefined 가정' : row.expression ? snippets?.(row.expression) ?? '원본에서 확인' : '초기화 식 없는 속성 → true')} (${sourceText(row.from ?? artifact.index.target.source, artifact)}) | ${escape(row.localName)} (${sourceText(row.to, artifact)}) |`);
    lines.push('', `마지막으로 계산한 자식 속성: ${escape(artifact.target.tag)}.${escape(artifact.target.attribute)} (${sourceText(artifact.propPath.sink, artifact)})`, '',
      '계산하지 않은 부모의 다른 속성:', '', ...artifact.propPath.omittedAttributes.map(source => `- ${sourceText(source, artifact)}: ${escape(snippets?.(source) ?? '원본에서 확인')}`), '',
      '다른 속성·자식 매개변수 초기화·본문·hooks의 정상 완료를 검사하지 않았다. 위 결과를 전체 React 실행의 성공으로 읽으면 안 된다.', '');
  }
  if (artifact.prefix) {
    lines.push(`선행 계산의 시작: ${sourceText(artifact.prefix.source, artifact)}`, '', escape(artifact.prefix.contract), '',
      '| 순서 | 저장 이름 | 원본 초기화 식 | 위치 |', '|---|---|---|---|');
    for (const [index, binding] of artifact.prefix.bindings.entries()) lines.push(`| ${index + 1} | ${escape(binding.name)} | ${escape(snippets?.(binding.initializer) ?? '원본 위치에서 확인')} | ${sourceText(binding.source, artifact)} |`);
    lines.push('');
    for (const binding of artifact.prefix.bindings.filter(item => item.projection)) lines.push(`${escape(binding.name)}은 정상 생성된 객체 또는 null로만 투영한다. JSX 속성·자식 내용과 생성 부수 효과를 실행한 결과는 아니다.`, '');
  }
  if (['jsx-guard-slice', 'jsx-reference-slice', 'jsx-object-flow'].includes(artifact.mode)) {
    lines.push(`표현식 시작 위치: ${sourceText(artifact.root, artifact)}`, '', '이 경로 추출에서 실행하지 않은 선행 평가:', '');
    for (const omitted of artifact.omittedEvaluations) lines.push(`- ${escape(omitted.reason)}: ${sourceText(omitted.source, artifact)}`);
    if (!artifact.omittedEvaluations.length) lines.push('- 선택한 표현식 안에는 생략한 선행 태그·형제 평가가 없다. 표현식 이전 코드는 별도다.');
    lines.push('');
  }
  if (artifact.flow) {
    if (artifact.flow.route === 'inline-child') lines.push('값 전달: 선택한 JSX의 정상 생성값을 바로 둘러싼 JSX 자식 자리에 전달한다.', '');
    else {
      lines.push(`값 전달: ${escape(artifact.flow.storedName)}에 저장한 객체를 같은 활성화의 아래 자식 자리에서 읽는다. 객체 내부를 재구성하거나 뒤 시점의 입력으로 초기화를 다시 계산하지 않는다.`, '',
        `참조를 포함한 return 식: ${sourceText(artifact.flow.returnExpression, artifact)}`, '');
      for (const omitted of artifact.flow.omittedStatements) lines.push(`- ${escape(omitted.reason)}: ${sourceText(omitted.source, artifact)}`);
      for (const [index, reference] of artifact.flow.references.entries()) {
        lines.push(`자식 참조 ${index + 1}: ${sourceText(reference.source, artifact)}`, '', '이 참조 앞에서 생략한 평가:', '');
        for (const omitted of reference.omittedEvaluations) lines.push(`- ${escape(omitted.reason)}: ${sourceText(omitted.source, artifact)}`);
        lines.push('');
      }
    }
  }
  if (artifact.bindings) {
    lines.push(renderInputBindings(artifact, { snippets }), '');
    const stored = artifact.bindings.storedResult;
    if (stored) {
      const labels = { 'jsx-child': 'JSX 자식 자리 참조', 'jsx-attribute': 'JSX 속성에 직접 적힌 값', 'condition-value': '조건 연산의 값', 'type-only': '타입에서만 참조',
        'return-value': '반환값 자리 참조', 'call-argument': '호출 인수', 'object-shorthand': '객체 속성 값', 'export-reference': 'export 이름 연결', 'write-reference': '값 변경 구문', 'other-reference': '기타 참조' };
      lines.push(`선택한 표현식의 결과는 ${escape(stored.name)} 변수의 초기값이다: ${sourceText(stored.declaration.source, artifact)}.`, '',
        '| 변수 참조 | 용도 | 다른 함수 안인가 |', '|---|---|---|');
      for (const use of stored.uses) lines.push(`| ${sourceText(use.source, artifact)} | ${labels[use.kind] ?? escape(use.kind)} | ${use.nestedFunction ? '예' : '아니요'} |`);
      if (stored.status !== 'declaration-found') lines.push('| — | 선언이 모호해서 참조를 연결하지 못했다 | — |');
      else if (!stored.uses.length) lines.push('| — | 이 원본 파일에서 참조를 찾지 못했다 | — |');
      if (stored.usesTruncated) lines.push('', `참조 ${stored.useCount}개 중 2,048개만 표시했다.`);
      lines.push('');
    }
  }
  if (artifact.outputSources) {
    const labels = { 'jsx-child': 'JSX 자식 참조', 'condition-value': '조건 연산', 'type-only': '타입 참조', 'return-value': '반환값',
      'call-argument': '호출 인수', 'object-shorthand': '객체 단축 속성', 'export-reference': 'export', 'write-reference': '대입 구문', 'other-reference': '기타 참조' };
    lines.push('관찰 변수의 소스상 사용처:', '', escape(artifact.outputSources.scope), '',
      '| 변수 | 선언 | 사용 위치 | 소스에 적힌 용도 | 다른 함수 안인가 |', '|---|---|---|---|---|');
    for (const binding of artifact.outputSources.bindings) {
      for (const use of binding.uses) lines.push(`| ${escape(binding.name)} | ${sourceText(binding.declaration.source, artifact)} | ${sourceText(use.source, artifact)} | ${escape(use.kind === 'jsx-attribute' ? `${use.tag}.${use.attribute} 속성에 직접 참조` : labels[use.kind] ?? use.kind)} | ${use.nestedFunction ? '예' : '아니요'} |`);
      if (!binding.uses.length) lines.push(`| ${escape(binding.name)} | ${sourceText(binding.declaration.source, artifact)} | — | ${binding.useCount ? '표시 제한으로 생략' : '이 원본 파일에 참조 없음'} | — |`);
      if (binding.usesTruncated) lines.push('', `${escape(binding.name)}의 참조 ${binding.useCount}곳 중 ${binding.uses.length}곳만 표시했다.`, '');
    }
    lines.push('', '위 위치에서 실제로 실행되거나 같은 값이 전달됐다는 뜻은 아니다. 구간 중간에 오류가 발생하면 아래 변수의 초기화가 완료되지 않았을 수도 있다. 이후 객체 변경·콜백 호출·React 전달은 별도 확인해야 한다.', '');
  }
  if (outputPropLinks) {
    lines.push(renderOutputPropLinks(artifact, outputPropLinks, propIndex, { propSnippets }), '');
  }
  if (inputs && typeof inputs === 'object' && !Array.isArray(inputs)) {
    lines.push('입력:', '');
    const names = Object.keys(inputs);
    for (const name of names.slice(0, 32)) {
      const text = valueText(inputs[name]);
      lines.push(`- ${escape(name)}: ${escape(text.length > 160 ? text.slice(0, 160) + '… (값 일부 생략)' : text)}`);
    }
    if (names.length > 32) lines.push(`- 추가 입력 ${names.length - 32}개는 이 표시에 생략됐다.`);
    lines.push('');
  }
  const patterns = artifact.parameterInputs?.filter(parameter => parameter.binding === 'object-pattern') ?? [];
  if (patterns.length) {
    lines.push('객체로 받는 함수 인수:', '', '| 입력 이름 | 인수 순서 | 원본 구조 분해 | 위치 |', '|---|---:|---|---|');
    for (const parameter of patterns) lines.push(`| ${escape(parameter.input)} | ${parameter.index + 1} | ${escape(snippets?.(parameter.source) ?? '원본에서 확인')} | ${sourceText(parameter.source, artifact)} |`);
    lines.push('');
  }
  lines.push('| 순서 | 계산과 선택 | 원본 |', '|---|---|---|');
  const prefixNames = new Set((artifact.prefix?.bindings ?? artifact.entryRegion?.bindings ?? []).map(binding => binding.name));
  const events = (observation.trace ?? []).filter(event => event.event !== 'bind' || prefixNames.has(event.name) || ['destructured-property', 'call-argument', 'prop-equation'].includes(event.bindingRole));
  for (const [index, event] of events.entries()) lines.push(`| ${index + 1} | ${escape(eventText(event, snippets))} | ${sourceText(event.source, artifact)} |`);
  if (!events.length) lines.push(`| — | ${observation.kind === 'unsupported' ? '지원 범위를 벗어나 결과를 확정하지 못했다.' : '분기·생성·오류 없이 값을 계산했다.'} | — |`);
  lines.push('', `${artifact.entryRegion ? '실행한 선행 const의 저장 값은 표시했다. 나머지 내부' : artifact.prefix ? '선택한 const 구간의 저장 값은 표시했다. 나머지 내부' : events.some(event => event.bindingRole === 'destructured-property') ? '객체에서 분해한 속성 값은 표시했다. 나머지 내부' : '내부'} 변수 저장 단계는 이 보기에서 생략했다. \`run --trace\`로 상세 기록을 확인할 수 있다.`);
  if (observation.traceTruncated) lines.push('', '실행 기록은 512개에서 생략됐다. 전체 경로가 모두 표시된 것은 아니다.');
  lines.push('', '검증하지 않은 범위:', '', ...artifact.contract.notProven.map(item => `- ${item}`), '');
  return lines.join('\n');
}

export function renderFunctionResultPreview(preview, { snippets } = {}) {
  const { index, body, inputs, observation, bindingObservation } = preview;
  const atCall = preview.inputBoundary === 'call-arguments';
  const text = node => escape(snippets?.(node) ?? '원본에서 확인');
  const shownValue = value => { const shown = valueText(value); return escape(shown.length > 240 ? shown.slice(0, 240) + '… (값 일부 생략)' : shown); };
  const lines = [`# ${escape(index.target.functionName)} 계산에서 사용 위치까지`, '',
    atCall ? '**지정한 호출 지점 입력에서 인수와 함수 본문을 계산한 예시다. 실제 앱의 호출 도달·함수 바인딩·요청 실행은 미확인이다.**' : '**지정한 함수 입력의 부분 실행 예시다. 원래 호출 인수의 값이나 실제 요청 실행을 확인한 결과는 아니다.**', '',
    escape(preview.contract.inputBoundary), '', '계산에 넣은 값:', ''];
  const names = Object.keys(inputs ?? {});
  for (const name of names.slice(0, 32)) lines.push(`- ${escape(name)}: ${shownValue(inputs[name])}`);
  if (names.length > 32) lines.push(`- 추가 ${names.length - 32}개 입력은 표시를 생략했다.`);
  lines.push('', '함수 반환 결과에서 바로 값을 받는 변수:', '', '| 변수 | 즉시 바인딩 값 | 의미 범위 |', '|---|---|---|');
  for (const projection of preview.projections) lines.push(`| ${escape(projection.localName)} | ${projection.status === 'unavailable' ? '확정하지 않음' : shownValue(projection.value)} | ${projection.status === 'scalar-at-binding' ? '명시한 입력에서 계산한 스칼라 값' : projection.status === 'object-snapshot' ? '이 지점의 객체 구성값; 이후 사용 시점의 값은 미확인' : '본문 또는 결과 바인딩이 완료되지 않음'} |`);
  if (observation.kind !== 'value') lines.push('', `${atCall ? '인수·본문 구간' : '본문'} 계산의 관찰: **${escape(observation.kind)}**. ${escape(observation.reason ?? observation.name ?? '')}`);
  if (bindingObservation && bindingObservation.kind !== 'value') lines.push('', `본문 반환 뒤 결과 바인딩의 관찰: **${escape(bindingObservation.kind)}**. ${escape(bindingObservation.reason ?? bindingObservation.name ?? '')}`);
  lines.push('', `계산한 함수 선언: ${sourceText(index.functionDeclaration, index)}. 계산과 선택은 다음 순서다.`, '', '| 순서 | 계산과 선택 | 원본 |', '|---|---|---|');
  const events = (observation.trace ?? []).filter(event => event.event !== 'bind' || ['destructured-property', 'call-argument'].includes(event.bindingRole));
  for (const [i, event] of events.entries()) lines.push(`| ${i + 1} | ${escape(eventText(event, snippets))} | ${sourceText(event.source, body)} |`);
  if (!events.length) lines.push('| — | 표시할 분기·생성·오류 기록 없음 | — |');
  lines.push('', `일반 지역 변수의 저장 기록은 생략했다. 전체 기록과 입력 계약은 \`explain --json ${atCall ? '--caller-inputs' : '--inputs'} …\` 결과에서 확인할 수 있다.`);
  if (observation.traceTruncated) lines.push('', '실행 기록은 512개에서 생략됐다. 전체 경로가 모두 표시된 것은 아니다.');
  lines.push('', `원본의 호출 위치: ${sourceText(index.call, index)}. ${atCall ? '위 스냅샷으로 계산한 원본 인수 식은 아래와 같다.' : '이곳에 적힌 입력 식은 아래와 같다. 실제 값은 위 함수 입력과 별도로 확인해야 한다.'}`, '',
    '| 인수 | 원본 값 식 | 함수에서 받는 입력 이름 |', '|---:|---|---|');
  for (const argument of index.arguments) lines.push(`| ${argument.index + 1} | ${text(argument.expression)} (${sourceText(argument.expression, index)}) | ${escape(body.parameterInputs[argument.index]?.input ?? '대응 매개변수 없음')} |`);
  const context = index.callContext;
  lines.push('', `같은 함수에서 호출보다 앞에 적힌 문장 ${context.precedingStatements.length}개: ${context.precedingStatements.map(row => sourceText(row.source, index)).join(', ') || '없음'}. 이 문장들의 실행은 계산 모델에 포함하지 않았다.`);
  const accepts = { truthy: '참으로 취급', falsy: '거짓으로 취급', nullish: 'null 또는 undefined' };
  lines.push('');
  for (const row of context.precedingStatements.filter(row => row.immediateExits)) for (const branch of row.immediateExits.branches) lines.push(`- 앞선 소스에는 ${text(row.immediateExits.condition)}이 ${accepts[branch.accepts]}되는 분기의 ${escape(branch.kind)} 구문이 있다 (${sourceText(branch.source, index)}).`);
  if (context.precedingDeclarators.length) lines.push(`- 같은 선언문 안의 선행 변수 선언: ${context.precedingDeclarators.map(row => `${text(row)} (${sourceText(row, index)})`).join(', ')}.`);
  const sites = new Map(), conditions = new Map();
  const guardId = guard => {
    const key = `${guard.condition.start}:${guard.condition.end}`;
    if (!conditions.has(key)) conditions.set(key, { id: `조건 ${conditions.size + 1}`, guard });
    return conditions.get(key).id;
  };
  const branchPath = guards => guards.map(guard => `${guardId(guard)}: ${accepts[guard.accepts]}`).join(' → ') || '상위 if·삼항·단락 분기 없음';
  const selectedPath = branchPath(context.guards);
  let otherUses = 0;
  for (const connection of index.connections) for (const use of connection.uses) {
    if (use.kind !== 'direct-payload-property') { otherUses++; continue; }
    const key = `${use.call.start}:${use.call.end}`;
    if (!sites.has(key)) sites.set(key, { use, fields: [], path: branchPath(use.context.guards) });
    sites.get(key).fields.push(`${escape(connection.localName)} → 인수 ${use.argumentIndex + 1}의 ${escape(use.payloadName)} (${sourceText(use.source, index)})`);
  }
  lines.push('', '사용 위치의 소스 분기:', '',
    '각 조건은 해당 원본 위치에서 읽는 식이다. 반복해서 읽는 속성 값이 같다고 가정하지 않는다. 아래는 실제 요청 실행을 예측하는 결정표가 아니다.', '',
    '| 조건 | 원본 식 | 위치 |', '|---|---|---|');
  for (const { id, guard } of conditions.values()) lines.push(`| ${id} | ${text(guard.condition)} | ${sourceText(guard.condition, index)} |`);
  if (!conditions.size) lines.push('| 없음 | — | — |');
  lines.push('', `결과 계산 호출 자체의 소스 분기: ${selectedPath}.`, '', '| 사용되는 호출 | 인자에 적힌 값 | 소스 분기 경로 |', '|---|---|---|');
  for (const site of sites.values()) lines.push(`| ${text(site.use.callee)} (${sourceText(site.use.call, index)}) | ${site.fields.join(', ')} | ${site.path}${site.use.nestedFunction ? '; 다른 함수에 캡처됨' : ''}${site.use.optionalCall ? '; 선택적 호출' : ''}${site.use.context.boundaries.length ? '; 별도 경계: ' + site.use.context.boundaries.map(row => `${escape(row.kind)} (${sourceText(row.source, index)})`).join(', ') : ''} |`);
  if (!sites.size) lines.push('| 없음 | — | — |');
  lines.push('', `그 밖의 결과 참조 ${otherUses}곳, 선택 밖 직접 호출 ${index.otherDirectCalls.length}곳, 함수의 다른 용도 참조 ${index.otherFunctionReferences.length}곳은 이 표에서 실행 해석하지 않았다. 선행 문장·별칭·덮어쓰기 불확실성을 포함한 전체 소스 색인은 입력 없이 \`explain\`하거나 JSON 출력으로 확인할 수 있다.`);
  lines.push('', '계산의 가정:', '', ...[...body.contract.assumptions, ...preview.contract.assumptions].map(item => `- ${escape(item)}`), '',
    '이 보기는 명시한 스칼라·값 레코드 계약의 부분 실행이다. 타입 검사를 런타임 입력 검증으로 사용하지 않는다. 프로토타입·객체 동일성·getter·Proxy·별칭 변경은 지원 범위 밖이다.', '',
    '미확인 범위:', '', ...preview.contract.notProven.map(item => `- ${escape(item)}`),
    '- 원본 모듈 초기화·실제 tsconfig·주변 코드·나중 외부 호출의 다른 인자 평가·DOM·브라우저 동작. 글의 한국어 문장은 현재 실행 문법이 아니며 수정 후 TypeScript를 생성하지 않는다.', '');
  return lines.join('\n');
}

export function renderFunctionResultLinks(artifact, { snippets } = {}) {
  const lines = [`# ${escape(artifact.target.functionName)} 반환값의 소스 연결`, '',
    '결과: **선언·직접 호출·결과를 받는 변수·이후 사용 위치를 연결했다. 이 호출이 실행되거나 외부에 반영됐다는 판정은 아니다.**', '',
    `함수 선언: ${sourceText(artifact.functionDeclaration, artifact)}`, '',
    `선택한 호출: ${sourceText(artifact.call, artifact)}`, '',
    '| 인수 순서 | 호출에 적힌 값 식 | 함수 매개변수 |', '|---:|---|---|'];
  for (const argument of artifact.arguments) lines.push(`| ${argument.index + 1} | ${escape(snippets?.(argument.expression) ?? '원본에서 확인')} (${sourceText(argument.expression, artifact)}) | ${argument.parameter ? `${escape(snippets?.(argument.parameter) ?? '원본에서 확인')} (${sourceText(argument.parameter, artifact)})` : '대응 매개변수 없음'} |`);
  lines.push('', '| 반환 속성 | 결과를 받는 변수 | 선언 위치 |', '|---|---|---|');
  for (const connection of artifact.connections) lines.push(`| ${connection.property === null ? '결과 전체' : escape(connection.property)} | ${escape(connection.localName)} | ${sourceText(connection.declaration, artifact)} |`);
  lines.push('', '외부 호출 인자에 적힌 직접 사용:', '', '| 변수 | 호출 대상 식 | 인자 속성 | 위치 | 조건 |', '|---|---|---|---|---|');
  let direct = 0;
  for (const connection of artifact.connections) for (const use of connection.uses.filter(use => use.kind === 'direct-payload-property')) {
    direct++;
    lines.push(`| ${escape(connection.localName)} | ${escape(snippets?.(use.callee) ?? '원본에서 확인')} | ${use.argumentIndex + 1}번째 인자의 ${escape(use.payloadName)} | ${sourceText(use.source, artifact)} | ${use.nestedFunction ? '다른 함수에 캡처됨; ' : ''}${use.optionalCall ? '선택적 호출; ' : ''}도달·실행은 미확인 |`);
  }
  if (!direct) lines.push('| — | 직접 호출 인자의 일반 속성 사용 없음 | — | — | — |');
  lines.push('', '호출을 둘러싼 소스 문맥:', '',
    '아래는 소스에 적힌 분기와 선행 문장이다. 각 조건을 통과해도 호출의 실행을 보증하지 않는다. 반복해서 읽는 속성 값이 같다고 가정하거나 선행 return의 조건을 이후 시점의 조건으로 바꾸지 않는다.', '');
  const text = node => escape(snippets?.(node) ?? '원본에서 확인');
  const accepts = { truthy: '참으로 취급되는 분기', falsy: '거짓으로 취급되는 분기', nullish: 'null 또는 undefined인 분기' };
  const path = context => context.guards.length ? context.guards.map(item => `${text(item.condition)} → ${accepts[item.accepts]} (${sourceText(item.condition, artifact)})`).join('; 다음에 ') : '이 함수 안의 상위 if·삼항·단락 분기가 없음';
  const context = artifact.callContext;
  lines.push(`- 결과 계산 호출의 분기: ${path(context)}.`);
  lines.push(`- 소스상 안쪽부터 둘러싼 함수: ${context.enclosingFunctions.map(fn => `${escape(fn.name ?? '이름 없는 함수')} (${sourceText(fn.source, artifact)})`).join(' → ') || '없음'}. 함수가 호출되는 순서와 횟수는 미확인이다.`);
  for (const item of context.boundaries) lines.push(`- 계산 호출을 둘러싼 별도 실행 경계: ${escape(item.kind)} (${sourceText(item.source, artifact)}).`);
  lines.push('', '결과 계산 호출보다 앞에 적힌 같은 함수의 문장:', '', '| 선행 문장 | 위치 | 바로 적힌 종료 구문 |', '|---|---|---|');
  for (const statement of context.precedingStatements) {
    const exits = statement.immediateExits;
    lines.push(`| ${text(statement.source)} | ${sourceText(statement.source, artifact)} | ${exits ? exits.branches.map(branch => `${text(exits.condition)} → ${accepts[branch.accepts]}에 ${escape(branch.kind)} 구문 (${sourceText(branch.source, artifact)})`).join('; ') : '별도로 판정하지 않음'} |`);
  }
  if (!context.precedingStatements.length) lines.push('| 없음 | — | — |');
  if (context.precedingDeclarators.length) lines.push('', '같은 선언문 안에서 먼저 적힌 변수 선언:', '', ...context.precedingDeclarators.map(row => `- ${text(row)} (${sourceText(row, artifact)})`));
  const sites = new Map();
  for (const connection of artifact.connections) for (const use of connection.uses.filter(use => use.kind === 'direct-payload-property')) {
    const key = `${use.call.start}:${use.call.end}`;
    if (!sites.has(key)) sites.set(key, { use, fields: [] });
    sites.get(key).fields.push(`${escape(connection.localName)} → ${escape(use.payloadName)}`);
  }
  lines.push('', '| 사용하는 호출 | 함께 전달하도록 적힌 값 | 소스 분기 경로 |', '|---|---|---|');
  for (const { use, fields } of sites.values()) lines.push(`| ${text(use.callee)} (${sourceText(use.call, artifact)}) | ${fields.join(', ')} | ${path(use.context)} |`);
  if (!sites.size) lines.push('| 없음 | — | — |');
  const knownStatements = new Set(context.precedingStatements.map(row => row.source.start));
  knownStatements.add(artifact.resultDeclaration.start);
  // A variable statement includes the `const` keyword, unlike its declaration.
  const extras = new Map(), boundaries = new Map();
  for (const { use } of sites.values()) {
    for (const row of use.context.precedingStatements) if (!knownStatements.has(row.source.start) && !(row.declarations?.length === 1 && row.declarations[0].start === artifact.resultDeclaration.start)) extras.set(`${row.source.start}:${row.source.end}`, row);
    for (const row of use.context.boundaries) boundaries.set(`${row.kind}:${row.source.start}`, row);
  }
  if (extras.size) lines.push('', '사용 지점의 추가 선행 문장(위 계산·바인딩 선언과 중복은 제외):', '', ...[...extras.values()].map(row => `- ${text(row.source)} (${sourceText(row.source, artifact)})`));
  if (boundaries.size) lines.push('', '사용 지점의 별도 실행 경계:', '', ...[...boundaries.values()].map(row => `- ${escape(row.kind)} (${sourceText(row.source, artifact)})`));
  lines.push('', '이 문맥은 완전한 제어 흐름 그래프가 아니다. 선행 문장·호출 대상·다른 인자·속성 계산의 예외나 변경, 반복·예외 처리, 함수 호출 여부는 실행 분석하지 않았다.');
  lines.push('', '그 밖의 참조와 덮어쓰기 불확실성:', '');
  let others = 0;
  const kinds = { 'payload-property-overwrite-uncertain': 'spread·계산 키·중복 속성 때문에 최종 값은 미확인',
    'object-prototype-setting': '일반 속성 추가가 아닌 prototype 설정', 'object-property': '객체 속성에 사용',
    'call-argument': '호출 인자로 사용', 'jsx-attribute': 'JSX 속성에 사용', 'return-value': '반환에 사용',
    'type-only': '타입에서만 사용', 'write-reference': '값을 변경하는 구문', 'other-reference': '그 밖의 사용' };
  for (const connection of artifact.connections) for (const use of connection.uses.filter(use => use.kind !== 'direct-payload-property')) {
    others++;
    lines.push(`- ${escape(connection.localName)}: ${kinds[use.kind] ?? escape(use.kind)} (${sourceText(use.source, artifact)})`);
  }
  if (!others) lines.push('- 이 결과 바인딩에는 다른 참조가 없다. 별칭 이후의 사용까지 추적했다는 뜻은 아니다.');
  lines.push('', `이 파일의 다른 직접 호출 ${artifact.otherDirectCalls.length}개, 함수의 다른 용도 참조 ${artifact.otherFunctionReferences.length}개는 이 연결의 대상 밖이다.`, '',
    '검증하지 않은 범위:', '', ...artifact.contract.notProven.map(item => `- ${escape(item)}`), '');
  return lines.join('\n');
}

export function renderPropertyLinks(artifact, { snippets } = {}) {
  const lines = [`# ${escape(artifact.target.tag)}의 파일 간 속성 연결`, '',
    '결과: **소스의 선언·매개변수 연결을 확인했다. 실행 결과를 판정한 것은 아니다.**', '',
    `부모 JSX: ${sourceText(artifact.target.source, artifact)}`, '',
    `자식 함수 선언: ${sourceText(artifact.component.source, artifact)}`, '',
    '| 부모 속성 | 원본 값 식 | 부모 위치 | 자식에서 받는 이름 | 자식 위치 |', '|---|---|---|---|---|'];
  for (const item of artifact.connections) lines.push(`| ${escape(item.property)} | ${escape(!item.provided ? '부모 JSX에 이 속성이 없음; 런타임 값은 미확인' : item.expression ? snippets?.(item.expression) ?? '원본 위치에서 확인' : '초기화 식 없는 JSX 속성')} | ${sourceText(item.from ?? artifact.target.source, artifact)} | ${escape(item.localName)} | ${sourceText(item.to, artifact)} |`);
  const defaults = artifact.connections.filter(item => item.defaultInitializer);
  if (defaults.length) lines.push('', '자식 매개변수의 기본값 식:', '', ...defaults.map(item => `- ${escape(item.localName)}: ${escape(snippets?.(item.defaultInitializer) ?? '원본에서 확인')} (${sourceText(item.defaultInitializer, artifact)}). ${escape(item.defaultScope)}.`));
  lines.push('', '자식 함수 안에서 같은 바인딩을 사용하는 위치:', '',
    '아래는 소스 참조다. 재대입·객체 변경·기본값 평가·콜백 실행을 거쳐도 부모의 값이 그대로 유지된다는 보장은 아니다.', '',
    '| 자식 변수 | 사용 형태 | 전체 사용 식 | 위치 |', '|---|---|---|---|');
  let uses = 0;
  for (const item of artifact.connections) for (const use of item.uses) {
    const label = use.kind === 'jsx-attribute' ? `<${use.tag}>의 ${use.attribute} 속성${use.direct ? '에 전달할 참조' : ' 계산식 안의 참조'}`
      : ({ 'jsx-expression': 'JSX 표현식 안의 참조', 'type-only': '타입 참조', 'write-reference': '재대입·증감', 'other-reference': '그 밖의 참조' })[use.kind];
    lines.push(`| ${escape(item.localName)} | ${escape(label)}${use.nestedFunction ? '; 다른 함수에 캡처됨' : ''} | ${escape(snippets?.(use.expression ?? use.source) ?? '원본에서 확인')} | ${sourceText(use.source, artifact)} |`);
    uses++;
  }
  if (!uses) lines.push('| — | 연결한 매개변수의 참조 없음 | — | — |');
  lines.push('', '따라간 import·export 별칭:', '');
  for (const step of artifact.component.aliasChain) lines.push(`- ${sourceText(step, artifact)}: ${escape(snippets?.(step) ?? '원본 위치에서 확인')}`);
  if (!artifact.component.aliasChain.length) lines.push('- 같은 원본 파일의 직접 선언이다.');
  lines.push('', '검증하지 않은 범위:', '', ...artifact.contract.notProven.map(item => `- ${escape(item)}`), '');
  return lines.join('\n');
}
