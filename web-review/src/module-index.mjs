import ts from 'typescript';
import path from 'node:path';
import { Unsupported, VERSION } from './core.mjs';
import { parseSource, hash, location } from './typescript.mjs';
import { ENGINE_SHA256 } from './fingerprint.mjs';

const ROOT = '/project';
function virtual(name) {
  if (typeof name !== 'string' || name.startsWith('/') || name.includes('\\') || name.includes(':') || name.startsWith('../') || path.posix.normalize(name) !== name) throw new Unsupported(`잘못된 상대 경로: ${name}`);
  return ROOT + '/' + name;
}

// The complete tracked path inventory is separate from downloaded contents.
// Otherwise a missing .web.ts or package.json could be incorrectly treated as
// nonexistent, causing the resolver to select a different runtime module.
export function indexModules({ files, inventory, configPath }) {
  if (!Array.isArray(inventory) || inventory.length > 100000 || new Set(inventory).size !== inventory.length) throw new Unsupported('파일 목록 형식·중복·크기 오류');
  const paths = new Set(inventory.map(virtual));
  const contents = new Map();
  let size = 0;
  for (const [name, text] of Object.entries(files)) {
    const filename = virtual(name);
    if (!paths.has(filename) || typeof text !== 'string') throw new Unsupported('원본 파일은 고정 목록에 있어야 합니다.');
    size += Buffer.byteLength(text);
    if (size > 8 * 1024 * 1024) throw new Unsupported('모듈 문맥 크기 제한(8 MiB) 초과');
    contents.set(filename, text);
  }
  const directories = new Map([[ROOT, { files: [], directories: [] }]]);
  for (const filename of paths) {
    let parent = path.posix.dirname(filename);
    if (!directories.has(parent)) directories.set(parent, { files: [], directories: [] });
    directories.get(parent).files.push(path.posix.basename(filename));
    while (parent !== ROOT) {
      const grandparent = path.posix.dirname(parent);
      if (!directories.has(grandparent)) directories.set(grandparent, { files: [], directories: [] });
      const name = path.posix.basename(parent);
      if (!directories.get(grandparent).directories.includes(name)) directories.get(grandparent).directories.push(name);
      parent = grandparent;
    }
  }
  const missingReads = new Set(), readPaths = new Set();
  const host = {
    useCaseSensitiveFileNames: true,
    fileExists: filename => paths.has(filename),
    readFile: filename => {
      if (paths.has(filename) && !contents.has(filename)) missingReads.add(filename);
      if (contents.has(filename)) readPaths.add(filename);
      if (filename.endsWith('/package.json') && contents.has(filename)) {
        try { JSON.parse(contents.get(filename)); }
        catch { throw new Unsupported(`잘못된 package.json: ${filename}`); }
      }
      return contents.get(filename);
    },
    directoryExists: filename => directories.has(filename),
    getDirectories: filename => (directories.get(filename)?.directories ?? []).map(name => path.posix.join(filename, name)),
    getCurrentDirectory: () => ROOT,
    realpath: filename => filename,
    readDirectory: (filename, extensions, excludes, includes, depth) => ts.matchFiles(filename, extensions, excludes, includes, true, ROOT, depth,
      directory => directories.get(directory) ?? { files: [], directories: [] }, filename => filename),
  };
  const config = virtual(configPath);
  const json = ts.readConfigFile(config, host.readFile);
  if (json.error) throw new Unsupported(ts.flattenDiagnosticMessageText(json.error.messageText, '\n'));
  const parsed = ts.parseJsonConfigFileContent(json.config, host, path.posix.dirname(config), undefined, config);
  const errors = parsed.errors.filter(e => e.code !== 18003);
  if (errors.length || missingReads.size) throw new Unsupported(`설정 해석 미완료: ${errors.map(e => ts.flattenDiagnosticMessageText(e.messageText, '\n')).join('; ')} ${[...missingReads].join(', ')}`);
  const configReads = [...readPaths];
  const edges = [];
  for (const [filename, source] of contents) {
    if (!/\.tsx?$/.test(filename) || filename.endsWith('.d.ts')) continue;
    const file = parseSource(source, filename);
    for (const statement of file.statements) {
      if (!ts.isImportDeclaration(statement) && !ts.isExportDeclaration(statement)) continue;
      if (!statement.moduleSpecifier || !ts.isStringLiteral(statement.moduleSpecifier)) continue;
      missingReads.clear(); readPaths.clear();
      const specifier = statement.moduleSpecifier.text;
      const resolution = ts.resolveModuleName(specifier, filename, parsed.options, host);
      const target = resolution.resolvedModule?.resolvedFileName;
      const typeOnly = ts.isImportDeclaration(statement) ? !!statement.importClause?.isTypeOnly : !!statement.isTypeOnly;
      edges.push({
        source: location(statement), specifier, typeOnly,
        target: target ?? null,
        status: missingReads.size ? 'unconfirmed-metadata' : target ? contents.has(target) ? 'resolved-loaded' : 'resolved-unloaded' : 'unresolved-in-snapshot',
        metadataRead: [...readPaths], metadataMissing: [...missingReads],
      });
    }
  }
  return {
    schema: VERSION, mode: 'module-index', typescript: ts.version, engineSha256: ENGINE_SHA256,
    config: configPath, compilerOptions: parsed.options, configReads,
    inventorySha256: hash(JSON.stringify([...inventory].sort())),
    files: [...contents].map(([file, text]) => ({ file, sha256: hash(text) })), edges,
    contract: {
      observation: '고정 파일 목록·설정·제공된 package.json에서 TypeScript가 선택한 모듈 경로',
      notProven: ['선택된 함수의 실행 의미', '모듈 초기화 효과', '외부 설치 패키지', '번들러 플러그인의 추가 변환', '심볼릭 링크·서브모듈의 실제 경로', '참조 프로젝트 전체와 실제 배포 환경'],
      plugins: '설정은 데이터로만 읽으며 플러그인·scripts는 실행하지 않음',
    },
  };
}
