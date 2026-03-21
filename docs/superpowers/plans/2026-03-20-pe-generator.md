# PE 직접 생성 (ml64/link 제거) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ml64.exe와 link.exe 없이 IR에서 직접 Windows PE 실행파일(.exe)을 생성하여 MSVC 도구 의존성 완전 제거

**Architecture:** IR → x86-64 기계어 인코더 → PE 파일 빌더 → .exe. 어셈블리 텍스트를 거치지 않고 바이트 수준에서 직접 생성. 2패스: 1패스에서 기계어 생성+레이블 수집, 2패스에서 점프/호출 오프셋 패치.

**Tech Stack:** 글 언어, x86-64 ISA, Windows PE 포맷

---

## 파일 구조

```
자체호스팅/
├── PE생성기.글           ← 신규: x86-64 인코더 + PE 빌더 통합
├── 네이티브컴파일러.글   ← 수정: 어셈블리생성기 대신 PE생성기 사용
```

## x86-64 인코딩 레퍼런스 (ml64 출력에서 추출)

```
push rbp                → 55
mov rbp,rsp             → 48 8B EC
sub rsp,IMM32           → 48 81 EC [imm32]
leave                   → C9
ret                     → C3

mov [rbp-N],rcx         → 48 89 4D [disp8] 또는 48 89 8D [disp32]
mov [rbp-N],imm32       → 48 C7 45 [disp8] [imm32] 또는 48 C7 85 [disp32] [imm32]
mov r10,[rbp-N]         → 4C 8B 55 [disp8] 또는 4C 8B 95 [disp32]
mov r11,[rbp-N]         → 4C 8B 5D [disp8] 또는 4C 8B 9D [disp32]
mov [rbp-N],r10         → 4C 89 55 [disp8] 또는 4C 89 95 [disp32]
mov rax,[rbp-N]         → 48 8B 45 [disp8] 또는 48 8B 85 [disp32]
mov [rbp-N],rax         → 48 89 45 [disp8] 또는 48 89 85 [disp32]
mov rcx,r10             → 49 8B CA
mov rdx,r10             → 49 8B D2

add r10,r11             → 4D 03 D3
sub r10,r11             → 4D 2B D3
cmp r10,r11             → 4D 3B D3
inc r10                 → 49 FF C2
test r10,r10            → 4D 85 D2
xor eax,eax             → 33 C0

setle al                → 0F 9E C0
sete al                 → 0F 94 C0
setne al                → 0F 95 C0
setg al                 → 0F 9F C0
setl al                 → 0F 9C C0
setge al                → 0F 9D C0

movzx r10,al            → 4C 0F B6 D0

lea rax,[rip+disp32]    → 48 8D 05 [disp32]

jne rel8                → 75 [rel8]
jmp rel8                → EB [rel8]
jmp rel32               → E9 [rel32]
call rel32              → E8 [rel32]
```

---

## Task 1: PE생성기.글 — 바이트 버퍼 인프라

**Files:**
- Create: `자체호스팅/PE생성기.글`

기계어 바이트를 누적할 버퍼와 유틸리티 함수.

- [ ] **Step 1: 바이트 버퍼 기본 구조 작성**

```글
(* PE생성기.글 — IR → PE 직접 생성 *)
포함 "구문분석기.글"
포함 "IR변환기.글"

(* ===== 기계어 바이트 버퍼 ===== *)
정수 최대코드크기 = 65536.
문자열 코드버퍼 = 0.      (* malloc으로 할당 *)
정수 코드위치 = 0.

[코드버퍼초기화]는 {
    코드버퍼 = 할당(최대코드크기).
    코드위치 = 0.
}

[정수 바이트를 바이트쓰기]는 {
    코드버퍼[코드위치] = 바이트.
    코드위치++다.
}

[정수 값을 리틀엔디안32쓰기]는 {
    (값)을 바이트쓰기다.
    (값 / 256)을 바이트쓰기다.
    (값 / 65536)을 바이트쓰기다.
    (값 / 16777216)을 바이트쓰기다.
}
```

