# Geul Compiler v0.7.2 Bug Fix Report

**Date**: 2026-04-14
**Base version**: v0.7.1
**Issues resolved**: 7 (most of the critical bugs on the issue list)
**Self-hosting status**: IDENTICAL fixed point preserved

---

## Overview

Of the 8 remaining v0.6.5 defects listed in `문제점.txt` (issue list), 7 have been resolved. For each bug we record (1) a reproduction case, (2) the root-cause code, (3) the fix, and (4) verification output.

### Change statistics

| File | Delta |
|---|---|
| `src/ir.gl` | +3 |
| `src/ir_codegen.gl` | +11 |
| `src/ir_transform.gl` | +80/-3 |
| `src/lexer.gl` | +12 |
| `src/parser.gl` | ±4 |
| `src/pe_gen.gl` | +79/-3 |
| **Total** | **+187/-8** |

---

## Bug #1: `&배열[i]` returns garbage address → segfault on dereference

### Symptom

```글
정수[4] 배열.
배열[0] = 10.
정수 참조 포인터 = &배열[0].
쓰기("주소: %p\n", 포인터).   (* Output: 0x0000000000000002 (garbage) *)
*포인터                        (* Segfault *)
```

A plain `&scalar` worked correctly, but a pointer obtained via `&array[index]` returned a bogus address, causing a segfault when dereferenced.

### Root Cause — Dual Problem

**Problem A (parser precedence)**: `src/parser.gl:549`
```글
(* 주소참조: &식별자 *)
((현재종류 == 종류_비트와))이면 {
    전진().
    정수 대상 = 기본표현식().   (* ← postfix excluded! *)
    ...
}
```

The unary `&` was invoking `기본표현식()` (primary expression, without postfix operations), so `&배열[0]` was parsed as `(&배열)[0]`. Unlike C, postfix `[]` was applied with lower precedence than `&`.

Evidence (IR dump):
```
t6 = 주소 t2                   ← &배열 first
t7 = 상수정수 0
t8 = 원소적재 t6, t7 [크기=1]  ← then [0] byte-access
```

**Problem B (IR transform)**: `src/ir_transform.gl:857`
```글
(종류 == 노드_주소참조)이면 {
    정수 대상 = 노드왼쪽풀[노드]를 표현식변환다.  (* If child is array access, loads value *)
    명령등록(명령_주소, 결과, 대상, ...).        (* Takes address of value slot *)
    반환 결과.
}
```

Even if the parser had produced `&(배열[0])` correctly, the child `표현식변환` would emit `명령_원소적재`, loading the array element **value** into a scratch slot. Then `명령_주소` would return **the stack address of that scratch slot** — a double-layered error.

### Fix

**Parser fix** (`parser.gl`):
```글
(* 주소참조: &식별자, &배열[인덱스], &묶음.필드 *)
((현재종류 == 종류_비트와))이면 {
    전진().
    정수 대상 = 접미표현식().   (* ← now includes postfix *)
    정수 노드 = 노드생성(노드_주소참조, 줄, 열).
    노드왼쪽풀[노드] = 대상.
    반환 노드.
}
```

**New IR opcode `명령_원소주소`** (`ir.gl`):
```글
명령_원소적재,
명령_원소저장,
명령_원소주소,   (* ← new: compute address only, no value load *)
```

**IR transform branch** (`ir_transform.gl`):
```글
(종류 == 노드_주소참조)이면 {
    정수 자식노드 = 노드왼쪽풀[노드].
    (* &배열[인덱스] → compute element address (no value load) *)
    (노드종류풀[자식노드] == 노드_배열접근)이면 {
        정수 배열기준 = 노드왼쪽풀[자식노드]를 표현식변환다.
        정수 인덱스기준 = 노드오른쪽풀[자식노드]를 표현식변환다.
        정수 결과주소 = -1을 새임시변수다.
        정수 명령번호주소 = 명령등록(명령_원소주소, 결과주소, 배열기준, ...).
        명령번호주소 >= 0이면 {
            (배열기준 >= 0) * (임시변수원소크기풀[배열기준] == 8) > 0이면 {
                명령정수값풀[명령번호주소] = 8.
            }
            아니면 { 명령정수값풀[명령번호주소] = 1. }
        }
        반환 결과주소.
    }
    (* Existing path: identifier/variable address *)
    ...
}
```

