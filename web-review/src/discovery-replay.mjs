import { isDeepStrictEqual } from 'node:util';
import { Unsupported } from './core.mjs';
import { discoverSource, liftSourceCandidate } from './discovery.mjs';
import { discoverChange } from './change-discovery.mjs';
import { hash } from './typescript.mjs';
import { ENGINE_SHA256 } from './fingerprint.mjs';

// The caller supplies bounded UTF-8 reads. Rebuild the complete recorded page,
// then return an ordinary existing artifact, with no inherited execution claim.
export function liftDiscoveredCandidate(report, { candidateId, revision, readText } = {}) {
  if (!Number.isSafeInteger(candidateId) || candidateId < 0 || candidateId >= 4096) throw new Unsupported('후보 번호는 0~4095 정수여야 합니다.');
  if (report?.engineSha256 !== ENGINE_SHA256) throw new Unsupported('후보 목록의 엔진이 현재와 다릅니다. 다시 탐색하세요.');
  if (typeof readText !== 'function') throw new Unsupported('원본을 읽는 함수가 필요합니다.');
  const texts = new Map();
  const read = (file, limit = 2 * 1024 * 1024) => {
    if (typeof file !== 'string' || !file) throw new Unsupported('후보 목록에 원본 파일 경로가 없습니다.');
    if (!texts.has(file)) {
      const text = readText(file, limit);
      if (typeof text !== 'string' || Buffer.byteLength(text) > limit) throw new Unsupported('원본 읽기의 형식·크기 제한을 확인하세요.');
      texts.set(file, text);
    }
    if (Buffer.byteLength(texts.get(file)) > limit) throw new Unsupported('원본 읽기의 크기 제한을 초과했습니다.');
    return texts.get(file);
  };
  let replay, side;
  if (report.schema === 'web-source-discovery-1') {
    if (revision !== undefined) throw new Unsupported('단일 파일 후보 목록에는 revision을 지정하지 않습니다.');
    const selection = report.selection;
    if (!selection || !['all', 'source-spans'].includes(selection.focus)) throw new Unsupported('후보 목록의 선택 범위가 잘못됐습니다.');
    const filename = report.source?.file;
    replay = discoverSource(read(filename), { filename, kind: selection.kind, limit: selection.limit, offset: selection.offset,
      ...(selection.focus === 'source-spans' ? { focusSpans: selection.focusSpans } : {}) });
    side = replay;
  } else if (report.schema === 'web-change-discovery-1') {
    if (!['before', 'after'].includes(revision)) throw new Unsupported('변경 후보에서는 revision을 before·after 중 하나로 지정해야 합니다.');
    const before = report.before, after = report.after;
    if (!before?.selection || !after?.selection || before.selection.kind !== after.selection.kind || before.selection.limit !== after.selection.limit) throw new Unsupported('전후 후보의 선택 조건이 일치하지 않습니다.');
    const beforeFilename = before.source?.file, afterFilename = after.source?.file, patchFilename = report.patch?.file;
    replay = discoverChange(read(beforeFilename), read(afterFilename), read(patchFilename, 16 * 1024 * 1024), {
      beforeFilename, afterFilename, patchFilename, kind: before.selection.kind, limit: before.selection.limit,
      beforeOffset: before.selection.offset, afterOffset: after.selection.offset, focus: report.focus,
    });
    side = replay[revision];
  } else throw new Unsupported('후보 탐색 목록 형식이 아닙니다.');
  if (!isDeepStrictEqual(report, replay)) throw new Unsupported('원본·패치 또는 후보 목록이 변경됐습니다. 다시 탐색하세요.');
  const candidate = side.candidates[candidateId];
  if (!candidate || candidate.id !== candidateId || candidate.status !== 'lowered') throw new Unsupported('해당 페이지에서 IR 추출이 확인된 후보만 사용할 수 있습니다. 해당 번호부터 다시 탐색하세요.');
  const artifact = liftSourceCandidate(read(side.source.file), candidate.kind, candidate.target, side.source.file);
  if (hash(JSON.stringify(artifact)) !== candidate.artifactSha256) throw new Unsupported('후보와 재추출한 분석 결과가 다릅니다. 다시 탐색하세요.');
  return artifact;
}
