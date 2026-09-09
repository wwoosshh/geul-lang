import { Unsupported } from './core.mjs';
import { ENGINE_SHA256 } from './fingerprint.mjs';

// A join of independently replayed SOURCE indexes. No value substitution,
// React invocation, or claim that a later use sees the observation snapshot.
export function linkOutputProps(slice, index) {
  if (slice?.mode !== 'const-bindings-slice' || index?.mode !== 'component-prop-bindings') throw new Unsupported('const 관찰과 컴포넌트 속성 색인이 필요합니다.');
  if (slice.engineSha256 !== ENGINE_SHA256 || index.engineSha256 !== ENGINE_SHA256) throw new Unsupported('같은 현재 엔진에서 다시 추출한 분석만 연결할 수 있습니다.');
  const parents = index.sources.filter(source => source.file === '/project/' + index.entry);
  if (parents.length !== 1 || parents[0].sha256 !== slice.source.sha256 || index.target.source.file !== parents[0].file) throw new Unsupported('const 원본과 속성 색인의 부모 파일 내용이 일치하지 않습니다.');
  const span = (a, b) => a && b && a.start === b.start && a.end === b.end;
  // TypeScript normalizes source-file separators even when the CLI artifact
  // retains a native Windows path. Compare their explicit spelling canonically.
  const sameFile = (a, b) => a.replaceAll('\\', '/') === b.replaceAll('\\', '/');
  const links = [];
  for (const binding of slice.outputSources.bindings) for (const use of binding.uses) {
    if (!sameFile(use.source.file, slice.source.file) || use.kind !== 'jsx-attribute' || !use.direct || use.tag !== index.target.tag || !span(use.element, index.target.source)) continue;
    const connections = index.connections.filter(connection => connection.provided && connection.property === use.attribute && connection.expression?.file === parents[0].file && span(connection.expression, use.source));
    if (connections.length > 1) throw new Unsupported('관찰 변수에 대응하는 속성 연결이 중복됐습니다.');
    if (!connections.length) continue;
    const connection = connections[0];
    links.push({ name: binding.name, declaration: binding.declaration.source, use, property: connection.property,
      parameter: { name: connection.localName, source: connection.to }, childUses: connection.uses,
      ...(connection.defaultInitializer ? { defaultInitializer: connection.defaultInitializer } : {}) });
  }
  if (!links.length) throw new Unsupported('관찰 변수를 선택한 부모 JSX 속성에 직접 적은 참조를 찾지 못했습니다. 변환된 식·표시 밖 참조는 결합하지 않습니다.');
  const linkedProperties = new Set(links.map(row => row.property));
  return { schema: 'web-output-prop-links-1', status: 'source-indexes-linked', engineSha256: ENGINE_SHA256,
    sourceAlignment: { constFile: slice.source.file, parentFile: parents[0].file, sha256: slice.source.sha256 },
    component: index.component, links,
    unlinkedProperties: index.connections.filter(row => !linkedProperties.has(row.property)).map(row => row.property),
    truncatedOutputReferences: slice.outputSources.bindings.filter(row => row.usesTruncated).map(row => ({ name: row.name, total: row.useCount, shown: row.uses.length })),
    scope: '내용 해시가 같은 원본의 const 선언·직접 JSX 참조와 원본 프로젝트 속성 색인을 결합한 탐색 결과',
    notProven: ['const 구간 이후의 객체 변경·별칭·다른 속성 평가·해당 JSX 도달', '실제 React 속성 전달·매개변수 기본값·자식 호출', '자식 hooks·참조 사용·최종 화면·사용자 상태', '후속 위치의 값이 앞선 관찰값과 같다는 사실'],
  };
}
