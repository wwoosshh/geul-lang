# 네이티브 백엔드 마일스톤 1 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 글 소스를 C 컴파일러 없이 네이티브 .exe로 컴파일 — 피보나치(10)=55를 ExitProcess 종료 코드로 반환

**Architecture:** 기존 파서/IR 재사용, 어셈블리 생성기 수정, ml64+link로 최종 빌드. 파이프라인: .글 → 파서 → AST → IR(타입 정보 추가) → x86-64 MASM .asm → ml64.exe → .obj → link.exe → .exe

**Tech Stack:** 글 언어, x86-64 MASM, ml64.exe (MSVC 도구), link.exe

**Spec:** 설계 승인 완료 (이전 대화에서)

---

## 파일 구조

```
자체호스팅/
├── (기존) 형태소분석기.글, 구문분석기.글, 토큰정의.글, 구문트리.글, 유니코드.글
├── (기존) 중간표현.글          ← 수정: 타입 필드 추가
├── (기존) IR변환기.글          ← 수정: 타입 전파 로직
├── (기존) 어셈블리생성기.글    ← 수정: 함수 프롤로그/에필로그, ExitProcess
├── (새로) 네이티브컴파일러.글  ← 통합 드라이버 (ml64+link 호출)
예제/
├── (새로) 네이티브테스트.글    ← 테스트용 피보나치
```

---

## Task 1: 테스트 프로그램 작성 + 수동 MASM 검증

**Files:**
- Create: `예제/네이티브테스트.글`
- Create: `예제/네이티브_수동.asm` (수동 작성 MASM, 목표 출력물 참고용)

목표: 먼저 "원하는 최종 결과물"을 수동으로 만들어 ml64+link로 빌드되는지 확인.

- [ ] **Step 1: 테스트 글 소스 작성**

```글
(* 네이티브 백엔드 테스트 — 피보나치(10) = 55를 종료 코드로 반환 *)

[정수 수를 피보나치]는 -> 정수 {
    수 <= 1이면 { 반환 수. }
    정수 가는 (수 - 1)을 피보나치다.
    정수 나는 (수 - 2)를 피보나치다.
    반환 가 + 나.
}

[시작하기]는 -> 정수 {
    정수 결과는 10을 피보나치다.
    반환 결과.
}
```

- [ ] **Step 2: 동일 로직의 MASM 어셈블리를 수동 작성**

```asm
; 네이티브_수동.asm — 피보나치(10)=55, ExitProcess로 반환
extrn ExitProcess : proc

.code

; 피보나치(rcx) → rax
_fn0 proc
    push rbp
    mov rbp, rsp
    sub rsp, 32

    ; 수 = rcx, 스택 [rbp-8]에 저장
    mov QWORD PTR [rbp-8], rcx

    ; 수 <= 1이면 반환 수
    cmp rcx, 1
    jg L_recurse
    mov rax, rcx
    leave
    ret

L_recurse:
    ; 가 = 피보나치(수-1)
    mov rcx, QWORD PTR [rbp-8]
    dec rcx
    call _fn0
    mov QWORD PTR [rbp-16], rax    ; 가 저장

    ; 나 = 피보나치(수-2)
    mov rcx, QWORD PTR [rbp-8]
    sub rcx, 2
    call _fn0
    ; rax = 나

    ; 반환 가 + 나
    add rax, QWORD PTR [rbp-16]
    leave
    ret
_fn0 endp

; main() → ExitProcess(피보나치(10))
main proc
    push rbp
    mov rbp, rsp
    sub rsp, 32

    mov rcx, 10
    call _fn0
    ; rax = 55

    mov rcx, rax
    call ExitProcess
main endp

end
```

- [ ] **Step 3: ml64 + link로 빌드하여 검증**

```powershell
# MSVC 환경에서:
ml64 /c /nologo 예제\네이티브_수동.asm /Fo예제\네이티브_수동.obj
link /nologo /entry:main /subsystem:console 예제\네이티브_수동.obj kernel32.lib /OUT:예제\네이티브_수동.exe
예제\네이티브_수동.exe
echo $LASTEXITCODE   # 55이면 성공
```

- [ ] **Step 4: 검증 후 정리**

이 수동 .asm이 성공하면 이것이 자동 생성의 "골든 레퍼런스". 실패하면 MASM 문법이나 ABI를 수정.

