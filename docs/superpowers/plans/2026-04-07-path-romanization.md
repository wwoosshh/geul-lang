# 경로 로마자화 (Path Romanization) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 모든 한글 디렉토리명과 파일명을 ASCII 영문으로 변경하여 UTF-8 경로 깨짐 문제 제거

**Architecture:** 3단계 접근 — (1) 매핑 테이블 확정 (2) 핵심 소스 + 빌드 시스템 먼저 변경 (3) 예제/문서/도구는 후속 정리. 소스 코드 내부의 한글 식별자/키워드는 변경하지 않음 — 파일명과 디렉토리명만 변경.

**Tech Stack:** Git, PowerShell, Python3 (일괄 리네임), CMake, MSVC

---

## 이름 매핑 테이블

### 디렉토리

| 현재 (한글) | 변경 (영문) | 설명 |
|-------------|-------------|------|
| `자체호스팅/` | `src/` | 컴파일러 소스 (프로젝트 핵심) |
| `부트스트랩/` | `bootstrap/` | C 부트스트랩 컴파일러 |
| `표준/` | `std/` | 표준 라이브러리 |
| `예제/` | `examples/` | 예제 프로그램 |
| `배포/` | `dist/` | 빌드 산출물 |
| `벤치마크/` | `bench/` | 벤치마크 |
| `벤치마크/글/` | `bench/geul/` | 글 벤치마크 소스 |
| `벤치마크/결과/` | `bench/results/` | 벤치마크 결과 |
| `도구/` | `tools/` | 개발 도구 |
| `도구/글-vscode/` | `tools/geul-vscode/` | VSCode 확장 |
| `도구/글-lsp/` | `tools/geul-lsp/` | LSP 서버 |
| `도구/글-vscode/표준/` | `tools/geul-vscode/std/` | 표준 라이브러리 복사본 |
| `프로젝트/` | `projects/` | 프로젝트 예제 |
| `테스트/` | `tests/` | 테스트 |

### 핵심 소스 파일 (`src/`, 구 `자체호스팅/`)

| 현재 | 변경 | 역할 |
|------|------|------|
| `네이티브컴파일러.글` | `compiler.gl` | 메인 드라이버 |
| `형태소분석기.글` | `lexer.gl` | 렉서 |
| `토큰정의.글` | `tokens.gl` | 토큰 열거형 |
| `유니코드.글` | `unicode.gl` | UTF-8 처리 |
| `구문트리.글` | `ast.gl` | AST 노드 정의 |
| `구문분석기.글` | `parser.gl` | 파서 |
| `중간표현.글` | `ir.gl` | IR 정의 |
| `IR변환기.글` | `ir_transform.gl` | AST → IR |
| `IR코드생성기.글` | `ir_codegen.gl` | IR → C 코드 |
| `코드생성기.글` | `codegen.gl` | AST → MASM |
| `어셈블리생성기.글` | `asm_gen.gl` | 어셈블리 생성 |
| `PE생성기.글` | `pe_gen.gl` | PE 실행파일 생성 |
| `ELF생성기.글` | `elf_gen.gl` | ELF 생성 |
| `주.글` | `main_c.gl` | C 트랜스파일러 드라이버 |

### 표준 라이브러리 (`std/`, 구 `표준/`)

| 현재 | 변경 |
|------|------|
| `기본.글` | `core.gl` |
| `입출력.글` | `io.gl` |
| `문자열.글` | `string.gl` |
| `메모리.글` | `memory.gl` |
| `체계.글` | `system.gl` |
| `목록.글` | `list.gl` |
| `변환.글` | `convert.gl` |
| `수학.글` | `math.gl` |
| `시간.글` | `time.gl` |
| `정밀시간.글` | `hrtimer.gl` |
| `에러.글` | `error.gl` |

### 부트스트랩 C 소스 (`bootstrap/src/`, `bootstrap/include/`)

| 현재 | 변경 |
|------|------|
| `형태소분석기.{c,h}` | `lexer.{c,h}` |
| `토큰.{c,h}` | `token.{c,h}` |
| `유니코드.{c,h}` | `unicode.{c,h}` |
| `구문트리.{c,h}` | `ast.{c,h}` |
| `구문분석기.{c,h}` | `parser.{c,h}` |
| `코드생성기.{c,h}` | `codegen.{c,h}` |
| `llvm생성기.{c,h}` | `llvm_gen.{c,h}` |
| `주.c` | `main.c` |

### 스크립트 / 빌드

