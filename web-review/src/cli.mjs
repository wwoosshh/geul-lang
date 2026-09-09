import fs from 'node:fs';
import path from 'node:path';
import { parseArgs } from 'node:util';
import { pathToFileURL } from 'node:url';
import { isUtf8 } from 'node:buffer';
import { compare, observe, Unsupported, VERSION } from './core.mjs';
import { liftExpression, hash } from './typescript.mjs';
import { describe, describeComparison } from './presentation.mjs';
import { liftJsxAttribute } from './jsx.mjs';
import { liftJsxProperty } from './jsx-property.mjs';
import { liftJsxGuards } from './jsx-guards.mjs';
import { liftJsxReference } from './jsx-reference.mjs';
import { liftJsxFlow } from './jsx-flow.mjs';
import { liftProject } from './project.mjs';
import { indexComponentProps } from './component-props.mjs';
import { indexFunctionResult } from './function-results.mjs';
import { previewFunctionResult, liftCallBindings } from './result-preview.mjs';
import { liftConstBindings } from './const-bindings.mjs';
import { liftCallEntry, liftCallArguments } from './call-entry.mjs';
import { discoverSource, renderDiscovery } from './discovery.mjs';
import { discoverChange, renderChangeDiscovery } from './change-discovery.mjs';
import { liftDiscoveredCandidate } from './discovery-replay.mjs';
import { liftRecord } from './record-slice.mjs';
import { liftPropExpression } from './prop-expression.mjs';
import { linkOutputProps } from './output-prop-links.mjs';
import { summarizeChanges, summarizeChangeConditions } from './change-rules.mjs';
import { renderExecution, renderPropertyLinks, renderFunctionResultLinks, renderFunctionResultPreview, renderIRStructure, renderCallEntryBoundary } from './report.mjs';
import { buildArtifactReading, renderReading } from './reading.mjs';
import { compareIRStructure } from './ir-structure.mjs';