**PE encoder** (`pe_gen.gl`):
```글
(* 원소 주소: 결과 = &배열[인덱스] — base + index*size, no deref *)
(종류 == 명령_원소주소)이면 {
    PE_적재_r10(인자1).              (* array base *)
    PE_적재_r11(인자2).              (* index *)
    PE_캐시무효화().
    정수 원소크기3 = 명령정수값풀[명령인덱스].
    원소크기3 == 8이면 { 인코딩_imul_r11_imm(8). }
    원소크기3 == 4이면 { 인코딩_imul_r11_imm(4). }
    인코딩_add_r10_r11().             (* r10 = base + index*size *)
    PE_저장_r10(결과).                (* store address as-is, no deref *)
    반환 1.
}
```

### Verification

```
주소: 0000002183DFF998       (* ← before fix: 0x2 *)
배열주소: 0000002183DFF998   (* ← matches *)
```

---

## Bug #2: Pointer-arithmetic scaling failure (`*(ptr + N)` returns 0)

### Symptom

```글
정수[4] 배열.
배열[0] = 10.  배열[1] = 20.  배열[2] = 30.
정수 참조 포인터 = &배열[0].
*포인터               (* 10 — correct *)
*(포인터 + 1)         (* 0 — wrong, should be 20 *)
*(포인터 + 2)         (* 0 — wrong, should be 30 *)
```

`포인터 + N` was adding bytes instead of scaled offsets, so it was reading intermediate bytes (+1 byte) rather than the next element (+8 bytes) of the `정수[4]` array.

### Root Cause

The pointer-arithmetic scaling logic (`ir_transform.gl:599`) consults `임시변수원소크기풀`:
```글
((연산자 == 종류_더하기) + (연산자 == 종류_빼기) > 0) * (왼쪽 >= 0) > 0이면 {
    임시변수원소크기풀[왼쪽] > 1이면 {
        포인터스케일 = 임시변수원소크기풀[왼쪽].
    }
}
```

But **the local variable declaration path never set `임시변수원소크기풀` for reference (pointer) types**. The existing code (`ir_transform.gl:1023`) only handled `노드_배열타입`:
```글
(타입노드 >= 0) * (노드종류풀[타입노드] == 노드_배열타입) > 0이면 {
    임시변수크기풀[변수] = 배열총크기계산(타입노드).
    임시변수원소크기풀[변수] = 배열원소크기결정(타입노드).
}
(* ← No branch for reference types *)
```

### Trap Encountered in the First Attempt

Naively setting `임시변수원소크기풀 = 8` for reference types **breaks self-hosting**. Why:

`PE_적재_r10` (`pe_gen.gl:1725`) interprets `임시변수원소크기풀 > 0` as an **"is array"** signal and enters the `lea` (address) path:
```글
(임시변수원소크기풀[임시번호] > 0) * (임시변수종류풀[임시번호] != 3) > 0이면 {
    주소적재 = 1.   (* ← lea path *)
}
```

Raising this signal on pointer variables would load **the stack-slot address of the pointer variable instead of the pointer value**. Code like `공허 참조 파일 = 파일_열기(...)` would silently break, and the compiler would fail to build itself.

In other words, the existing field was overloaded to carry both **"is array"** and **"pointer element size"** signals, and they had to be separated.

### Fix

**New dedicated field** (`ir.gl`):
```글
정수[65536] 임시변수원소크기풀.         (* Existing: array element size *)
정수[65536] 임시변수포인터원소크기풀.   (* New: pointer-arithmetic scaling only *)
```

