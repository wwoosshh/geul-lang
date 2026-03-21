# 글 언어 종합 벤치마크 시스템 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 글 언어의 컴파일러/런타임 성능을 C, Python, Go, Rust, Java와 비교 측정하는 종합 벤치마크 시스템 구축

**Architecture:** PowerShell 중앙 제어 스크립트가 각 언어별 벤치마크를 컴파일/실행하고, 내부 고정밀 타이머 + 외부 Stopwatch로 이중 측정. 결과를 콘솔 표로 출력.

**Tech Stack:** 글 언어, C (MSVC), Python 3, Go, Rust, Java, PowerShell 7+

**Spec:** `docs/superpowers/specs/2026-03-19-benchmark-design.md`

---

## 파일 구조

```
벤치마크/
├── 실행.ps1              ← 중앙 제어 (진입점)
├── 설정.ps1              ← 언어 탐지, 경로, 목록
├── 글/
│   ├── 피보나치.글
│   ├── 정렬.글
│   ├── 행렬곱.글
│   ├── 소수판별.글
│   ├── 파일처리.글
│   └── 메모리할당.글
├── c/
│   ├── fibonacci.c
│   ├── sort.c
│   ├── matrix.c
│   ├── primes.c
│   ├── fileio.c
│   └── memory.c
├── python/
│   ├── fibonacci.py
│   ├── sort.py
│   ├── matrix.py
│   ├── primes.py
│   ├── fileio.py
│   └── memory.py
├── go/
│   ├── fibonacci.go
│   ├── sort.go
│   ├── matrix.go
│   ├── primes.go
│   ├── fileio.go
│   └── memory.go
├── rust/
│   ├── fibonacci.rs
│   ├── sort.rs
│   ├── matrix.rs
│   ├── primes.rs
│   ├── fileio.rs
│   └── memory.rs
├── java/
│   ├── Fibonacci.java
│   ├── Sort.java
│   ├── Matrix.java
│   ├── Primes.java
│   ├── FileIO.java
│   └── Memory.java
└── 결과/
    └── (자동 생성)

표준/정밀시간.글            ← 신규 표준 라이브러리 모듈
```

---

## Task 1: 표준/정밀시간.글 모듈 생성

**Files:**
- Create: `표준/정밀시간.글`

이 모듈은 Windows `QueryPerformanceCounter`를 래핑하여 마이크로초 정밀도 타이머를 제공한다.

- [ ] **Step 1: `표준/정밀시간.글` 작성**

```글
(*
 * 정밀시간 표준 라이브러리
 * Windows QueryPerformanceCounter를 이용한 고정밀 시간 측정
 *
 * 사용법:
 *   정밀시작다.
 *   (* ... 측정할 코드 ... *)
 *   실수 경과 = 정밀끝다.   (* 밀리초 단위 *)
 *)

(* === 외부 Windows API 선언 === *)
외부 [긴정수 참조 값을 QueryPerformanceCounter]는 -> 정수.
외부 [긴정수 참조 값을 QueryPerformanceFrequency]는 -> 정수.

(* === 내부 상태 === *)
정적 긴정수 시작틱 = 0.
정적 긴정수 측정빈도 = 0.

(* 정밀시작: 타이머 시작 *)
[정밀시작]는 {
    긴정수 빈도 = 0.
    &빈도를 QueryPerformanceFrequency다.
    측정빈도 = 빈도다.
    &시작틱을 QueryPerformanceCounter다.
}

(* 정밀끝: 경과 시간을 밀리초(ms)로 반환 *)
[정밀끝]는 -> 실수 {
    긴정수 끝틱 = 0.
    &끝틱을 QueryPerformanceCounter다.
    반환 (끝틱 - 시작틱) * 1000.0 / 측정빈도.
}
```

- [ ] **Step 2: 정밀시간 모듈 테스트**

간단한 테스트 파일로 검증:
```글
포함 "표준/기본.글"
포함 "표준/정밀시간.글"

[시작하기]는 {
    정밀시작다.
    정수 합계 = 0.
    정수 번호 = 0.
    (번호 < 1000000)동안 {
        합계 = 합계 + 번호.
        번호++다.
    }
    실수 경과는 정밀끝다.
    "합계: %d\n"을 합계를 쓰기다.
    "경과: %.3f ms\n"을 경과를 쓰기다.
}
```

