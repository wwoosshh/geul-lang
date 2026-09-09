import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import ts from 'typescript';
import { liftProject } from '../src/project.mjs';
import { observe, encode, decode } from '../src/core.mjs';

// A fixed-seed grammar generator is an adversarial implementation check. Its
// programs are synthetic; they do not enlarge the real-project denominator.
test('generated control-flow and cross-file programs match native JS with fixed seed', () => {
  let state = 0x9e3779b9;
  const random = n => { state ^= state << 13; state ^= state >>> 17; state ^= state << 5; return (state >>> 0) % n; };
  const leaf = ['x', 'y', 'null', 'false', 'true', '0', '-0', '1', '""', '"value"', 'record?.value'];
  const binary = ['&&', '||', '??', '===', '!=='];
  function expression(depth) {
    if (!depth) return leaf[random(leaf.length)];
    switch (random(4)) {
      case 0: return `!(${expression(depth - 1)})`;
      case 1: return `(${expression(depth - 1)}) ${binary[random(binary.length)]} (${expression(depth - 1)})`;
      case 2: return `(${expression(depth - 1)}) ? (${expression(depth - 1)}) : (${expression(depth - 1)})`;
      default: return expression(0);
    }
  }
  const values = [null, false, true, 0, -0, '', 's', undefined, NaN];
  let comparisons = 0;
  for (let i = 0; i < 80; i++) {
    const helper = `export function helper(x: any, y: any, record: any) { const a = ${expression(2)}; if (${expression(1)}) { const x = a; return x; } return ${expression(2)}; }`;
    const main = `import { helper as call } from "./helper"; export function decide(x: any, y: any, record: any) { const first = call(x, y, record); if (first) { const y = first; return y; } return ${expression(2)}; }`;
    const artifact = liftProject({ files: { 'main.ts': main, 'helper.ts': helper }, entry: 'main.ts', functionName: 'decide' });
    const helperExports = {}, mainExports = {};
    const compile = source => ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
    vm.runInNewContext(compile(helper), { exports: helperExports }, { timeout: 100 });
    vm.runInNewContext(compile(main), { exports: mainExports, require: () => helperExports }, { timeout: 100 });
    for (let j = 0; j < 18; j++) {
      const inputs = { x: encode(values[random(values.length)]), y: encode(values[random(values.length)]), record: encode(j % 3 === 0 ? null : { value: values[random(values.length)] }) };
      const args = ['x', 'y', 'record'].map(k => decode(inputs[k]));
      let native;
      try { native = { kind: 'value', value: encode(mainExports.decide(...args)) }; }
      catch (e) { if (e.name === 'TypeError') native = { kind: 'throw', name: 'TypeError' }; else throw e; }
      assert.deepEqual(observe(artifact.ir, inputs), native, `seed program ${i}, input ${j}\n${helper}\n${main}`);
      comparisons++;
    }
  }
  assert.equal(comparisons, 1440);
});