---

## Task 2: 중간표현.글에 타입 필드 추가

**Files:**
- Modify: `자체호스팅/중간표현.글`

기존 IR 명령어에 타입 정보를 추가. 기존 코드를 최소한으로 수정.

- [ ] **Step 1: 타입 열거형 추가**

`중간표현.글`의 명령종류 나열 뒤에 추가:

```글
(* ===== IR 타입 종류 ===== *)
나열 IR타입은 {
    IR타입_없음 = 0,
    IR타입_정수,      (* int, 4바이트 *)
    IR타입_긴정수,    (* long long, 8바이트 *)
    IR타입_실수,      (* double, 8바이트 *)
    IR타입_문자,      (* char, 1바이트 *)
    IR타입_참거짓,    (* bool, 4바이트 *)
    IR타입_참조,      (* pointer, 8바이트 *)
    IR타입_공허       (* void *)
}.
```

- [ ] **Step 2: 명령어 타입 풀 배열 추가**

기존 `명령결과풀`, `명령좌항풀` 등과 같은 패턴으로:

```글
정수[131072] 명령타입풀.   (* 각 명령어의 결과 타입 *)
```

- [ ] **Step 3: 임시변수 타입 풀 추가**

```글
정수[32768] 임시변수타입풀.  (* 각 임시변수의 타입 *)
```

- [ ] **Step 4: 명령어 생성 함수에 타입 매개변수 추가**

기존 `명령추가` 함수를 수정하지 않고, 타입을 설정하는 헬퍼 추가:

```글
[정수 명령번호를 정수 타입을 명령타입설정]은 {
    명령번호 >= 0이면 {
        명령타입풀[명령번호] = 타입.
    }
}

[정수 임시번호를 정수 타입을 임시타입설정]은 {
    임시번호 >= 0이면 {
        임시변수타입풀[임시번호] = 타입.
    }
}
```

- [ ] **Step 5: IR 덤프에 타입 표시 추가**

기존 `IR텍스트출력` 함수에서 타입 정보도 출력하도록 수정.

- [ ] **Step 6: 기존 IR→C 백엔드에 영향 없는지 확인**

```
글cc.exe 예제\한글전용_인사.글
```
Expected: 기존과 동일하게 컴파일 성공. (타입 풀은 추가만 되고 기존 코드가 참조하지 않으므로 무영향)

---

## Task 3: IR변환기.글에 타입 전파 로직 추가

**Files:**
- Modify: `자체호스팅/IR변환기.글`

AST→IR 변환 시 타입 정보를 같이 기록.

- [ ] **Step 1: 리터럴 변환에 타입 설정**

`정수변환`, `실수변환`, `문자열변환` 등의 함수에서 IR 명령 생성 후 타입 설정:

```글
(* 정수 리터럴 *)
정수 임시는 임시생성().
임시를 IR타입_긴정수를 임시타입설정다.
```

- [ ] **Step 2: 이항 연산에 타입 전파**

양쪽 피연산자의 타입을 기반으로 결과 타입 결정:
- 정수 + 정수 → 정수
- 정수 + 실수 → 실수
- 비교 연산 → 참거짓

- [ ] **Step 3: 함수 반환 타입 전파**

호출 결과의 타입을 함수 선언의 반환 타입에서 가져오기.

- [ ] **Step 4: 변수 선언 타입 기록**

변수 등록 시 AST의 타입 노드를 읽어 IR 타입으로 변환.

- [ ] **Step 5: 테스트 — IR 덤프로 타입 확인**

`네이티브테스트.글`을 IR로 변환하고 덤프하여 모든 명령에 타입이 붙는지 확인.

---

## Task 4: 어셈블리생성기.글 수정 — 네이티브 실행파일 생성

**Files:**
- Modify: `자체호스팅/어셈블리생성기.글`

기존 어셈블리 생성기를 수정하여 마일스톤 1 범위의 정수 프로그램을 올바르게 생성.

- [ ] **Step 1: ExitProcess 호출 추가**

`main` 함수(시작하기)의 에필로그에서 `ExitProcess(rax)` 호출:

```글
(* main 함수 에필로그 수정 *)
문자열_비교(함수이름, "시작하기") == 0이면 {
    "    mov rcx, rax\n"을 쓰기다.
    "    call ExitProcess\n"을 쓰기다.
}
```