Run: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "부트스트랩\compile_test.ps1" "정밀시간테스트"`
Expected: `경과: X.XXX ms` 형태의 출력 (0보다 큰 값)

- [ ] **Step 3: 테스트 파일 정리, 커밋**

---

## Task 2: 벤치마크 디렉토리 구조 + C 벤치마크 6개 (기준선)

**Files:**
- Create: `벤치마크/c/fibonacci.c`
- Create: `벤치마크/c/sort.c`
- Create: `벤치마크/c/matrix.c`
- Create: `벤치마크/c/primes.c`
- Create: `벤치마크/c/fileio.c`
- Create: `벤치마크/c/memory.c`

C가 기준선(baseline)이므로 먼저 작성. 모든 벤치마크는 내부 QPC 타이머로 핵심 구간만 측정하고 `RESULT:밀리초` 형식으로 출력.

- [ ] **Step 1: 디렉토리 생성**

```bash
mkdir -p 벤치마크/{글,c,python,go,rust,java,결과}
```

- [ ] **Step 2: `벤치마크/c/fibonacci.c` 작성**

```c
#include <stdio.h>
#include <windows.h>

int fib(int n) {
    if (n <= 1) return n;
    return fib(n - 1) + fib(n - 2);
}

int main(void) {
    LARGE_INTEGER freq, start, end;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&start);

    int result = fib(40);

    QueryPerformanceCounter(&end);
    double ms = (double)(end.QuadPart - start.QuadPart) * 1000.0 / freq.QuadPart;
    printf("fib(40) = %d\n", result);
    printf("RESULT:%.3f\n", ms);
    return 0;
}
```

- [ ] **Step 3: `벤치마크/c/sort.c` 작성**

100만 개 정수 퀵소트. `rand()`로 배열 생성, 정렬 구간만 측정.

```c
#include <stdio.h>
#include <stdlib.h>
#include <windows.h>

void quicksort(int *arr, int low, int high) {
    if (low >= high) return;
    int pivot = arr[high];
    int i = low;
    for (int j = low; j < high; j++) {
        if (arr[j] < pivot) {
            int tmp = arr[i]; arr[i] = arr[j]; arr[j] = tmp;
            i++;
        }
    }
    int tmp = arr[i]; arr[i] = arr[high]; arr[high] = tmp;
    quicksort(arr, low, i - 1);
    quicksort(arr, i + 1, high);
}

#define N 1000000

int main(void) {
    int *arr = malloc(N * sizeof(int));
    srand(42);
    for (int i = 0; i < N; i++) arr[i] = rand();

    LARGE_INTEGER freq, start, end;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&start);

    quicksort(arr, 0, N - 1);

    QueryPerformanceCounter(&end);
    double ms = (double)(end.QuadPart - start.QuadPart) * 1000.0 / freq.QuadPart;
    printf("sorted[0]=%d sorted[%d]=%d\n", arr[0], N-1, arr[N-1]);
    printf("RESULT:%.3f\n", ms);
    free(arr);
    return 0;
}
```

- [ ] **Step 4: `벤치마크/c/matrix.c` 작성**

500x500 행렬 곱셈. 행렬은 1차원 배열, 곱셈 구간만 측정.

```c
#include <stdio.h>
#include <stdlib.h>
#include <windows.h>

#define SZ 500

