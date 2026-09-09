// This evaluator consumes data, never source text. Its domain is an acyclic
// JSON-like value tree plus explicitly tagged JavaScript scalar values.
import { stringIntrinsic } from './string-intrinsics.mjs';
export const VERSION = 'web-expression-0.1';
export const ARRAY_PROFILE = 'dense-standard-array-1';
export const ARRAY_LIMIT = 16384;
export const STRING_LIMIT = 1024 * 1024;
export class Unsupported extends Error {
  constructor(message, location) { super(message); this.name = 'Unsupported'; this.location = location; }
}
class ComparisonWorkLimit extends Unsupported {}
function charge(budget, amount = 1, message = '실행 단계 제한을 초과했습니다.') {
  if (budget.sharedWork) {
    budget.sharedWork.remaining -= amount;
    if (budget.sharedWork.remaining < 0) throw new ComparisonWorkLimit(`비교 전체의 실행 작업량 제한(${budget.sharedWork.limit})을 초과했습니다. 부분 결과를 완료로 반환하지 않습니다.`);
  }
  budget.steps -= amount;
  if (budget.steps < 0) throw new Unsupported(message);
}
function boundedString(value) {
  if (value.length > STRING_LIMIT) throw new Unsupported('문자열·속성 이름의 길이 제한(1048576 UTF-16 코드 단위)을 초과했습니다.');
  return value;
}
function chargeStrings(budget, ...values) {
  const length = values.reduce((sum, value) => sum + (typeof value === 'string' ? value.length : 0), 0);
  charge(budget, length, '문자열 처리의 실행 작업량 제한을 초과했습니다.');
}
class EvaluationThrow extends Error {
  constructor(name) { super(name); this.exceptionName = name; }
}
class JsxValue {
  constructor(tag, attributes, children) { this.tag = tag; this.attributes = attributes; this.children = children; }
}
class OpaqueObject {}
const constructedRecords = new WeakSet();
const own = (value, key) => Object.hasOwn(value, key);
export function encode(value, depth = 0, budget = { nodes: 131072, bytes: 8 * 1024 * 1024 }, { input = false, arrays = false } = {}) {
  if (--budget.nodes < 0 || (budget.bytes -= 32) < 0) throw new Unsupported('관찰 값의 전개 크기 제한을 초과했습니다.');
  if (depth > 64) throw new Unsupported('값 중첩 제한(64)을 초과했습니다.');
  if (value instanceof OpaqueObject) {
    if (!input) throw new Unsupported('내부를 모르는 객체의 반환 데이터는 확인할 수 없습니다.');
    return { $opaque: 'truthy-object' };
  }
  const reserveText = text => {
    boundedString(text);
    // Conservative JSON upper bound, including escaped control characters and
    // repeated references to the same string in an expanded observation tree.
    if ((budget.bytes -= 6 * text.length) < 0) throw new Unsupported('관찰 값의 전개 용량 제한을 초과했습니다.');
  };
  if (value === undefined) return { $value: 'undefined' };
  if (typeof value === 'number' && !Number.isFinite(value)) return { $value: String(value) };
  if (Object.is(value, -0)) return { $value: '-0' };
  if (value instanceof JsxValue) {
    reserveText(value.tag);
    return { $jsx: { tag: value.tag, attributes: encode(value.attributes, depth + 1, budget, { input, arrays }), children: value.children.map(child => encode(child, depth + 1, budget, { input, arrays })) } };
  }
  if (typeof value === 'string') reserveText(value);
  if (value === null || ['boolean', 'number', 'string'].includes(typeof value)) return value;
  if (Array.isArray(value) && arrays) {
    if (Object.getPrototypeOf(value) !== Array.prototype || value.length > ARRAY_LIMIT) throw new Unsupported('배열은 표준 Array 프로토타입과 길이 제한(16384)을 만족해야 합니다.');
    const descriptors = Object.getOwnPropertyDescriptors(value);
    if (Object.getOwnPropertySymbols(value).length || Object.keys(descriptors).length !== value.length + 1) throw new Unsupported('배열의 빈칸·추가 속성·심볼은 지원하지 않습니다.');
    const items = [];
    for (let index = 0; index < value.length; index++) {
      const descriptor = descriptors[index];
      if (!descriptor || !own(descriptor, 'value') || !descriptor.enumerable) throw new Unsupported('배열은 빈칸·접근자 없는 열거 가능한 자체 원소여야 합니다.');
      items.push(encode(descriptor.value, depth + 1, budget, { input, arrays }));
    }
    return { $array: items };
  }
  if (typeof value !== 'object' || Array.isArray(value) ||
      ![Object.prototype, null].includes(Object.getPrototypeOf(value))) {
    throw new Unsupported('입력은 스칼라 또는 getter·Proxy·배열 없는 값 레코드여야 합니다.');
  }
  const entries = Object.entries(Object.getOwnPropertyDescriptors(value)).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0);
  if (Object.getOwnPropertySymbols(value).length || entries.some(([, d]) => !own(d, 'value'))) {
    throw new Unsupported('접근자 또는 심볼 속성은 지원하지 않습니다.');
  }
  if (entries.some(([, d]) => !d.enumerable)) throw new Unsupported('열거 불가능한 속성을 값 레코드로 바꿀 수 없습니다.');
  return { $record: Object.fromEntries(entries.map(([k, d]) => { reserveText(k); return [k, encode(d.value, depth + 1, budget, { input, arrays })]; })) };
}
export function decode(value, depth = 0, { arrays = false } = {}, budget = { nodes: 131072 }) {
  if (--budget.nodes < 0) throw new Unsupported('입력 값의 전개 크기 제한을 초과했습니다.');
  if (depth > 64) throw new Unsupported('값 중첩 제한(64)을 초과했습니다.');
  if (typeof value === 'string') return boundedString(value);
  if (value === null || typeof value === 'boolean') return value;
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Unsupported('잘못된 값 인코딩');
  if (Object.keys(value).length !== 1) throw new Unsupported('잘못된 값 태그');
  if (own(value, '$opaque')) {
    if (value.$opaque !== 'truthy-object') throw new Unsupported('알 수 없는 불투명 값 태그');
    return new OpaqueObject();
  }
  if (own(value, '$value')) {
    const tags = { undefined, NaN, Infinity, '-Infinity': -Infinity, '-0': -0 };
    if (!own(tags, value.$value)) throw new Unsupported('알 수 없는 스칼라 태그');
    return tags[value.$value];
  }
  if (own(value, '$record') && value.$record && typeof value.$record === 'object' && !Array.isArray(value.$record)) {
    return Object.assign(Object.create(null), Object.fromEntries(Object.entries(value.$record).map(([k, v]) => [boundedString(k), decode(v, depth + 1, { arrays }, budget)])));
  }
  if (own(value, '$array')) {
    if (!arrays) throw new Unsupported('배열 값은 dense-standard-array-1 프로필을 명시한 분석에서만 지원합니다.');
    // Encoding is JSON data. Check every position rather than Array.map, which
    // would silently preserve holes in an in-process malformed input.
    const items = value.$array;
    if (!Array.isArray(items) || items.length > ARRAY_LIMIT || Reflect.ownKeys(items).length !== items.length + 1) throw new Unsupported('잘못된 배열 인코딩 또는 길이 제한 초과');
    const result = [];
    for (let index = 0; index < items.length; index++) {
      const descriptor = Object.getOwnPropertyDescriptor(items, String(index));
      if (!descriptor || !own(descriptor, 'value') || !descriptor.enumerable) throw new Unsupported('배열 인코딩의 빈칸·접근자는 지원하지 않습니다.');
      result.push(decode(descriptor.value, depth + 1, { arrays }, budget));
    }
    return result;
  }
  throw new Unsupported('값은 $value 또는 $record로 인코딩해야 합니다.');
}
function scalar(value) {
  if (value !== null && typeof value === 'object') throw new Unsupported('객체 동일성·암묵적 객체 변환은 지원하지 않습니다.');
  return value;
}
function preview(value) {
  if (value instanceof OpaqueObject) return { category: 'opaque', profile: 'truthy-object' };
  if (value instanceof JsxValue) return { category: 'jsx', tag: value.tag };
  if (Array.isArray(value)) return { category: 'array', length: value.length };
  if (value !== null && typeof value === 'object') return { category: 'record', keys: Object.keys(value).slice(0, 8).map(key => key.slice(0, 80)) };
  if (typeof value === 'string' && value.length > 256) return { category: 'string-preview', prefix: value.slice(0, 256), length: value.length };
  return { category: 'scalar', value: encode(value) };
}
export const BINARY = new Set(['===', '!==', '&&', '||', '??', '<', '<=', '>', '>=', '+', '-', '*', '/', '%', '==', '!=']);
export function evaluate(node, inputs, budget = { steps: 100000 }, locals = Object.create(null)) {
  charge(budget);
  const ev = n => evaluate(n, inputs, budget, locals);
  const trace = event => {
    if (!budget.trace) return;
    if (budget.trace.length < 512) budget.trace.push({ source: node.source, ...event });
    else budget.traceTruncated = true;
  };
  switch (node.kind) {
    case 'literal': return decode(node.value, 0, { arrays: !!budget.arrays });
    case 'input':
      if (!own(inputs, node.name)) throw new Unsupported(`입력 누락: ${node.name}`);
      return inputs[node.name];
    case 'local':
      if (!own(locals, node.name)) throw new Unsupported(`지역 값 누락: ${node.name}`);
      return locals[node.name];
    case 'let': {
      const value = ev(node.value);
      trace({ event: 'bind', name: node.label ?? node.name, value: preview(value),
        ...(node.bindingRole === 'destructured-property' ? { bindingRole: node.bindingRole, bindingKey: node.bindingKey } : {}),
        ...(node.bindingRole === 'prop-equation' ? { bindingRole: node.bindingRole, provided: node.provided } : {}),
        ...(node.bindingRole === 'call-argument' ? { bindingRole: node.bindingRole, argumentIndex: node.argumentIndex } : {}) });
      return evaluate(node.body, inputs, budget, { ...locals, [node.name]: value });
    }
    case 'jsx': {
      const attributes = Object.create(null);
      for (const attribute of node.attributes) attributes[attribute.name] = ev(attribute.value);
      const children = node.children.map(ev);
      trace({ event: 'jsx', tag: node.tag, attributes: Object.fromEntries(Object.entries(attributes).map(([key, value]) => [key, preview(value)])), childCount: children.length });
      return new JsxValue(node.tag, attributes, children);
    }
    case 'array': {
      if (!budget.arrays) throw new Unsupported('배열 연산 프로필이 필요합니다.');
      if (node.items.length > ARRAY_LIMIT) throw new Unsupported('배열 길이 제한(16384)을 초과했습니다.');
      const result = node.items.map(ev);
      trace({ event: 'array', length: result.length });
      return result;
    }
    case 'array-filter':
    case 'array-concat': {
      if (!budget.arrays) throw new Unsupported('배열 연산 프로필이 필요합니다.');
      const receiver = ev(node.base), method = node.kind === 'array-filter' ? 'filter' : 'concat';
      // Member lookup happens before evaluating call arguments. A null receiver
      // therefore throws even if a later argument is outside our value model.
      if (receiver == null) {
        trace({ event: 'throw', name: 'TypeError', key: method });
        throw new EvaluationThrow('TypeError');
      }
      if (!Array.isArray(receiver)) throw new Unsupported(`${method}는 표준 배열 수신자에 한정합니다.`);
      if (node.kind === 'array-filter') {
        const result = [], length = receiver.length;
        trace({ event: 'filter-start', length, parameter: node.parameterLabel });
        for (let index = 0; index < length; index++) {
          charge(budget, 1, '배열 순회 단계 제한을 초과했습니다.');
          const value = receiver[index];
          const selected = !!evaluate(node.predicate, inputs, budget, { ...locals, [node.parameter]: value });
          trace({ event: 'filter-item', source: node.predicate.source, index, selected, value: preview(value) });
          if (selected) result.push(value);
        }
        trace({ event: 'filter-result', inputLength: length, length: result.length });
        return result;
      }
      // Finish all argument evaluations before the concat algorithm copies any
      // elements; keep shallow references, including constructedRecords marks.
      const arguments_ = node.arguments.map(ev), result = [];
      for (const [part, value] of [receiver, ...arguments_].entries()) {
        if (!Array.isArray(value)) throw new Unsupported('concat의 인수는 표준 배열에 한정합니다. 비배열 인수는 지원하지 않습니다.');
        if (result.length + value.length > ARRAY_LIMIT) throw new Unsupported('배열 길이 제한(16384)을 초과했습니다.');
        charge(budget, value.length, '배열 복사 단계 제한을 초과했습니다.');
        const start = result.length;
        for (const item of value) result.push(item);
        trace({ event: 'concat-part', part, start, length: value.length });
      }
      trace({ event: 'concat-result', length: result.length });
      return result;
    }
    case 'record': {
      const value = Object.create(null);
      for (const property of node.properties) {
        const item = ev(property.value);
        if (property.spread) {
          // CopyDataProperties reads OWN enumerable data fields, never the
          // prototype. Keep references: spreading is shallow, not encode/decode.
          if (item instanceof OpaqueObject || item instanceof JsxValue || typeof item === 'string' ||
              (item !== null && typeof item === 'object' && Object.getPrototypeOf(item) !== null)) {
            throw new Unsupported('객체 spread는 값 레코드·null·undefined·숫자·불리언에 한정합니다. 문자열·불투명 객체·JSX는 지원하지 않습니다.');
          }
          const keys = item !== null && typeof item === 'object' ? Object.keys(item) : [];
          charge(budget, keys.length, '객체 spread 복사 단계 제한을 초과했습니다.');
          trace({ event: 'record-spread', source: property.source, copied: keys.length, value: preview(item) });
          for (const key of keys) {
            const replaced = own(value, key);
            value[key] = item[key];
            trace({ event: 'record-copy-field', source: property.source, name: key.slice(0, 256),
              ...(key.length > 256 ? { nameTruncated: true } : {}), replaced, value: preview(item[key]) });
          }
          continue;
        }
        const replaced = own(value, property.name);
        value[property.name] = item;
        trace({ event: node.projection === 'binding-values' ? 'observed-binding' : node.projection === 'jsx-property-values' ? 'observed-jsx-property'
          : node.projection === 'call-argument-values' ? 'observed-call-preparation' : 'record-field', source: property.source, name: property.name, value: preview(value[property.name]) });
        if (replaced) trace({ event: 'record-overwrite', source: property.source, name: property.name });
      }
      constructedRecords.add(value);
      return value;
    }
    case 'object-child': {
      const value = ev(node.value);
      const contributed = value !== null && typeof value === 'object';
      trace({ event: 'object-child', contributed, value: preview(value) });
      return contributed;
    }
    case 'intrinsic': {
      const value = ev(node.value);
      const operation = stringIntrinsic(node.name);
      if (!operation) throw new Unsupported('알 수 없는 내장 연산');
      if (value == null) {
        trace({ event: 'throw', name: 'TypeError', key: operation.method });
        throw new EvaluationThrow('TypeError');
      }
      if (typeof value !== 'string') throw new Unsupported(`${operation.method} 관찰은 원시 문자열과 변경되지 않은 표준 메서드에 한정합니다.`);
      chargeStrings(budget, value);
      const result = boundedString(operation.run(value));
      // Case conversion may expand the output. Charge its materialization too;
      // trim cannot expand and retains its existing work accounting.
      if (operation.method === 'toLowerCase') chargeStrings(budget, result);
      trace({ event: 'intrinsic', name: node.name, input: preview(value), result: preview(result) });
      return result;
    }
    case 'access': {
      let value = ev(node.base);
      for (const step of node.steps) {
        if (value == null && step.optional) {
          trace(step.value ? { event: 'optional-stop', keySource: step.value.source, computed: true } : { event: 'optional-stop', key: step.key });
          return undefined;
        }
        // A computed key expression runs AFTER the base but BEFORE a normal
        // access's null-base failure. Optional short-circuit skips it entirely.
        // Only primitive strings are admitted: no ToPropertyKey conversion or
        // user-provided coercion is inferred for objects, numbers or symbols.
        const key = step.value ? ev(step.value) : step.key;
        if (typeof key !== 'string') throw new Unsupported('계산한 속성 키는 원시 문자열에 한정합니다. 키 변환은 지원하지 않습니다.');
        if (step.value) trace({ event: 'access-key', key: preview(key), keySource: step.value.source });
        if (value == null) {
          trace({ event: 'throw', name: 'TypeError', key: key.length > 256 ? key.slice(0, 256) + '… (일부 생략)' : key });
          throw new EvaluationThrow('TypeError');
        }
        if (Array.isArray(value)) {
          if (!budget.arrays || (key !== 'length' && !/^(0|[1-9][0-9]*)$/.test(key)) || !own(value, key)) throw new Unsupported('배열 속성 읽기는 length와 존재하는 자체 원소의 문자열 인덱스에 한정합니다.');
          value = Object.getOwnPropertyDescriptor(value, key).value;
          if (step.value) trace({ event: 'computed-read', key: preview(key), value: preview(value) });
          continue;
        }
        if (typeof value !== 'object' || value instanceof JsxValue || value instanceof OpaqueObject) throw new Unsupported('속성 읽기는 값 레코드에 한정합니다. 불투명 객체의 내부는 확인하지 않습니다.');
        const descriptor = Object.getOwnPropertyDescriptor(value, key);
        if (descriptor && !own(descriptor, 'value')) throw new Unsupported('getter는 지원하지 않습니다.');
        if (!descriptor && constructedRecords.has(value)) throw new Unsupported('생성한 객체의 미존재 속성은 프로토타입 확인이 필요합니다.');
        // Missing own properties are undefined only under the explicit
        // null-prototype value-record contract; never inspect a prototype.
        value = descriptor?.value;
        if (step.value) trace({ event: 'computed-read', key: preview(key), value: preview(value) });
      }
      return value;
    }
    case 'unary': {
      const value = ev(node.value);
      if (node.op === '!') return !value;
      if (node.op === 'typeof') return typeof value;
      chargeStrings(budget, value);
      if (node.op === '+') return +scalar(value);
      if (node.op === '-') return -scalar(value);
      throw new Unsupported(`미지원 단항 연산: ${node.op}`);
    }
    case 'conditional': {
      const condition = ev(node.condition);
      trace({ event: 'branch', condition: preview(condition), conditionSource: node.condition.source,
        ...(node.condition.generatedOperation ? { generatedOperation: node.condition.generatedOperation } : {}), selected: condition ? 'yes' : 'no' });
      return condition ? ev(node.yes) : ev(node.no);
    }
    case 'binary': {
      const left = ev(node.left);
      if (['&&', '||', '??'].includes(node.op)) {
        const useRight = node.op === '&&' ? !!left : node.op === '||' ? !left : left == null;
        trace({ event: 'short-circuit', operator: node.op, left: preview(left), leftSource: node.left.source, evaluatedRight: useRight });
        return useRight ? ev(node.right) : left;
      }
      const right = ev(node.right);
      if (node.op === '==' || node.op === '!=') {
        if (node.right.kind !== 'literal' || node.right.value !== null) throw new Unsupported('느슨한 비교는 우변 null만 지원합니다.');
        return node.op === '==' ? left == null : left != null;
      }
      if (node.op === '===' || node.op === '!==') {
        const leftObject = left !== null && typeof left === 'object';
        const rightObject = right !== null && typeof right === 'object';
        if (leftObject && rightObject) throw new Unsupported('객체끼리의 동일성 비교는 지원하지 않습니다.');
        if (typeof left === 'string' && typeof right === 'string') chargeStrings(budget, left, right);
        // A record and a scalar have different types; no coercion or identity
        // assumption is needed to determine strict equality.
        return node.op === '===' ? left === right : left !== right;
      }
      scalar(left); scalar(right);
      if (node.op === '+' && (typeof left === 'string' || typeof right === 'string')) {
        // Scalar-only ToString is unambiguous here. Refuse excessive growth
        // BEFORE concatenating, including repeated local-value doubling.
        const a = String(left), b = String(right);
        if (a.length + b.length > STRING_LIMIT) throw new Unsupported('문자열 연결 결과의 길이 제한을 초과했습니다.');
        chargeStrings(budget, a, b);
        return a + b;
      }
      chargeStrings(budget, left, right);
      switch (node.op) {
        case '===': return left === right;
        case '!==': return left !== right;
        case '<': return left < right;
        case '<=': return left <= right;
        case '>': return left > right;
        case '>=': return left >= right;
        case '+': return left + right;
        case '-': return left - right;
        case '*': return left * right;
        case '/': return left / right;
        case '%': return left % right;
        default: throw new Unsupported(`미지원 이항 연산: ${node.op}`);
      }
    }
    default: throw new Unsupported(`알 수 없는 IR 노드: ${node.kind}`);
  }
}
function observeWithWork(ir, encodedInputs, { trace = false } = {}, sharedWork) {
  const arrays = ir.valueProfile === ARRAY_PROFILE;
  const budget = { steps: 100000, arrays, sharedWork, ...(trace ? { trace: [] } : {}) };
  const finish = result => trace ? { ...result, trace: budget.trace, traceTruncated: !!budget.traceTruncated } : result;
  try {
    if (!encodedInputs || typeof encodedInputs !== 'object' || Array.isArray(encodedInputs)) throw new Unsupported('입력은 이름에서 인코딩된 값으로 가는 JSON 객체여야 합니다.');
    const inputs = Object.fromEntries(Object.entries(encodedInputs).map(([key, value]) => [key, decode(value, 0, { arrays })]));
    return finish({ kind: 'value', value: encode(evaluate(ir, inputs, budget), 0, undefined, { arrays }) });
  } catch (error) {
    if (error instanceof ComparisonWorkLimit) throw error;
    if (error instanceof EvaluationThrow) return finish({ kind: 'throw', name: error.exceptionName });
    if (error instanceof Unsupported) return finish({ kind: 'unsupported', reason: error.message });
    throw error;
  }
}
export function observe(ir, encodedInputs, options) {
  return observeWithWork(ir, encodedInputs, options);
}
export function inputNames(ir, names = new Set()) {
  if (ir.kind === 'input') names.add(ir.name);
  for (const value of Object.values(ir)) {
    if (Array.isArray(value)) for (const item of value) {
      if (item?.kind) inputNames(item, names);
      else if (item?.value?.kind) inputNames(item.value, names);
    }
    if (value && typeof value === 'object' && own(value, 'kind')) inputNames(value, names);
  }
  return [...names].sort();
}
export function compare(before, after, domains, { limit = 65536, workLimit = 8000000, inputByteLimit = 128 * 1024 * 1024 } = {}) {
  if (![limit, workLimit, inputByteLimit].every(value => Number.isSafeInteger(value) && value > 0) || limit > 65536 || workLimit > 8000000 || inputByteLimit > 128 * 1024 * 1024) throw new Unsupported('비교 제한값은 양의 정수이며 기본 상한 이하여야 합니다.');
  if (!domains || typeof domains !== 'object' || Array.isArray(domains)) throw new Unsupported('비교 도메인은 이름에서 값 목록으로 가는 객체여야 합니다.');
  const names = [...new Set([...inputNames(before), ...inputNames(after)])].sort();
  if (names.join('\0') !== Object.keys(domains).sort().join('\0')) throw new Unsupported('도메인은 비교에 쓰인 모든 입력과 정확히 일치해야 합니다.');
  let count = 1;
  let meanInputBytes = 0;
  for (const name of names) {
    if (!Array.isArray(domains[name]) || !domains[name].length) throw new Unsupported(`빈 입력 도메인: ${name}`);
    for (const value of domains[name]) decode(value, 0, { arrays: before.valueProfile === ARRAY_PROFILE || after.valueProfile === ARRAY_PROFILE });
    meanInputBytes += domains[name].reduce((sum, value) => sum + Buffer.byteLength(JSON.stringify(value)), 0) / domains[name].length;
    count *= domains[name].length;
    if (!Number.isSafeInteger(count) || count > limit) throw new Unsupported(`도메인 조합 제한(${limit})을 초과했습니다.`);
  }
  let nodes = 0;
  const queue = [before, after];
  while (queue.length) {
    const node = queue.pop();
    if (++nodes * count > workLimit) throw new Unsupported(`비교 작업량 제한(${workLimit})을 초과했습니다.`);
    for (const value of Object.values(node)) {
      if (value?.kind) queue.push(value);
      if (Array.isArray(value)) for (const item of value) {
        if (item?.kind) queue.push(item);
        else if (item?.value?.kind) queue.push(item.value);
      }
    }
  }
  if (count * meanInputBytes > inputByteLimit) throw new Unsupported('입력 직적곱의 처리 용량 제한을 초과했습니다.');
  const changes = [], unknown = [];
  const sharedWork = { remaining: workLimit, limit: workLimit };
  let unchanged = 0;
  function visit(index, inputs) {
    if (index < names.length) {
      for (const value of domains[names[index]]) visit(index + 1, { ...inputs, [names[index]]: value });
      return;
    }
    const oldValue = observeWithWork(before, inputs, undefined, sharedWork), newValue = observeWithWork(after, inputs, undefined, sharedWork);
    if (oldValue.kind === 'unsupported' || newValue.kind === 'unsupported') unknown.push({ inputs, before: oldValue, after: newValue });
    else if (JSON.stringify(oldValue) !== JSON.stringify(newValue)) changes.push({ inputs, before: oldValue, after: newValue });
    else unchanged++;
  }
  visit(0, {});
  return {
    status: unknown.length ? 'inconclusive' : changes.length ? 'different-in-declared-domain' : 'equal-in-declared-domain',
    scope: '명시한 입력 값의 직적곱에 한정',
    checked: count, unchanged, changes, unknown,
    executionWork: { charged: workLimit - sharedWork.remaining, limit: workLimit, unit: 'IR 노드 방문·필터 순회·목록 및 레코드 복사·문자열 처리 코드 단위에 예약한 작업 단계' },
    assumptions: ['구조를 읽는 입력 레코드는 별칭·getter·Proxy·프로토타입이 없는 값 레코드', ...(before.valueProfile === ARRAY_PROFILE || after.valueProfile === ARRAY_PROFILE ? ['배열은 빈칸·추가 속성·접근자·Proxy·하위 클래스 없는 표준 배열이며 Array와 Object의 프로토타입·메서드·species·isConcatSpreadable을 변경하지 않음'] : []), '불투명 객체 태그를 사용한 입력은 null이 아니고 참으로 취급되며 typeof가 object라는 가정', '입력 도메인은 호출자가 정한 가정이며 TypeScript 타입으로 증명하지 않음'],
    notProven: ['도메인 밖 입력', '상태 도달 가능성', '전체 컴포넌트·DOM·서버의 동작', '오류 메시지·스택의 동일성'],
  };
}
