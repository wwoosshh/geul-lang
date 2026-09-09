import assert from 'node:assert/strict';

function sourceLines(text) {
  assert.ok(typeof text === 'string' && text.length <= 8 * 1024 * 1024);
  if (!text) return [];
  const parts = text.split('\n'), terminated = text.endsWith('\n');
  if (terminated) parts.pop();
  assert.ok(parts.length <= 262144, 'Source line limit');
  let offset = 0;
  return parts.map((value, index) => {
    const hasNewline = index < parts.length - 1 || terminated;
    const row = { text: value, terminated: hasNewline, start: offset, end: offset + value.length + Number(hasNewline) };
    offset = row.end; return row;
  });
}

// Reconstruct the entire after file from a single-file Git unified patch. A
// hunk count alone is not enough: every deleted/context line, added line, gap,
// ordering and end-of-file newline must agree with the supplied original blobs.
export function inspectUnifiedPatch(patch, beforeText, afterText) {
  assert.ok(typeof patch === 'string' && patch.length <= 16 * 1024 * 1024);
  const before = sourceLines(beforeText), after = sourceLines(afterText);
  if (patch === '') {
    assert.equal(beforeText, afterText);
    return { schema: 'checked-source-diff-1', hunks: [], removed: [], added: [], reconstructed: true };
  }
  assert.ok(patch.endsWith('\n'), 'Truncated Git patch');
  const lines = patch.split('\n'); lines.pop();
  const hunks = [], removed = [], added = [], checks = [], output = [];
  let index = 0, oldCursor = 0, fileHeaders = 0, sawOldPath = false, sawNewPath = false;
  while (index < lines.length && !lines[index].startsWith('@@')) {
    const line = lines[index++];
    if (line.startsWith('diff --git ')) { fileHeaders++; assert.equal(fileHeaders, 1, 'Only a single-file patch is accepted'); }
    else if (line.startsWith('--- ')) { assert.equal(sawOldPath, false); sawOldPath = true; }
    else if (line.startsWith('+++ ')) { assert.equal(sawNewPath, false); sawNewPath = true; }
    else assert.match(line, /^(index |old mode |new mode |new file mode |deleted file mode )/, 'Unknown or binary patch header');
  }
  assert.equal(fileHeaders, 1);
  if (index < lines.length) { assert.ok(sawOldPath && sawNewPath); }
  const plain = row => ({ text: row.text, terminated: row.terminated });
  const appendBefore = (start, end) => { for (let i = start; i < end; i++) output.push(plain(before[i])); };
  while (index < lines.length) {
    const header = lines[index++].match(/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$/);
    assert.ok(header, 'Malformed or unexpected hunk header');
    const [oldLine, oldCount, newLine, newCount] = [Number(header[1]), header[2] === undefined ? 1 : Number(header[2]),
      Number(header[3]), header[4] === undefined ? 1 : Number(header[4])];
    for (const value of [oldLine, oldCount, newLine, newCount]) assert.ok(Number.isSafeInteger(value) && value >= 0 && value <= 262144);
    assert.ok(oldCount > 0 || newCount > 0, 'Empty hunk');
    if (oldCount) assert.ok(oldLine > 0); if (newCount) assert.ok(newLine > 0);
    const oldStart = oldCount ? oldLine - 1 : oldLine, newStart = newCount ? newLine - 1 : newLine;
    assert.ok(oldStart >= oldCursor && oldStart + oldCount <= before.length);
    assert.ok(newStart + newCount <= after.length);
    appendBefore(oldCursor, oldStart);
    assert.equal(newStart, output.length, 'Inconsistent gap or hunk order');
    let oldRead = 0, newRead = 0, last;
    const hunk = { before: { line: oldLine, count: oldCount }, after: { line: newLine, count: newCount }, removed: [], added: [] };
    while (index < lines.length && (!lines[index].startsWith('@@'))) {
      const line = lines[index];
      if (line === '\\ No newline at end of file') {
        assert.ok(last && !last.marked, 'Unexpected EOF marker'); last.token.terminated = false; last.marked = true; index++; continue;
      }
      if (oldRead === oldCount && newRead === newCount) break;
      const kind = line[0]; assert.ok([' ', '-', '+'].includes(kind), 'Invalid hunk line'); index++;
      const token = { text: line.slice(1), terminated: true };
      if (kind !== '+') {
        assert.ok(oldRead < oldCount);
        const source = before[oldStart + oldRead]; assert.equal(token.text, source.text, 'Deleted/context text differs from before blob');
        checks.push({ token, source: plain(source) });
        if (kind === '-') {
          const row = { line: oldStart + oldRead + 1, start: source.start, end: source.end };
          removed.push(row); hunk.removed.push(row.line);
        }
        oldRead++;
      }
      if (kind !== '-') {
        assert.ok(newRead < newCount);
        const source = after[newStart + newRead]; assert.equal(token.text, source.text, 'Added/context text differs from after blob');
        checks.push({ token, source: plain(source) }); output.push(token);
        if (kind === '+') {
          const row = { line: newStart + newRead + 1, start: source.start, end: source.end };
          added.push(row); hunk.added.push(row.line);
        }
        newRead++;
      }
      last = { token, marked: false };
    }
    assert.equal(oldRead, oldCount, 'Truncated before hunk'); assert.equal(newRead, newCount, 'Truncated after hunk');
    oldCursor = oldStart + oldCount; hunks.push(hunk);
  }
  appendBefore(oldCursor, before.length);
  for (const check of checks) assert.deepEqual(check.token, check.source, 'EOF newline marker does not match original text');
  assert.deepEqual(output, after.map(plain), 'Patch does not reconstruct the entire after file');
  return { schema: 'checked-source-diff-1', hunks, removed, added, reconstructed: true };
}

export function intersectChangedLines(changed, spans, sourceText) {
  const lines = sourceLines(sourceText);
  assert.ok(Array.isArray(spans) && spans.length <= 256);
  for (const span of spans) assert.ok(Number.isSafeInteger(span.start) && Number.isSafeInteger(span.end)
    && span.start >= 0 && span.start < span.end && span.end <= sourceText.length, 'Invalid selected source span');
  let previousLine = 0;
  return changed.map(row => {
    assert.ok(Number.isSafeInteger(row.line) && row.line > previousLine && row.line <= lines.length);
    previousLine = row.line; const line = lines[row.line - 1];
    assert.equal(row.start, line.start); assert.equal(row.end, line.end);
    const matching = spans.map((span, index) => ({ span, index })).filter(({ span }) => span.start < line.end && span.end > line.start);
    return { ...row, selectedSpanIndices: matching.map(row => row.index),
      relation: matching.length ? 'line-intersects-selected-source' : 'line-outside-selected-source' };
  });
}
