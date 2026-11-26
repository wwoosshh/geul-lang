# Go 로 옮긴 여섯 짝

`research/cpu` 의 C 여섯(`fib.c` · `sieve.c` · `bubble.c` · `matmul.c` · `sha256.c` · `rope.c`)을 줄마다 Go 로 옮겼다. C 가 글 소스를
옮긴 그대로다 — 같은 알고리즘, 같은 입력 크기, 같은 반복의 꼴과 차례, 같은 함수 나눔(`rotr`, `listNew/listAdd/listCheck/listValue`,
`hashBlock`, rope 의 두 배 정밀도 · 큰 정수 함수들), 같은 타입(`int64_t` → `int64`, `double` → `float64`, `float` → `float32`,
`char` 버퍼 → `[]byte`). 언어가 아니라 컴파일러를 견주려는 것이라 Go 답게 고쳐 쓰지 않았다. 인라인은 컴파일러에 맡겼다(`//go:`
지시어 없음). 표준 라이브러리만(`fmt`, `os`, `math` 의 `Float64bits` 류) 쓰고 `unsafe` · 어셈블리 · 고루틴 · `math/bits` ·
`crypto/sha256` 은 쓰지 않는다.

## 빌드

Go 1.27.4 (windows/amd64)로 확인했다. 파일마다 따로 빌드한다(여섯 모두 `package main` 이라 폴더째 `go build .` 는 안 된다).

```bash
# 이 폴더에서. GOAMD64=v1 은 기본값이다 — 올리지 않는다(아래 "실수").
for p in fib sieve bubble matmul sha256 rope; do
  GOAMD64=v1 go build -o "$OUT/$p.exe" $p.go                         # 최적화(기본)
  GOAMD64=v1 go build -gcflags="-N -l" -o "$OUT/${p}_noopt.exe" $p.go # 최적화 · 인라인 끔(C -O0 의 짝)
done
```

`-gcflags` 는 명령줄의 파일에만 걸린다 — 런타임 · `fmt` 는 최적화된 그대로다(C -O0 이 최적화된 libc 를 쓰는 것과 같다).

| | 출력(표준출력 한 줄) | 기본 | `-N -l` |
|---|---|---|---|
| fib | `102334155` | 같음 | 같음 |
| sieve | `3001134` | 같음 | 같음 |
| bubble | `5 49684 99999` | 같음 | 같음 |
| matmul | `234371186.250000` | 같음 | 같음 |
| sha256 | `f85505310ac55800e8f0eaf99106e28513c68366d240f98a5c50e8c9208bba25` | 같음 | 같음 |
| rope | `113896039283458 1 0` | 같음 | 같음 |

줄 끝을 빼면 C 의 출력과 바이트까지 같다. 줄 끝은 글처럼 `\n` 하나다 — zig cc 로 만든 C 는 윈도의 텍스트 모드 표준출력이 `\n` 을
`\r\n` 으로 바꿔 쓰지만, 소스는 `\n` 이라 그대로 두었다(`재기.py` 는 출력을 `strip()` 해 견준다). `gofmt` · `go vet` 은 조용하다.

## C 와 다른 곳(언어가 시켜서)

- **0 으로 채움** — Go 는 `make` 와 지역 배열을 늘 0 으로 채운다(C 의 `malloc` · 지역 배열은 채우지 않는다). 큰 `make`(sieve 50 MB,
  sha256 64 MB, matmul 2 MB × 3, rope 8 MB × 2)는 운영체제가 0 으로 준 쪽을 받아 대개 따로 채우지 않지만, `hashBlock` 의
  `var w [64]int64` 는 부를 때마다(64 바이트 블록마다, 100만 번) 512 바이트를 채운다. 나머지(`hashEnd` 의 `tail`, rope 의 `freq` ·
  큰 정수 · dd 임시값)는 뜨거운 길이 아니다.
