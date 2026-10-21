"""연구 옵션: 컴파일러를 품는 프로그램(GPU 뒷단 같은)이 켜는 언어 확장 (명세 9절, D-51). 기계어를 내는 명령줄 빌드는 켜지 않는다 —
1.x 의 프로그램은 그대로다. 앞단의 출력(--check, --dump-*)은 `geulc.py --연구` 로 켜서 자체 구현의 덤프 드라이버와 견준다.

- `반실수`: IEEE 754 binary16 의 저장 형식. 좁히기(정수 · 짧은실수 · 실수 → 반실수)는 `으로 반실수` 로만 —
  암시 좁히기는 컴파일 오류. 넓히기는 암시(정확하다). 반실수가 든 산술 · 비교는 짧은실수로 올려 계산한다. 이 규칙은 sema 에
  있고 16비트 실수 타입이 있을 때만 닿는다(1.x 의 프로그램에는 그런 타입이 없다).
"""
from . import lexer, parser, types as T

RESEARCH_TYPES = {"반실수": T.HALF}


def enable():
    """연구 타입의 이름을 렉서 · 파서 · 타입 표에 넣는다(같은 프로세스에서 여러 번 불러도 같다)."""
    for name, t in RESEARCH_TYPES.items():
        lexer.KEYWORDS.add(name)
        parser.BASE_TYPES.add(name)
        T.BASE_BY_NAME[(name, False)] = t
