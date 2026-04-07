# 프로젝트 구조

```
geul/
├── src/                  ★ 컴파일러 소스 (글 언어로 작성)
│   ├── compiler.gl          메인 드라이버
│   ├── lexer.gl             렉서 (접사 분리)
│   ├── tokens.gl            토큰/역할/어미 열거형
│   ├── unicode.gl           UTF-8 처리
│   ├── ast.gl               AST 노드 정의
│   ├── parser.gl            파서 (SOV 어순)
│   ├── ir.gl                IR 3주소 코드
│   ├── ir_transform.gl      AST → IR
│   ├── ir_codegen.gl        IR → C 코드
│   ├── codegen.gl           AST → MASM 어셈블리
│   ├── asm_gen.gl           어셈블리 생성기
│   ├── pe_gen.gl            IR → x86-64 → PE
│   ├── elf_gen.gl           IR → ELF (미완성)
│   └── main_c.gl            C 트랜스파일러 드라이버
│
├── bootstrap/            C 부트스트랩 컴파일러
│   ├── src/                 C 소스
│   ├── include/             C 헤더
│   ├── build/               빌드 결과 (geulcc.exe)
│   ├── dist_build.ps1       배포용 빌드 스크립트
│   └── build.bat            부트스트랩 빌드
│
├── std/                  표준 라이브러리
│   ├── core.gl              기본 정의 (외부함수 선언)
│   ├── io.gl                파일/콘솔 I/O
│   ├── string.gl            문자열 처리
│   ├── memory.gl            메모리 관리
│   ├── math.gl              수학 함수
│   ├── convert.gl           타입 변환
│   ├── system.gl            시스템 호출
│   ├── time.gl              시간 측정
│   ├── hrtimer.gl           고정밀 타이머
│   ├── list.gl              동적 배열
│   └── error.gl             에러 처리
│
├── examples/             예제 프로그램
├── dist/                 배포 바이너리
├── bench/                벤치마크
├── tools/                개발 도구 (VSCode 확장 등)
├── tests/                테스트
├── projects/             프로젝트 예제
├── docs/                 문서
│
├── README.md             프로젝트 소개
├── STRUCTURE.md          이 파일
├── CHANGELOG.md          변경 이력
├── VERSION               현재 버전
└── install.ps1           원커맨드 설치 스크립트
```

## 빌드 파이프라인

```
사용자 .gl 소스
    ↓
geulc.exe (dist/compiler.exe)  ← 사용자가 사용하는 네이티브 컴파일러
    ↓
.exe (Windows PE)

compiler.exe 빌드 과정:
    src/*.gl → geulcc(bootstrap) → .c → MSVC → nc_stage0.exe
    nc_stage0 → nc_stage1 (native PE) → self-compile → compiler.exe
```

## 디렉토리 규칙

| 디렉토리 | 내용 | Git 추적 |
|----------|------|----------|
| src/ | 컴파일러 소스 (.gl) | O |
| bootstrap/ | C 부트스트랩 소스 | O (src/, include/) |
| std/ | 표준 라이브러리 (.gl) | O |
| examples/ | 예제 소스 | O |
| dist/ | 빌드 결과물 (.exe) | X (릴리즈로 배포) |
| bench/ | 벤치마크 소스+결과 | O |
| docs/ | 문서 | O |
| tools/ | 개발 도구 소스 | O (바이너리 제외) |
