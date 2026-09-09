import { decode } from './core.mjs';
import { stringIntrinsic } from './string-intrinsics.mjs';
import { projectFiniteConditions } from './condition-view.mjs';
import { diffRecordValues } from './record-diff.mjs';
import { diffArrayValues } from './array-diff.mjs';
import { summarizeChangeConditions, summarizeChanges } from './change-rules.mjs';

function valueText(encoded) {
  if (encoded?.$opaque === 'truthy-object') return '내부 미확인 객체(참으로 취급·typeof object)';
  if (encoded?.$jsx) {
    const { tag, attributes, children } = encoded.$jsx;
    return `<${tag}> 속성 ${valueText(attributes)}, 자식 [${children.map(valueText).join(', ')}]`;
  }
  if (encoded?.$record) return `{ ${Object.entries(encoded.$record).map(([key, value]) => `${JSON.stringify(key)}: ${valueText(value)}`).join(', ')} }`;
  if (encoded?.$array) return `[${encoded.$array.map(valueText).join(', ')}]`;
  return decodedText(decode(encoded));
}
function decodedText(value) {
  if (value === undefined) return '미정(undefined)';
  if (value === null) return '빈값(null)';
  if (value === true) return '참';
  if (value === false) return '거짓';
  if (typeof value === 'string') return JSON.stringify(value);
  if (Object.is(value, -0)) return '-0';
  if (typeof value === 'number') return String(value);
  return `{ ${Object.entries(value).map(([key, item]) => `${JSON.stringify(key)}: ${decodedText(item)}`).join(', ')} }`;
}
export function describe(ir) {
  switch (ir.kind) {
    case 'literal': return valueText(ir.value);
    case 'input': return `입력 ${JSON.stringify(ir.name)}`;
    case 'local': return `저장한 값 ${JSON.stringify(ir.label ?? ir.name)}`;
    case 'let': return `먼저 (${describe(ir.value)})을 ${JSON.stringify(ir.name)}에 저장하고, ${describe(ir.body)}`;
    case 'jsx': return `<${ir.tag}>를 만들며 ${ir.attributes.map(a => `${a.name}에 (${describe(a.value)})`).join(', ')}을 전달한다. 자식은 [${ir.children.map(describe).join(', ')}]이다`;
    case 'record': return `${ir.projection === 'binding-values' ? '구간 끝의 변수 값 관찰' : ir.projection === 'jsx-property-values' ? '선택 JSX 속성의 존재·값 관찰' : '객체'} { ${ir.properties.map(p => p.spread ? `(${describe(p.value)})의 열거 가능한 자체 속성을 얕게 복사` : `${JSON.stringify(p.name)}: (${describe(p.value)})`).join(', ')} }${ir.properties.some(p => p.spread) ? ' (적힌 순서대로 계산하며 뒤 속성이 같은 이름의 앞 속성을 덮어쓴다)' : ''}`;
    case 'object-child': return `(${describe(ir.value)})을 직접 JSX 자식 자리에서 읽으며 null이 아닌 객체 값인지 확인`;
    case 'array': return `적힌 순서의 목록 [${ir.items.map(describe).join(', ')}]`;
    case 'array-filter': return `(${describe(ir.base)})의 원소를 앞에서부터 ${JSON.stringify(ir.parameterLabel)}로 받아, (${describe(ir.predicate)})이 참으로 취급되는 원소만 원래 순서대로 남긴 새 목록`;
    case 'array-concat': return `(${describe(ir.base)}) 뒤에 [${ir.arguments.map(describe).join(', ')}]의 각 목록 원소를 순서대로 이어 붙인 새 목록 (중복을 제거하지 않음)`;
    case 'intrinsic': {
      const operation = stringIntrinsic(ir.name);
      if (!operation) throw new Error('알 수 없는 내장 연산');
      return `${operation.label} (${operation.fragment})을 (${describe(ir.value)})에 적용`;
    }
    case 'access': return `(${describe(ir.base)})에서 ${ir.steps.map(s => `${s.value ? `계산한 문자열 키 (${describe(s.value)})` : JSON.stringify(s.key)}${s.optional ? '(앞값이 null·undefined면 키 계산·읽기를 생략하고 미정으로 종료)' : ''}`).join(' → ')} 읽기`;
    case 'unary': return ir.op === '!' ? `(${describe(ir.value)})의 참 취급 여부를 뒤집기` : `${ir.op}(${describe(ir.value)})`;
    case 'conditional': return `(${describe(ir.condition)})이 참으로 취급되면 (${describe(ir.yes)}), 아니면 (${describe(ir.no)})`;
    case 'binary': {
      const a = describe(ir.left), b = describe(ir.right);
      if (ir.op === '&&') return `(${a})이 거짓으로 취급되면 그 값, 아니면 (${b})`;
      if (ir.op === '||') return `(${a})이 참으로 취급되면 그 값, 아니면 (${b})`;
      if (ir.op === '??') return `(${a})이 null·undefined면 (${b}), 아니면 앞의 값`;
      const words = { '===': '엄격히 같음', '!==': '엄격히 다름', '==': 'null·undefined인지 비교', '!=': 'null·undefined가 아닌지 비교' };
      return `(${a}) ${words[ir.op] ?? ir.op} (${b})`;
    }
    default: throw new Error(`알 수 없는 표현: ${ir.kind}`);
  }
}
function observationText(obs) {
  return obs.kind === 'value' ? valueText(obs.value) : obs.kind === 'throw' ? 'TypeError 발생' : `미지원: ${obs.reason}`;
}
function changeText(before, after) {
  const arrayText = (a, b) => {
    if (!a?.$array || !b?.$array) return null;
    const delta = diffArrayValues(a, b);
    if (delta.status !== 'verified-array-observation-delta' || !delta.edits.length) return null;
    return `목록 ${delta.beforeLength}개 → ${delta.afterLength}개: ` + delta.edits.map(edit => [
      ...(edit.removed.length ? [`이전 ${edit.beforeStart + 1}번째부터 ${edit.removed.length}개 제외 ${valueText({ $array: edit.removed })}`] : []),
      ...(edit.inserted.length ? [`이후 ${edit.afterStart + 1}번째부터 ${edit.inserted.length}개 추가 ${valueText({ $array: edit.inserted })}`] : []),
    ].join('; ')).join('; ') + '. 이 목록 수정으로 이후 관찰값을 복원했다 (객체 이동·동일성 판정은 아님)';
  };
  if (before.kind === 'value' && after.kind === 'value') {
    const text = arrayText(before.value, after.value);
    if (text) return text;
  }
  if (before.kind === 'value' && after.kind === 'value' && before.value?.$record && after.value?.$record) {
    const delta = diffRecordValues(before.value, after.value);
    if (delta.status === 'verified-observation-delta' && delta.changes.length) {
      const fields = delta.changes.map(change => {
        const path = '결과' + change.path.map(key => `[${JSON.stringify(key)}]`).join('');
        if (change.kind === 'added') return `${path} 속성 추가: 없음 → ${valueText(change.after)}`;
        if (change.kind === 'removed') return `${path} 속성 삭제: ${valueText(change.before)} → 없음`;
        const array = arrayText(change.before, change.after);
        if (array) return `${path} ${array}`;
        return `${path} 값 변경: ${valueText(change.before)} → ${valueText(change.after)}`;
      });
      return fields.join('; ') + '. 그 밖의 관찰 필드 값·존재 여부는 같다';
    }
  }
  return `${observationText(before)} → ${observationText(after)}`;
}
function conditionsText(axes, names, domains) {
  return axes.flatMap((values, axis) => {
    const name = names[axis], domain = domains[name];
    if (values.length === domain.length) return [];
    const projected = projectFiniteConditions(domain, values);
    if (projected?.kind === 'record-fields-in-domain') return projected.fields.map(field => {
      const location = name + field.path.map(key => `[${JSON.stringify(key)}]`).join('');
      return field.values.length === 1 ? `${location} = ${valueText(field.values[0])}` : `${location}의 값이 [${field.values.map(valueText).join(', ')}] 중 하나`;
    });
    return [values.length === 1 ? `${name} = ${valueText(domain[values[0]])}` : `입력 ${name}의 값이 [${values.map(index => valueText(domain[index])).join(', ')}] 중 하나`];
  });
}
export function describeBooleanConditions(view, { sourceLink = () => '' } = {}) {
  const lines = [`지정 입력 ${view.checked}조합: 전달 ${view.present}개, 미전달 ${view.absent}개, 오류 ${view.errors.length}개, 미확인 ${view.unknown.length}개.`, ''];
  if (!view.rules.length) lines.push('이 입력집에는 전달되는 조합이 없습니다.');
  else {
    lines.push(view.rules.length === 1 ? '다음 조건을 모두 만족하면 전달됩니다(지정 입력집 안에서).' : '다음 묶음 중 하나를 만족하면 전달됩니다. 각 묶음 안의 조건은 모두 필요합니다(지정 입력집 안에서).', '');
    view.rules.forEach((rule, index) => {
      if (view.rules.length > 1) lines.push(`묶음 ${index + 1} (${rule.matchedRows}조합):`, '');
      if (!rule.conditions.length) lines.push('- 지정 입력집 전체');
      for (const condition of rule.conditions) {
        const name = condition.name + condition.path.map(key => /^[A-Za-z_$][\w$]*$/.test(key) ? '.' + key : `[${JSON.stringify(key)}]`).join('');
        const values = condition.values.map(valueText);
        const sources = [...new Set(condition.sources.map(sourceLink).filter(Boolean))];
        lines.push(`- \`${name}\`: ${values.length === 1 ? values[0] : values.join(' 또는 ')}${sources.length ? ' — ' + sources.join(', ') : ''}`);
      }
      lines.push('');
    });
  }
  if (view.errors.length || view.unknown.length) lines.push('오류·미확인 입력은 미전달로 분류하지 않았습니다. 상세 입력은 모델 자료를 확인하세요.', '');
  lines.push('목록에서 생략된 항목은 이 입력집의 해당 묶음 안에서 값을 바꾸어도 전달 여부가 같았습니다. 입력집 밖 값까지 불필요하다는 뜻은 아닙니다.');
  return lines.join('\n');
}
export function describeBooleanChange(result) {
  const cover = summarizeChanges(result, result.domains);
  const words = observation => observation.kind === 'throw' ? 'TypeError 발생' : observation.kind === 'value' && typeof observation.value === 'boolean'
    ? observation.value ? '전달됨' : '전달되지 않음' : null;
  if (cover.status !== 'verified-finite-cover' || !cover.rules.length || cover.rules.length > 8 || cover.rules.some(rule => !words(rule.before) || !words(rule.after))) return describeChangeSummary(result);
  const lines = ['# 변경 범위', ''];
  for (const rule of cover.rules) {
    lines.push(`버튼 생성값의 자식 자리 전달: **${words(rule.before)} → ${words(rule.after)}** (${rule.matchedRows}조합).`, '', '다음 조건을 모두 만족하는 입력에서 바뀝니다.', '');
    const conditions = conditionsText(rule.axes, cover.names, result.domains);
    lines.push(...(conditions.length ? conditions.map(text => '- ' + text) : ['- 지정 입력집 전체']), '');
  }
  lines.push(`전체 ${result.checked}조합 중 변경 ${result.changes.length}개, 동일 ${result.unchanged}개, 미확인 ${result.unknown.length}개입니다. 지정 입력집 밖 동작과 최종 화면 표시는 이 결과로 단정하지 않습니다.`);
  return lines.join('\n');
}
export function describeChangeSummary(result) {
  const summary = result.changeConditions ?? (result.domains ? summarizeChangeConditions(result, result.domains) : undefined);
  const lines = ['# 변경 범위', ''];
  if (summary?.status === 'verified-finite-change-conditions' && result.domains && summary.envelope) {
    const envelope = summary.envelope, conditions = conditionsText(envelope.axes, summary.names, result.domains);
    lines.push(`변경이 발견된 입력의 공통 범위: ${conditions.length ? conditions.join(' 그리고 ') : '명시한 입력 도메인 전체'}.`,
      `이 범위의 ${envelope.matchedRows}조합 중 변경 ${envelope.changedRows}개, 동일 ${envelope.unchangedRows}개, 미확인 ${envelope.unknownRows}개입니다.`);
    if (envelope.unchangedRows || envelope.unknownRows) lines.push('이 공통 조건만으로 변경을 단정할 수 없습니다. 나머지 입력값에 따라 결과가 같거나 미확인일 수 있습니다.');
    lines.push(`차이가 생긴 입력만 따로 묶은 정확한 조건은 ${summary.rules.length}개입니다. 이 묶음은 서로 다른 전후 결과를 포함할 수 있습니다.`,
      '공통 범위 밖에서 확인된 변경은 없지만, 미확인 입력과 도메인 밖 입력의 결과는 보증하지 않습니다.');
  } else lines.push(result.changes.length ? '변경을 확인했지만 공통 조건으로 요약하지 못했습니다. 아래 입력별 결과를 확인하세요.'
    : result.unknown.length ? '확인한 입력에서는 변경이 없지만 미확인 입력이 남아 있습니다.' : '명시한 입력 범위에서 관찰 결과의 변경을 찾지 못했습니다.');
  lines.push('', `명시한 입력 ${result.checked}조합을 비교했습니다.`,
    `값 또는 오류 발생이 바뀐 조합 ${result.changes.length}개, 같은 조합 ${result.unchanged}개, 미확인 ${result.unknown.length}개입니다.`);
  return lines.join('\n');
}
export function describeComparison(result, maximum = 20) {
  const callEntry = result.observationMeaning?.mode === 'call-entry-slice';
  const entryOutcome = observation => observation.kind === 'value'
    ? observation.value === true ? '호출 식 평가 직전에 도달' : observation.value === false ? '조기 반환으로 호출 식에 도달하지 않음' : observationText(observation)
    : observation.kind === 'throw' ? `선행 계산에서 ${observation.name} 발생` : observationText(observation);
  const transition = (before, after) => callEntry ? `${entryOutcome(before)} → ${entryOutcome(after)}` : changeText(before, after);
  const lines = [describeChangeSummary(result), '', '<details>', '<summary>입력별 변경과 관찰 계약</summary>', ''];
  if (callEntry) lines.push(`선택 호출 ${JSON.stringify(result.observationMeaning.callee)}의 평가 직전 도달 여부를 비교합니다. 함수 반환값을 비교한 것이 아닙니다.`,
    '호출 대상·인수 식은 비교 범위 밖입니다. 도달 결과가 같아도 이 식이나 실행 효과는 다를 수 있습니다.');
  if (result.observationMeaning?.mode === 'call-arguments-slice') lines.push(`선택 호출 ${JSON.stringify(result.observationMeaning.callee)}의 조기 반환·인수별 준비 값·오류를 비교합니다. callee 식별자 값 읽기의 정상 완료를 가정하며 실제 호출·반환·효과는 비교하지 않았습니다.`);
  if (result.observationBindings) lines.push(`관찰한 구간 끝의 변수: ${result.observationBindings.names.map(name => JSON.stringify(name)).join(', ')}.`);
  const summary = result.changeRules;
  if (summary?.status === 'verified-finite-cover' && result.domains) {
    lines.push(`변경 입력을 빠짐·겹침 없이 덮는 규칙 ${summary.rules.length}개를 만들었습니다.`, '');
    for (const rule of summary.rules.slice(0, maximum)) {
      const conditions = conditionsText(rule.axes, summary.names, result.domains);
      lines.push(`- ${conditions.length ? conditions.join(' 그리고 ') + '일 때' : '명시한 도메인의 모든 입력에서'}: ${transition(rule.before, rule.after)} (${rule.matchedRows}조합)`);
    }
    if (summary.rules.length > maximum) lines.push(`나머지 ${summary.rules.length - maximum}개 규칙은 JSON 결과에 있습니다.`);
    lines.push('', '각 규칙에 적지 않은 입력·객체 필드는 명시한 도메인 안에서 제한하지 않습니다. 필드로 풀어 쓴 조건도 원래 도메인에서 같은 입력을 선택하는지 확인했습니다. 미확인 입력은 이 규칙에 포함하지 않았습니다.');
    if (summary.optimization === 'work-limit') lines.push('작업량 제한에서 묶기를 멈췄지만 모든 변경 입력을 덮는지 별도로 확인했습니다.');
  } else {
    lines.push('');
    for (const item of result.changes.slice(0, maximum)) lines.push(`- ${Object.entries(item.inputs).map(([key, value]) => `${key} = ${valueText(value)}`).join(', ')}일 때: ${transition(item.before, item.after)}`);
    if (result.changes.length > maximum) lines.push(`나머지 ${result.changes.length - maximum}개 변경은 JSON 결과에 있습니다.`);
    if (summary?.status === 'not-generated') lines.push(`규칙 묶기를 생성하지 않았습니다: ${summary.reason}`);
  }
  if (result.beforeContract) lines.push(`변경 전 관찰 범위: ${result.beforeContract.observation}`, `변경 후 관찰 범위: ${result.afterContract.observation}`);
  lines.push(...(result.assumptions ?? []).map(item => `가정: ${item}`));
  lines.push('이 설명은 선택한 관찰과 명시한 입력 범위에 한정됩니다. 전체 화면·기획 의도·서버의 동작은 보증하지 않습니다.');
  lines.push('', '</details>');
  return lines.join('\n');
}
