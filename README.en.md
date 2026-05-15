# Geul Programming Language

**A programming language where you code in Korean.**

```geul
포함 "std.gl"

[시작하기]는 -> 정수 {
    문자열 이름 = "세계".
    정수 년도 = 2026.
    "안녕, {이름}! {년도}년입니다.\n"을 쓰다.
    반환 0.
}
```

---

## Features

- **100% Korean keywords** — No English function names exposed to user code
- **SOV word order** — Like Korean grammar: `target을 function하다` (object-verb)
- **Particle binding** — Particles like `을/를`, `에`, `로` determine argument roles
- **String interpolation** — `"name: {이름}, age: {나이}"` — insert variables directly
- **Native code generation** — Compiles `.gl → .exe` directly without a C compiler
- **Self-hosting** — The Geul compiler compiles itself
- **VS Code integration** — Syntax highlighting, F5 run, LSP autocompletion

## Performance

> C compiled with MSVC `/O2`. Measured on Intel Ultra 5 226V, median of 5 runs.

| Benchmark | Geul Native | C (/O2) | Ratio | Python | Ratio |
|-----------|----------:|-------:|-----:|-------:|-----:|
| Recursive fib(40) | 464 ms | 321 ms | 1.45x | 7,364 ms | 23.0x |
| Sieve of primes 1M | 10 ms | 8 ms | 1.30x | 167 ms | 22.0x |
| Bubble sort 30K | 1,564 ms | 564 ms | 2.77x | 38,377 ms | 68.0x |

**1.3–2.8x vs C(/O2)** — 22–68x faster than Python

---

## Installation

### Method 1: One-command install (PowerShell)
```powershell
irm https://raw.githubusercontent.com/wwoosshh/geul-lang/main/install.ps1 | iex
```
After installation, open a **new terminal** for PATH to take effect.