| 현재 | 변경 |
|------|------|
| `부트스트랩/배포빌드.ps1` | `bootstrap/dist_build.ps1` |
| `부트스트랩/빌드.bat` | `bootstrap/build.bat` |
| `벤치마크/네이티브벤치.ps1` | `bench/native_bench.ps1` |
| `벤치마크/설정.ps1` | `bench/config.ps1` |
| `벤치마크/실행.ps1` | `bench/run.ps1` |

### 변경하지 않는 것

- `.글` 파일 내부의 한글 소스 코드 (키워드, 식별자, 주석) — **불변**
- `.c/.h` 파일 내부의 한글 식별자 (함수명, 변수명) — **불변** (C 컴파일러가 UTF-8 식별자를 처리함)
- `docs/` 내 한글 .md 파일명 — **Phase 3에서 선택적 처리**
- `예제/` 내 .글 파일명 — **Phase 3에서 선택적 처리**

---

## 실행 순서 원칙

1. **Bottom-up:** 리프 파일 먼저, 디렉토리는 마지막에
2. **한 계층씩:** `포함` 참조 그래프의 리프(tokens.gl, unicode.gl)부터 루트(compiler.gl)까지
3. **빌드 검증:** 각 Phase 후 글cc 재빌드 + 네이티브 컴파일러 빌드 확인

---

## Phase 1: 컴파일러 핵심 소스 리네임

### Task 1: 자체호스팅 .글 파일 리네임 + 포함문 수정

**Files:**
- Rename: `자체호스팅/` 내 14개 .글 파일
- Modify: 각 .글 파일 내부의 `포함 "..."` 문

이 Task는 Python 스크립트로 일괄 처리합니다. 모든 파일이 동시에 변경되어야 `포함` 참조가 깨지지 않습니다.

- [ ] **Step 1: 리네임 스크립트 작성 및 실행**

```python
# rename_src.py — /c/workspace/geul/ 에서 실행
import os, shutil

src_dir = '자체호스팅'

# 파일 매핑: 한글 → 영문
file_map = {
    '네이티브컴파일러.글': 'compiler.gl',
    '형태소분석기.글': 'lexer.gl',
    '토큰정의.글': 'tokens.gl',
    '유니코드.글': 'unicode.gl',
    '구문트리.글': 'ast.gl',
    '구문분석기.글': 'parser.gl',
    '중간표현.글': 'ir.gl',
    'IR변환기.글': 'ir_transform.gl',
    'IR코드생성기.글': 'ir_codegen.gl',
    '코드생성기.글': 'codegen.gl',
    '어셈블리생성기.글': 'asm_gen.gl',
    'PE생성기.글': 'pe_gen.gl',
    'ELF생성기.글': 'elf_gen.gl',
    '주.글': 'main_c.gl',
}

# 포함문 매핑 (파일 내부의 포함 경로도 변경)
include_map = {}
for k, v in file_map.items():
    include_map[f'포함 "{k}"'] = f'포함 "{v}"'

# 1. 파일 내용에서 포함문 교체
for old_name in file_map:
    fpath = os.path.join(src_dir, old_name)
    if not os.path.exists(fpath):
        continue
    with open(fpath, 'r', encoding='utf-8') as f:
        content = f.read()
    for old_inc, new_inc in include_map.items():
        content = content.replace(old_inc, new_inc)
    with open(fpath, 'w', encoding='utf-8') as f:
        f.write(content)

# 2. 파일 리네임
for old_name, new_name in file_map.items():
    old_path = os.path.join(src_dir, old_name)
    new_path = os.path.join(src_dir, new_name)
    if os.path.exists(old_path):
        shutil.move(old_path, new_path)
        print(f'  {old_name} → {new_name}')
```

Run: `python3 rename_src.py`

- [ ] **Step 2: 디렉토리 리네임 `자체호스팅/` → `src/`**

```bash
# git mv 사용 (히스토리 보존)
git mv 자체호스팅 src
```

- [ ] **Step 3: 검증 — 모든 포함문이 올바른지 확인**

```bash
grep -r '포함 "' src/*.gl | grep -v '/\*'
```

모든 `포함` 경로가 영문 파일명을 가리키는지 확인.

- [ ] **Step 4: 커밋**

```bash
git add -A
git commit -m "rename: 자체호스팅/*.글 → src/*.gl 영문 파일명으로 변경"
```

---

### Task 2: 표준 라이브러리 리네임

