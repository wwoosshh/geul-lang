# 미구현 언어 기능 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 시스템 프로그래밍 언어 핵심 기능 8건 (A1-A5, B1-B3) 중 즉시+단기 6건 구현

**Architecture:** 쉬운 승리(typedef, const, static) 먼저, 그 다음 높은 임팩트(unsigned, 포인터 산술, union) 순. 각 Task 후 `python3 build.py --install`로 자체빌드 검증.

**Tech Stack:** 글 언어, x86-64 PE, 네이티브 자체빌드

---

## 파일 구조

| 파일 | 수정 내용 |
|------|-----------|
| `src/ir_transform.gl` | typedef 등록, union 필드등록, const 강제, 포인터 산술 스케일링, unsigned 타입 전파 |
| `src/pe_gen.gl` | unsigned div/shr/setcc 분기, static BSS 배치 |
| `src/ir.gl` | unsigned 플래그 배열 (임시변수부호풀) |

---

### Task 1: typedef 네이티브 지원 (A3)

**Files:**
- Modify: `src/ir_transform.gl:1266-1273` (프로그램변환 별칭 디스패치)
- Modify: `src/ir_transform.gl` (별칭 테이블 + 타입 해석)
- Test: `tests/typedef_test.gl`

- [ ] **Step 1: 테스트 작성**

```글
포함 "std/core.gl".

별칭 정수길이는 긴정수.
별칭 바이트는 문자.

[시작하기]는 → 정수 {
    정수길이 큰수 = 100.
    바이트 글자 = 65.
    쓰기("값: %lld, 문자: %c\n", 큰수, 글자).
    반환 0.
}
```

`tests/typedef_test.gl`로 저장. Expected: `값: 100, 문자: A`

- [ ] **Step 2: 별칭 등록 테이블 추가**

`src/ir_transform.gl` 상단 (묶음 관련 배열 근처)에:

```글
(* 별칭(typedef) 테이블 *)
정수 최대별칭항 = 256.
문자열[256] 별칭이름풀.
정수[256] 별칭타입풀.      (* 원본 타입의 AST 노드 인덱스 *)
정수 별칭수 = 0.

[정수 노드를 별칭등록]은 {
    별칭수 < 최대별칭항이면 {
        별칭이름풀[별칭수] = 노드이름풀[노드].
        별칭타입풀[별칭수] = 노드왼쪽풀[노드].
        별칭수를 증가하다.
    }
}

[문자열 이름으로 별칭찾기]는 → 정수 {
    정수 번호 = 0.
    (번호 < 별칭수)동안 {
        문자열_비교(이름, 별칭이름풀[번호]) == 0이면 {
            반환 별칭타입풀[번호].
        }
        번호를 증가하다.
    }
    반환 -1.
}
```

- [ ] **Step 3: 프로그램변환에서 별칭 디스패치 추가**

`src/ir_transform.gl` 1270행 근처, `노드_묶음정의` 디스패치 뒤에:

```글
        (노드종류풀[항목] == 노드_별칭정의)이면 {
            항목을 별칭등록다.
        }
```

- [ ] **Step 4: 타입 해석에서 별칭을 원본으로 치환**

변수 선언 시 타입이 `노드_묶음타입명`으로 인식될 때, 먼저 별칭 테이블을 검색. `src/ir_transform.gl`의 변수 선언 처리 (약 905행) 근처에서, 타입 노드가 `노드_묶음타입명`이지만 묶음 크기가 0이면 별칭 검색:

```글
        (* 타입이 별칭이면 원본 타입으로 치환 *)
        (타입노드 >= 0) * (노드종류풀[타입노드] == 노드_묶음타입명) > 0이면 {
            정수 별칭원본 = 노드이름풀[타입노드]로 별칭찾기다.
            별칭원본 >= 0이면 {
                타입노드 = 별칭원본.
            }
        }
```

이 코드를 기존 묶음 타입 처리 **앞에** 삽입하여 별칭이 먼저 해석되도록 함.

- [ ] **Step 5: 빌드 + 테스트**

```bash
python3 build.py --install
dist/compiler.exe tests/typedef_test.gl && tests/typedef_test.exe
```

Expected: `값: 100, 문자: A`

- [ ] **Step 6: 커밋**

```bash
git add src/ir_transform.gl tests/typedef_test.gl
git commit -m "feat: typedef(별칭) 네이티브 지원"
```

