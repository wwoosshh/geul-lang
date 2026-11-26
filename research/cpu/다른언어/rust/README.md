# Rust 짝 — 여섯 C 프로그램을 줄마다

[`research/cpu`](../../README.md) 의 C 여섯을 Rust 로 줄마다 옮겼다. 알고리즘 · 입력 크기 · 반복의 꼴과 차례 · 함수 나눔 · 타입이 같다.
언어가 아니라 컴파일러를 견주려는 짝이라서 더 빠른 Rust 꼴로 고쳐 쓰지 않았다.

| 파일 | 짝 |
|---|---|
| [fib.rs](fib.rs) | [fib.c](../../fib.c) |
| [sieve.rs](sieve.rs) | [sieve.c](../../sieve.c) |
| [bubble.rs](bubble.rs) | [bubble.c](../../bubble.c) |
| [matmul.rs](matmul.rs) | [matmul.c](../../matmul.c) |
| [sha256.rs](sha256.rs) | [sha256.c](../../sha256.c) |
| [rope.rs](rope.rs) | [rope.c](../../rope.c) |

## 빌드

std 만 쓴다(Cargo · 외부 크레이트 없음). rustc 1.98.1, `stable-x86_64-pc-windows-gnu`(Visual Studio 없이 링크된다).

```bash
rustc -C opt-level=3 fib.rs -o fib_o3.exe    # 릴리스
rustc -C opt-level=0 fib.rs -o fib_o0.exe    # 디버그에 가까운 것 — debug-assertions 와 정수 넘침 검사가 켜진다
```

sieve · bubble · matmul · sha256 · rope 도 같다. 에디션을 주지 않으면 rustc 는 2015 로 읽는다. 2015 · 2018 · 2021 · 2024 모두 경고 없이
빌드된다.

## 확인한 출력

두 빌드 모두 아래 출력을 냈다. `-C opt-level=3 -C target-cpu=native` 로 빌드해도 같고, 그 빌드의 rope · matmul 어셈블리에도 융합 곱셈(vfmadd 등)이 없다.

| | 출력 |
|---|---|
| fib | `102334155` |
| sieve | `3001134` |
| bubble | `5 49684 99999` |
| matmul | `234371186.250000` |
| sha256 | `f85505310ac55800e8f0eaf99106e28513c68366d240f98a5c50e8c9208bba25` |
| rope | `113896039283458 1 0` |

sha256 의 범위 검사도 C 와 같다. 차례 반복을 65 까지 돌린 사본으로 돌려 보면 `error: index 64 out of [0, 64)` 를 찍고 1 로 끝난다.

## 옮긴 규칙

- `int64_t` → `i64`. 저장하는 타입은 늘 i64 이고 색인할 때만 `as usize` 로 바꾼다. `double` → `f64`, `float` → `f32`. C 의 비트 memcpy
  → `to_bits` · `from_bits`(i64 · i32 로 다시 읽는다).
- `char` 버퍼 → `Vec<u8>` · `[u8]`. C 가 `& 255` 로 읽는 곳은 `(x as i64) & 255` 그대로다. `(char)v` 를 넣는 곳은 `v as u8`,
  `tail[n] = -128` 은 `(-128i64) as u8`(바이트 0x80)로 썼다.
- `for (init; cond; step)` → `let mut i = init; while cond { …; step }`. 반복자 · 범위 · `step_by` 로 바꾸지 않았다. d_log 의 `break` 는
  C 처럼 증가 앞에서 빠진다.
- 색인은 모두 안전한 Rust 의 범위 검사 색인이다. `unsafe` · `get_unchecked` · SIMD · 스레드 · `rotate_right` · `mul_add` · `#[inline]` 은
  쓰지 않았다. 인라인은 컴파일러에 맡긴다.
- `(int64_t)d` → `d as i64`, `(double)n` → `n as f64`, `(float)d` → `d as f32`(가장 가까운 짝수로 반올림 — C 와 같다). i64 의 `>>` 는
  C 처럼 산술 자리옮김이다.
- `printf` → `println!`(`%f` → `{:.6}`), `fprintf(stderr, …)` → `eprintln!`, `exit(1)` → `std::process::exit(1)`.

## C 와 꼭 같게 쓰지 못한 곳

1. **할당.** `malloc(n)` → `vec![0; n]`. 안전한 Rust 는 초기화하지 않은 버퍼를 주지 않기 때문이다. 큰 블록은 운영체제가 주는 새
   페이지(이미 0)라서 0 으로 채우는 데 드는 값은 작을 것이다. 페이지는 C 처럼 처음 쓸 때 들어온다. 초기화하지 않은 C 의 지역 배열과 구조체도
   0 으로 채우고 시작한다. `int64_t w[64]`, `char tail[128]`, `hashstate s`, `pw` · `term[BIGW]`, `a` · `b` · `c[BIGW]`,
   `double freq[64]` 가 그렇다. sha256 의 `realloc` 은 `Vec::resize`(늘어난 자리는 0)로 옮겼다.