- **범위 검사** — 슬라이스 · 배열 색인마다 Go 의 범위 검사가 남는다(컴파일러가 증명하면 지운다). 언어의 뜻 그대로 두었다.
- **자리 옮김** — Go 는 자리 수가 음수면 패닉하고 64 이상이면 값이 정해져 있다(C 는 정의되지 않음). 상수로 접히지 않는 자리 수에는
  그 검사가 붙는다. 이 프로그램들의 자리 수는 늘 0 ~ 63 이다.
- **C 포인터** — 배열을 가리키는 `int64_t *h` · `const char *block` → `[]int64` · `[]byte`, 포인터 덧셈 `d + k` → `d[k:]`, 큰 정수의
  `int64_t *a`(BIGW 칸) → `[BIGW]int64` 의 `a[:]`. `dd *` 는 `*dd` 그대로 — `ddAdd(&sum, &sum, &term)` 같은 겹친 부름도 그대로다.
- **C 의 `int` 참거짓 → `bool`** — `is_inf` · `is_nan` · `big_is_zero` 의 돌려줌, `fast_sure` · `cc` · `done`. Go 에는 bool 과 정수
  사이의 암묵 변환이 없어 정수로 두면 문장의 꼴이 바뀐다.
- **NUL 로 끝나는 문자열** — `hexWords` 는 C 처럼 NUL 까지 읽는다(문자열마다 끝에 `\x00`). `hashEnd` 는 C 처럼 65 바이트에 NUL 을
  넣어 돌려주고 `main` 이 `[:64]` 를 찍는다(C 의 `%s` 가 NUL 에서 멈추는 것).
- **`realloc`** — Go 에 없어 새 `make` + `copy`. 정수목록의 `{data, len, cap}` 칸, 8 에서 시작해 꽉 차면 두 배로 늘리는 규칙,
  `listCheck` 의 글월과 `exit(1)` 은 그대로다(색인 64 와 -1 로 시험: `error: index 64 out of [0, 64)`, 종료 코드 1).
- **`char` 의 부호** — Go 의 `byte` 는 부호가 없다. C 가 `& 255` 로 읽는 곳은 결과가 같고(그대로 `& 255` 를 적었다),
  `tail[n] = -128` 은 같은 비트의 `0x80` 이다.
- **상수 · 이름** — `static const int64_t MASK` → `const MASK int64`, `#define BIGW 9` → `const BIGW = 9`,
  `static const double LN2` → `const LN2 float64`(C 와 같은 double 로 반올림된다). 이름은 camelCase(`list_add` → `listAdd`),
  `hash_add` 의 매개변수 `len` 은 Go 의 내장 이름이라 `length`.
- **실수(FMA)** — Go 명세는 `x*y + z` 를 FMA 하나로 합치는 것을 허용한다. amd64 의 컴파일러는 GOAMD64=v3 이상에서만 합친다 —
  기본값 v1 로 빌드하면 합치지 않는다(C 의 `-ffp-contract=off` 의 짝). rope · matmul 의 두 빌드 모두 `main.*` 에 VFMADD 류 명령이
  없고 rope 의 해시(표 전체의 비트)가 C 와 같다. v3 이나 arm64 에서는 rope 의 결과가 바뀔 수 있다 — 거기서도 같게 하려면 곱마다
  `float64(...)` 를 씌워야 하는데, 소스의 꼴이 바뀌므로 하지 않았다.

## 참고 — 기본 빌드에서 컴파일러가 한 것(`-gcflags=-m`, 디스어셈블)

- sha256: `rotr` 와 `listValue` 는 `hashBlock` 안으로 인라인, `listCheck` 는 아니다(`fmt.Printf` · `os.Exit` 를 부르는 몸이 인라인
  예산을 넘는다 — 라운드마다 부름 하나). 바이트 넷을 모으는 식은 `MOVL` + `BSWAP` 하나가 된다(색인마다 범위 검사는 남는다).
  `main` 의 `hashstate` 는 스택에 있다.
- rope: `twoSum` · `fastSum` · `twoProd` · `dAbs` · `dFloor` · `scale2` · `floatNext` 는 인라인, `ddAdd` · `ddMul` · `ddDiv` ·
  `fastTrig` · `fastFloat` 는 부름으로 남는다. dd 임시값은 모두 스택에 있다(힙으로 새지 않는다).