**Files:**
- Rename: `표준/` 내 11개 .글 파일
- Modify: `std/core.gl` (구 `기본.글`) 내부의 `포함 "표준/..."` → `포함 "std/..."`
- Modify: `src/compiler.gl` (구 `네이티브컴파일러.글`) — std 경로 참조가 있으면 수정

- [ ] **Step 1: 표준 라이브러리 리네임 스크립트**

```python
# rename_std.py
import os, shutil

std_dir = '표준'
file_map = {
    '기본.글': 'core.gl',
    '입출력.글': 'io.gl',
    '문자열.글': 'string.gl',
    '메모리.글': 'memory.gl',
    '체계.글': 'system.gl',
    '목록.글': 'list.gl',
    '변환.글': 'convert.gl',
    '수학.글': 'math.gl',
    '시간.글': 'time.gl',
    '정밀시간.글': 'hrtimer.gl',
    '에러.글': 'error.gl',
}

# 포함문에서는 "표준/파일.글" → "std/파일.gl" 형태
include_map = {}
for k, v in file_map.items():
    include_map[f'표준/{k}'] = f'std/{v}'

# 1. 표준 라이브러리 파일 내 포함문 수정
for old_name in file_map:
    fpath = os.path.join(std_dir, old_name)
    if not os.path.exists(fpath):
        continue
    with open(fpath, 'r', encoding='utf-8') as f:
        content = f.read()
    for old_inc, new_inc in include_map.items():
        content = content.replace(old_inc, new_inc)
    with open(fpath, 'w', encoding='utf-8') as f:
        f.write(content)

# 2. src/ 디렉토리 내 파일에서도 표준 경로 수정
for gl_file in os.listdir('src'):
    if gl_file.endswith('.gl'):
        fpath = os.path.join('src', gl_file)
        with open(fpath, 'r', encoding='utf-8') as f:
            content = f.read()
        changed = False
        for old_inc, new_inc in include_map.items():
            if old_inc in content:
                content = content.replace(old_inc, new_inc)
                changed = True
        if changed:
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write(content)

# 3. 파일 리네임
for old_name, new_name in file_map.items():
    old_path = os.path.join(std_dir, old_name)
    new_path = os.path.join(std_dir, new_name)
    if os.path.exists(old_path):
        shutil.move(old_path, new_path)
        print(f'  {old_name} → {new_name}')
```

Run: `python3 rename_std.py`

- [ ] **Step 2: 디렉토리 리네임**

```bash
git mv 표준 std
```

- [ ] **Step 3: 커밋**

```bash
git add -A
git commit -m "rename: 표준/*.글 → std/*.gl 표준 라이브러리 영문화"
```

---

### Task 3: 부트스트랩 C 소스 리네임

**Files:**
- Rename: `부트스트랩/src/` 내 8개 .c 파일
- Rename: `부트스트랩/include/` 내 7개 .h 파일
- Modify: 각 .c 파일의 `#include` 문
- Modify: `CMakeLists.txt`
- Rename: `부트스트랩/배포빌드.ps1` → `dist_build.ps1`
- Rename: `부트스트랩/빌드.bat` → `build.bat`

- [ ] **Step 1: C/H 파일 리네임 + #include 수정 스크립트**

```python
# rename_bootstrap.py
import os, shutil

base = '부트스트랩'
c_map = {
    '형태소분석기': 'lexer',
    '토큰': 'token',
    '유니코드': 'unicode',
    '구문트리': 'ast',
    '구문분석기': 'parser',
    '코드생성기': 'codegen',
    'llvm생성기': 'llvm_gen',
    '주': 'main',
}

# include 매핑
inc_map = {}
for k, v in c_map.items():
    inc_map[f'"{k}.h"'] = f'"{v}.h"'
    inc_map[f'"{k}.c"'] = f'"{v}.c"'

# 1. 파일 내용에서 #include 교체
for subdir in ['src', 'include']:
    dirpath = os.path.join(base, subdir)
    if not os.path.isdir(dirpath):
        continue
    for fname in os.listdir(dirpath):
        fpath = os.path.join(dirpath, fname)
        with open(fpath, 'r', encoding='utf-8') as f:
            content = f.read()
        for old, new in inc_map.items():
            content = content.replace(old, new)
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(content)

# 2. 파일 리네임
for subdir in ['src', 'include']:
    dirpath = os.path.join(base, subdir)
    if not os.path.isdir(dirpath):
        continue
    for fname in os.listdir(dirpath):
        stem, ext = os.path.splitext(fname)
        if stem in c_map:
            old_path = os.path.join(dirpath, fname)
            new_path = os.path.join(dirpath, c_map[stem] + ext)
            shutil.move(old_path, new_path)
            print(f'  {subdir}/{fname} → {subdir}/{c_map[stem]}{ext}')

# 3. 스크립트 리네임
for old, new in [('배포빌드.ps1', 'dist_build.ps1'), ('빌드.bat', 'build.bat')]:
    old_path = os.path.join(base, old)
    new_path = os.path.join(base, new)
    if os.path.exists(old_path):
        shutil.move(old_path, new_path)
        print(f'  {old} → {new}')
```