2. **sha256 의 전역 `K`.** C 의 `static intlist *K = NULL` 은 `static K: OnceLock<Box<IntList>>` 로 옮겼다. 함수의 꼴은 같다.
   hash_block 은 C 처럼 차례마다 `list_value(K, t)` 를 부른다. prepare() 는 C 처럼 이미 있으면 돌아가고, 없으면 목록을 만들어 채운 뒤
   넣는다. C 는 K 에 먼저 넣고 채우지만 한 스레드에서는 결과가 같다.
   **값이 드는 곳:** OnceLock 읽기는 acquire 적재와 검사여서, LLVM 이 그것을 64 차례 반복 밖으로 끌어내지 못한다. -O3 의 차례마다 상태
   적재 · 시험 · 분기가 있고, Box 포인터 · `len`(list_check) · Vec 길이(Rust 의 범위 검사) · 자료 포인터를 다시 읽는다. 반면 clang -O2 는 C 의
   같은 반복에서 `K` 와 `K->len` 을 반복 밖으로 끌어내고 반복 앞에서 `len >= 64` 를 한 번만 본다. 그러니 sha256 에서 나는 차이의 일부는
   이 전역 읽기 때문이다. K 를 hash_block 의 인자로 넘기면 이 값이 없어지지만, C 에 없는 끌어내기라서 그렇게 하지 않았다.
3. **rope 의 전역 변수.** C 의 파일 범위 static 스무 개 남짓은 계산하는 동안 바뀐다(hard_cases, fast_sure, fast_cos · fast_sin,
   rope_cos · rope_sin …). 안전한 Rust 에는 동기화 없는 가변 전역이 없다(`static mut` 은 unsafe). 그래서 이 변수들을 C 의 차례대로 `Globals`
   구조체 하나에 담았다. main 이 C 의 초기값으로 이것을 만들고, 쓰는 함수에 `g: &mut Globals`(읽기만 하면 `&Globals`)로 넘긴다. 함수 나눔
   · 몸통 · 부르는 차례는 그대로이고 인자만 하나 늘었다.
4. **rope 의 `dd *r` 출력 매개변수는 반환값으로 옮겼다.** C(와 글 원본)는 r 이 입력 a · b 와 같은 자리여도 되도록 짰고, 실제로
   `dd_add(&sum, &sum, &term)` 처럼 부른다. 안전한 Rust 는 한 번의 부름에 같은 변수를 `&mut` 와 `&` 로 함께 넘길 수 없다. 모든 도움
   함수가 입력을 다 읽은 뒤에야 r 을 쓰므로 `sum = dd_add(&sum, &term)` 와 값이 같다. 입력은 C 처럼 참조(`&Dd`)로 받는다. 같은 까닭으로
   `round_to_float(&rope_cos)` 는 `rope_cos` 를 지역 변수에 복사해서 넘긴다.
5. **C 의 `int` 참거짓**(`is_inf`, `is_nan`, `big_is_zero`, `fast_sure`, `cc`, `done`)은 `bool` 로 옮겼다.
6. **포인터 인자는 조각(slice)으로 옮겼다.** `int64_t *h`, `const char *block`, 큰 정수의 `int64_t *a` 는 `&mut [i64]` · `&[u8]` 이 되었다.
   `hash_block(s->h, d + k)` 는 `hash_block(&mut s.h, &d[k as usize..])`(k 부터 끝까지)이다. 조각은 길이를 가지므로 범위 검사는 그 길이에
   대해 한다.
7. **NUL 로 끝나는 문자열.** hex_words 는 C 처럼 0 바이트까지 읽는다(바이트 문자열 끝에 `\0` 을 붙였다). hash_end 는 끝이 0 인 65
   바이트를 돌려주고, main 은 printf("%s") 처럼 0 앞까지 찍는다.
8. **줄바꿈 바이트.** `println!` 은 `\n` 을 쓴다. zig cc(mingw)로 빌드한 C 는 텍스트 모드라 `\r\n` 을 쓴다. 줄 내용은 같고, 재기.py 는
   `strip()` 해서 견준다.
9. **정수 나눗셈.** Rust 의 `/` · `%` 는 나누는 수가 상수가 아니면 0 과 `MIN / -1` 을 검사한다. 해당하는 곳은 rope 의 big_div_small 하나이고,
   prepare_pi 에서만 돈다.
10. **린트.** C 의 대문자 지역 이름(sha256 의 A … H · S0 · S1, rope 의 M)은 그대로 두고 `#![allow(non_snake_case)]` 를 붙였다. C 에서도 쓰기만
    하고 읽지 않는 `halfpi_dd` 에는 `#[allow(dead_code)]`, C 처럼 곧 덮어쓰는 첫 값(d_log 의 `m = v`, round_to_float 의 `other = t`)에는
    `#[allow(unused_assignments)]` 를 붙였다. 그 밖의 경고는 없다.

## 잴 때 알아 둘 것

- zig cc 는 기본으로 이 컴퓨터의 CPU 를 겨눈다(C -O2 의 sha256 어셈블리에 AVX2 의 ymm 이 나온다). rustc 의 기본은 기준 x86-64(SSE2)다.
  같은 조건으로 견주려면 `-C target-cpu=native` 를 더한다. 그 빌드도 여섯 출력이 같다.
- rustc 의 `-C opt-level=3` 은 기본으로 코드 생성 단위가 16 이고 크레이트 안에서 thin LTO 를 한다. 단위를 하나로 하려면
  `-C codegen-units=1` 을 준다.
- `-C opt-level=0` 은 debug-assertions 를 켜므로 정수 넘침 검사도 켜진다(어셈블리에 `panic_const_add_overflow` 가 있다). 여섯 모두 넘침 없이
  돈다. C -O0 와 견주면 이 검사만큼 더 든다.
