#!/usr/bin/env python3
"""비교용: PTX 의 부동소수 덧셈·뺄셈·곱셈에서 반올림 표지(.rn)를 지운다 (docs/17 §7 PTX 계약 P1).

  python research/gpu/탐침/반올림빼기.py <입력.ptx> <출력.ptx>

고치기 전의 글ptx.py 가 내던 꼴(add.f32·sub.f32·mul.f32)을 다시 만들어, 드라이버가 곱과 덧셈을 FMA 로 합치는지 견주는 데
쓴다. 의미를 고르는 수단이 아니다 — 합침은 소스가 밝힐 때만 한다(2단계에서 정할 말).
"""
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 3
    text = open(argv[0], encoding="ascii").read()
    out, n = re.subn(r"\b(add|sub|mul)\.rn\.(f32|f64)\b", r"\1.\2", text)
    open(argv[1], "w", encoding="ascii", newline="\n").write(out)
    print(f"반올림 표지 {n}개를 지웠다: {argv[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