---

### Task 2: const 강제 (B3)

**Files:**
- Modify: `src/ir_transform.gl:548-568` (대입 처리)
- Modify: `src/ir_transform.gl` (변수 속성 배열)
- Test: `tests/const_test.gl`

- [ ] **Step 1: 테스트 작성**

```글
포함 "std/core.gl".

[시작하기]는 → 정수 {
    상수 정수 최대값 = 100.
    쓰기("최대: %d\n", 최대값).
    반환 0.
}
```

Expected: `최대: 100` (컴파일 성공)

```글
(* const_error_test.gl — 이 파일은 컴파일 오류가 나야 함 *)
포함 "std/core.gl".

[시작하기]는 → 정수 {
    상수 정수 최대값 = 100.
    최대값 = 200.
    반환 0.
}
```

Expected: 타입 오류 메시지 출력

- [ ] **Step 2: 변수 상수 플래그 배열 추가**

`src/ir_transform.gl` 상단에:

```글
정수[4096] 변수상수풀.
```

- [ ] **Step 3: 변수 선언 시 상수 플래그 저장**

변수 등록 함수 근처에서, AST 노드의 `상수` 플래그(노드플래그풀의 비트 2)를 확인:

```글
        (* 상수 플래그 저장 *)
        (노드플래그풀[선언] & 4) != 0이면 {
            변수상수풀[변수수 - 1] = 1.
        }
```

먼저 `노드플래그풀`에서 상수 비트가 어디에 설정되는지 파서를 확인할 것.

- [ ] **Step 4: 대입 시 상수 검사**

`src/ir_transform.gl` 556행 근처, 변수 찾기 후:

```글
            (* 상수 변수 대입 금지 *)
            정수 변수인덱스 = 노드이름풀[왼쪽노드]로 변수인덱스찾기다.
            (변수인덱스 >= 0) * (변수상수풀[변수인덱스] == 1) > 0이면 {
                쓰기("오류: 상수 '%s'에 대입할 수 없습니다\n", 노드이름풀[왼쪽노드]).
                타입오류수를 증가하다.
            }
```

- [ ] **Step 5: 빌드 + 테스트**

```bash
python3 build.py --install
dist/compiler.exe tests/const_test.gl && tests/const_test.exe
dist/compiler.exe --strict tests/const_error_test.gl  # 오류 발생해야 함
```

- [ ] **Step 6: 커밋**

```bash
git add src/ir_transform.gl tests/const_test.gl tests/const_error_test.gl
git commit -m "feat: const(상수) 변수 대입 금지 강제"
```

---

### Task 3: union 네이티브 지원 (A2)

**Files:**
- Modify: `src/ir_transform.gl:71-102` (필드 등록 + 크기)
- Modify: `src/ir_transform.gl:1266-1273` (프로그램변환 디스패치)
- Test: `tests/union_test.gl`

- [ ] **Step 1: 테스트 작성**

```글
포함 "std/core.gl".

합침 값 {
    정수 정수값.
    실수 실수값.
}

[시작하기]는 → 정수 {
    값 데이터.
    데이터.정수값 = 42.
    쓰기("정수: %d\n", 데이터.정수값).
    반환 0.
}
```

Expected: `정수: 42`

- [ ] **Step 2: 합침 필드 등록 함수 추가**

`src/ir_transform.gl`의 `묶음필드등록` 뒤에:

```글
[정수 노드를 합침필드등록]은 {
    정수 필드 = 노드왼쪽풀[노드].
    정수 최대크기 = 0.
    (필드 >= 0)동안 {
        묶음오프셋수 < 최대묶음필드항이면 {
            묶음오프셋이름풀[묶음오프셋수] = 필드이름풀[필드].
            묶음오프셋소속풀[묶음오프셋수] = 노드이름풀[노드].
            묶음오프셋값풀[묶음오프셋수] = 0.  (* union은 모든 필드 오프셋 0 *)
            묶음오프셋수를 증가하다.
        }
        최대크기 = 최대크기 + 0.  (* 모든 필드 8바이트 고정이므로 *)
        최대크기 < 8이면 { 최대크기 = 8. }
        필드 = 필드다음풀[필드].
    }
    (* union 전체 크기 = 최대 필드 크기 (현재는 모든 필드 8바이트) *)
    묶음크기수 < 최대묶음크기항이면 {
        묶음크기이름풀[묶음크기수] = 노드이름풀[노드].
        묶음크기값풀[묶음크기수] = 8.  (* 현재 모든 필드 8바이트 *)
        묶음크기수를 증가하다.
    }
}
```

