"""연구 갈래(GPU — docs/17)의 언어 확장을 켠다. 1.x 의 컴파일러(geulc.py)는 켜지 않는다 — 호환 약속(docs/17 §8: 새 문법은
1.x 코드를 깨지 않는 방식, 새 옵션으로만 들어온다). research/gpu/글ptx.py 가 앞단을 부르기 전에 켠다.

- `반실수` (docs/17 §7 "4단계 2"): IEEE 754 binary16 의 저장 형식. 좁히기(짧은실수 · 실수 → 반실수)는 `으로 반실수` 로만 —
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