- [ ] **Step 2: 레이블 테이블**

```글
(* ===== 레이블 → 코드 오프셋 매핑 ===== *)
정수 최대레이블수 = 4096.
문자열[4096] 레이블이름풀.
정수[4096] 레이블오프셋풀.
정수 레이블수 = 0.

(* 패치 대기 목록: 아직 확정 안 된 점프/호출의 위치 *)
정수[4096] 패치위치풀.     (* 코드버퍼 내 패치할 오프셋 *)
문자열[4096] 패치대상풀.    (* 대상 레이블 이름 *)
정수[4096] 패치종류풀.      (* 0=rel32, 1=rel8 *)
정수 패치수 = 0.
```

- [ ] **Step 3: 글cc로 빌드하여 문법 검증**

---

## Task 2: x86-64 명령어 인코더

**Files:**
- Modify: `자체호스팅/PE생성기.글`

14개 명령어 패턴을 바이트로 인코딩하는 함수들.

- [ ] **Step 1: 레지스터 인코딩 상수**

```글
(* x86-64 레지스터 번호 *)
정의 레지_RAX 0.
정의 레지_RCX 1.
정의 레지_RDX 2.
정의 레지_RBX 3.
정의 레지_RSP 4.
정의 레지_RBP 5.
정의 레지_R10 10.
정의 레지_R11 11.
```

- [ ] **Step 2: push/pop/leave/ret**

```글
[정수 레지를 인코딩_push]는 { ... }    (* 55 = push rbp *)
[인코딩_leave]는 { 0xC9를 바이트쓰기다. }
[인코딩_ret]는 { 0xC3을 바이트쓰기다. }
```

- [ ] **Step 3: mov reg,[rbp-N] / mov [rbp-N],reg**

disp8 (오프셋 <= 127) vs disp32 분기 처리. REX 프리픽스(0x48/0x4C) 처리.

- [ ] **Step 4: mov [rbp-N],imm32**

```
48 C7 45 disp8 imm32    (오프셋 <= 127)
48 C7 85 disp32 imm32   (오프셋 > 127)
```

- [ ] **Step 5: add/sub/cmp r10,r11**

```
4D 03 D3 = add r10,r11
4D 2B D3 = sub r10,r11
4D 3B D3 = cmp r10,r11
```

- [ ] **Step 6: setCC al / movzx r10,al / test r10,r10**

- [ ] **Step 7: jmp/jne (rel8/rel32) / call rel32**

점프는 2패스가 필요: 1패스에서 패치 목록에 등록, 2패스에서 오프셋 해결.

- [ ] **Step 8: lea rax,[rip+disp32] (문자열 상수 참조)**

- [ ] **Step 9: mov rcx,r10 / mov rdx,r10 (레지스터간 이동)**

- [ ] **Step 10: inc r10 / xor eax,eax**

---

## Task 3: IR → 기계어 변환 루프

**Files:**
- Modify: `자체호스팅/PE생성기.글`

기존 어셈블리생성기의 IR 순회 구조를 참고하여, IR 명령어를 기계어로 변환하는 메인 루프.

- [ ] **Step 1: 함수 프롤로그/에필로그 인코딩**

```
프롤로그: push rbp / mov rbp,rsp / sub rsp,framesize
에필로그: leave / ret (또는 main: mov rcx,rax / call ExitProcess)
```

- [ ] **Step 2: IR 산술 명령어 처리**

명령_더하기, 명령_빼기: r10에 좌항 로드, r11에 우항 로드, add/sub, 결과 저장.

- [ ] **Step 3: IR 비교/분기 명령어 처리**

명령_같음~명령_작거나같음: cmp + setCC + movzx.
명령_조건분기: test + jnz/jmp.
명령_이동: jmp.

- [ ] **Step 4: IR 호출/반환 처리**

명령_인자전달: rcx/rdx/r8/r9에 로드.
명령_호출: call rel32 (내부 함수) 또는 call [rip+disp32] (임포트 함수).
명령_반환: mov rax,결과 + leave + ret.