int main(void) {
    double *A = malloc(SZ * SZ * sizeof(double));
    double *B = malloc(SZ * SZ * sizeof(double));
    double *C = calloc(SZ * SZ, sizeof(double));
    for (int i = 0; i < SZ * SZ; i++) { A[i] = (double)(i % 100); B[i] = (double)((i * 7) % 100); }

    LARGE_INTEGER freq, start, end;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&start);

    for (int i = 0; i < SZ; i++)
        for (int k = 0; k < SZ; k++)
            for (int j = 0; j < SZ; j++)
                C[i * SZ + j] += A[i * SZ + k] * B[k * SZ + j];

    QueryPerformanceCounter(&end);
    double ms = (double)(end.QuadPart - start.QuadPart) * 1000.0 / freq.QuadPart;
    printf("C[0][0]=%.1f C[499][499]=%.1f\n", C[0], C[SZ*SZ-1]);
    printf("RESULT:%.3f\n", ms);
    free(A); free(B); free(C);
    return 0;
}
```

- [ ] **Step 5: `벤치마크/c/primes.c` 작성**

에라토스테네스 체, 100만까지.

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

#define LIMIT 1000000

int main(void) {
    char *sieve = malloc(LIMIT + 1);

    LARGE_INTEGER freq, start, end;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&start);

    memset(sieve, 1, LIMIT + 1);
    sieve[0] = sieve[1] = 0;
    for (int i = 2; (long long)i * i <= LIMIT; i++) {
        if (sieve[i]) {
            for (int j = i * i; j <= LIMIT; j += i)
                sieve[j] = 0;
        }
    }
    int count = 0;
    for (int i = 2; i <= LIMIT; i++) if (sieve[i]) count++;

    QueryPerformanceCounter(&end);
    double ms = (double)(end.QuadPart - start.QuadPart) * 1000.0 / freq.QuadPart;
    printf("primes up to %d: %d\n", LIMIT, count);
    printf("RESULT:%.3f\n", ms);
    free(sieve);
    return 0;
}
```

- [ ] **Step 6: `벤치마크/c/fileio.c` 작성**

파일 읽고 공백 기준 단어 수 세기. 파일 경로는 argv[1]로 받음.

```c
#include <stdio.h>
#include <stdlib.h>
#include <windows.h>

int main(int argc, char *argv[]) {
    if (argc < 2) { printf("Usage: fileio <path>\n"); return 1; }
    FILE *f = fopen(argv[1], "rb");
    if (!f) { printf("Cannot open %s\n", argv[1]); return 1; }
    _fseeki64(f, 0, SEEK_END);
    long long sz = _ftelli64(f);
    _fseeki64(f, 0, SEEK_SET);
    char *buf = malloc(sz + 1);
    fread(buf, 1, sz, f);
    buf[sz] = 0;
    fclose(f);

    LARGE_INTEGER freq, start, end;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&start);

    int words = 0, in_word = 0;
    for (long long i = 0; i < sz; i++) {
        char c = buf[i];
        if (c == ' ' || c == '\n' || c == '\r' || c == '\t') {
            in_word = 0;
        } else if (!in_word) {
            in_word = 1;
            words++;
        }
    }

    QueryPerformanceCounter(&end);
    double ms = (double)(end.QuadPart - start.QuadPart) * 1000.0 / freq.QuadPart;
    printf("words: %d\n", words);
    printf("RESULT:%.3f\n", ms);
    free(buf);
    return 0;
}
```

- [ ] **Step 7: `벤치마크/c/memory.c` 작성**

64바이트 100만 회 순차 할당 → 일괄 해제 + 10만 노드 연결 리스트 순회.

```c
#include <stdio.h>
#include <stdlib.h>
#include <windows.h>

#define ALLOC_COUNT 1000000
#define LIST_SIZE 100000

typedef struct Node { int value; struct Node *next; } Node;

int main(void) {
    LARGE_INTEGER freq, start, end;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&start);

    /* Part 1: malloc/free */
    void *ptrs[1000];
    int total_freed = 0;
    for (int batch = 0; batch < 1000; batch++) {
        for (int i = 0; i < 1000; i++)
            ptrs[i] = malloc(64);
        for (int i = 0; i < 1000; i++)
            free(ptrs[i]);
        total_freed += 1000;
    }

    /* Part 2: linked list */
    Node *head = NULL;
    for (int i = 0; i < LIST_SIZE; i++) {
        Node *n = malloc(sizeof(Node));
        n->value = i;
        n->next = head;
        head = n;
    }
    long long sum = 0;
    for (Node *cur = head; cur; cur = cur->next)
        sum += cur->value;
    /* cleanup */
    while (head) { Node *tmp = head; head = head->next; free(tmp); }

    QueryPerformanceCounter(&end);
    double ms = (double)(end.QuadPart - start.QuadPart) * 1000.0 / freq.QuadPart;
    printf("allocs: %d, list sum: %lld\n", total_freed, sum);
    printf("RESULT:%.3f\n", ms);
    return 0;
}
```

- [ ] **Step 8: C 벤치마크 전체 컴파일 테스트**

```powershell
cd 벤치마크/c
cl /O2 /nologo fibonacci.c /Fe:fibonacci.exe /link kernel32.lib && .\fibonacci.exe
```
Expected: `RESULT:XXX.XXX` 출력