- [ ] **Step 3: 프로그램변환에서 합침 디스패치 추가**

1270행 근처:

```글
        (노드종류풀[항목] == 노드_합침정의)이면 {
            항목을 합침필드등록다.
        }
```

- [ ] **Step 4: 빌드 + 테스트**

```bash
python3 build.py --install
dist/compiler.exe tests/union_test.gl && tests/union_test.exe
```

Expected: `정수: 42`

- [ ] **Step 5: 커밋**

```bash
git add src/ir_transform.gl tests/union_test.gl
git commit -m "feat: union(합침) 네이티브 지원"
```

---

### Task 4: 포인터 산술 타입 인식 (A5)

**Files:**
- Modify: `src/ir_transform.gl:492-528` (이항 연산 처리)
- Test: `tests/ptrarith_test.gl`

- [ ] **Step 1: 테스트 작성**

```글
포함 "std/core.gl".

[시작하기]는 → 정수 {
    정수[5] 배열.
    배열[0] = 10. 배열[1] = 20. 배열[2] = 30.

    정수 참조 포인터 = 배열.
    정수 참조 두번째 = 포인터 + 1.  (* 8바이트 이동해야 함 *)
    쓰기("값: %d\n", *두번째).
    반환 0.
}
```

Expected: `값: 20` (포인터+1이 8바이트 이동하여 배열[1] 접근)

- [ ] **Step 2: 이항 연산에서 포인터+정수 스케일링**

`src/ir_transform.gl` 492-497행, `노드_이항연산` 블록에서 `이항명령생성` 호출 전에 포인터 산술 스케일링 삽입:

```글
    (종류 == 노드_이항연산)이면 {
        정수 왼쪽 = 노드왼쪽풀[노드]를 표현식변환다.
        정수 오른쪽 = 노드오른쪽풀[노드]를 표현식변환다.
        정수 결과 = -1을 새임시변수다.
        정수 연산종류 = 노드연산자풀[노드].
        정수 명령 = 연산종류를 연산자명령변환다.

        (* 포인터 산술: ptr + n → ptr + (n * 원소크기) *)
        정수 스케일필요 = 0.
        정수 원소크기 = 0.
        ((연산종류 == 종류_더하기) + (연산종류 == 종류_빼기) > 0)이면 {
            (왼쪽 >= 0) * (임시변수원소크기풀[왼쪽] > 1) > 0이면 {
                스케일필요 = 1.
                원소크기 = 임시변수원소크기풀[왼쪽].
            }
        }
        스케일필요 == 1이면 {
            정수 크기임시 = -1을 새임시변수다.
            상수정수명령생성(크기임시, 원소크기).
            정수 스케일된 = -1을 새임시변수다.
            이항명령생성(명령_곱하기, 스케일된, 오른쪽, 크기임시).
            이항명령생성(명령, 결과, 왼쪽, 스케일된).
        }
        아니면 {
            이항명령생성(명령, 결과, 왼쪽, 오른쪽).
        }
        (* 이하 타입 결정 코드 유지 *)
```

- [ ] **Step 3: 빌드 + 테스트**

```bash
python3 build.py --install
dist/compiler.exe tests/ptrarith_test.gl && tests/ptrarith_test.exe
```

Expected: `값: 20`

- [ ] **Step 4: 커밋**

```bash
git add src/ir_transform.gl tests/ptrarith_test.gl
git commit -m "feat: 포인터 산술 타입 인식 (ptr+1 → sizeof 스케일링)"
```

---

### Task 5: unsigned 산술 (A1)

**Files:**
- Modify: `src/ir.gl` (unsigned 플래그 배열)
- Modify: `src/ir_transform.gl` (unsigned 타입 전파)
- Modify: `src/pe_gen.gl:2087-2120,2282-2286,503-508,2170-2175` (div/shr/setcc 분기)
- Test: `tests/unsigned_test.gl`

- [ ] **Step 1: 테스트 작성**

```글
포함 "std/core.gl".

[시작하기]는 → 정수 {
    부호없는 정수 값 = 4294967295.  (* 0xFFFFFFFF *)
    부호없는 정수 반 = 값 / 2.
    쓰기("반: %u\n", 반).
    부호없는 정수 시프트 = 값 >> 1.
    쓰기("시프트: %u\n", 시프트).
    반환 0.
}
```

