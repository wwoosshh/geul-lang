import test from 'node:test';
import assert from 'node:assert/strict';
import { indexFunctionResult } from '../src/function-results.mjs';
import { renderFunctionResultLinks } from '../src/report.mjs';
import { Unsupported } from '../src/core.mjs';

const index = (source, options = {}) => indexFunctionResult(source, { functionName: 'normalize', filename: '/source.tsx', ...options });
test('result fields, aliases, call arguments and lexical shadowing are source linked', () => {
  const source = `function normalize(input: any) { return input; }
function caller(input: any) {
  const { amount: balance, date } = normalize(input);
  sink.mutate({ amount: balance, date });
  function nested() { sink.mutate({ balance }); }
  function shadow(balance: any) { sink.mutate({ balance }); }
}`;
  const artifact = index(source);
  assert.equal(artifact.mode, 'function-result-bindings');
  assert.equal(artifact.ir, undefined);
  assert.deepEqual(artifact.connections.map(row => [row.property, row.localName]), [['amount', 'balance'], ['date', 'date']]);
  assert.equal(artifact.connections[0].uses.length, 2);
  assert.equal(artifact.connections[0].uses[0].kind, 'direct-payload-property');
  assert.equal(artifact.connections[0].uses[0].payloadName, 'amount');
  assert.equal(artifact.connections[0].uses[1].nestedFunction, true);
  assert.equal(artifact.connections[1].uses.length, 1);
  assert.equal(source.slice(artifact.arguments[0].parameter.start, artifact.arguments[0].parameter.end), 'input: any');
  const report = renderFunctionResultLinks(artifact, { snippets: node => source.slice(node.start, node.end) });
  assert.match(report, /sink.mutate/);
  assert.match(report, /도달·실행은 미확인/);
  assert.match(report, /다른 함수에 캡처됨/);
});

test('spread, computed keys, duplicate keys and prototype setters are not confirmed payload fields', () => {
  const artifact = index(`function normalize(input: any) { return input; }
const { value, __proto__ } = normalize(input);
sink({ value, ...later });
sink({ [key]: other, value });
sink({ value, value: other });
sink({ __proto__: value });
sink({ __proto__ });
sink?.take({ value });
`);
  const uses = artifact.connections[0].uses;
  assert.deepEqual(uses.map(use => use.kind), ['payload-property-overwrite-uncertain', 'payload-property-overwrite-uncertain', 'payload-property-overwrite-uncertain', 'object-prototype-setting', 'direct-payload-property']);
  assert.equal(uses.at(-1).optionalCall, true);
  assert.equal(artifact.connections[1].uses[0].kind, 'direct-payload-property');
  assert.equal(artifact.connections[1].uses[0].payloadName, '__proto__');
});

test('whole result, JSX use, function aliases and unselected calls stay separate', () => {
  const source = `function normalize(input: any) { return input; }
const value = normalize(input);
const alias = normalize;
const ignored = alias(input);
const second = normalize(other);
send(value);
const jsx = <View data={value}/>;
`;
  assert.throws(() => index(source), /정확히 한 곳/);
  const artifact = index(source, { line: 2 });
  assert.equal(artifact.connections[0].property, null);
  assert.deepEqual(artifact.connections[0].uses.map(use => use.kind), ['call-argument', 'jsx-attribute']);
  assert.equal(artifact.otherDirectCalls.length, 1);
  assert.equal(artifact.otherFunctionReferences.length, 1);
});

test('ambiguous, mutable, transformed and defaulted result bindings are refused', () => {
  for (const call of [
    'let { value } = normalize(input);', 'const { value = 1 } = normalize(input);',
    'const { ...value } = normalize(input);', 'const { nested: { value } } = normalize(input);',
    'const {} = normalize(input);', 'const { [key]: value } = normalize(input);',
    'const { a: value, b: value } = normalize(input);', 'const value = await normalize(input);',
    'const value = normalize(...inputs);', 'const value = normalize(input).field;',
  ]) assert.throws(() => index(`function normalize(input: any) { return input; } ${call}`), Unsupported, call);
  assert.throws(() => index('function normalize(x: any) {} function normalize(x: any) {} const value = normalize(input);'), Unsupported);
  assert.throws(() => index('function normalize(x: any) {} function other(normalize: any) { const value = normalize(input); }'), Unsupported);
});