- [ ] **Step 9: 커밋**

---

## Task 3: 글 벤치마크 6개

**Files:**
- Create: `벤치마크/글/피보나치.글`
- Create: `벤치마크/글/정렬.글`
- Create: `벤치마크/글/행렬곱.글`
- Create: `벤치마크/글/소수판별.글`
- Create: `벤치마크/글/파일처리.글`
- Create: `벤치마크/글/메모리할당.글`

모든 글 벤치마크는 `포함 "표준/기본.글"`과 `포함 "표준/정밀시간.글"`을 사용. C 벤치마크와 동일한 알고리즘.

- [ ] **Step 1: `벤치마크/글/피보나치.글` 작성**

```글
포함 "표준/기본.글"
포함 "표준/정밀시간.글"

[정수 수를 피보나치]는 -> 정수 {
    수 <= 1이면 { 반환 수. }
    반환 (수 - 1)을 피보나치 + (수 - 2)를 피보나치.
}

[시작하기]는 {
    정밀시작다.
    정수 결과는 40을 피보나치다.
    실수 경과는 정밀끝다.
    "fib(40) = %d\n"을 결과를 쓰기다.
    "RESULT:%.3f\n"을 경과를 쓰기다.
}
```

- [ ] **Step 2: `벤치마크/글/정렬.글` 작성**

```글
포함 "표준/기본.글"
포함 "표준/정밀시간.글"

외부 [정수 씨앗을 srand]는.
외부 [rand]는 -> 정수.

정의 개수 1000000.

[정수 참조 배열을 정수 낮은값을 정수 높은값을 빠른정렬]은 {
    낮은값 >= 높은값이면 { 반환. }
    정수 기준은 배열[높은값].
    정수 위치는 낮은값.
    정수 순회는 낮은값.
    (순회 < 높은값)동안 {
        배열[순회] < 기준이면 {
            정수 임시는 배열[위치].
            배열[위치] = 배열[순회].
            배열[순회] = 임시.
            위치++다.
        }
        순회++다.
    }
    정수 임시는 배열[위치].
    배열[위치] = 배열[높은값].
    배열[높은값] = 임시.
    배열을 낮은값을 (위치 - 1)을 빠른정렬다.
    배열을 (위치 + 1)을 높은값을 빠른정렬다.
}

[시작하기]는 {
    정수 참조 배열은 할당(개수 * 4).
    42를 srand다.
    정수 번호 = 0.
    (번호 < 개수)동안 {
        배열[번호] = rand().
        번호++다.
    }

    정밀시작다.
    배열을 0을 (개수 - 1)을 빠른정렬다.
    실수 경과는 정밀끝다.

    "sorted[0]=%d sorted[%d]=%d\n"을 배열[0]을 (개수 - 1)을 배열[개수 - 1]을 쓰기다.
    "RESULT:%.3f\n"을 경과를 쓰기다.
    배열을 해제다.
}
```

- [ ] **Step 3: `벤치마크/글/행렬곱.글` 작성**

```글
포함 "표준/기본.글"
포함 "표준/정밀시간.글"

정의 크기 500.

[시작하기]는 {
    실수 참조 가는 할당(크기 * 크기 * 8).
    실수 참조 나는 할당(크기 * 크기 * 8).
    실수 참조 다는 초기할당(크기 * 크기, 8).
    정수 번호 = 0.
    (번호 < 크기 * 크기)동안 {
        가[번호] = (번호 % 100) * 1.0.
        나[번호] = ((번호 * 7) % 100) * 1.0.
        번호++다.
    }

    정밀시작다.

    정수 행 = 0.
    (행 < 크기)동안 {
        정수 중 = 0.
        (중 < 크기)동안 {
            정수 열 = 0.
            (열 < 크기)동안 {
                다[행 * 크기 + 열] = 다[행 * 크기 + 열] + 가[행 * 크기 + 중] * 나[중 * 크기 + 열].
                열++다.
            }
            중++다.
        }
        행++다.
    }

    실수 경과는 정밀끝다.
    "C[0][0]=%.1f C[499][499]=%.1f\n"을 다[0]을 다[크기 * 크기 - 1]을 쓰기다.
    "RESULT:%.3f\n"을 경과를 쓰기다.
    가를 해제다.
    나를 해제다.
    다를 해제다.
}
```

