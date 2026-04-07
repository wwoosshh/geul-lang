/**
 * 글 Language Server
 *
 * 최소 LSP 서버 -- 진단(diagnostics)과 키워드/함수 자동완성 제공.
 * 전송: stdin/stdout JSON-RPC (표준 LSP).
 */

const {
  createConnection,
  TextDocuments,
  ProposedFeatures,
  DiagnosticSeverity,
  TextDocumentSyncKind,
  CompletionItemKind,
} = require('./vscode-languageserver/node');
const { TextDocument } = require('./vscode-languageserver-textdocument');
const { execFile } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');

// ── 연결 초기화 ──────────────────────────────────────────

const connection = createConnection(ProposedFeatures.all);
const documents = new TextDocuments(TextDocument);

let compilerPath = '';
let tempDir = os.tmpdir();

// ── 컴파일러 경로 탐색 ──────────────────────────────────

function findCompiler() {
  // 1) 설치된 네이티브컴파일러 (사용자 환경)
  const installDir = path.join(process.env.LOCALAPPDATA || '', 'geul-lang', 'bin');
  const installed = path.join(installDir, '\uB124\uC774\uD2F0\uBE0C\uCEF4\uD30C\uC77C\uB7EC.exe');
  if (fs.existsSync(installed)) return installed;

  // 2) 같은 도구 폴더 근처 (개발 환경)
  const sibling = path.resolve(__dirname, '..', '..', '\uBC30\uD3EC', '\uB124\uC774\uD2F0\uBE0C\uCEF4\uD30C\uC77C\uB7EC.exe');
  if (fs.existsSync(sibling)) return sibling;

  // 3) PATH 탐색 — geulc.exe (영문 복사본)
  try {
    const { execFileSync } = require('child_process');
    const result = execFileSync('where', ['geulc.exe'], {
      encoding: 'utf8', timeout: 3000, windowsHide: true,
    });
    const found = result.trim().split('\n')[0].trim();
    if (found && fs.existsSync(found)) return found;
  } catch (_) { /* 무시 */ }

  return '';
}

// ── 초기화 ───────────────────────────────────────────────

connection.onInitialize(() => {
  compilerPath = findCompiler();
  if (compilerPath) {
    connection.console.log(`글 LSP: 컴파일러 발견 -- ${compilerPath}`);
  } else {
    connection.console.log('글 LSP: 컴파일러를 찾지 못했습니다. 진단 기능이 비활성화됩니다.');
  }

  return {
    capabilities: {
      textDocumentSync: TextDocumentSyncKind.Full,
      completionProvider: {
        resolveProvider: false,
        triggerCharacters: ['.', '_'],
      },
    },
  };
});

// ── 진단(Diagnostics) ───────────────────────────────────

/**
 * 컴파일러 오류 출력을 LSP Diagnostic 배열로 변환한다.
 * 기대 형식: "파일명:줄:열: 오류: 메시지" 또는 "줄:열: 오류: 메시지"
 */
function parseCompilerOutput(text) {
  const diagnostics = [];
  const lines = text.split(/\r?\n/);

  for (const line of lines) {
    // "파일명:줄:열: 오류: 메시지" 또는 "줄:열: 오류: 메시지"
    let match = line.match(/(?:.*?:)?(\d+):(\d+):\s*오류:\s*(.+)/);
    if (match) {
      const lineNum = Math.max(0, parseInt(match[1], 10) - 1);
      const colNum = Math.max(0, parseInt(match[2], 10) - 1);
      const message = match[3].trim();
      diagnostics.push({
        severity: DiagnosticSeverity.Error,
        range: {
          start: { line: lineNum, character: colNum },
          end: { line: lineNum, character: colNum + 1 },
        },
        message,
        source: '글',
      });
      continue;
    }

    // "오류:" 만 있는 행 (줄/열 정보 없음)
    match = line.match(/오류:\s*(.+)/);
    if (match) {
      diagnostics.push({
        severity: DiagnosticSeverity.Error,
        range: {
          start: { line: 0, character: 0 },
          end: { line: 0, character: 1 },
        },
        message: match[1].trim(),
        source: '글',
      });
    }
  }

  return diagnostics;
}

/** debounce 타이머 맵 (URI -> timeout) */
const pendingValidations = new Map();

function scheduleValidation(doc) {
  const uri = doc.uri;
  if (pendingValidations.has(uri)) {
    clearTimeout(pendingValidations.get(uri));
  }
  pendingValidations.set(uri, setTimeout(() => {
    pendingValidations.delete(uri);
    validateDocument(doc);
  }, 500));
}