**Element-size helper for reference targets** (`ir_transform.gl`):
```글
[정수 참조타입노드를 참조원소크기결정]은 → 정수 {
    참조타입노드 < 0이면 { 반환 0. }
    정수 대상타입 = 노드왼쪽풀[참조타입노드].
    대상타입 < 0이면 { 반환 0. }
    정수 대상종류 = 노드종류풀[대상타입].
    대상종류 == 노드_기본타입이면 {
        정수 원시타입 = 노드연산자풀[대상타입].
        (원시타입 == 종류_문자) * (원시타입 != 종류_문자열) > 0이면 { 반환 1. }
        (원시타입 == 종류_공허)이면 { 반환 1. }
        반환 8.
    }
    반환 8.
}
```

**Set at variable declaration** (`ir_transform.gl`):
```글
(* If reference (pointer) type, store pointer-arithmetic scaling size *)
(타입노드 >= 0) * (노드종류풀[타입노드] == 노드_참조타입) > 0이면 {
    임시변수포인터원소크기풀[변수] = 참조원소크기결정(타입노드).
}
```

**Extended scaling logic** (`ir_transform.gl`):
```글
((연산자 == 종류_더하기) + (연산자 == 종류_빼기) > 0) * (왼쪽 >= 0) > 0이면 {
    임시변수원소크기풀[왼쪽] > 1이면 {
        포인터스케일 = 임시변수원소크기풀[왼쪽].
    }
    아니면 임시변수포인터원소크기풀[왼쪽] > 1이면 {   (* ← added *)
        포인터스케일 = 임시변수포인터원소크기풀[왼쪽].
    }
}
```

### Verification

```
기본: 10
오프셋1: 20    (* ← before fix: 0 *)
오프셋2: 30    (* ← before fix: 0 *)
```

---

## Bug #3: Garbage values when accessing struct-pointer parameter fields via `의`

### Symptom

```글
묶음 점은 정수 가로, 정수 세로.

[점 참조 포인터를 의표시]는 {
    쓰기("의-접근: 가로=%d 세로=%d\n", 포인터의 가로, 포인터의 세로).
}
(* Output: 의-접근: 가로=306183712 세로=306183776 — garbage *)
```

For pointer parameters, `→` (arrow) worked correctly, but `의` (dot access) returned garbage values that looked like stack addresses.

### Root Cause

The `명령_필드적재` handler at `pe_gen.gl:3035`:
```글
(종류 == 명령_필드적재)이면 {
    정수 화살표여부 = 명령타입풀[명령인덱스].
    화살표여부 == 1이면 {
        PE_적재_r10(인자1).                 (* → : load pointer VALUE into r10 *)
    }
    아니면 (인자1 >= 0) * (임시변수종류풀[인자1] == 2) > 0이면 {
        ... global struct lea ...
    }
    아니면 {
        정수 구조체오프셋 = PE_임시오프셋[인자1].
        인코딩_lea_r10_rbp(구조체오프셋).   (* 의 : assume local struct → lea *)
    }
    ...
    인코딩_mov_r10_deref_r10().             (* load field value *)
}
```

The code mistook a **pointer parameter for a local struct** and emitted `lea r10, [rbp+offset]`. This yields **the stack-slot address of the pointer variable** (i.e. a pointer-to-pointer). Adding the field offset and dereferencing then reads garbage.

### Fix (`pe_gen.gl`)

Detect pointer parameters and automatically apply arrow semantics:
```글
(종류 == 명령_필드적재)이면 {
    정수 화살표여부 = 명령타입풀[명령인덱스].
    (* Even with '의' access, apply arrow semantics if the target is a pointer parameter *)
    (화살표여부 == 0) * (인자1 >= 0) * (임시변수종류풀[인자1] == 3) * (임시변수원소크기풀[인자1] > 0) > 0이면 {
        화살표여부 = 1.
    }
    화살표여부 == 1이면 {
        PE_적재_r10(인자1).
    }
    ...
}
```

`임시변수종류풀[인자1] == 3` means "parameter"; `임시변수원소크기풀[인자1] > 0` means "pointer-typed parameter" (already set to 8 at `ir_transform.gl:1367` for reference-type parameters). `명령_필드저장` receives the same treatment.

### Verification

