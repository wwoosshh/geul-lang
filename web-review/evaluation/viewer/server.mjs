import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';
import { hash } from '../../src/typescript.mjs';
import { ENGINE_SHA256 } from '../../src/fingerprint.mjs';

const directory = path.dirname(fileURLToPath(import.meta.url));
const packageRoot = path.resolve(directory, '../..'), projectRoot = path.dirname(packageRoot);
export function loadPracticeData(output = path.join(projectRoot, 'build/web-pilot')) {
  const manifest = JSON.parse(fs.readFileSync(path.join(output, 'manifest.json'), 'utf8'));
  const bytes = fs.readFileSync(path.join(output, 'viewer-data.json'));
  if (manifest.status !== 'draft-not-issued' || manifest.participants !== 0 || manifest.engineSha256 !== ENGINE_SHA256 || manifest.generatorSha256 !== hash(fs.readFileSync(path.join(packageRoot, 'scripts/prepare-pilot.mjs'))) || manifest.materialHashes['viewer-data.json'] !== hash(bytes)) throw new Error('예행 검토 자료가 오래됐거나 변경됐습니다. test:corpus와 prepare:pilot을 다시 실행하세요.');
  const data = JSON.parse(bytes);
  if (manifest.tasksSha256 !== hash(fs.readFileSync(path.join(packageRoot, 'evaluation/tasks.json')))) throw new Error('과제 정의가 변경됐습니다. prepare:pilot을 다시 실행하세요.');
  if (data.status !== 'practice-only' || data.participants !== 0 || data.engineSha256 !== ENGINE_SHA256) throw new Error('예행 검토 전용 자료가 아닙니다.');
  const sources = new Map();
  const tasks = data.tasks.map((task, index) => {
    const mapped = task.sources.map((source, position) => {
      const id = `${index}-${position}`, absolute = fs.realpathSync(source.file);
      const base = fs.realpathSync(path.join(projectRoot, 'build/web-corpus'));
      const relative = path.relative(base, absolute);
      if (!relative || relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative)) throw new Error('원본 파일이 고정 사례 경계를 벗어났습니다.');
      if (hash(fs.readFileSync(absolute)) !== source.sha256) throw new Error('원본이 변경됐습니다.');
      sources.set(id, { ...source, file: absolute });
      return { id, label: source.label, revision: source.revision, sha256: source.sha256 };
    });
    const original = task.original.map(item => {
      const position = task.sources.findIndex(source => path.resolve(source.file) === path.resolve(item.file));
      if (position < 0) throw new Error('원본 식의 파일 연결이 없습니다.');
      return { expression: item.expression, line: item.line, sourceId: mapped[position].id };
    });
    return { ...task, sources: mapped, original };
  });
  return { sources, publicData: { ...data, tasks, materialSha256: hash(bytes) } };
}

export function createPracticeServer({ loaded = loadPracticeData() } = {}) {
  const assets = new Map([['/', ['index.html', 'text/html']], ['/app.mjs', ['app.mjs', 'text/javascript']], ['/session.mjs', ['session.mjs', 'text/javascript']], ['/style.css', ['style.css', 'text/css']]]);
  return http.createServer((request, response) => {
    const headers = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'" };
    const send = (status, body, type = 'text/plain') => { response.writeHead(status, { ...headers, 'Content-Type': type + '; charset=utf-8' }); response.end(request.method === 'HEAD' ? undefined : body); };
    try {
      const address = `127.0.0.1:${response.socket.localPort}`;
      if (request.headers.host !== address || (request.headers.origin && request.headers.origin !== `http://${address}`)) return send(403, 'localhost에서만 사용할 수 있습니다.');
      if (!['GET', 'HEAD'].includes(request.method)) return send(405, '이 서버는 자료 읽기만 지원합니다.');
      const url = new URL(request.url, `http://${address}`);
      if (url.pathname === '/api/data') return send(200, JSON.stringify(loaded.publicData), 'application/json');
      if (url.pathname === '/api/source') {
        const source = loaded.sources.get(url.searchParams.get('id'));
        if (!source) return send(404, '선택한 원본이 없습니다.');
        const bytes = fs.readFileSync(source.file);
        if (hash(bytes) !== source.sha256) return send(409, '원본이 변경됐습니다. 자료를 다시 생성하세요.');
        return send(200, JSON.stringify({ text: bytes.toString('utf8'), label: source.label, revision: source.revision }), 'application/json');
      }
      const asset = assets.get(url.pathname);
      if (!asset) return send(404, '자료를 찾지 못했습니다.');
      return send(200, fs.readFileSync(path.join(directory, asset[0])), asset[1]);
    } catch (error) { console.error('예행 검토 자료 읽기 실패:', error.message); return send(500, '자료를 읽지 못했습니다. 서버 로그를 확인하세요.'); }
  });
}
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const { values } = parseArgs({ options: { port: { type: 'string', default: '0' } } });
  const port = Number(values.port);
  if (!Number.isInteger(port) || port < 0 || port > 65535) throw new Error('포트는 0~65535 정수여야 합니다.');
  const server = createPracticeServer();
  server.listen(port, '127.0.0.1', () => process.stdout.write(`예행 검토 전용: http://127.0.0.1:${server.address().port}\n`));
}