function validateDocument(doc) {
  if (!compilerPath) {
    // 컴파일러가 없으면 진단 비활성
    connection.sendDiagnostics({ uri: doc.uri, diagnostics: [] });
    return;
  }

  // 임시 파일에 현재 텍스트 기록
  const tmpFile = path.join(tempDir, `글lsp_${process.pid}.글`);
  const text = doc.getText();

  fs.writeFile(tmpFile, text, 'utf8', (writeErr) => {
    if (writeErr) {
      connection.console.log(`임시 파일 쓰기 실패: ${writeErr.message}`);
      return;
    }

    // 네이티브컴파일러 --검사 tmpFile
    execFile(compilerPath, ['--검사', tmpFile], {
      encoding: 'utf8',
      timeout: 10000,
      windowsHide: true,
    }, (err, stdout, stderr) => {
      const output = (stderr || '') + '\n' + (stdout || '');
      const diagnostics = parseCompilerOutput(output);
      connection.sendDiagnostics({ uri: doc.uri, diagnostics });

      // 임시 파일 정리
      fs.unlink(tmpFile, () => {});
    });
  });
}

// ── 문서 변경 이벤트 ────────────────────────────────────

documents.onDidChangeContent((change) => {
  scheduleValidation(change.document);
});

documents.onDidClose((event) => {
  // 파일 닫힘 -- 진단 제거
  connection.sendDiagnostics({ uri: event.document.uri, diagnostics: [] });
});

// ── 자동완성(Completion) ────────────────────────────────

/** 키워드 목록 */
const KEYWORDS = [
  // 타입
  { label: '정수', detail: 'int', kind: CompletionItemKind.Keyword },
  { label: '실수', detail: 'double', kind: CompletionItemKind.Keyword },
  { label: '문자', detail: 'char', kind: CompletionItemKind.Keyword },
  { label: '문자열', detail: 'char*', kind: CompletionItemKind.Keyword },
  { label: '참거짓', detail: 'bool (정수 별칭)', kind: CompletionItemKind.Keyword },
  { label: '공허', detail: 'void', kind: CompletionItemKind.Keyword },
  { label: '긴정수', detail: 'long', kind: CompletionItemKind.Keyword },
  { label: '참조', detail: '포인터 (*)', kind: CompletionItemKind.Keyword },
  { label: '상수', detail: 'const', kind: CompletionItemKind.Keyword },
  { label: '정적', detail: 'static', kind: CompletionItemKind.Keyword },
  { label: '외부', detail: 'extern', kind: CompletionItemKind.Keyword },

  // 구조
  { label: '묶음', detail: 'struct', kind: CompletionItemKind.Keyword },
  { label: '나열', detail: 'enum', kind: CompletionItemKind.Keyword },
  { label: '합침', detail: 'union', kind: CompletionItemKind.Keyword },
  { label: '별칭', detail: 'typedef', kind: CompletionItemKind.Keyword },

  // 제어 흐름
  { label: '이면', detail: 'if (조건이면)', kind: CompletionItemKind.Keyword },
  { label: '아니면', detail: 'else', kind: CompletionItemKind.Keyword },
  { label: '동안', detail: 'while (조건 동안)', kind: CompletionItemKind.Keyword },
  { label: '반복', detail: 'for', kind: CompletionItemKind.Keyword },
  { label: '반복하기', detail: 'do-while', kind: CompletionItemKind.Keyword },
  { label: '반환', detail: 'return', kind: CompletionItemKind.Keyword },
  { label: '탈출', detail: 'break', kind: CompletionItemKind.Keyword },
  { label: '계속', detail: 'continue', kind: CompletionItemKind.Keyword },
  { label: '갈래', detail: 'switch', kind: CompletionItemKind.Keyword },
  { label: '경우', detail: 'case', kind: CompletionItemKind.Keyword },
  { label: '기본', detail: 'default', kind: CompletionItemKind.Keyword },

  // 전처리
  { label: '포함', detail: '#include', kind: CompletionItemKind.Keyword },
  { label: '정의', detail: '#define', kind: CompletionItemKind.Keyword },
  { label: '만약정의', detail: '#ifdef', kind: CompletionItemKind.Keyword },
  { label: '만약미정의', detail: '#ifndef', kind: CompletionItemKind.Keyword },
  { label: '끝', detail: '#endif', kind: CompletionItemKind.Keyword },

  // 기타
  { label: '크기', detail: 'sizeof', kind: CompletionItemKind.Keyword },
  { label: '없음', detail: 'NULL', kind: CompletionItemKind.Keyword },
  { label: '참', detail: 'true (1)', kind: CompletionItemKind.Keyword },
  { label: '거짓', detail: 'false (0)', kind: CompletionItemKind.Keyword },

  // 가변인자
  { label: '가변목록', detail: 'va_list', kind: CompletionItemKind.Keyword },
  { label: '가변시작', detail: 'va_start', kind: CompletionItemKind.Keyword },
  { label: '가변인자', detail: 'va_arg', kind: CompletionItemKind.Keyword },
  { label: '가변끝', detail: 'va_end', kind: CompletionItemKind.Keyword },
];

