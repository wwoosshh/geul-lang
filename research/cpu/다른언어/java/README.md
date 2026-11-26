# Java 로 옮긴 여섯 짝

`research/cpu` 의 C 여섯(`fib.c` · `sieve.c` · `bubble.c` · `matmul.c` · `sha256.c` · `rope.c`)을 Java SE 로 줄마다 옮긴 것이다.
C 가 글 소스를 옮긴 것과 같은 뜻으로 — 언어의 꼴로 다시 쓰지 않고, 같은 알고리즘 · 같은 입력 크기 · 같은 반복의 짜임과 순서 ·
같은 함수 나눔으로. 기본 패키지이고 파일마다 `public static void main` 이 하나다.

| 파일 | 짝 |
|---|---|
| [Fib.java](Fib.java) | [fib.c](../../fib.c) |
| [Sieve.java](Sieve.java) | [sieve.c](../../sieve.c) |
| [Bubble.java](Bubble.java) | [bubble.c](../../bubble.c) |
| [Matmul.java](Matmul.java) | [matmul.c](../../matmul.c) |
| [Sha256.java](Sha256.java) | [sha256.c](../../sha256.c) |
| [Rope.java](Rope.java) | [rope.c](../../rope.c) |

## 빌드 · 실행

JDK 26.0.2.1(Oracle HotSpot, 기본 G1)로 확인했다. 클래스 파일은 저장소 밖에 둔다. 저장소 꼭대기에서:

```
javac -encoding UTF-8 -d <클래스폴더> research/cpu/다른언어/java/*.java
java -cp <클래스폴더> Fib
java -cp <클래스폴더> Sieve
java -cp <클래스폴더> Bubble
java -cp <클래스폴더> Matmul
java -cp <클래스폴더> Sha256
java -cp <클래스폴더> Rope
```

- 소스는 모두 ASCII 라 `-encoding` 은 없어도 된다. `*.java` 는 PowerShell 에서도 javac 가 스스로 펼친다.
- JVM 옵션은 필요 없다. 기본 힙(물리 메모리의 1/4 — 32 GB 기계에서 최대 8 GB)으로 충분하다. 가장 큰 배열은 sieve 50 MB,
  sha256 64 MB, rope 16 MB, matmul 6 MB 이다.
- `javac -Xlint:all` 에서 경고 · 오류가 없다.

## 출력

모두 C 와 바이트까지 같다. 한 줄 + LF 이고, `println` 대신 `print(... + "\n")` 을 써서 윈도에서도 CRLF 가 되지 않는다.

| 프로그램 | 표준출력 |
|---|---|
| Fib | `102334155` |
| Sieve | `3001134` |
| Bubble | `5 49684 99999` |
| Matmul | `234371186.250000` |
| Sha256 | `f85505310ac55800e8f0eaf99106e28513c68366d240f98a5c50e8c9208bba25` |
| Rope | `113896039283458 1 0` |

실수 결과는 JIT 단계에 따라 달라지지 않는다. Rope · Matmul 은 `-Xint` · `-XX:TieredStopAtLevel=1`(C1 만) ·
`-XX:-TieredCompilation`(C2 만)으로 돌렸고, Sha256 은 뒤의 둘로 돌렸다. 모두 출력이 같았다. JDK 17 부터 Java 의 실수는 늘 엄격한
IEEE 754 이고(JEP 306), `a * b + c` 를 스스로 합치지 않는다. C 를 `-ffp-contract=off` 로 빌드하는 것과 같다(`UseFMA` 플래그는
`Math.fma` 의 내장 구현에만 쓰이고, 여기서는 `Math.fma` 를 쓰지 않는다).

## 옮긴 규칙

- 타입: `int64_t` → `long`, `int32_t` → `int`, `double` · `float` 는 그대로. 배열 첨자는 쓰는 자리에서 `(int)` 로 바꾼다.
  변환은 C 와 같다: `(long)x` 는 0 쪽으로 자르고, `(float)d` 는 가장 가까운 짝수로 반올림한다. `>>` 는 산술 시프트다.
  시프트 양은 모두 0 ~ 63 안이라 Java 가 6 비트로 자르는 일이 없다(`rotr` 의 `32 - n` 은 7 ~ 30).
- `char` 버퍼 → `byte[]`. C 와 같은 `& 255` 로 읽는다.
- 함수 → `static` 메서드. 이름은 camelCase 다: `list_new` → `listNew`, `hash_block` → `hashBlock`, `dd_add` → `ddAdd`,
  `big_div_small` → `bigDivSmall` …
- 구조체 → 필드만 가진 `static final` 안쪽 클래스: `dd` → `Rope.DD`, `intlist` → `Sha256.IntList`, `hashstate` → `Sha256.HashState`.
  결과를 첫 인자에 쓰는 C 의 꼴(`dd_add(r, a, b)`)을 그대로 둔다. 연산마다 새 객체를 돌려주지 않는다.