- [ ] **Step 5: IR 상수/변수 처리**

명령_상수정수: mov [rbp-N],imm32.
명령_상수문자열: lea rax,[rip+disp32] (문자열 오프셋은 .rdata 기준).
명령_복사: mov 간 이동.

- [ ] **Step 6: 레이블 패치 (2패스)**

모든 함수의 기계어 생성 후, 패치 목록 순회하여 점프/호출 오프셋 해결.

- [ ] **Step 7: 피보나치 반복문 버전으로 기계어 검증**

ml64 출력과 바이트 단위 비교 (100% 동일할 필요 없음, 동작만 동일하면 됨).

---

## Task 4: PE 파일 빌더

**Files:**
- Modify: `자체호스팅/PE생성기.글`

생성된 기계어 + 문자열 상수 + 임포트 테이블을 유효한 PE 파일로 조립.

- [ ] **Step 1: DOS 헤더 (64 bytes)**

```
"MZ" + 58 bytes of zeros + PE offset at 0x3C = 0x40
```

- [ ] **Step 2: PE Signature + COFF Header (24 bytes)**

```
"PE\0\0"
Machine: 0x8664 (x86-64)
NumberOfSections: 2 (.text, .rdata)
SizeOfOptionalHeader: 0xF0 (240)
Characteristics: 0x0022 (EXECUTABLE_IMAGE | LARGE_ADDRESS_AWARE)
```

- [ ] **Step 3: Optional Header (240 bytes)**

```
Magic: 0x020B (PE32+)
AddressOfEntryPoint: .text 시작 + main 함수 오프셋
ImageBase: 0x00400000
SectionAlignment: 0x1000
FileAlignment: 0x200
SizeOfImage, SizeOfHeaders 계산
Import Directory RVA/Size (Data Directory[1])
```

- [ ] **Step 4: Section Headers**

```
.text: 기계어 코드
.rdata: 문자열 상수 + 임포트 테이블
```

- [ ] **Step 5: Import Table 구성**

```
Import Directory Entry (kernel32.dll):
  - OriginalFirstThunk → Import Lookup Table
  - Name → "kernel32.dll"
  - FirstThunk → Import Address Table
  - Functions: ExitProcess

Import Directory Entry (ucrtbase.dll):  (* msvcrt.dll 대신 *)
  - Functions: printf

Null terminator entry
```

- [ ] **Step 6: 파일 쓰기**

바이트 배열을 순서대로 파일에 출력: DOS Header → PE Header → Section Headers → .text → .rdata

- [ ] **Step 7: 검증 — 생성된 .exe를 dumpbin으로 확인 + 실행**

---

## Task 5: 네이티브컴파일러 통합

**Files:**
- Modify: `자체호스팅/네이티브컴파일러.글`

ml64/link 호출을 PE생성기 호출로 교체.

- [ ] **Step 1: 어셈블리생성기 대신 PE생성기 포함**

```
포함 "PE생성기.글"     (* 어셈블리생성기.글 대신 *)
```

- [ ] **Step 2: 파이프라인 변경**

```
기존: IR → 어셈프로그램생성 → .asm → ml64 → link → .exe
변경: IR → PE프로그램생성 → .exe (직접 생성)
```

- [ ] **Step 3: 종합 테스트**

```
네이티브컴파일러.exe 예제\네이티브_종합테스트.글
```
Expected: `피보나치(10) = 55`, `1부터 10까지 합 = 55`, `테스트 통과!`

ml64.exe, link.exe 호출 0회.

---

## 검증 기준

마일스톤 5 완료 조건:
1. `네이티브컴파일러.exe`가 ml64/link를 호출하지 않고 .exe를 직접 생성
2. 생성된 .exe가 정상 실행 (피보나치 + printf 출력)
3. MSVC 도구 의존성 제거 (네이티브컴파일러.exe 빌드에만 글cc 필요)