/** 표준 라이브러리 함수 목록 */
const STDLIB_FUNCTIONS = [
  // 입출력 (동사형 호출 포함)
  { label: '쓰기', detail: 'printf -- 서식 출력', kind: CompletionItemKind.Function },
  { label: '쓰다', detail: '쓰기의 동사형 — "값을 쓰다."', kind: CompletionItemKind.Function },
  { label: '쓰기_줄', detail: 'puts -- 줄 출력', kind: CompletionItemKind.Function },
  { label: '파일에_쓰기', detail: 'fprintf', kind: CompletionItemKind.Function },
  { label: '버퍼에_쓰기', detail: 'snprintf', kind: CompletionItemKind.Function },
  { label: '파일_열기', detail: '파일을 모드로 열기 -> 공허 참조', kind: CompletionItemKind.Function },
  { label: '파일_닫기', detail: '파일 닫기 -> 정수', kind: CompletionItemKind.Function },
  { label: '파일_읽기', detail: 'fread 래퍼', kind: CompletionItemKind.Function },
  { label: '파일_쓰기', detail: 'fwrite 래퍼', kind: CompletionItemKind.Function },
  { label: '파일_글넣기', detail: 'fputs 래퍼', kind: CompletionItemKind.Function },
  { label: '파일_글자넣기', detail: 'fputc 래퍼', kind: CompletionItemKind.Function },
  { label: '줄_읽기', detail: 'fgets 래퍼', kind: CompletionItemKind.Function },
  { label: '파일_글자읽기', detail: 'fgetc 래퍼', kind: CompletionItemKind.Function },
  { label: '파일_위치이동', detail: 'fseek 래퍼', kind: CompletionItemKind.Function },
  { label: '파일_위치', detail: 'ftell 래퍼', kind: CompletionItemKind.Function },
  { label: '파일_끝인가', detail: 'feof 래퍼', kind: CompletionItemKind.Function },
  { label: '파일_삭제', detail: 'remove 래퍼', kind: CompletionItemKind.Function },

  // 문자열
  { label: '글자수', detail: 'strlen -- 문자열 길이', kind: CompletionItemKind.Function },
  { label: '문자열_비교', detail: 'strcmp', kind: CompletionItemKind.Function },
  { label: '문자열_같은가', detail: 'strcmp == 0', kind: CompletionItemKind.Function },
  { label: '문자열_일부비교', detail: 'strncmp', kind: CompletionItemKind.Function },
  { label: '문자열_복사', detail: 'strcpy', kind: CompletionItemKind.Function },
  { label: '문자열_일부복사', detail: 'strncpy', kind: CompletionItemKind.Function },
  { label: '문자열_연결', detail: 'strcat', kind: CompletionItemKind.Function },
  { label: '문자열_찾기', detail: 'strstr', kind: CompletionItemKind.Function },
  { label: '문자_찾기', detail: 'strchr', kind: CompletionItemKind.Function },
  { label: '문자_역찾기', detail: 'strrchr', kind: CompletionItemKind.Function },
  { label: '문자열_복제', detail: 'strdup', kind: CompletionItemKind.Function },
  { label: '정수로_변환', detail: 'atoi', kind: CompletionItemKind.Function },
  { label: '긴정수로_변환', detail: 'atol', kind: CompletionItemKind.Function },

  // 동사형 호출
  { label: '더하다', detail: '더하기의 동사형', kind: CompletionItemKind.Function },
  { label: '빼다', detail: '빼기의 동사형', kind: CompletionItemKind.Function },
  { label: '읽다', detail: '읽기의 동사형', kind: CompletionItemKind.Function },
  { label: '열다', detail: '열기의 동사형', kind: CompletionItemKind.Function },
  { label: '닫다', detail: '닫기의 동사형', kind: CompletionItemKind.Function },
  { label: '반환하다', detail: '값을 반환하다', kind: CompletionItemKind.Keyword },
  { label: '증가하다', detail: '변수를 증가하다 (++)', kind: CompletionItemKind.Keyword },
  { label: '감소하다', detail: '변수를 감소하다 (--)', kind: CompletionItemKind.Keyword },

  // 메모리
  { label: '할당', detail: 'malloc -- 메모리 할당', kind: CompletionItemKind.Function },
  { label: '초기할당', detail: 'calloc -- 0 초기화 할당', kind: CompletionItemKind.Function },
  { label: '재할당', detail: 'realloc', kind: CompletionItemKind.Function },
  { label: '해제', detail: 'free -- 메모리 해제', kind: CompletionItemKind.Function },
  { label: '메모리_비교', detail: 'memcmp', kind: CompletionItemKind.Function },
  { label: '메모리_복사', detail: 'memcpy', kind: CompletionItemKind.Function },
  { label: '메모리_이동', detail: 'memmove', kind: CompletionItemKind.Function },
  { label: '메모리_채우기', detail: 'memset', kind: CompletionItemKind.Function },

  // 변환
  { label: '글을_정수로', detail: '문자열 -> 정수', kind: CompletionItemKind.Function },
  { label: '글을_실수로', detail: '문자열 -> 실수', kind: CompletionItemKind.Function },
  { label: '글을_긴정수로', detail: '문자열 -> 긴정수', kind: CompletionItemKind.Function },
  { label: '글을_정밀실수로', detail: '문자열 -> 정밀 실수', kind: CompletionItemKind.Function },
  { label: '정수를_글로', detail: '정수 -> 문자열', kind: CompletionItemKind.Function },
  { label: '긴정수를_글로', detail: '긴정수 -> 문자열', kind: CompletionItemKind.Function },
  { label: '실수를_글로', detail: '실수 -> 문자열', kind: CompletionItemKind.Function },
  { label: '실수를_정밀글로', detail: '실수 -> 문자열 (자릿수 지정)', kind: CompletionItemKind.Function },

  // 수학
  { label: '제곱근', detail: 'sqrt', kind: CompletionItemKind.Function },
  { label: '거듭제곱', detail: 'pow', kind: CompletionItemKind.Function },
  { label: '반올림', detail: 'round', kind: CompletionItemKind.Function },
  { label: '올림', detail: 'ceil', kind: CompletionItemKind.Function },
  { label: '내림', detail: 'floor', kind: CompletionItemKind.Function },
  { label: '실수_나머지', detail: 'fmod', kind: CompletionItemKind.Function },
  { label: '최솟값', detail: 'fmin', kind: CompletionItemKind.Function },
  { label: '최댓값', detail: 'fmax', kind: CompletionItemKind.Function },
  { label: '실수_절댓값', detail: 'fabs', kind: CompletionItemKind.Function },
  { label: '사인', detail: 'sin', kind: CompletionItemKind.Function },
  { label: '코사인', detail: 'cos', kind: CompletionItemKind.Function },
  { label: '탄젠트', detail: 'tan', kind: CompletionItemKind.Function },
  { label: '자연로그', detail: 'log', kind: CompletionItemKind.Function },
  { label: '상용로그', detail: 'log10', kind: CompletionItemKind.Function },
  { label: '지수함수', detail: 'exp', kind: CompletionItemKind.Function },

  // 체계
  { label: '종료', detail: 'exit', kind: CompletionItemKind.Function },
  { label: '명령_실행', detail: 'system', kind: CompletionItemKind.Function },
  { label: '절댓값', detail: 'abs', kind: CompletionItemKind.Function },

  // 시간
  { label: '현재시각', detail: 'time -- 현재 시각(초)', kind: CompletionItemKind.Function },
  { label: '시간차이', detail: 'difftime', kind: CompletionItemKind.Function },
  { label: '경과틱', detail: 'clock', kind: CompletionItemKind.Function },
];

/** 표준 라이브러리 상수 */
const STDLIB_CONSTANTS = [
  { label: '표준입력', detail: 'stdin', kind: CompletionItemKind.Constant },
  { label: '표준출력', detail: 'stdout', kind: CompletionItemKind.Constant },
  { label: '표준오류', detail: 'stderr', kind: CompletionItemKind.Constant },
  { label: '원주율', detail: '3.14159...', kind: CompletionItemKind.Constant },
  { label: '자연상수', detail: '2.71828...', kind: CompletionItemKind.Constant },
  { label: '초당틱', detail: '1000000 (CLOCKS_PER_SEC)', kind: CompletionItemKind.Constant },
];

const ALL_COMPLETIONS = [...KEYWORDS, ...STDLIB_FUNCTIONS, ...STDLIB_CONSTANTS];

connection.onCompletion(() => {
  return ALL_COMPLETIONS;
});

// ── 서버 시작 ────────────────────────────────────────────

documents.listen(connection);
connection.listen();
