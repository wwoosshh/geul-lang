// These operations are valid only for primitive strings with unmodified
// standard methods. Runtime/Unicode versions are bound by fingerprint.mjs.
const definitions = Object.freeze({
  'string.trim': Object.freeze({
    method: 'trim', run: Function.call.bind(String.prototype.trim),
    evidence: 'standard-string-trim', label: '표준 문자열 trim',
    reading: '아래 원시 문자열의 양끝 공백을 표준 trim으로 제거한 결과를 사용합니다.',
    fragment: '양끝 공백 제거',
    action: '양끝 공백을 표준 trim으로 제거',
  }),
  'string.toLowerCase': Object.freeze({
    method: 'toLowerCase', run: Function.call.bind(String.prototype.toLowerCase),
    evidence: 'standard-string-to-lower-case', label: '표준 문자열 toLowerCase',
    reading: '아래 원시 문자열을 유니코드 기본 소문자 변환 규칙으로 바꿉니다. 주변 글자에 따라 결과가 달라지거나 글자 수가 늘 수 있으며, 언어권별 변환은 적용하지 않습니다.',
    fragment: '유니코드 기본 소문자 변환',
    action: '유니코드 기본 규칙으로 소문자 변환',
  }),
});
export const stringIntrinsic = name => Object.hasOwn(definitions, name) ? definitions[name] : undefined;
export const stringAssumptions = names => [...names].sort().map(name => `원시 문자열과 변경되지 않은 표준 String.prototype.${stringIntrinsic(name).method}`);