Expected: `반: 2147483647`, `시프트: 2147483647` (unsigned로 처리되어 양수 유지)

- [ ] **Step 2: unsigned 플래그 배열 추가**

`src/ir.gl`에 임시변수 배열 근처:

```글
정수[65536] 임시변수부호풀.  (* 0=signed(기본), 1=unsigned *)
```

- [ ] **Step 3: IR 변환에서 unsigned 타입 전파**

`src/ir_transform.gl`에서 변수 선언 시 `종류_부호없는` 타입 감지:

```글
        (타입토큰 == 종류_부호없는)이면 {
            임시변수부호풀[변수] = 1.
        }
```

- [ ] **Step 4: PE 코드젠에서 unsigned 분기**

`src/pe_gen.gl`:

**나누기 (2087행):** `idiv` → `div` 분기:
```글
    (종류 == 명령_나누기)이면 {
        (* 실수 분기는 기존 유지 *)
        ...
        (* 정수 나누기 *)
        PE_적재_rax(인자1).
        임시변수부호풀[인자1] == 1이면 {
            (* unsigned: xor rdx,rdx + div *)
            인코딩_xor_rdx_rdx().
            PE_적재_r11(인자2).
            인코딩_div_r11().
        }
        아니면 {
            인코딩_cqo().
            PE_적재_r11(인자2).
            인코딩_idiv_r11().
        }
        PE_저장_rax(결과).
    }
```

**오른쪽 시프트 (2282행):** `sar` → `shr` 분기:
```글
    (종류 == 명령_오른쪽이동)이면 {
        PE_적재_r10(인자1).
        PE_적재_rcx(인자2).
        임시변수부호풀[인자1] == 1이면 {
            인코딩_shr_r10_cl().
        }
        아니면 {
            인코딩_sar_r10_cl().
        }
        PE_저장_r10(결과).
    }
```

**비교 (2170행):** signed setcc → unsigned setcc 분기:
```글
    (* unsigned 비교면 다른 조건 코드 사용 *)
    정수 부호없음 = 0.
    (인자1 >= 0) * (임시변수부호풀[인자1] == 1) > 0이면 { 부호없음 = 1. }
    부호없음 == 1이면 {
        (종류 == 명령_큼)이면         { 인코딩_setcc(151). }  (* 0x97 seta *)
        (종류 == 명령_작음)이면       { 인코딩_setcc(146). }  (* 0x92 setb *)
        (종류 == 명령_크거나같음)이면 { 인코딩_setcc(147). }  (* 0x93 setae *)
        (종류 == 명령_작거나같음)이면 { 인코딩_setcc(150). }  (* 0x96 setbe *)
    }
    아니면 {
        (* 기존 signed 비교 유지 *)
    }
```

새 인코딩 함수 추가:
- `인코딩_div_r11`: `49 F7 F3` (REX.W+B, F7 /6, r11)
- `인코딩_shr_r10_cl`: `49 D3 EA` (REX.W+B, D3 /5, r10)
- `인코딩_xor_rdx_rdx`: `48 31 D2`

- [ ] **Step 5: 빌드 + 테스트**

```bash
python3 build.py --install
dist/compiler.exe tests/unsigned_test.gl && tests/unsigned_test.exe
```

- [ ] **Step 6: 커밋**

```bash
git add src/ir.gl src/ir_transform.gl src/pe_gen.gl tests/unsigned_test.gl
git commit -m "feat: unsigned 산술 (div/shr/setcc 분기)"
```

---

### Task 6: 전체 검증 + 고정점

- [ ] **Step 1: 전체 테스트**

```bash
python3 build.py --test --fixpoint
```

Expected: 모든 테스트 PASS, 고정점 달성

- [ ] **Step 2: 기존 예제 프로그램 확인**

```bash
for f in examples/구구단.글 examples/피보나치.글 examples/버블정렬.글 examples/종합검증.글; do
    dist/compiler.exe "$f" 2>&1 | tail -1
done
```

- [ ] **Step 3: 이슈 추적 문서 갱신**

`docs/superpowers/plans/2026-04-07-language-feature-fixes.md`에서 완료 항목을 해결 완료 섹션으로 이동.