```
의-접근: 가로=10 세로=20     (* ← before fix: 306183712 / 306183776 *)
```

---

## Bug #4: Global variable negative initialization evaluated to 0

### Symptom

```글
정수 에러 = 0 - 3.    (* Runtime value: 0 — wrong *)
정수 직접음수 = -5.   (* Runtime value: 0 — wrong *)
```

If the initializer of a global variable was an **expression** rather than a plain literal, it was silently ignored, leaving the BSS default value of 0.

### Root Cause

The global-initialization loop at `pe_gen.gl:4325`:
```글
정수 초기노드종류 = 노드종류풀[초기노드].
(* Only integer literals are handled *)
(초기노드종류 == 노드_정수리터럴)이면 {
    정수 초기값 = 노드정수풀[초기노드].
    ... generate mov [rip+disp32], r10 ...
}
(* ← No branches for unary/binary operators → expressions are ignored *)
```

`-5` is `노드_단항연산(빼기, 5)`, and `0 - 3` is `노드_이항연산(빼기, 0, 3)` — neither matched.

### Fix (`pe_gen.gl`)

Added two compile-time constant-folding helpers:
```글
[정수 노드를 정수상수표현인가]는 → 정수 {
    노드 < 0이면 { 반환 0. }
    정수 종류 = 노드종류풀[노드].
    (종류 == 노드_정수리터럴)이면 { 반환 1. }
    (종류 == 노드_단항연산)이면 {
        정수 연산자 = 노드연산자풀[노드].
        (연산자 == 종류_빼기) + (연산자 == 종류_더하기) > 0이면 {
            반환 정수상수표현인가(노드왼쪽풀[노드]).
        }
        반환 0.
    }
    (종류 == 노드_이항연산)이면 {
        정수 연산자2 = 노드연산자풀[노드].
        (연산자2 == 종류_더하기) + (연산자2 == 종류_빼기) + (연산자2 == 종류_곱하기) + (연산자2 == 종류_나누기) > 0이면 {
            ... recurse on both operands ...
        }
        반환 0.
    }
    반환 0.
}

[정수 노드를 정수상수평가]는 → 긴정수 {
    (* Literal: return as-is *)
    (* Unary minus: -X *)
    (* Binary +/-/*/: recursive compute *)
    ...
}
```

Generalized the global-initialization loop:
```글
(* If the initializer is a constant expression, fold and emit it — literal + unary/binary arithmetic *)
정수상수표현인가(초기노드) != 0이면 {
    긴정수 초기값긴 = 정수상수평가(초기노드).
    정수 초기값 = 초기값긴.
    ... existing code emission ...
}
```

### Verification

```
에러: -3          (* ← before fix: 0 *)
직접음수: -5      (* ← before fix: 0 *)
```

---

## Bug #5: Numeric constant macros evaluate to 0 at runtime

### Symptom

```글
정의 원주율 3.14159.
정의 상수정수 42.

쓰기("원주율: %f\n", 원주율).       (* Output: 0.000000 *)
쓰기("상수정수: %d\n", 상수정수).   (* Output: 14163998 (garbage) *)
```

### Root Cause

Macros are registered in `compiler.gl`, but `매크로치환` was **only used during function-call name mangling** (`pe_gen.gl:280`):
```글
[문자열 이름을 PE_호출맹글링]은 → 문자열 {
    문자열 치환됨은 이름을 매크로치환다.   (* ← only here *)
    ...
}
```

So **function aliases** such as `정의 쓰기 printf` worked, but value macros were never consulted: they were treated as plain identifiers → undefined variable → garbage/0.

### Fix (`ir_transform.gl`)