Run: `python3 rename_bootstrap.py`

- [ ] **Step 2: CMakeLists.txt 수정**

```cmake
cmake_minimum_required(VERSION 3.16)
project(geulcc C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

if(MSVC)
    add_compile_options(/utf-8)
endif()

if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    add_compile_options(-Wall -Wextra -finput-charset=UTF-8 -fexec-charset=UTF-8)
endif()

include_directories(include)

set(SOURCES
    src/unicode.c
    src/token.c
    src/lexer.c
    src/ast.c
    src/parser.c
    src/main.c
)

add_executable(geulcc ${SOURCES})

enable_testing()
add_test(NAME lexer_hello COMMAND geulcc -토큰 ${CMAKE_SOURCE_DIR}/../examples/hello.gl)
add_test(NAME parser_hello COMMAND geulcc -구문 ${CMAKE_SOURCE_DIR}/../examples/hello.gl)
```

- [ ] **Step 3: dist_build.ps1 경로 업데이트**

`dist_build.ps1` 내 유니코드 이스케이프 경로를 영문으로 변경:

```powershell
$root = "geul"
$basePath = "C:\workspace\$root"
$selfhost = "$basePath\src"
$bootstrap = "$basePath\bootstrap"
$geul = "gl"
$std = "std"
$outDir = "$basePath\dist"
```

파일 이름 배열도 영문으로 변경:
```powershell
$fileNames = @(
    "tokens", "unicode", "lexer", "ast", "parser",
    "ir", "ir_transform", "ir_codegen", "asm_gen",
    "pe_gen", "elf_gen", "compiler"
)

foreach ($fn in $fileNames) {
    $fpath = Join-Path $selfhost "$fn.$geul"
    ...
}
```

`$stdBasicName`, `$stdBasic`도 동일하게:
```powershell
$stdBasicName = "core.$geul"
$stdBasic = Join-Path $basePath (Join-Path $std $stdBasicName)
```

- [ ] **Step 4: 디렉토리 리네임**

```bash
git mv 부트스트랩 bootstrap
```

- [ ] **Step 5: 부트스트랩 빌드 검증**

```bash
cd bootstrap && mkdir -p build && cd build
cmake .. -G "NMake Makefiles"
nmake
# 또는
cd bootstrap && powershell -File build.bat
```

`geulcc.exe` (구 `글cc.exe`)가 생성되는지 확인.

- [ ] **Step 6: 커밋**

```bash
git add -A
git commit -m "rename: 부트스트랩 → bootstrap, C 소스 영문화, 빌드 스크립트 업데이트"
```

---

## Phase 2: 나머지 디렉토리 리네임

### Task 4: 예제/배포/벤치마크/테스트/도구/프로젝트 디렉토리 리네임

**Files:**
- Rename: 6개 최상위 디렉토리
- Modify: 소스 내 경로 참조가 있으면 수정

- [ ] **Step 1: 디렉토리 일괄 리네임**

```bash
git mv 예제 examples
git mv 배포 dist
git mv 벤치마크 bench
git mv 테스트 tests
git mv 도구 tools
git mv 프로젝트 projects
```

- [ ] **Step 2: 벤치마크 하위 디렉토리 리네임**

```bash
git mv bench/글 bench/geul
git mv bench/결과 bench/results
```

- [ ] **Step 3: 도구 하위 디렉토리 리네임**

```bash
git mv tools/글-vscode tools/geul-vscode
git mv tools/글-lsp tools/geul-lsp
# 표준 라이브러리 복사본도 리네임
git mv tools/geul-vscode/표준 tools/geul-vscode/std
git mv tools/geul-vscode/bin/표준 tools/geul-vscode/bin/std
```

- [ ] **Step 4: 벤치마크 스크립트 리네임**

```bash
git mv bench/네이티브벤치.ps1 bench/native_bench.ps1
git mv bench/설정.ps1 bench/config.ps1
git mv bench/실행.ps1 bench/run.ps1
```

- [ ] **Step 5: 빌드도구.글 내 하드코딩된 경로 수정**