- [ ] **Step 4: `벤치마크/글/소수판별.글` 작성**

```글
포함 "표준/기본.글"
포함 "표준/정밀시간.글"

정의 한계 1000000.

[시작하기]는 {
    문자열 체는 할당(한계 + 1).

    정밀시작다.

    메모리_채우기(체, 1, 한계 + 1).
    체[0] = 0.
    체[1] = 0.
    정수 번호 = 2.
    (번호 * 번호 <= 한계)동안 {
        체[번호]이면 {
            정수 배수는 번호 * 번호.
            (배수 <= 한계)동안 {
                체[배수] = 0.
                배수 = 배수 + 번호.
            }
        }
        번호++다.
    }
    정수 개수 = 0.
    번호 = 2.
    (번호 <= 한계)동안 {
        체[번호]이면 { 개수++다. }
        번호++다.
    }

    실수 경과는 정밀끝다.
    "primes up to %d: %d\n"을 한계를 개수를 쓰기다.
    "RESULT:%.3f\n"을 경과를 쓰기다.
    체를 해제다.
}
```

- [ ] **Step 5: `벤치마크/글/파일처리.글` 작성**

```글
포함 "표준/기본.글"
포함 "표준/정밀시간.글"

[정수 argc를 문자열 참조 argv를 시작하기]는 {
    argc < 2이면 {
        "사용법: 파일처리 <경로>\n"을 쓰기다.
        반환.
    }
    문자열 경로는 argv[1].
    공허 참조 파일은 파일_열기(경로, "rb").
    파일 == 0이면 {
        "파일 열기 실패: %s\n"을 경로를 쓰기다.
        반환.
    }
    파일_위치이동(파일, 0, 2).
    긴정수 크기는 파일_위치(파일).
    파일_위치이동(파일, 0, 0).
    문자열 버퍼는 할당(크기 + 1).
    파일_읽기(버퍼, 1, 크기, 파일).
    버퍼[크기] = 0.
    파일_닫기(파일).

    정밀시작다.

    정수 단어수 = 0.
    정수 단어중 = 0.
    긴정수 위치 = 0.
    (위치 < 크기)동안 {
        문자 글자는 버퍼[위치].
        (글자 == 32) + (글자 == 10) + (글자 == 13) + (글자 == 9) > 0이면 {
            단어중 = 0.
        }
        아니면 {
            단어중 == 0이면 {
                단어중 = 1.
                단어수++다.
            }
        }
        위치++다.
    }

    실수 경과는 정밀끝다.
    "words: %d\n"을 단어수를 쓰기다.
    "RESULT:%.3f\n"을 경과를 쓰기다.
    버퍼를 해제다.
}
```

- [ ] **Step 6: `벤치마크/글/메모리할당.글` 작성**

```글
포함 "표준/기본.글"
포함 "표준/정밀시간.글"

정의 할당횟수 1000000.
정의 목록크기 100000.

묶음 노드는 정수 값, 노드 참조 다음.

[시작하기]는 {
    정밀시작다.

    (* 1부: 100만 회 malloc/free — 1000개씩 배치 처리 *)
    공허 참조[1000] 포인터들.
    정수 배치 = 0.
    정수 총해제 = 0.
    (배치 < 1000)동안 {
        정수 번호 = 0.
        (번호 < 1000)동안 {
            포인터들[번호] = 할당(64).
            번호++다.
        }
        번호 = 0.
        (번호 < 1000)동안 {
            포인터들[번호]을 해제다.
            번호++다.
        }
        총해제 = 총해제 + 1000.
        배치++다.
    }

    (* 2부: 연결 리스트 *)
    노드 참조 머리는 0.
    정수 번호 = 0.
    (번호 < 목록크기)동안 {
        노드 참조 새것은 크기(노드)를 할당다.
        새것→값 = 번호.
        새것→다음 = 머리.
        머리 = 새것.
        번호++다.
    }
    긴정수 합계 = 0.
    노드 참조 현재는 머리.
    (현재 != 0)동안 {
        합계 = 합계 + 현재→값.
        현재 = 현재→다음.
    }
    (* 정리 *)
    (머리 != 0)동안 {
        노드 참조 임시는 머리.
        머리 = 머리→다음.
        임시를 해제다.
    }

    실수 경과는 정밀끝다.
    "allocs: %d, list sum: %lld\n"을 총해제를 합계를 쓰기다.
    "RESULT:%.3f\n"을 경과를 쓰기다.
}
```