During identifier resolution (after failed variable / enum / function lookups), consult the macro table and emit a numeric literal:
```글
(* Numeric macro substitution — emit integer/float values as constants *)
문자열 매크로값 = 매크로치환(식별이름).
매크로값 != 식별이름이면 {
    정수 첫글자 = 매크로값[0].
    정수 시작위치 = 0.
    첫글자 == 45이면 { 시작위치 = 1. 첫글자 = 매크로값[1]. }  (* negative *)
    (첫글자 >= 48) * (첫글자 <= 57) > 0이면 {                  (* starts with a digit *)
        정수 소수점개수 = 0.
        정수 위치 = 시작위치.
        정수 유효숫자 = 1.
        (매크로값[위치] != 0) * (유효숫자 == 1) > 0동안 {
            정수 글자 = 매크로값[위치].
            글자 == 46이면 { 소수점개수 = 소수점개수 + 1. }
            아니면 ((글자 < 48) + (글자 > 57) > 0)이면 { 유효숫자 = 0. }
            위치 = 위치 + 1.
        }
        (유효숫자 == 1) * (소수점개수 == 1) > 0이면 {
            (* Float macro → 명령_상수실수 *)
            ...
        }
        (유효숫자 == 1) * (소수점개수 == 0) > 0이면 {
            (* Integer macro → 명령_상수정수 *)
            정수 매인덱스2 = 명령등록(명령_상수정수, 매결과2, ...).
            명령정수값풀[매인덱스2] = strtoll_10(매크로값).
            ...
        }
    }
}
```

### Verification

```
원주율: 3.141590    (* ← before fix: 0.000000 *)
상수정수: 42        (* ← before fix: 14163998 *)
```

---

## Bug #6: Morphological analyzer mis-splits Korean identifiers (`와이` → `와`+`이` crash)

### Symptom

```글
정수 와이 = 100.   (* ← compiler segfaults *)
```

The Korean lexer, following its particle-splitting rules, broke `와이` into `와` (conjunctive particle) + `이` (subject particle), and the parser crashed on the resulting tokens.

### Root Cause

The declaration-name-mode splitting logic at `lexer.gl:654`:
```글
(어근알려짐 == 0) * 조사인가(선접종류) * (선어근길이 >= 3) > 0이면 {
    참거짓 부분제외 = 0.
    (* Exclusion dictionary check (나이, 넓이, etc.) *)
    ...
    부분제외 == 0이면 {
        어근알려짐 = 1.
        심볼등록(선어근).    (* ← self-confirms '와' as a valid symbol *)
    }
}
```

When processing `와이`:
1. Suffix `이` (3 bytes) matches → stem `와` (3 bytes) remains
2. `와` is not a keyword, not in the exclusion dictionary, and not a pre-existing symbol
3. Stem length ≥ 3 bytes passes the condition
4. No compound-word match in the exclusion dictionary either
5. → Register `와` as a symbol self-referentially and split → tokens `와` + `이`
6. The parser sees `정수 와 이 = 100.` → crash

The fundamental flaw: **there was no check for the case where the stem itself is a particle/ending (affix text)**.

### Fix (`lexer.gl`)

Add an affix-text exact match check for single-syllable stems:
```글
(어근알려짐 == 0) * 조사인가(선접종류) * (선어근길이 >= 3) > 0이면 {
    참거짓 부분제외 = 0.
    (* If the stem is one syllable and matches an affix text exactly, disallow splitting (e.g. 와이=와+이) *)
    선어근길이 == 3이면 {
        정수 조사검사번 = 0.
        (조사검사번 < 접사수) * (부분제외 == 0)동안 {
            접사바이트수배열[조사검사번] == 3이면 {
                문자열_일부비교(단어시작, 접사텍스트배열[조사검사번], 3) == 0이면 {
                    부분제외 = 1.
                }
            }
            조사검사번 = 조사검사번 + 1.
        }
    }
    ... existing exclusion-dictionary check ...
}
```

### Verification

```
와이=100 원넓이=314
```

---

## Bug #7: Incorrect argument passing when string interpolation is mixed with format specifiers

### Symptom

```글
정수 값 = 255.
문자열 이름 = "철수".
쓰기("이름={이름} 값=%d 16진=%x\n", 값, 값).
(* Output: 이름=철수 값=2026569728 16진=fffffffc — garbage *)
```

When `{interpolation}` tokens and `%d`/`%x` format specifiers were mixed in the same string, argument mapping went wrong.

### Root Cause

