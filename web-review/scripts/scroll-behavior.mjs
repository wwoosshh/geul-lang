import vm from 'node:vm';
import assert from 'node:assert/strict';
import ts from 'typescript';
import { linkJsxFlowProps } from '../src/jsx-flow.mjs';
import { parseSource, hash } from '../src/typescript.mjs';
import { observe, decode, compare } from '../src/core.mjs';
import { finiteBooleanView } from '../src/condition-view.mjs';
import { describeBooleanConditions, describeBooleanChange } from '../src/presentation.mjs';

// Case-specific orchestration of existing analyses. Selection and domain are
// supplied by the pinned corpus; behavior conditions are never authored here.
export function buildScrollBehavior(project, sink, domains, sourceLink) {
  const model = linkJsxFlowProps({ ...project, sink, assumePlainProps: true });
  const view = finiteBooleanView(model.ir, domains);
  return { model, view, text: describeBooleanConditions(view, { sourceLink }) };
}

// Independent execution oracle: transpile the exact selected parent JSX and
// child region, including the ORIGINAL props and parameter binding. Helpers
// and JSX factory are explicit normal-delivery premises, not a React renderer.
export function nativeScrollBehavior(project, model) {
  const source = project.files[project.entry], parentFile = parseSource(source, model.parent.source.file);
  let selected;
  function find(node) {
    if (node.getStart() === model.index.target.source.start && node.end === model.index.target.source.end) selected = node;
    ts.forEachChild(node, find);
  }
  find(parentFile); assert.ok(selected);
  let expression = selected;
  while (expression.parent && (ts.isParenthesizedExpression(expression.parent) || ts.isBinaryExpression(expression.parent) || ts.isConditionalExpression(expression.parent))) expression = expression.parent;
  assert.ok(model.parent.guards.every(guard => guard.source.start >= expression.getStart() && guard.source.end <= expression.end));
  const childSource = project.files[model.child.source.file.slice('/project/'.length)], child = model.child;
  const parameter = childSource.slice(model.index.component.parameter.start, model.index.component.parameter.end);
  const body = child.flow.route === 'stored-const'
    ? childSource.slice(child.prefix.source.start, child.flow.returnExpression.end) + ';'
    : `return ${childSource.slice(child.root.start, child.root.end)};`;
  const nativeSource = `function ${project.tag}(${parameter}) { ${body} }\n${source.slice(expression.getStart(), expression.end)};`;
  const script = new vm.Script(ts.transpileModule(nativeSource, { compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022 } }).outputText);
  return { nativeSource, run(inputs) {
    let element, contributed = false;
    const React = { Fragment: 'fragment', createElement(tag, props, ...children) {
      if (typeof tag === 'function') return tag(props);
      if (tag === 'button' && props?.className === 'scroll-back-to-content') { element = { tag, props }; return element; }
      if (element && children.includes(element)) contributed = true;
      return { tag };
    } };
    const environment = {
      React, ...Object.fromEntries(Object.entries(inputs).map(([name, value]) => [name, decode(value)])),
      renderSidebars: () => null, renderWelcomeScreen: false, WelcomeScreenCenterTunnel: { Out: 'Welcome' },
      MobileShapeActions: 'MobileShapeActions', Island: 'Island', FixedSideContainer: 'FixedSideContainer',
      SCROLLBAR_WIDTH: 0, SCROLLBAR_MARGIN: 0, app: { scene: { getNonDeletedElementsMap: () => new Map() } },
      elements: [], UIOptions: {}, actionManager: { renderAction: () => null }, setAppState: () => {}, renderToolbar: () => null,
      renderAppTopBar: () => null, renderJSONExportDialog: () => null, renderImageExportDialog: () => null,
      onPenModeToggle: () => {}, renderTopLeftUI: () => null, renderTopRightUI: () => null, t: key => key,
    };
    try { script.runInNewContext(environment, { timeout: 100 }); return { kind: 'value', value: contributed }; }
    catch (error) { if (error.name === 'TypeError') return { kind: 'throw', name: 'TypeError' }; throw error; }
  } };
}