### Method 2: VS Code extension manual install
1. Download `.vsix` from [Releases](https://github.com/wwoosshh/geul-lang/releases)
2. VS Code → `Ctrl+Shift+P` → "Install from VSIX" → select file

### Method 3: Build from source
```bash
# Build bootstrap compiler (requires MSVC)
powershell -File bootstrap/build_temp.ps1

# Build native compiler
bootstrap/build/글cc.exe src/compiler.gl
```

---

## Usage

### Native compiler (no C compiler needed)
```bash
compiler.exe source.gl                    # Generate .exe directly
compiler.exe source.gl -o output.exe      # Specify output path
compiler.exe --emit-asm source.gl         # Output .asm assembly
compiler.exe --dump-ir source.gl          # Dump IR intermediate representation
compiler.exe --check source.gl            # Syntax check only (no compilation)
```

### VS Code
| Shortcut | Function |
|----------|----------|
| **F5** | Compile + Run |
| **Ctrl+Shift+B** | Build (.exe generation) |

---

## Syntax Guide

### Basic Structure

```geul
포함 "std.gl"

[시작하기]는 -> 정수 {
    "안녕하세요!\n"을 쓰다.
    반환 0.
}
```

- `포함` — Include standard library (#include)
- `[시작하기]` — Program entry point (main)
- `.` — Statement terminator (instead of semicolons)
- `(* ... *)` — Comments

### Variables and Types

```geul
정수 나이 = 25.                  (* int *)
실수 원주율 = 3.14159.           (* double *)
문자열 이름 = "홍길동".          (* char* *)
문자 첫글자 = 'A'.               (* char *)
참거짓 활성 = 참.                (* bool *)
긴정수 큰값 = 1000000000.       (* long long *)
상수 정수 최대값 = 100.          (* const int *)
```

### Arrays

```geul
정수[10] 점수.                   (* int scores[10]; *)
점수[0] = 95.
점수[1] = 87.
정수 첫점수 = 점수[0].

문자[256] 버퍼.                  (* char buffer[256]; *)
```

### Function Definition and Calling

```geul
(* Function definition *)
[정수 왼쪽을 정수 오른쪽에 더하기]는 -> 정수 {
    반환 왼쪽 + 오른쪽.
}

(* SOV call — Korean word order *)
정수 결과는 5를 3에 더하다.

(* Verb-form call — 더하다 → 더하기 auto-matched *)
정수 결과2는 10을 20에 더하다.

(* Direct call — C style *)
정수 결과3 = 더하기(5, 3).
```

> **Verb-form calls**: `쓰다` automatically finds the `쓰기` function, `더하다` finds `더하기`.

### String Interpolation

```geul
문자열 이름 = "철수".
정수 나이 = 25.
정수 점수 = 95.

"이름: {이름}, 나이: {나이}세\n"을 쓰다.
"{이름}의 점수는 {점수}점입니다\n"을 쓰다.
```

Output:
```
이름: 철수, 나이: 25세
철수의 점수는 95점입니다
```

Format is automatically determined by variable type:
| Type | Format |
|------|--------|
| `정수` (int) | `%d` |
| `문자열` (string) | `%s` |
| `실수` (float) | `%f` |
| `문자` (char) | `%c` |
| `긴정수` (long long) | `%lld` |

Traditional printf style `"값: %d\n"을 값을 쓰다.` also works.

### Conditionals

```geul
(* Basic conditional *)
값 > 10이면 {
    "10보다 큽니다\n"을 쓰다.
}
아니면 {
    "10 이하입니다\n"을 쓰다.
}

(* Comparison operators: ==, !=, <, >, <=, >= *)
이름이 "철수"와 같으면 {
    "철수입니다\n"을 쓰다.
}
```

### Loops

```geul
(* while loop *)
정수 번호 = 0.
(번호 < 10)동안 {
    "%d\n"을 번호를 쓰다.
    번호를 증가하다.
}

(* C-style for loop — colon as separator *)
반복 (정수 순번 = 0: 순번 < 5: 순번++) {
    "%d\n"을 순번을 쓰다.
}

(* do-while loop *)
반복하기 {
    번호를 증가하다.
} 번호 < 100 동안.

(* Loop control *)
(참)동안 {
    번호 >= 50이면 { 탈출. }     (* break *)
    번호 % 2 == 0이면 { 계속. }  (* continue *)
}
```

### Increment/Decrement

```geul
번호를 증가하다.                 (* number++ *)
번호를 감소하다.                 (* number-- *)
번호++.                          (* C-style postfix increment *)
++번호.                          (* C-style prefix increment *)
```

### Compound Assignment

```geul
합계 += 10.                      (* sum = sum + 10 *)
값 -= 5.
값 *= 2.
값 /= 3.
값 %= 7.
```

### Ternary Operator

```geul
정수 결과 = 값 > 0 ? 값 : 0 - 값.   (* absolute value *)
```

### Switch (갈래)

```geul
갈래 (값) {
    경우 1: {
        "하나\n"을 쓰다.
    }
    경우 2: {
        "둘\n"을 쓰다.
    }
    기본: {
        "기타\n"을 쓰다.
    }
}
```

### Structs (묶음)

```geul
묶음 점은 정수 가로, 정수 세로.

[시작하기]는 -> 정수 {
    점 위치.
    위치의 가로 = 10.
    위치의 세로 = 20.
    "위치: (%d, %d)\n"을 위치의 가로를 위치의 세로를 쓰다.
    반환 0.
}
```

### Enums (나열)

```geul
나열 색깔은 { 빨강, 초록, 파랑 }

[시작하기]는 -> 정수 {
    정수 내색 = 초록.
    "색깔: %d\n"을 내색을 쓰다.    (* 1 *)
    반환 0.
}
```

### Unions (합침)

```geul
합침 값저장은 정수 정수값, 실수 실수값, 문자열 문자열값.
```

### Type Aliases

```geul
별칭 크기는 긴정수.               (* typedef long long size; *)
크기 파일크기 = 1048576.
```

### Pointers and Memory

```geul
정수 값 = 42.
정수* 주소 = &값.                 (* address-of *)
정수 복사 = *주소.                (* dereference *)

(* Dynamic memory *)
문자열 버퍼 = 1024를 할당하다.    (* malloc *)
버퍼를 해제하다.                  (* free *)

(* Pointer member access *)
점* 참조 = &위치.
참조→가로 = 30.                  (* -> member access *)
```

### Type Casting

```geul
정수 정수값 = 65.
문자 문자값 = 정수값으로 문자.     (* (char)intVal *)
실수 실수값 = 정수값으로 실수.     (* (double)intVal *)
```

### Function Pointers

```geul
[정수, 정수 -> 정수] 연산.        (* int (*op)(int, int) *)
연산 = 더하기.
정수 결과 = 연산(3, 5).
```

### Variadic Functions

```geul
[문자열 형식을 ... 내출력]은 {
    가변목록 목록.
    형식을 목록을 가변시작다.
    형식을 목록을 vprintf다.
    목록을 가변끝다.
}
```

### Static Variables/Functions

```geul
정적 정수 호출횟수 = 0.           (* static int *)

정적 [카운트증가]는 {             (* static function *)
    호출횟수를 증가하다.
}
```

### Preprocessor

```geul
포함 "std.gl"                     (* #include *)
정의 최대크기 1024                 (* #define *)
외부 정수 전역값.                  (* extern *)

만약정의 디버그                    (* #ifdef *)
    "디버그 모드\n"을 쓰다.
아니면                             (* #else *)
    "릴리즈 모드\n"을 쓰다.
끝                                 (* #endif *)
```

### Sizeof

```geul
정수 바이트 = 크기(정수).          (* sizeof(int) *)
```

---

## Syntax Reference Table

| Syntax | Geul | C Equivalent |
|--------|------|--------------|
| Variable declaration | `정수 값은 42.` | `int val = 42;` |
| Constant | `상수 정수 값 = 42.` | `const int val = 42;` |
| Function definition | `[정수 수를 제곱]은 -> 정수 { }` | `int square(int n) { }` |
| SOV call | `42를 제곱하다.` | `square(42);` |
| Direct call | `제곱(42).` | `square(42);` |
| Return | `결과를 반환하다.` | `return result;` |
| String interpolation | `"{이름}은 {나이}세"` | *(auto-generates printf)* |
| Increment/Decrement | `번호를 증가하다.` | `number++;` |
| Compound assignment | `값 += 10.` | `val += 10;` |
| Ternary | `조건 ? 참 : 거짓` | `cond ? true : false` |
| If | `값 > 10이면 { }` | `if (val > 10) { }` |
| Else | `아니면 { }` | `else { }` |
| While | `(조건)동안 { }` | `while (cond) { }` |
| For | `반복 (init: cond: step) { }` | `for (init; cond; step) { }` |
| Do-while | `반복하기 { } 조건 동안.` | `do { } while (cond);` |
| Switch | `갈래 (값) { 경우 1: { } }` | `switch (val) { case 1: { } }` |
| Break | `탈출.` | `break;` |
| Continue | `계속.` | `continue;` |
| Struct | `묶음 이름은 fields.` | `struct name { fields };` |
| Enum | `나열 이름은 { values }` | `enum name { values };` |
| Union | `합침 이름은 fields.` | `union name { fields };` |
| Type alias | `별칭 새이름은 기존타입.` | `typedef oldtype newname;` |
| Member access | `객체의 필드` | `obj.field` |
| Pointer access | `참조→필드` | `ptr->field` |
| Type cast | `값으로 타입` | `(type)val` |
| Sizeof | `크기(타입)` | `sizeof(type)` |
| Include | `포함 "file"` | `#include "file"` |
| Define | `정의 이름 값` | `#define name val` |
| Conditional compilation | `만약정의 이름 ... 끝` | `#ifdef name ... #endif` |
| Comment | `(* content *)` | `/* content */` |

---

## Examples

### Multiplication Table

```geul
포함 "std.gl"

[시작하기]는 -> 정수 {
    정수 단 = 2.
    (단 <= 9)동안 {
        정수 곱 = 1.
        (곱 <= 9)동안 {
            정수 결과는 단 * 곱.
            "%d x %d = %d\n"을 단을 곱을 결과를 쓰다.
            곱을 증가하다.
        }
        "\n"을 쓰다.
        단을 증가하다.
    }
    반환 0.
}
```

### Fibonacci (Recursive)

```geul
포함 "std.gl"

[정수 수를 피보나치]는 -> 정수 {
    수 <= 1이면 { 수를 반환하다. }
    정수 앞값은 (수 - 1)을 피보나치하다.
    정수 뒷값은 (수 - 2)를 피보나치하다.
    앞값 + 뒷값을 반환하다.
}

[시작하기]는 -> 정수 {
    정수 결과는 10을 피보나치하다.
    "피보나치(10) = {결과}\n"을 쓰다.
    반환 0.
}
```

### String Interpolation

```geul
포함 "std.gl"

[시작하기]는 -> 정수 {
    문자열 이름 = "홍길동".
    정수 나이 = 30.
    문자열 도시 = "서울".
    정수 인원 = 5.

    "{이름}은 {도시}에 삽니다\n"을 쓰다.
    "나이: {나이}세, 팀원: {인원}명\n"을 쓰다.
    반환 0.
}
```

---

## Architecture

```
.gl source → Morphological analysis → Parsing → AST → IR
                                                  ↓
                                    ┌──────────────┴──────────────┐
                                    ↓                             ↓
                              C code generation            x86-64 machine code
                                    ↓                             ↓
                              cl.exe/gcc                   Direct PE generation
                                    ↓                             ↓
                                 .exe                           .exe
                           (C transpile)              (Native, zero external tools)
```

### Compiler Components

| Component | File | Description |
|-----------|------|-------------|
| Lexer | `src/lexer.gl` | Korean morpheme separation (3-level recursive) |
| Parser | `src/parser.gl` | SOV word-order recursive descent parser |
| IR Transform | `src/ir_transform.gl` | AST → 3-address code + static type checking |
| C Code Generator | `src/ir_codegen.gl` | IR → C11 code |
| PE Generator | `src/pe_gen.gl` | IR → x86-64 → PE directly |
| Standard Library | `std/*.gl` | 9 modules, 62 functions |

### Optimizations

- **Immediate arithmetic** — Constant immediate value encoding
- **Compare-branch fusion** — Direct `cmp + jcc` generation
- **Register pinning** — Loop variables pinned to callee-saved registers
- **Peephole optimization** — Dead store/unnecessary copy elimination
- **Loop-invariant code motion** — Constant loads hoisted out of loops
- **Tail call optimization** — Self-recursion converted to `jmp`

### Static Type Checking

Type mismatches are caught at compile time and cause build errors.

```geul
정수 값 = "문자열".    (* Type error: incompatible type assignment → build aborted *)
```

| Check Point | Description |
|------------|-------------|
| Variable declaration | Compatibility between declared type and initializer |
| Assignment | Compatibility between LHS and RHS types |
| Function return | Return value type vs. declared return type |
| Function call | Argument count matching |

Type compatibility rules:
- Integer family (`정수`, `긴정수`, `짧은정수`, `문자`, `참거짓`) — free conversion within
- Float family (`실수`, `짧은실수`) — free conversion within
- Integer → Float implicit widening allowed
- Incompatible types (integer ← string, string ← integer, etc.) cause errors

---

## Requirements

- Windows 10/11
- No additional requirements (MSVC not needed)

---

## License

MIT

---

## Changelog

### v0.5 (2026-04-02)
- **Native self-hosting achieved** — Compiler compiles itself, fixed-point SHA256 match
- **fopen UTF-8/ACP wrapper** — Support for opening files with Korean paths
- **5th+ parameter offset fix** — Stack layout correction after callee-saved register pushes
- **64-bit integer parsing** — atoi → _atoi64, handles large constants like 0xC0000080

### v0.4 (2026-04-01)
- **Static type checking system** — Type compatibility verification at 4 points: declaration, assignment, return, call
- **`*=`, `/=`, `%=` compound assignment fix** — Works correctly for variables, arrays, and struct members
- **Multi-argument SOV function call fix** — Resolved `에`/`로` particle parameter name mismatch
- **`--emit-asm` implementation** — x86-64 MASM assembly file output

### v0.3 (2026-03-27)
- Native PE direct generation
- Peephole optimization, inlining, loop-invariant code motion

## Future Plans

- [ ] Linux ELF generation (cross-platform)
- [ ] Package manager
- [ ] Debug information (PDB) generation
- [ ] Error handling (`시도/실패`)
- [ ] Complete C runtime removal

[Full roadmap](docs/15-향후로드맵.md)