The `노드_호출` handler at `ir_transform.gl:824` **replaces the entire call** with `보간호출생성` if the first argument is a string literal containing an interpolation token:
```글
(첫인자값노드 >= 0) * (노드종류풀[첫인자값노드] == 노드_문자열리터럴) > 0이면 {
    ...
    보간대상 > 0이면 {
        보간호출생성(문자열내용).   (* Ignores extra args, emits segment-wise calls *)
        반환 -1.
    }
}
```

`보간호출생성` splits the string on `{name}` and issues a separate `printf()` for each segment. The trailing segment `" 값=%d 16진=%x\n"` is emitted as its own printf call — but that printf **does not receive the arguments corresponding to `%d`/`%x`**, so it reads garbage off the stack.

### Fix (`ir_transform.gl`)

Skip the interpolation path when extra arguments are present (fall through to the normal printf path):
```글
정수 첫인자 = 노드왼쪽풀[노드].
첫인자 >= 0이면 {
    정수 첫인자값노드 = 인자값풀[첫인자].
    정수 보간대상 = 0.
    정수 추가인자있음 = 0.
    인자다음풀[첫인자] >= 0이면 { 추가인자있음 = 1. }   (* ← added *)
    (첫인자값노드 >= 0) * (노드종류풀[첫인자값노드] == 노드_문자열리터럴) * (추가인자있음 == 0) > 0이면 {
        ...
    }
}
```

### Policy Decision

- **Pure interpolation** (`"{이름}={값}"` alone): continues to work
- **Pure format** (`"값=%d", 값`): continues to work
- **Mixed** (`"이름={이름} %d", 값`): format specifiers are honored; `{이름}` is emitted literally

This forces the user to pick one or the other — predictability over convenience.

### Verification

```
이름={이름} 값=255 16진=ff   (* ← %d, %x correct *)
플레인: 철수=255              (* ← pure interpolation still works *)
```

---

## Non-reproducible / Documented Workarounds

### Backslash escapes (`\\` → `\`)

Verified correct in all tested cases. Judged to have been fixed at some point after `문제점.txt` was written:
```
Single: [\]       ✓
Double: [\\]      ✓
Path:   [C:\Users\test]   ✓
```

### `공허 참조` function pointers

By design, `공허 참조` is **a generic `void*` pointer** (e.g. for `malloc` results) and is not intended as a function-pointer type. The dedicated function-pointer syntax should be used instead:

```글
[->공허] 콜백 = 함수이름.   (* void-returning function pointer *)
콜백().                     (* Works correctly *)
```

---

## Overall Verification

- **Self-hosting fixed point**: IDENTICAL (stage2 == stage3 SHA256)
- **Regression suite `tests/*.gl`** (9 files): all `exit=0`
- **New reproduction cases** (14): all `exit=0`

## Known Remaining Issues

- **Byte-load path for char-pointer dereference**: `*(charPtr+N)` has a byte-unit read encoding flaw (scaling works correctly, but the dereference encoding is flawed).
- **Unary `*` parser precedence**: symmetric to the `&` issue — `*p[i]` parses as `(*p)[i]`. No affected real-world code has been observed yet, so deferred as follow-up work.

---

## Architectural Lessons

1. **Use semantically separated signal fields**: `임시변수원소크기풀` was overloaded to signal both "is array" and "pointer element size", causing the pointer-scaling fix to break self-hosting. Resolved by introducing the dedicated `임시변수포인터원소크기풀` field.

2. **Lvalue paths are independent**: address-of (`&`), assignment LHS, and reference dereference require **code paths distinct from rvalue evaluation**. Blindly running the child through `표현식변환` is inappropriate for lvalues.

3. **Make parser precedence explicit**: taking a unary operator's operand as `기본표현식()` conflicts with C-style postfix > unary precedence. Unary operators must apply to the result of `접미표현식()`.

4. **Morphological splitting has a self-reference trap**: registering a suspected symbol and then deciding "it's registered so it's valid" is a circular logic that causes crashes. Splitting conditions need independent checks such as "the stem is not itself an affix".
