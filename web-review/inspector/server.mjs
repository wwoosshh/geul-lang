import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';
import { ENGINE_SHA256 } from '../src/fingerprint.mjs';
import { hash } from '../src/typescript.mjs';

const directory = path.dirname(fileURLToPath(import.meta.url)), pkg = path.dirname(directory);
const assets = new Map([['/', ['index.html', 'text/html']], ['/index.html', ['index.html', 'text/html']], ['/style.css', ['style.css', 'text/css']], ['/app.mjs', ['app.mjs', 'text/javascript']]]);
export function loadInspectorData(output = path.resolve(pkg, '../build/web-inspector')) {
  const manifest = JSON.parse(fs.readFileSync(path.join(output, 'manifest.json'), 'utf8'));
  const bytes = fs.readFileSync(path.join(output, 'data.json'));
  if (manifest.schema !== 'web-inspector-manifest-1' || manifest.engineSha256 !== ENGINE_SHA256 || manifest.dataSha256 !== hash(bytes)
    || manifest.producerSha256 !== hash(fs.readFileSync(path.join(pkg, 'scripts/prepare-inspector.mjs')))) throw new Error('작업대 자료가 오래됐거나 변경됐습니다. npm run prepare:inspector로 다시 생성하세요.');
  for (const [file, digest] of Object.entries(manifest.assetHashes)) {
    if (!['index.html', 'style.css', 'app.mjs'].includes(file) || hash(fs.readFileSync(path.join(directory, file))) !== digest) throw new Error('화면 자산이 달라졌습니다. 작업대 자료를 다시 생성하세요.');
  }
  if (Object.keys(manifest.assetHashes).length !== 3) throw new Error('화면 자산 목록이 불완전합니다.');
  const dependencies = ['array-trace-oracle.mjs', 'check-array-traces.mjs', 'diff-spans.mjs', 'check-slice-scope.mjs'];
  if (!manifest.producerDependencies || Object.keys(manifest.producerDependencies).length !== dependencies.length
    || dependencies.some(file => manifest.producerDependencies[file] !== hash(fs.readFileSync(path.join(pkg, 'scripts', file))))) throw new Error('근거 생성 도구가 달라졌습니다. 작업대 자료를 다시 생성하세요.');
  const data = JSON.parse(bytes);
  if (data.schema !== 'web-review-inspector-1' || data.status !== 'research-demo' || data.engineSha256 !== ENGINE_SHA256 || data.humanParticipants !== 0
    || data.wholeBehaviorCasesVerified !== 0 || data.states.length !== 160 || data.sources.length !== 4) throw new Error('고정된 연구 작업대 자료가 아닙니다.');
  for (const source of data.sources) {
    if (hash(source.text) !== source.sha256 || hash(fs.readFileSync(source.file)) !== source.sha256) throw new Error('원본 소스가 변경됐습니다. 다시 분석해 작업대 자료를 생성하세요.');
  }
  return { data, manifest, bytes };
}
export function createInspectorServer({ output } = {}) {
  const loaded = loadInspectorData(output);
  return http.createServer((request, response) => {
    const headers = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'" };
    const send = (status, body, type = 'text/plain') => { response.writeHead(status, { ...headers, 'Content-Type': type + '; charset=utf-8' }); response.end(request.method === 'HEAD' ? undefined : body); };
    try {
      const host = `127.0.0.1:${response.socket.localPort}`;
      if (request.headers.host !== host || (request.headers.origin && request.headers.origin !== `http://${host}`)) return send(403, '이 작업대의 localhost 주소에서만 사용할 수 있습니다.');
      if (!['GET', 'HEAD'].includes(request.method)) return send(405, '이 작업대는 고정된 자료 읽기만 지원합니다.');
      const url = new URL(request.url, `http://${host}`);
      if (url.pathname === '/api/data') {
        for (const source of loaded.data.sources) if (hash(fs.readFileSync(source.file)) !== source.sha256) return send(409, '원본이 달라졌습니다. 작업대 자료를 다시 생성한 뒤 서버를 재시작하세요.');
        return send(200, loaded.bytes, 'application/json');
      }
      const asset = assets.get(url.pathname);
      if (!asset) return send(404, '이 작업대에 없는 자료입니다.');
      const bytes = fs.readFileSync(path.join(directory, asset[0]));
      if (hash(bytes) !== loaded.manifest.assetHashes[asset[0]]) return send(409, '화면 자산이 달라졌습니다. 자료를 다시 생성한 뒤 서버를 재시작하세요.');
      return send(200, bytes, asset[1]);
    } catch (error) { process.stderr.write(`작업대 자료 읽기 실패: ${error.message}\n`); return send(500, '자료를 읽지 못했습니다. 작업대 서버 로그를 확인하세요.'); }
  });
}
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const { values } = parseArgs({ options: { port: { type: 'string', default: '56679' } } });
  const port = Number(values.port);
  if (!Number.isInteger(port) || port < 0 || port > 65535) throw new Error('포트는 0~65535 정수여야 합니다.');
  const server = createInspectorServer();
  server.listen(port, '127.0.0.1', () => process.stdout.write(`검토 작업대: http://127.0.0.1:${server.address().port}\n`));
}