function readText(filename, limit = 2 * 1024 * 1024) {
  const stat = fs.statSync(filename);
  if (!stat.isFile() || stat.size > limit) throw new Unsupported(`일반 파일과 크기 제한(${limit} bytes)을 확인하세요.`);
  const bytes = fs.readFileSync(filename);
  if (bytes.length > limit || !isUtf8(bytes)) throw new Unsupported('크기 제한 초과 또는 올바르지 않은 UTF-8 파일');
  return bytes.toString('utf8');
}
const readJSON = (filename, limit) => JSON.parse(readText(filename, limit));
function readArtifact(filename) {
  const artifact = readJSON(filename, 16 * 1024 * 1024);
  if (artifact.schema !== VERSION) throw new Unsupported('알 수 없는 분석 파일 형식');
  // Recompute IR from the hash-bound embedded expression: supplied IR is not
  // blindly treated as a checked translation. Original full source is separately replayed.
  let replay;
  if (artifact.mode === 'closed-pure-project') replay = readProject(artifact.manifest);
  else if (artifact.mode === 'component-prop-bindings') replay = readPropBindings(artifact.manifest);
  else if (artifact.mode === 'prop-expression-slice') replay = readPropExpression(artifact.manifest);
  else if (artifact.mode === 'function-body-slice') replay = readFunction(artifact.sourceFile, artifact.functionName);
  else if (artifact.mode === 'function-result-bindings') replay = indexFunctionResult(readText(artifact.source.file), { ...artifact.target, filename: artifact.source.file });
  else if (artifact.mode === 'const-bindings-slice') replay = liftConstBindings(readText(artifact.source.file), { ...artifact.target, filename: artifact.source.file });
  else if (artifact.mode === 'call-entry-slice') replay = liftCallEntry(readText(artifact.source.file), { ...artifact.target, filename: artifact.source.file });
  else if (artifact.mode === 'call-arguments-slice') replay = liftCallArguments(readText(artifact.source.file), { ...artifact.target, filename: artifact.source.file });
  else if (artifact.mode === 'call-bindings-slice') replay = liftCallBindings(readText(artifact.source.file), { ...artifact.target, filename: artifact.source.file });
  else if (artifact.mode === 'record-expression-slice') replay = liftRecord(readText(artifact.source.file), { ...artifact.target, filename: artifact.source.file });
  else {
    const source = readText(artifact.source.file);
    if (artifact.mode === 'expression-slice') replay = liftExpression(source, artifact.source.expression, artifact.source.file, artifact.source);
    else if (artifact.mode === 'jsx-attribute-slice') replay = liftJsxAttribute(source, { ...artifact.target, filename: artifact.source.file });
    else if (artifact.mode === 'jsx-property-slice') replay = liftJsxProperty(source, { ...artifact.target, filename: artifact.source.file });
    else if (artifact.mode === 'jsx-guard-slice') replay = liftJsxGuards(source, { ...artifact.target, prefixLine: artifact.prefix?.line, filename: artifact.source.file });
    else if (artifact.mode === 'jsx-reference-slice') replay = liftJsxReference(source, { ...artifact.target, filename: artifact.source.file });
    else if (artifact.mode === 'jsx-object-flow') replay = liftJsxFlow(source, { ...artifact.target, prefixLine: artifact.prefix?.line, filename: artifact.source.file });
    else throw new Unsupported('알 수 없는 분석 모드');
  }
  if (JSON.stringify(replay) !== JSON.stringify(artifact)) throw new Unsupported('원본 또는 분석 결과가 변경되었습니다. 다시 추출해야 합니다.');
  return artifact;
}
function readFunction(filename, functionName) {
  const sourceFile = path.resolve(filename), entry = path.basename(sourceFile);
  return { ...liftProject({ files: { [entry]: readText(sourceFile) }, entry, functionName, isolation: 'function-body' }), sourceFile };
}
function readManifest(manifestFile) {
  const manifestText = readText(manifestFile), manifest = JSON.parse(manifestText);
  const base = fs.realpathSync(path.dirname(manifestFile));
  if (!Array.isArray(manifest.files) || manifest.files.length > 32 || new Set(manifest.files).size !== manifest.files.length) throw new Unsupported('프로젝트 파일 목록이 잘못됐습니다.');
  const files = {}, seen = new Set();
  const readBound = name => {
    const filename = fs.realpathSync(path.resolve(base, name));
    const relative = path.relative(base, filename);
    const stat = fs.statSync(filename, { bigint: true });
    const identity = `${stat.dev}:${stat.ino}`;
    if (!relative || relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative) || seen.has(identity)) throw new Unsupported('프로젝트 경계 밖 또는 중복 파일');
    seen.add(identity);
    return readText(filename);
  };
  for (const name of manifest.files) files[name] = readBound(name);
  let context;
  if (manifest.context) {
    const spec = manifest.context;
    if (!Array.isArray(spec.metadata) || spec.metadata.length > 32 || typeof spec.inventory !== 'string' || typeof spec.configPath !== 'string') throw new Unsupported('프로젝트 context에는 metadata 목록, inventory 파일, configPath가 필요합니다.');
    const metadata = Object.fromEntries(spec.metadata.map(name => [name, readBound(name)]));
    context = { metadata, inventory: JSON.parse(readBound(spec.inventory)), configPath: spec.configPath };
  }
  return { files, context, spec: manifest, provenance: { manifest: path.resolve(manifestFile), manifestSha256: hash(manifestText) } };
}
function readProject(manifestFile) {
  const { files, context, spec, provenance } = readManifest(manifestFile);
  return { ...liftProject({ files, entry: spec.entry, functionName: spec.functionName, context }), ...provenance };
}
function readPropBindings(manifestFile) {
  const { files, context, spec, provenance } = readManifest(manifestFile);
  return { ...indexComponentProps({ files, context, entry: spec.entry, tag: spec.tag, line: spec.line, properties: spec.properties, includeAbsent: spec.includeAbsent }), ...provenance };
}
function readPropExpression(manifestFile) {
  const { files, context, spec, provenance } = readManifest(manifestFile);
  return { ...liftPropExpression({ files, context, entry: spec.entry, tag: spec.tag, line: spec.line, properties: spec.properties,
    includeAbsent: spec.includeAbsent, assumePlainProps: spec.assumePlainProps, sink: spec.sink }), ...provenance };
}
function sourceSnippets(artifact) {
  const cache = new Map();
  return source => {
    if (!source) return undefined;
    const record = artifact.sources?.find(s => s.file === source.file) ?? artifact.source;
    if (!record) return undefined;
    const filename = ['function-body-slice', 'call-bindings-slice'].includes(artifact.mode) ? artifact.sourceFile : source.file.startsWith('/project/') && artifact.manifest ? path.resolve(path.dirname(artifact.manifest), source.file.slice('/project/'.length)) : source.file;
    if (!cache.has(filename)) {
      const text = readText(filename);
      if (hash(text) !== record.sha256) throw new Unsupported('설명을 만드는 동안 원본 파일이 변경되었습니다.');
      cache.set(filename, text);
    }
    const snippet = cache.get(filename).slice(source.start, source.end);
    return snippet.length > 160 ? snippet.slice(0, 160) + '… (일부 생략)' : snippet;
  };
}
export function main(args) {
  const { values, positionals } = parseArgs({ args, allowPositionals: true, strict: true, options: {
    file: { type: 'string' }, function: { type: 'string' }, expression: { type: 'string' }, out: { type: 'string' }, container: { type: 'string' }, tag: { type: 'string' }, attribute: { type: 'string' }, equals: { type: 'string' }, line: { type: 'string' },
    inputs: { type: 'string' }, 'caller-inputs': { type: 'string' }, domains: { type: 'string' }, before: { type: 'string' }, after: { type: 'string' }, json: { type: 'boolean' }, trace: { type: 'boolean' },
    'prefix-line': { type: 'string' },
    'start-line': { type: 'string' }, 'end-line': { type: 'string' }, outputs: { type: 'string' },
    name: { type: 'string' }, column: { type: 'string' },
    callee: { type: 'string' },
    kind: { type: 'string' }, limit: { type: 'string' }, offset: { type: 'string' },
    patch: { type: 'string' }, 'before-offset': { type: 'string' }, 'after-offset': { type: 'string' }, focus: { type: 'string' },
    candidate: { type: 'string' }, revision: { type: 'string' },
    'array-profile': { type: 'string' },
    'props-index': { type: 'string' },
  } });
  const requireValue = name => { if (!values[name]) throw new Unsupported(`--${name}이 필요합니다.`); return values[name]; };
  let result, rendered;
  if (positionals[0] !== 'lift-candidate' && ['candidate', 'revision'].some(name => values[name] !== undefined)) throw new Unsupported('--candidate·--revision은 lift-candidate에서만 사용할 수 있습니다.');
  if (!['discover', 'discover-change'].includes(positionals[0]) && ['kind', 'limit', 'offset'].some(name => values[name] !== undefined)) throw new Unsupported('--kind·--limit·--offset은 후보 탐색에서만 사용할 수 있습니다.');
  if (positionals[0] !== 'discover-change' && ['patch', 'before-offset', 'after-offset', 'focus'].some(name => values[name] !== undefined)) throw new Unsupported('--patch·--before-offset·--after-offset·--focus는 discover-change에서만 사용할 수 있습니다.');
  if (values['array-profile'] !== undefined && positionals[0] !== 'lift-const-bindings') throw new Unsupported('--array-profile은 lift-const-bindings에서만 사용할 수 있습니다.');
  if (values['props-index'] !== undefined && !['explain', 'read'].includes(positionals[0])) throw new Unsupported('--props-index는 explain·read의 소스 연결 보기에만 사용할 수 있습니다.');
  if (values['caller-inputs'] && (values.inputs || positionals[0] !== 'explain')) throw new Unsupported('--caller-inputs는 explain에서 --inputs와 구별하여 사용해야 합니다.');
  if (positionals.length !== 1) throw new Unsupported('명령: discover | discover-change | lift-candidate | lift-expression | lift-record | lift-prop-expression | lift-jsx-attribute | lift-jsx-property | lift-jsx-guards | lift-jsx-reference | lift-jsx-flow | lift-function | lift-project | lift-const-bindings | lift-call-bindings | lift-call-entry | lift-call-arguments | index-props | index-function-result | read | run | explain | compare');
  if (positionals[0] === 'lift-candidate') {
    if (Object.keys(values).some(name => !['file', 'candidate', 'revision', 'json', 'out'].includes(name))) throw new Unsupported('lift-candidate는 file·candidate·revision·json·out만 받습니다.');
    result = liftDiscoveredCandidate(readJSON(requireValue('file'), 16 * 1024 * 1024), {
      candidateId: Number(requireValue('candidate')), ...(values.revision !== undefined ? { revision: values.revision } : {}), readText,
    });
  } else if (positionals[0] === 'discover-change') {
    if (Object.keys(values).some(name => !['before', 'after', 'patch', 'kind', 'limit', 'before-offset', 'after-offset', 'focus', 'json', 'out'].includes(name))) throw new Unsupported('discover-change는 before·after·patch·kind·limit·before-offset·after-offset·focus·json·out만 받습니다.');
    const beforeFilename = path.resolve(requireValue('before')), afterFilename = path.resolve(requireValue('after'));
    const patchFilename = path.resolve(requireValue('patch'));
    result = discoverChange(readText(beforeFilename), readText(afterFilename), readText(patchFilename, 16 * 1024 * 1024), {
      beforeFilename, afterFilename, patchFilename, ...(values.kind !== undefined ? { kind: values.kind } : {}), ...(values.limit !== undefined ? { limit: Number(values.limit) } : {}),
      ...(values.focus !== undefined ? { focus: values.focus } : {}),
      ...(values['before-offset'] !== undefined ? { beforeOffset: Number(values['before-offset']) } : {}), ...(values['after-offset'] !== undefined ? { afterOffset: Number(values['after-offset']) } : {}),
    });
    rendered = renderChangeDiscovery(result);
  } else if (positionals[0] === 'discover') {
    if (Object.keys(values).some(name => !['file', 'kind', 'limit', 'offset', 'json', 'out'].includes(name))) throw new Unsupported('discover는 file·kind·limit·offset·json·out만 받으며 입력 실행을 하지 않습니다.');
    const filename = path.resolve(requireValue('file'));
    result = discoverSource(readText(filename), { filename, ...(values.kind !== undefined ? { kind: values.kind } : {}),
      ...(values.limit !== undefined ? { limit: Number(values.limit) } : {}), ...(values.offset !== undefined ? { offset: Number(values.offset) } : {}) });
    rendered = renderDiscovery(result);
  } else if (positionals[0] === 'lift-expression') {
    const filename = path.resolve(requireValue('file'));
    result = liftExpression(readText(filename), requireValue('expression'), filename, { container: values.container });
  } else if (positionals[0] === 'lift-record') {
    const filename = path.resolve(requireValue('file'));
    result = liftRecord(readText(filename), { line: Number(requireValue('line')), filename,
      ...(values.column !== undefined ? { column: Number(values.column) } : {}) });
  } else if (positionals[0] === 'lift-call-entry' || positionals[0] === 'lift-call-arguments') {
    const filename = path.resolve(requireValue('file'));
    result = (positionals[0] === 'lift-call-entry' ? liftCallEntry : liftCallArguments)(readText(filename), { callee: requireValue('callee'), filename,
      ...(values.line !== undefined ? { line: Number(values.line) } : {}) });
  } else if (positionals[0] === 'lift-jsx-attribute') {
    const filename = path.resolve(requireValue('file'));
    result = liftJsxAttribute(readText(filename), { tag: requireValue('tag'), attribute: requireValue('attribute'), ...(values.line !== undefined ? { line: Number(values.line) } : {}), filename });
  } else if (positionals[0] === 'lift-jsx-property') {
    const filename = path.resolve(requireValue('file'));
    result = liftJsxProperty(readText(filename), { tag: requireValue('tag'), attribute: requireValue('attribute'), ...(values.line !== undefined ? { line: Number(values.line) } : {}), filename });
  } else if (positionals[0] === 'lift-const-bindings') {
    const filename = path.resolve(requireValue('file'));
    result = liftConstBindings(readText(filename), { filename, startLine: Number(requireValue('start-line')),
      endLine: Number(requireValue('end-line')), outputs: requireValue('outputs').split(',').map(name => name.trim()), arrayProfile: values['array-profile'] });
  } else if (positionals[0] === 'lift-call-bindings') {
    const filename = path.resolve(requireValue('file'));
    result = liftCallBindings(readText(filename), { functionName: requireValue('function'), filename,
      ...(values.line !== undefined ? { line: Number(values.line) } : {}) });
  } else if (positionals[0] === 'lift-function') {
    result = readFunction(requireValue('file'), requireValue('function'));
  } else if (['lift-jsx-guards', 'lift-jsx-flow'].includes(positionals[0])) {
    const filename = path.resolve(requireValue('file'));
    const lift = positionals[0] === 'lift-jsx-flow' ? liftJsxFlow : liftJsxGuards;
    result = lift(readText(filename), { tag: requireValue('tag'), attribute: values.attribute, equals: values.equals, ...(values.line !== undefined ? { line: Number(values.line) } : {}), ...(values['prefix-line'] !== undefined ? { prefixLine: Number(values['prefix-line']) } : {}), filename });
  } else if (positionals[0] === 'lift-project') {
    result = readProject(path.resolve(requireValue('file')));
  } else if (positionals[0] === 'lift-prop-expression') {
    result = readPropExpression(path.resolve(requireValue('file')));
  } else if (positionals[0] === 'lift-jsx-reference') {
    const filename = path.resolve(requireValue('file'));
    result = liftJsxReference(readText(filename), { name: requireValue('name'),
      ...(values.line !== undefined ? { line: Number(values.line) } : {}), ...(values.column !== undefined ? { column: Number(values.column) } : {}), filename });
  } else if (positionals[0] === 'index-props') {
    result = readPropBindings(path.resolve(requireValue('file')));
  } else if (positionals[0] === 'index-function-result') {
    const filename = path.resolve(requireValue('file'));
    result = indexFunctionResult(readText(filename), { functionName: requireValue('function'), filename,
      ...(values.line !== undefined ? { line: Number(values.line) } : {}) });
  } else if (positionals[0] === 'read') {
    if (values.inputs || values.domains || values.trace) throw new Unsupported('read는 입력 실행·비교가 아닌 계산 구조 보기입니다. inputs·domains·trace를 받지 않습니다.');
    const artifact = readArtifact(requireValue('file'));
    if (!artifact.ir) throw new Unsupported('소스 연결 색인에는 실행 IR이 없습니다. explain으로 연결을 확인하세요.');
    const propIndex = values['props-index'] ? readArtifact(values['props-index']) : undefined;
    const outputPropLinks = propIndex ? linkOutputProps(artifact, propIndex) : undefined;
    result = { ...buildArtifactReading(artifact), engineSha256: artifact.engineSha256, source: artifact.source ?? artifact.sources, contract: artifact.contract,
      ...(artifact.sourceLinks ? { sourceLinks: artifact.sourceLinks } : {}),
      ...(artifact.bindings ? { inputBindings: { scope: artifact.bindings.scope, inputs: artifact.bindings.inputs, notProven: artifact.bindings.notProven } } : {}),
      ...(outputPropLinks ? { outputPropLinks, propIndexManifest: propIndex.manifest, propIndexManifestSha256: propIndex.manifestSha256 } : {}) };
    rendered = renderReading(artifact, result, { snippets: sourceSnippets(artifact), outputPropLinks, propIndex, ...(propIndex ? { propSnippets: sourceSnippets(propIndex) } : {}) });
  } else if (positionals[0] === 'run' || positionals[0] === 'explain') {
    const artifact = readArtifact(requireValue('file'));
    let propIndex, outputPropLinks;
    if (values['props-index']) {
      propIndex = readArtifact(values['props-index']);
      outputPropLinks = linkOutputProps(artifact, propIndex);
    }
    if (values['caller-inputs'] && artifact.mode !== 'function-result-bindings') throw new Unsupported('--caller-inputs는 함수 결과 연결에만 사용할 수 있습니다.');
    if (['component-prop-bindings', 'function-result-bindings'].includes(artifact.mode)) {
      if (positionals[0] !== 'explain') throw new Unsupported('소스 연결 색인은 실행 모델이 아닙니다. explain으로 원본 연결을 확인하세요.');
      if (artifact.mode === 'function-result-bindings' && (values.inputs || values['caller-inputs'])) {
        const source = readText(artifact.source.file);
        if (hash(source) !== artifact.source.sha256) throw new Unsupported('설명 준비 중 원본이 변경되었습니다.');
        result = previewFunctionResult(source, { ...artifact.target, filename: artifact.source.file,
          inputs: readJSON(values.inputs ?? values['caller-inputs']), inputBoundary: values['caller-inputs'] ? 'call-arguments' : 'function-parameters' });
        const snippets = sourceSnippets(artifact);
        rendered = renderFunctionResultPreview(result, { snippets: loc => loc ? snippets({ ...loc, file: artifact.source.file }) : undefined });
      } else {
        result = artifact;
        rendered = (artifact.mode === 'component-prop-bindings' ? renderPropertyLinks : renderFunctionResultLinks)(artifact, { snippets: sourceSnippets(artifact) });
      }
    } else {
      const inputs = readJSON(requireValue('inputs'));
      result = { observation: observe(artifact.ir, inputs, { trace: values.trace || positionals[0] === 'explain' }), source: artifact.source ?? artifact.sources, scope: artifact.contract,
        ...(outputPropLinks ? { outputPropLinks, propIndexManifest: propIndex.manifest, propIndexManifestSha256: propIndex.manifestSha256 } : {}) };
      if (positionals[0] === 'explain') rendered = renderExecution(artifact, result.observation, { inputs, snippets: sourceSnippets(artifact),
        ...(outputPropLinks ? { outputPropLinks, propIndex, propSnippets: sourceSnippets(propIndex) } : {}) });
    }
  } else if (positionals[0] === 'compare') {
    const before = readArtifact(requireValue('before')), after = readArtifact(requireValue('after'));
    const bindingModes = ['const-bindings-slice', 'call-bindings-slice'];
    const bindingPair = bindingModes.includes(before.mode) && bindingModes.includes(after.mode)
      && JSON.stringify(before.observationBindings) === JSON.stringify(after.observationBindings);
    if (!before.ir || !after.ir || (before.mode !== after.mode && !bindingPair)
      || (['call-entry-slice', 'call-arguments-slice'].includes(before.mode) && before.target.callee !== after.target.callee)
      || ((bindingModes.includes(before.mode) || bindingModes.includes(after.mode)) && !bindingPair)
      || (before.mode === 'jsx-reference-slice' && before.target.name !== after.target.name) || (['jsx-attribute-slice', 'jsx-property-slice', 'jsx-guard-slice', 'jsx-object-flow', 'prop-expression-slice'].includes(before.mode) && (before.target.tag !== after.target.tag || before.target.attribute !== after.target.attribute || before.target.equals !== after.target.equals))) throw new Unsupported('비교할 실행 모델·관찰 모드·출력 변수·JSX 대상이 일치하지 않습니다.');
    const domains = readJSON(requireValue('domains'));
    const comparison = compare(before.ir, after.ir, domains);
    result = { ...comparison,
      ...(before.mode === 'call-entry-slice' ? { observationMeaning: { mode: 'call-entry-slice', callee: before.target.callee,
        boundary: 'before-callee-and-arguments' }, beforeExcludedCall: before.excludedCall, afterExcludedCall: after.excludedCall } : {}),
      ...(before.mode === 'call-arguments-slice' ? { observationMeaning: { mode: 'call-arguments-slice', callee: before.target.callee,
        boundary: 'before-invocation-with-callee-read-assumption' }, beforePreparedCall: before.preparedCall, afterPreparedCall: after.preparedCall } : {}),
      ...(bindingPair ? { observationBindings: before.observationBindings } : {}),
      changeRules: summarizeChanges(comparison, domains),
      changeConditions: summarizeChangeConditions(comparison, domains),
      structureComparison: compareIRStructure(before.ir, after.ir),
      assumptions: [...new Set([...comparison.assumptions, ...(before.contract.assumptions ?? []), ...(after.contract.assumptions ?? [])])],
      notProven: [...new Set([...comparison.notProven, ...before.contract.notProven, ...after.contract.notProven])],
      beforeContract: before.contract, afterContract: after.contract,
      beforeSource: before.source ?? before.sources, afterSource: after.source ?? after.sources, domains, domainsSha256: hash(JSON.stringify(domains)) };
    if (!values.json) {
      const beforeSnippets = sourceSnippets(before), afterSnippets = sourceSnippets(after);
      rendered = describeComparison(result) + '\n\n<details>\n<summary>계산 구조와 원본 식의 차이</summary>\n\n'
        + renderIRStructure(result.structureComparison, before, after, { beforeSnippets, afterSnippets }) + '\n\n</details>';
      if (['call-entry-slice', 'call-arguments-slice'].includes(before.mode)) rendered += '\n\n변경 전\n\n' + renderCallEntryBoundary(before, { snippets: beforeSnippets })
        + '\n\n변경 후\n\n' + renderCallEntryBoundary(after, { snippets: afterSnippets });
    }
  } else throw new Unsupported(`알 수 없는 명령: ${positionals[0]}`);
  if (values.out) {
    const output = path.resolve(values.out);
    const content = rendered && !values.json ? rendered : JSON.stringify(result, null, 2) + '\n';
    if (Buffer.byteLength(content) > 16 * 1024 * 1024) throw new Unsupported('출력 파일 제한(16 MiB)을 초과했습니다.');
    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.writeFileSync(output, content, { flag: 'wx' });
    process.stdout.write(`${output}\n`);
  } else {
    const output = values.json ? JSON.stringify(result, null, 2) : rendered ?? (result.ir ? describe(result.ir) : result.changes ? describeComparison(result) : JSON.stringify(result, null, 2));
    if (Buffer.byteLength(output) > 16 * 1024 * 1024) throw new Unsupported('출력 제한(16 MiB)을 초과했습니다.');
    process.stdout.write(output + '\n');
  }
  if (result.status === 'inconclusive' || result.observation?.kind === 'unsupported' || result.bindingObservation?.kind === 'unsupported') process.exitCode = 2;
  return result;
}
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try { main(process.argv.slice(2)); }
  catch (error) {
    process.stderr.write(JSON.stringify({ status: error instanceof Unsupported ? 'unsupported' : 'error', message: error.message, location: error.location }) + '\n');
    process.exitCode = 2;
  }
}
