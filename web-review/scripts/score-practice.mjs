import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { parseArgs } from 'node:util';
import { fileURLToPath } from 'node:url';
import { hash } from '../src/typescript.mjs';
import { loadPracticeData } from '../evaluation/viewer/server.mjs';
import { makePracticeScoringPacket, inspectPracticeScores, validateRubric } from '../evaluation/scoring.mjs';

const pkg = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'), root = path.dirname(pkg);
const { values, positionals } = parseArgs({ allowPositionals: true, options: {
  response: { type: 'string' }, id: { type: 'string' }, packet: { type: 'string' },
} });
assert.equal(positionals.length, 1, 'Usage: score-practice.mjs prepare --response file --id name | inspect --packet directory');
const mode = positionals[0]; assert.ok(['prepare', 'inspect'].includes(mode));
function read(file) {
  const stat = fs.statSync(file); assert.ok(stat.isFile() && stat.size <= 1024 * 1024, 'Input JSON must be a file no larger than 1 MiB.');
  const bytes = fs.readFileSync(file); return { value: JSON.parse(bytes), sha256: hash(bytes) };
}
const write = (directory, name, value) => {
  const bytes = JSON.stringify(value, null, 2) + '\n';
  fs.writeFileSync(path.join(directory, name), bytes, { flag: 'wx' }); return hash(bytes);
};
if (mode === 'prepare') {
  assert.ok(values.response && values.id && !values.packet);
  const { publicData } = loadPracticeData();
  const manifest = read(path.join(root, 'build/web-pilot/manifest.json')).value;
  const rubricFile = read(path.join(pkg, 'evaluation/rubric.json'));
  const rubric = validateRubric(rubricFile.value);
  assert.equal(manifest.rubricSha256, rubricFile.sha256, 'Regenerate pilot materials after changing the rubric.');
  assert.equal(manifest.scoringHelperSha256, hash(fs.readFileSync(path.join(pkg, 'evaluation/scoring.mjs'))));
  const response = read(path.resolve(values.response));
  const packet = makePracticeScoringPacket(response.value, { rubric, responseId: values.id, materialSha256: publicData.materialSha256 });
  const base = path.join(root, 'build/web-score-practice'); fs.mkdirSync(base, { recursive: true });
  const directory = fs.mkdtempSync(path.join(base, 'run-'));
  const privateDir = path.join(directory, 'private'); fs.mkdirSync(privateDir);
  const originalSheetSha256 = write(privateDir, 'original-sheet.json', packet.sheet);
  const originalRecordSha256 = write(privateDir, 'original-record.json', packet.privateRecord);
  write(directory, 'score-sheet.json', packet.sheet);
  const rubricSha256 = write(privateDir, 'rubric.json', rubric);
  write(privateDir, 'manifest.json', { schema: 'geul-practice-score-packet-1', mode: 'practice-only', participant: null,
    responseId: values.id, responseSha256: response.sha256, materialSha256: publicData.materialSha256,
    originalSheetSha256, originalRecordSha256, rubricSha256,
    scoringHelperSha256: manifest.scoringHelperSha256 });
  process.stdout.write(JSON.stringify({ directory, status: 'awaiting-human-scores', mode: 'practice-only', participant: null,
    instruction: '채점자에게 score-sheet.json만 제공하고 조건 정보가 있는 private 디렉터리는 가린다. 점수·근거·범위 밖 단정 여부를 사람이 입력한다.' }) + '\n');
} else {
  assert.ok(values.packet && !values.response && !values.id);
  const directory = path.resolve(values.packet), privateDir = path.join(directory, 'private');
  const manifest = read(path.join(privateDir, 'manifest.json')).value;
  assert.equal(manifest.schema, 'geul-practice-score-packet-1'); assert.equal(manifest.mode, 'practice-only'); assert.equal(manifest.participant, null);
  assert.equal(manifest.scoringHelperSha256, hash(fs.readFileSync(path.join(pkg, 'evaluation/scoring.mjs'))), 'This packet belongs to a different scoring implementation.');
  const original = read(path.join(privateDir, 'original-sheet.json'));
  const record = read(path.join(privateDir, 'original-record.json'));
  const rubric = read(path.join(privateDir, 'rubric.json'));
  assert.equal(original.sha256, manifest.originalSheetSha256); assert.equal(record.sha256, manifest.originalRecordSha256);
  assert.equal(rubric.sha256, manifest.rubricSha256);
  const recreated = makePracticeScoringPacket(record.value.originalResponse, {
    rubric: rubric.value, materialSha256: manifest.materialSha256, responseId: manifest.responseId,
  });
  assert.deepEqual(recreated.sheet, original.value);
  const sheet = read(path.join(directory, 'score-sheet.json'));
  process.stdout.write(JSON.stringify(inspectPracticeScores(sheet.value, original.value), null, 2) + '\n');
}
