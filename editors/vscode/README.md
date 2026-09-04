# 글 문법 강조 (VS Code)

`.gl` 파일에 색을 입힌다. 컴파일러는 들어 있지 않다 — 컴파일은 `geulc` 가 한다.

## 넣는 법

이 폴더를 확장 폴더 아래에 두고 VS Code 를 다시 켠다.

| 운영체제 | 자리 |
|---|---|
| Windows | `%USERPROFILE%\.vscode\extensions\geul` |
| macOS·Linux | `~/.vscode/extensions/geul` |

```
git clone https://github.com/wwoosshh/geul-lang
```

받은 저장소의 `editors/vscode` 를 위 자리로 복사하면 된다. 마켓플레이스에는 올리지 않았다.

## 무엇에 색이 붙는가

| 것 | 스코프 |
|---|---|
| 주석 `(* … *)` (겹칠 수 있다) | `comment.block.geul` |
| 문자열과 그 안의 보간 `"{a + b}"` | `string.quoted.double.geul`, `meta.embedded.geul` |
| 이스케이프 `\n`, 서식 `%lld` | `constant.character.escape.geul`, `constant.other.placeholder.geul` |
| 함수 이름 — `[정수 값을 두배]는` 의 `두배` | `entity.name.function.geul` |
| 괄호 호출 이름 — `해제(x)` 의 `해제` | `entity.name.function.call.geul` |
| 동사형 호출 — `단어를 해제하다.` 의 `해제하`+`다` | `entity.name.function.call.geul` + `keyword.other.verb-ending.geul` |
| **역할 조사** `을/를·에·에서·로/으로·와/과` | `keyword.operator.particle.geul` |
| 주제·주격 `는/은·이/가` | `keyword.operator.topic.geul` |
| 범위 반복 표시자 `부터·까지·전까지` | `keyword.control.range.geul` |
| 제어 `이면·아니면·반복·동안·갈래·반환·계속·탈출·시도·혹은` | `keyword.control.geul` |
| 타입 `정수·실수·문자열·참거짓·문자·공허·참조·결과` 등 | `storage.type.geul` |
| 상수 `참·거짓·없음` | `constant.language.geul` |

**조사에 따로 색을 주는 것이 이 문법 파일의 요점이다.** 글에서 조사는 장식이 아니라 인자를
매개변수에 대응시키는 표지이므로(명세 3.5), 연산자와 같은 무게로 보이는 편이 맞다.

## 아는 한계

- 한글이 낱말 글자라서 `\b` 를 쓸 수 없다. 경계는 전부 앞뒤 살펴보기로 적었다.
- `이면`·`동안` 은 앞말에 붙여 쓰므로 앞을 보지 않고 잡는다. 이름이 우연히 `이면` 으로
  끝나면 잘못 칠한다.
- `부터`·`까지`·`전까지` 는 이름 안에도 나올 수 있어(`식_기호까지`) 숫자·괄호 뒤이거나
  띄어 쓴 것만 잡는다. `끝전까지` 처럼 한글에 붙여 쓴 것은 놓친다.
- 문법 파일은 구조와 정규식만 검사했고 VS Code 안에서 그려 보지는 않았다.