function inputsIn(domains) {
  return Object.entries(domains).reduce((rows, [name, values]) => rows.flatMap(row => values.map(value => ({ ...row, [name]: value }))), [{}]);
}

export function verifyScrollBehavior(project, result, domains) {
  const native = nativeScrollBehavior(project, result.model);
  const rows = inputsIn(domains);
  for (const inputs of rows) assert.deepEqual(native.run(inputs), observe(result.model.ir, inputs));
  // Nullish state and parent guard must retain short-circuit exception order.
  const boundaries = inputsIn({ ...domains, appState: [null, { $value: 'undefined' }] });
  for (const inputs of boundaries) assert.deepEqual(native.run(inputs), observe(result.model.ir, inputs));
  return { nativeExecutions: rows.length + boundaries.length, domainInputs: rows.length,
    boundaryInputs: boundaries.length, nativeSource: native.nativeSource };
}

export function probeScrollChanges(project, sink, domains, sourceLink, baseline) {
  const childFile = baseline.model.child.source.file.slice('/project/'.length), source = project.files[childFile];
  const file = parseSource(source, childFile), initializers = new Map();
  function find(node) { if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) initializers.set(node.name.text, node.initializer); ts.forEachChild(node, find); }
  find(file);
  const ready = initializers.get('shouldRenderScrollBackToContent'); assert.ok(ready);
  const withoutMenu = source.replace(/&&\s*!appState\.openMenu\b/, ''); assert.notEqual(source, withoutMenu);
  const viewRestricted = source.slice(0, ready.getStart()) + `(${ready.getText(file)}) && !appState.viewModeEnabled` + source.slice(ready.end);
  const prop = baseline.model.index.connections.find(row => row.property === 'scrollBackToContentUIEnabled').expression;
  const parentSource = project.files[project.entry];
  const parentDisabled = parentSource.slice(0, prop.start) + 'false' + parentSource.slice(prop.end);
  const probes = [
    { id: 'remove-menu-guard', files: { ...project.files, [childFile]: withoutMenu } },
    { id: 'restore-view-mode-guard', files: { ...project.files, [childFile]: viewRestricted } },
    { id: 'parent-disables-scroll-ui', files: { ...project.files, [project.entry]: parentDisabled } },
  ];
  return probes.map(probe => {
    const modified = { ...project, files: probe.files };
    // Removing a guard may remove a newline. Re-select the unique button by
    // its structural selector rather than retaining its previous line number.
    const result = buildScrollBehavior(modified, { ...sink, line: undefined }, domains, source => sourceLink(source, probe.id));
    const verification = verifyScrollBehavior(modified, result, domains);
    const comparison = { ...compare(baseline.model.ir, result.model.ir, domains), domains };
    assert.equal(comparison.unknown.length, 0); assert.ok(comparison.changes.length > 0);
    assert.notEqual(result.text, baseline.text, '원본 조건을 바꾸면 표시 문서도 바뀌어야 한다.');
    // No hand-written behavior predicate. Assert only the structural change
    // the probe is intended to exercise, and compare all values to source JS.
    const fields = result.view.rules.flatMap(rule => rule.conditions.map(row => [row.name, ...row.path].join('.')));
    if (probe.id === 'remove-menu-guard') assert.ok(!fields.includes('appState.openMenu'));
    if (probe.id === 'restore-view-mode-guard') assert.ok(fields.includes('appState.viewModeEnabled'));
    if (probe.id === 'parent-disables-scroll-ui') assert.equal(result.view.present, 0);
    return { id: probe.id, synthetic: true, sourceHashes: Object.fromEntries(Object.entries(probe.files).map(([file, source]) => [file, hash(source)])),
      files: probe.files, model: result.model, view: result.view, comparison, ...verification,
      text: describeBooleanChange(comparison) + '\n\n## 수정 후 전달 조건\n\n' + result.text };
  });
}