- [ ] **Step 2: 외부 심볼 선언 추가**

.asm 파일 상단에 `extrn ExitProcess : proc` 추가.

- [ ] **Step 3: 함수 호출 규약 검증**

Windows x64 ABI:
- 인자 1~4: rcx, rdx, r8, r9
- 반환값: rax
- 호출자가 32바이트 섀도 스페이스 확보
- 스택 16바이트 정렬

기존 코드가 이미 대부분 구현되어 있으나, 재귀 호출 시 callee-saved 레지스터(rbx) 보존이 필요할 수 있음.

- [ ] **Step 4: 재귀 호출 시 로컬 변수 보존 확인**

피보나치의 `가` 변수가 두 번째 재귀 호출 후에도 살아있어야 함. 스택 기반이므로 자동으로 보존되지만, 레지스터 기반이면 push/pop 필요.

기존 코드는 스택 기반(모든 임시변수가 `[rbp-N]`)이므로 자동 보존됨. 확인만 필요.

- [ ] **Step 5: 테스트용 어셈블리 출력**

`네이티브테스트.글`에서 어셈블리를 생성하고, Task 1의 수동 .asm과 비교하여 구조적으로 동일한지 확인.

---

## Task 5: 네이티브컴파일러.글 — 통합 드라이버

**Files:**
- Create: `자체호스팅/네이티브컴파일러.글`

전체 파이프라인을 하나로 묶는 드라이버.

- [ ] **Step 1: 기본 구조 작성**

글도구.글과 유사한 구조. 자체호스팅 파서의 재귀 함수 버그 때문에 글cc.exe로 빌드.

```
사용법: 네이티브컴파일러 <소스.글>
```

파이프라인:
1. 소스 파일 읽기
2. 포함 전처리
3. 파싱 (AST 생성)
4. IR 변환 (타입 포함)
5. 어셈블리 생성 (.asm 파일 출력)
6. ml64.exe 호출 (.asm → .obj)
7. link.exe 호출 (.obj → .exe)

- [ ] **Step 2: ml64.exe 경로 탐색**

MSVC 설치 경로에서 ml64.exe 찾기:
```
C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\ml64.exe
```

- [ ] **Step 3: link.exe 호출 구성**

```
link /nologo /entry:main /subsystem:console 출력.obj kernel32.lib /OUT:출력.exe
/LIBPATH:"..." (MSVC lib + Windows SDK lib)
```

- [ ] **Step 4: 빌드 + 테스트**

```powershell
# 1. 네이티브컴파일러를 글cc로 빌드
글cc.exe 자체호스팅\네이티브컴파일러.글

# 2. 네이티브컴파일러로 테스트 프로그램 컴파일
자체호스팅\네이티브컴파일러.exe 예제\네이티브테스트.글

# 3. 결과 확인
예제\네이티브테스트.exe
echo $LASTEXITCODE   # 55이면 성공!
```

---

## Task 6: 추가 테스트 + 엣지 케이스

**Files:**
- Create: `예제/네이티브_조건문테스트.글`
- Create: `예제/네이티브_반복문테스트.글`

- [ ] **Step 1: 조건문 테스트**

```글
[시작하기]는 -> 정수 {
    정수 값은 42.
    값 > 10이면 { 반환 1. }
    반환 0.
}
```
Expected: 종료 코드 1

- [ ] **Step 2: 반복문 테스트**

```글
[시작하기]는 -> 정수 {
    정수 합계 = 0.
    정수 번호 = 1.
    (번호 <= 10)동안 {
        합계 = 합계 + 번호.
        번호++다.
    }
    반환 합계.
}
```
Expected: 종료 코드 55 (1+2+...+10)

- [ ] **Step 3: 모든 테스트 통과 확인**

3개 프로그램 (피보나치, 조건문, 반복문) 모두 네이티브 컴파일 후 올바른 종료 코드 반환.

---

## 검증 기준

마일스톤 1 완료 조건:
1. `네이티브컴파일러.exe 예제\네이티브테스트.글` 실행 시 .exe 생성
2. 생성된 .exe가 C 컴파일러 없이 동작
3. 종료 코드가 55 (피보나치(10))
4. 조건문/반복문 테스트도 통과