`projects/6_빌드시스템/빌드도구.글` 190행:
```
변경 전: 파일_글넣기("compiler: C:\\workspace\\한글\\배포\\네이티브컴파일러.exe\n", 설정).
변경 후: 파일_글넣기("compiler: C:\\workspace\\geul\\dist\\compiler.exe\n", 설정).
```

- [ ] **Step 6: 커밋**

```bash
git add -A
git commit -m "rename: 예제/배포/벤치마크/테스트/도구/프로젝트 → 영문 디렉토리명"
```

---

### Task 5: 루트 잔여 .obj 파일 정리

**Files:**
- Delete: 루트의 .obj 파일들 (빌드 잔여물, git에 포함되지 않아야 함)

- [ ] **Step 1: .obj 파일 삭제**

```bash
rm -f *.obj
rm -f src/*.obj src/*.c src/*.exe
```

- [ ] **Step 2: .gitignore 확인**

`.gitignore`에 `*.obj`, `*.exe` (배포 제외), `*.c` (트랜스파일 결과)가 포함되어 있는지 확인.

- [ ] **Step 3: 커밋**

```bash
git add -A
git commit -m "clean: 루트 빌드 잔여물(.obj) 삭제"
```

---

## Phase 3: 빌드 파이프라인 검증 + 고정점

### Task 6: 전체 빌드 파이프라인 검증

- [ ] **Step 1: 부트스트랩 컴파일러 빌드**

```bash
cd bootstrap
powershell -File build.bat
# 또는 Makefile 사용
ls build/geulcc.exe
```

- [ ] **Step 2: C 트랜스파일 경유 네이티브 컴파일러 빌드**

```bash
bootstrap/build/geulcc.exe src/compiler.gl --emit-c
# → src/compiler.c 생성
# MSVC로 컴파일
cl /nologo /O2 /utf-8 src/compiler.c /Fe:dist/nc_stage0.exe ...
```

- [ ] **Step 3: Stage 0 → Stage 1 (네이티브 PE)**

```bash
dist/nc_stage0.exe src/compiler.gl -출력 dist/nc_stage1.exe
```

- [ ] **Step 4: Stage 1로 예제 프로그램 컴파일**

```bash
dist/nc_stage1.exe examples/구구단.gl
dist/nc_stage1.exe examples/피보나치.gl
```

- [ ] **Step 5: 자체 컴파일 (고정점 시도)**

```bash
# Stage 1으로 자기 자신 컴파일
dist/nc_stage1.exe src/compiler.gl -출력 dist/nc_stage2.exe

# Stage 2로 자기 자신 컴파일
dist/nc_stage2.exe src/compiler.gl -출력 dist/nc_stage3.exe

# 고정점 검증
fc /b dist/nc_stage2.exe dist/nc_stage3.exe
```

- [ ] **Step 6: STRUCTURE.md 업데이트**

새 디렉토리 구조를 반영하여 STRUCTURE.md 수정.

- [ ] **Step 7: 커밋**

```bash
git add -A
git commit -m "verify: 영문 경로 빌드 파이프라인 검증 완료"
```

---

## Phase 3.5 (선택): 예제/문서 파일명 영문화

### Task 7 (선택): 예제 .글 파일명 영문화

이 Task는 기능에 영향 없으며 선택 사항.

| 현재 | 변경 |
|------|------|
| `구구단.글` | `multiplication.gl` |
| `피보나치.글` | `fibonacci.gl` |
| `인사.글` | `hello.gl` |
| `버블정렬.글` | `bubblesort.gl` |
| `수식계산기.글` | `calculator.gl` |
| ... | ... |

> 예제 파일은 사용자 대면 콘텐츠이므로, 한글 파일명이 교육적 가치가 있다면 유지해도 됨.
> 빌드 파이프라인에는 영향 없음.

---

## 영향 범위 요약

| 영역 | 영향 | 필수 |
|------|------|------|
| 자체호스팅 소스 `포함` 문 | 파일명 변경 반영 필요 | **필수** |
| 부트스트랩 `#include` 문 | 파일명 변경 반영 필요 | **필수** |
| CMakeLists.txt | 소스 파일 목록 변경 | **필수** |
| dist_build.ps1 | 경로 전체 영문화 | **필수** |
| .글 파일 내 한글 코드 | **변경 없음** | - |
| .c/.h 파일 내 한글 식별자 | **변경 없음** | - |
| docs/ .md 파일명 | **변경 없음** (내용에 영향 없음) | 선택 |