- 전역 → 정적 필드. 자리가 고정된 C 의 정적 배열 · 구조체(`sin_coef` · `cos_coef`, `halfpi_dd`, `dd_ln2`, `rope_cos` · `rope_sin`)는
  `static final` 참조로 썼다. 내용은 바뀌고 자리만 고정된다. 정적 포인터(`K`, `rope_cos_tab` · `rope_sin_tab`)는 `final` 이 아닌
  정적 필드다. `#define BIGW 9` → `static final int BIGW = 9`.
- 비트 바꾸기(`memcpy`) → `Double.doubleToRawLongBits` · `longBitsToDouble`, `Float.floatToRawIntBits` · `intBitsToFloat`.
- 참 · 거짓으로 쓰는 C 의 `int` → `boolean`: `is_inf` · `is_nan` · `big_is_zero` 의 반환값과 `fast_sure` · `done` · `cc` 다.
  글 원본에서는 `참거짓` 이다.
- 정수목록은 용량 8 에서 두 배씩 자라는 목록 그대로다(`realloc` → `Arrays.copyOf`). `listValue` 가 `listCheck` 를 부르고, 범위를
  벗어나면 C 와 같은 `error: index … out of [0, …)` 를 표준출력에 찍은 뒤 `System.exit(1)` 한다. 이 길은 따로 시험했다(종료 코드 1, 같은 바이트).
- 출력: `printf` → `System.out.print(… + "\n")`, `%f` → `String.format(Locale.ROOT, "%f", sum)`, `fprintf(stderr, …)` →
  `System.err.print`, `exit(1)` → `System.exit(1)`.
- 쓰지 않은 것: `MessageDigest`, `Integer/Long.rotateRight`, 스트림, 스레드, `Math.fma`, Unsafe · VarHandle · Vector API.

## C 와 같게 할 수 없던 곳

1. **스택의 구조체 · 배열.** Java 에는 스택에 두는 구조체 · 배열이 없다. 그래서 C 의 지역 `dd s, t, v;` 는 같은 블록의 `new DD()` 가
   된다. `hash_block` 의 `int64_t w[64]` 는 부를 때마다 `new long[64]` 가 된다. 64 MB 에 약 105 만 번이고, 한 번에 528 B 를 0 으로
   채운다. 첨자가 반복 변수라 C2 의 탈출 분석이 이 할당을 없애지 못한다. `char tail[128]` · `int64_t pw[BIGW]` · `double freq[64]`
   도 `new` 로 옮겼다. rope 의 `DD` 임시값은 준비 단계(원주율, 주파수 64 개)와 느린 길 한 번에만 나온다. 뜨거운 길(`fastTrig` ·
   `fastFloat`)은 원시값뿐이다. 프로그램의 꼴을 지키려고 정적 임시 저장소로 끌어올리지 않았다. 측정에서 할당을 빼고 싶다면
   의미가 있는 곳은 `w` 하나다.
2. **구조체 대입.** Java 의 객체 대입은 같은 객체를 가리키게 할 뿐이다. 그래서 `pw = t`, `dd sum = x, term = x`,
   `dd s = r, …, ts = r`, `rope_sin = s` 같은 값 복사는 필드마다 복사해서 썼다.
3. **포인터 산술.** `hash_block(s->h, d + k)` → `hashBlock(s.h, d, k)`. 블록 포인터를 (배열, `long` 오프셋)으로 넘기고,
   `block[4 * i]` 는 `block[(int)(off + 4 * i)]` 가 된다.
4. **C 문자열.** C 의 문자열 상수는 0 으로 끝나는 `char` 배열이다. C 에 없는 작은 도움 함수 둘을 더했다. `cstr(String)` 은 0 으로
   끝나는 `byte[]` 를 만든다(`prepare` 에서 네 번, `hash_end` 에서 한 번). `jstr(byte[])` 는 `%s` 처럼 0 까지 읽는다. 둘 다 뜨거운
   반복 밖에서만 쓰인다.
5. **0 으로 채운 할당.** `malloc` 과 달리 Java 의 `new` 배열은 0 으로 채워진다. 여섯 모두 읽기 전에 모든 원소를 쓰므로 결과는
   같고, 채우는 일만 JVM 몫으로 더해진다(sieve 50 MB, sha256 64 MB, rope 16 MB, matmul 6 MB).
6. **범위 검사.** JVM 은 배열 접근마다 범위를 본다. C 는 sha256 의 `list_check` 밖에서는 보지 않는다. JIT 은 증명할 수 있는 검사를 지운다.
7. **프로세스 시간에 드는 것.** JVM 시작, 해석 실행 뒤의 JIT 컴파일(`main` 안의 반복은 OSR 로 컴파일된다), 그리고 문자열 잇기
   (`invokedynamic`)와 `String.format` 의 첫 쓰임 비용이 든다. Matmul 의 `String.format` 은 `Formatter` 와 로캘 자료
   (`DecimalFormatSymbols`, CLDR 제공자)를 올린다. Fib 보다 클래스가 약 230 개 많고, 거의 모두 CDS 보관 파일에서 온다.
   `Locale.US` 로 바꿔도 올리는 클래스는 같다.

시간은 재지 않았다. 빌드와 출력만 확인했다.