- [ ] **Step 7: 글 벤치마크 피보나치 컴파일 테스트**

Run: `powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& '.\글도구.exe' 실행 '벤치마크\글\피보나치.글'"`
Expected: `RESULT:XXX.XXX` 출력

- [ ] **Step 8: 커밋**

---

## Task 4: Python 벤치마크 6개

**Files:**
- Create: `벤치마크/python/fibonacci.py`
- Create: `벤치마크/python/sort.py`
- Create: `벤치마크/python/matrix.py`
- Create: `벤치마크/python/primes.py`
- Create: `벤치마크/python/fileio.py`
- Create: `벤치마크/python/memory.py`

모든 Python 벤치마크는 `time.perf_counter()`로 내부 측정, `RESULT:%.3f` 출력.

- [ ] **Step 1: 6개 Python 벤치마크 파일 작성**

각 파일은 C 버전과 동일한 알고리즘, 동일한 입력. 재귀 한도 설정 (`sys.setrecursionlimit(100000)` for fibonacci). 파일처리는 `sys.argv[1]`로 경로 수신.

- [ ] **Step 2: `python fibonacci.py` 테스트**

Expected: `RESULT:XXX.XXX`

- [ ] **Step 3: 커밋**

---

## Task 5: Go 벤치마크 6개

**Files:**
- Create: `벤치마크/go/fibonacci.go`
- Create: `벤치마크/go/sort.go`
- Create: `벤치마크/go/matrix.go`
- Create: `벤치마크/go/primes.go`
- Create: `벤치마크/go/fileio.go`
- Create: `벤치마크/go/memory.go`

모든 Go 파일은 `package main`, 단독 빌드 가능. `time.Now()` / `time.Since()` 사용.

- [ ] **Step 1: 6개 Go 벤치마크 파일 작성**
- [ ] **Step 2: `go run fibonacci.go` 테스트**
- [ ] **Step 3: 커밋**

---

## Task 6: Rust 벤치마크 6개

**Files:**
- Create: `벤치마크/rust/fibonacci.rs`
- Create: `벤치마크/rust/sort.rs`
- Create: `벤치마크/rust/matrix.rs`
- Create: `벤치마크/rust/primes.rs`
- Create: `벤치마크/rust/fileio.rs`
- Create: `벤치마크/rust/memory.rs`

`std::time::Instant`로 측정. `rustc -C opt-level=2`로 빌드.

- [ ] **Step 1: 6개 Rust 벤치마크 파일 작성**
- [ ] **Step 2: `rustc -C opt-level=2 fibonacci.rs && ./fibonacci.exe` 테스트**
- [ ] **Step 3: 커밋**

---

## Task 7: Java 벤치마크 6개

**Files:**
- Create: `벤치마크/java/Fibonacci.java`
- Create: `벤치마크/java/Sort.java`
- Create: `벤치마크/java/Matrix.java`
- Create: `벤치마크/java/Primes.java`
- Create: `벤치마크/java/FileIO.java`
- Create: `벤치마크/java/Memory.java`

`System.nanoTime()`으로 측정. `javac` 컴파일, `java` 실행.

- [ ] **Step 1: 6개 Java 벤치마크 파일 작성**
- [ ] **Step 2: `javac Fibonacci.java && java Fibonacci` 테스트**
- [ ] **Step 3: 커밋**

---

## Task 8: 설정.ps1 — 언어 탐지 및 설정

**Files:**
- Create: `벤치마크/설정.ps1`

- [ ] **Step 1: `설정.ps1` 작성**

