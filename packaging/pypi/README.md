# 글 (geul) — 한국어 문법으로 쓰는 자체호스팅 시스템 언어

글은 한국어 어순(SOV)과 조사(을/를/에/에서/로)를 문법으로 삼는 시스템 프로그래밍 언어입니다.
이 꾸러미는 글 컴파일러 `geulc`(Windows x64)를 설치합니다. C 컴파일러·링커 없이 `.gl` 소스에서
Windows 실행 파일을 바로 만듭니다.

## 설치

```
pip install geul
```

`pipx install geul` 이나 `uv tool install geul` 도 됩니다. 설치 없이 한 번만 돌리려면
`uvx --from geul geulc 안녕.gl`.

## 쓰기

`안녕.gl`:

```
[시작하기]는 -> 정수 {
    "안녕, 글!\n"을 쓰다.
    반환 0.
}
```

```
geulc 안녕.gl        # 안녕.exe 를 만든다
안녕.exe
```

옵션: `-o <출력.exe>`, `--check`, `--창`, `--핫스왑`, `--dump-ir`, `--version`, `--help`
([명세 6절](https://github.com/wwoosshh/geul-lang/blob/v2/docs/03-%EB%AC%B8%EB%B2%95-%EB%AA%85%EC%84%B8.md)).
`python -m geul` 도 같습니다.

## 조사가 인자의 역할을 정한다

```
[문자열 원본을 문자열 대상에 복사]는 -> 정수 { ... }

원본을 대상에 복사하다.          (* 동사형 호출 — 인자는 자리가 아니라 조사로 대응된다 *)
```

같은 타입의 인자가 역할이 다른데 조사를 안 붙이면 컴파일러가 거부합니다. `copy(dst, src)` 처럼
자리를 바꿔 써도 조용히 컴파일되는 실수를 문법의 격이 막습니다.

## 알아 둘 것

- **Windows x64 전용입니다.** 만들어지는 실행 파일도 Windows x64 이고 `kernel32.dll`·`shell32.dll` 만 씁니다.
- 꾸러미에는 GitHub 릴리스와 **바이트가 같은** `geulc.exe` 와 표준 라이브러리(`표준/`)가 들어 있습니다 —
  게시 워크플로가 대조한 뒤에만 올라갑니다. `geulc` 명령은 그것을 부르는 얇은 파이썬 런처이고,
  표준 라이브러리는 꾸러미 안의 것을 씁니다.
- 파이썬이 없어도 됩니다: [GitHub 릴리스](https://github.com/wwoosshh/geul-lang/releases)의 zip 을 풀면
  `geulc.exe` 하나로 돌아갑니다(옆에 `표준/` 이 있으면 소스는 어느 폴더에 있어도 됩니다).

## 더 보기

- [저장소와 README](https://github.com/wwoosshh/geul-lang/tree/v2)
- [입문서 — 열네 장](https://github.com/wwoosshh/geul-lang/blob/v2/docs/09-%EC%9E%85%EB%AC%B8.md)
- [표준 라이브러리](https://github.com/wwoosshh/geul-lang/blob/v2/docs/06-%ED%91%9C%EC%A4%80-%EB%9D%BC%EC%9D%B4%EB%B8%8C%EB%9F%AC%EB%A6%AC.md)
- 라이선스: MIT
