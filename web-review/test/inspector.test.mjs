import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { fileURLToPath } from 'node:url';
import { once } from 'node:events';
import { ENGINE_SHA256 } from '../src/fingerprint.mjs';
import { hash } from '../src/typescript.mjs';
import { loadInspectorData, createInspectorServer } from '../inspector/server.mjs';

const pkg = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
function fixture(t) {
  const output = fs.mkdtempSync(path.join(os.tmpdir(), 'geul-inspector-'));
  t.after(() => {
    assert.equal(path.dirname(path.resolve(output)), path.resolve(os.tmpdir()));
    assert.match(path.basename(output), /^geul-inspector-/);
    fs.rmSync(output, { recursive: true, force: true });
  });
  const sources = Array.from({ length: 4 }, (_, index) => {
    const file = path.join(output, `source-${index}.tsx`), text = `const fixture = ${index};\n`;
    fs.writeFileSync(file, text); return { file, text, sha256: hash(text) };
  });
  const data = { schema: 'web-review-inspector-1', status: 'research-demo', engineSha256: ENGINE_SHA256,
    humanParticipants: 0, wholeBehaviorCasesVerified: 0, states: Array.from({ length: 160 }, (_, key) => ({ key })), sources };
  fs.writeFileSync(path.join(output, 'data.json'), JSON.stringify(data));
  const manifest = { schema: 'web-inspector-manifest-1', engineSha256: ENGINE_SHA256, dataSha256: hash(fs.readFileSync(path.join(output, 'data.json'))),
    producerSha256: hash(fs.readFileSync(path.join(pkg, 'scripts/prepare-inspector.mjs'))),
    producerDependencies: Object.fromEntries(['array-trace-oracle.mjs', 'check-array-traces.mjs', 'diff-spans.mjs', 'check-slice-scope.mjs'].map(file => [file, hash(fs.readFileSync(path.join(pkg, 'scripts', file)))])),
    assetHashes: Object.fromEntries(['index.html', 'style.css', 'app.mjs'].map(file => [file, hash(fs.readFileSync(path.join(pkg, 'inspector', file)))])) };
  const save = () => fs.writeFileSync(path.join(output, 'manifest.json'), JSON.stringify(manifest)); save();
  return { output, data, manifest, save };
}
async function start(t, output) {
  const server = createInspectorServer({ output });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => new Promise(resolve => server.close(resolve)));
  return server.address().port;
}
function request(port, route = '/api/data', options = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port, path: route, ...options }, response => {
      const chunks = []; response.on('data', chunk => chunks.push(chunk));
      response.on('end', () => resolve({ status: response.statusCode, headers: response.headers, text: Buffer.concat(chunks).toString('utf8') }));
    }); req.on('error', reject); req.end();
  });
}
test('inspector refuses mismatched engine, material, assets and original contents', t => {
  const f = fixture(t);
  assert.equal(loadInspectorData(f.output).data.states.length, 160);
  const digest = f.manifest.engineSha256;
  f.manifest.engineSha256 = 'stale'; f.save(); assert.throws(() => loadInspectorData(f.output), /오래됐거나 변경/);
  f.manifest.engineSha256 = digest; f.manifest.assetHashes['app.mjs'] = 'changed'; f.save(); assert.throws(() => loadInspectorData(f.output), /화면 자산/);
  f.manifest.assetHashes['app.mjs'] = hash(fs.readFileSync(path.join(pkg, 'inspector/app.mjs'))); f.save();
  for (const file of Object.keys(f.manifest.producerDependencies)) {
    const original = f.manifest.producerDependencies[file];
    f.manifest.producerDependencies[file] = 'changed'; f.save(); assert.throws(() => loadInspectorData(f.output), /근거 생성 도구/);
    f.manifest.producerDependencies[file] = original; f.save();
  }
  fs.appendFileSync(path.join(f.output, 'data.json'), ' '); assert.throws(() => loadInspectorData(f.output), /오래됐거나 변경/);
});
test('inspector serves only the fixed local read routes and reports source changes', async t => {
  const f = fixture(t), port = await start(t, f.output);
  const data = await request(port);
  assert.equal(data.status, 200); assert.equal(JSON.parse(data.text).humanParticipants, 0);
  assert.match(data.headers['content-type'], /application\/json/);
  assert.equal((await request(port, '/')).status, 200);
  assert.equal((await request(port, '/api/data', { method: 'HEAD' })).text, '');
  assert.equal((await request(port, '/api/data', { method: 'POST' })).status, 405);
  assert.equal((await request(port, '/api/data', { headers: { origin: 'https://example.invalid' } })).status, 403);
  assert.equal((await request(port, '/api/data', { headers: { host: 'example.invalid' } })).status, 403);
  assert.equal((await request(port, '/api/source?file=C:/private')).status, 404);
  fs.appendFileSync(f.data.sources[0].file, 'changed');
  assert.equal((await request(port)).status, 409);
  assert.throws(() => loadInspectorData(f.output), /원본 소스가 변경/);
});
test('inspector refuses evaluation claims and incomplete bundles', t => {
  const f = fixture(t);
  f.data.humanParticipants = 1;
  fs.writeFileSync(path.join(f.output, 'data.json'), JSON.stringify(f.data));
  f.manifest.dataSha256 = hash(fs.readFileSync(path.join(f.output, 'data.json'))); f.save();
  assert.throws(() => loadInspectorData(f.output), /고정된 연구 작업대/);
  delete f.manifest.assetHashes['style.css']; f.save();
  assert.throws(() => loadInspectorData(f.output), /자산 목록이 불완전/);
});