기능:
1. 각 언어 컴파일러/런타임 존재 여부 탐지 (`Get-Command`)
2. MSVC 환경 설정: `vcvarsall.bat x64`를 호출하여 PATH/INCLUDE/LIB 설정. 이미 설정된 경우(cl.exe가 PATH에 있으면) 스킵. 못 찾으면 글도구.글과 동일한 하드코딩 경로 사용.
3. 글도구.exe 경로 설정 (프로젝트 루트에서 상대 경로)
4. 벤치마크 목록 배열 정의
5. 10MB 테스트 데이터 파일 생성 함수 (`벤치마크/결과/testdata.txt`)
6. 각 언어별 컴파일/실행 명령 템플릿
7. **글 최적화**: 글도구.exe는 현재 /O2를 지원하지 않으므로, 글 벤치마크는 글도구로 .c 파일만 생성(검사 모드)한 뒤, 설정.ps1의 MSVC 경로로 직접 `cl /O2`로 컴파일. 이렇게 해야 C 기준선과 동일 최적화 수준에서 비교 가능.

구조:
```powershell
$Script:ProjectRoot = Split-Path $PSScriptRoot -Parent
$Script:BenchDir = $PSScriptRoot
$Script:ResultDir = Join-Path $BenchDir "결과"

# 언어 탐지
$Script:Languages = @{}
# C (MSVC)
$Script:Languages["C"] = @{ Available = $false; Compiler = ""; ... }
# 글
# Python
# Go
# Rust
# Java

# 벤치마크 목록
$Script:Benchmarks = @(
    @{ Name="피보나치"; ... },
    ...
)
```

- [ ] **Step 2: 테스트 — 설정 로드 확인**

```powershell
. .\벤치마크\설정.ps1
$Languages.Keys
```

- [ ] **Step 3: 커밋**

---

## Task 9: 실행.ps1 — 중앙 제어 스크립트

**Files:**
- Create: `벤치마크/실행.ps1`

- [ ] **Step 1: `실행.ps1` 핵심 구조 작성**

기능:
1. `설정.ps1` dot-source
2. 시스템 정보 출력 (OS, CPU, RAM)
3. 설치된 언어 목록 출력
4. 각 벤치마크 순회:
   a. 각 언어별 컴파일 (컴파일 시간 측정)
   b. 5회 반복 실행 (내부 RESULT + 외부 Stopwatch)
   c. 1회차 제외, 2~5회 중앙값 산출
5. 결과 표 출력 (벤치마크당)
6. 종합 요약 출력
7. 결과를 타임스탬프 파일로 저장

핵심 함수:
```powershell
function Invoke-Benchmark($benchName, $langConfig, $args) {
    $results = @()
    for ($i = 0; $i -lt 5; $i++) {
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $output = & $langConfig.RunCmd $args 2>&1
        $sw.Stop()
        $external = $sw.Elapsed.TotalMilliseconds
        $internal = ($output | Select-String "RESULT:(.+)" | ...).Matches.Groups[1].Value
        $results += @{ Internal = [double]$internal; External = $external }
    }
    # 1회차 제외, 2~5회 중앙값
    $valid = $results[1..4] | Sort-Object Internal
    $median = ($valid[1].Internal + $valid[2].Internal) / 2
    return $median
}
```

- [ ] **Step 2: 콘솔 출력 포맷팅 구현**

스펙의 표 형식 그대로 구현. UTF-8 박스 문자 사용.

- [ ] **Step 3: 컴파일러 스트레스 테스트 (7, 8번) 구현**

7번: 글도구로 자체호스팅 소스 컴파일 시간 측정
8번: PowerShell에서 1000개 함수 포함 .글 파일 자동 생성 후 컴파일 시간 측정. 함수 템플릿:
```글
[정수 x를 함수_001]는 -> 정수 { 반환 x + 1. }
[정수 x를 함수_002]는 -> 정수 { 반환 x + 2. }
... (1000개)
```

- [ ] **Step 4: 결과 파일 저장 구현**

`벤치마크/결과/YYYY-MM-DD-HHMMSS.txt`로 콘솔 출력 동일 내용 저장.

- [ ] **Step 5: 전체 통합 테스트**

Run: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "벤치마크\실행.ps1"`
Expected: 설치된 언어에 대해 벤치마크 실행, 결과 표 출력

- [ ] **Step 6: 커밋**

---

## Task 10: 종합 테스트 및 마무리

- [ ] **Step 1: 전체 벤치마크 1회 실행**

모든 벤치마크가 정상 작동하는지 확인. 오류 발생 시 수정.

- [ ] **Step 2: 결과 파일 생성 확인**

`벤치마크/결과/` 디렉토리에 결과 파일 존재 확인.

- [ ] **Step 3: 최종 커밋**
