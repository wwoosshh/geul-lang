#!/usr/bin/env python3
"""3단계 — 선형 커널들의 글 소스(선형.gl)를 만든다. 손으로 쓰면 누적 변수가 수십 개라 틀리기 쉬워서 만든다
(2단계 타일생성.py 와 같은 까닭).

  python research/gpu/3단계/선형생성.py [-o research/gpu/3단계/선형.gl] [판 …]     판 = RMxRNxTX (예: 8x4x32)

순서의 약속 — 모든 판이 지킨다. 그래서 어느 판으로 계산해도, 몇 행을 함께 계산해도 칸마다 비트가 같다:
  p_g      = Σ 입력[r, k] · 가중치[k, n]   (k ≡ g mod 16, k 오름차순, 곱해더하기로 차례로 — 반올림 한 번씩)   g = 0 … 15
  출력[r, n] = 끝손질( ((치우침[n] + p₀) + p₁) + … + p₁₅ )
판마다 다른 것은 한 블록이 맡는 행·열의 수뿐이다: 블록은 TX × 16 스레드(블록안세로 = 가닥 g), 스레드 하나가 행 RM 개 × 열 RN 개
(열은 TX 간격)를 자기 가닥으로 맡는다. 범위 밖의 행·열은 마지막 행·열을 읽고 쓰지 않는다.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
기본판 = ["1x1x32", "4x4x32", "8x4x32"]   # 글gpt2.py 의 선형판과 같게

끝손질 = {
    "": ["출력[행{i} * 열수 + 열{i}] = 합{i}."],
    "_잔차": ["출력[행{i} * 열수 + 열{i}] = 잔차[행{i} * 열수 + 열{i}] + 합{i}."],
    "_겔루": ["짧은실수 u{i} = 0.7978845608 * (합{i} + 0.044715 * 합{i} * 합{i} * 합{i}).",
             "짧은실수 th{i} = 1.0 - 2.0 / (근사지수(2.0 * u{i}) + 1.0).",
             "출력[행{i} * 열수 + 열{i}] = 0.5 * 합{i} * (1.0 + th{i})."],
}


def 이름(RM, RN, TX, epi):
    return f"선형{RM}x{RN}x{TX}{epi}"


def kernel(RM, RN, TX, epi):
    W = TX * RN
    assert 16 * W * 4 <= 16384
    params = ("짧은실수 참조 입력에서 짧은실수 참조 가중치와 짧은실수 참조 치우침과 "
              + ("짧은실수 참조 잔차와 " if epi == "_잔차" else "")
              + "짧은실수 참조 출력에 정수 행수로 정수 깊이로 정수 열수로")
    L = [f"(* 행 {RM} × 열 {W} 을 블록 하나({TX} × 16 스레드)가 — 스레드 하나가 행 {RM} × 열 {RN} 을 한 가닥으로 *)",
         f"[{params} {이름(RM, RN, TX, epi)}]는 {{",
         "    정수 tx = 블록안가로().",
         "    정수 가닥 = 블록안세로().",
         f"    정수 행0 = 블록가로() * {RM}.",
         f"    정수 열0 = 블록세로() * {W}."]
    for i in range(RM):
        L += [f"    정수 i{i} = 행0 + {i}.", f"    i{i} >= 행수이면 {{ i{i} = 행수 - 1. }}"]
    for j in range(RN):
        L += [f"    정수 c{j} = 열0 + tx + {j * TX}.", f"    c{j} >= 열수이면 {{ c{j} = 열수 - 1. }}"]
    L.append("    짧은실수 영 = 0 으로 짧은실수.")
    L += [f"    짧은실수 a{i}_{j} = 영." for i in range(RM) for j in range(RN)]
    L.append("    반복 (정수 k = 가닥: k < 깊이: k += 16) {")
    L += [f"        짧은실수 w{j} = 가중치[k * 열수 + c{j}]." for j in range(RN)]
    L += [f"        짧은실수 x{i} = 입력[i{i} * 깊이 + k]." for i in range(RM)]
    L += [f"        a{i}_{j} = 곱해더하기(x{i}, w{j}, a{i}_{j})." for i in range(RM) for j in range(RN)]
    L.append("    }")
    L.append("    짧은실수 참조 칸 = 큰공유메모리().")
    for i in range(RM):
        L += [f"    칸[가닥 * {W} + tx + {j * TX}] = a{i}_{j}." for j in range(RN)]
        L.append("    동기화().")
        L.append(f"    가닥 < {RN}이면 {{")
        L.append(f"        정수 행{i} = 행0 + {i}.")
        L.append(f"        정수 열{i} = 열0 + 가닥 * {TX} + tx.")
        L.append(f"        (행{i} < 행수 그리고 열{i} < 열수)이면 {{")
        L.append(f"            짧은실수 합{i} = 치우침[열{i}].")
        L.append(f"            반복 (정수 g는 0부터 16 전까지) {{ 합{i} += 칸[g * {W} + 가닥 * {TX} + tx]. }}")
        L += ["            " + x.format(i=i) for x in 끝손질[epi]]
        L.append("        }")
        L.append("    }")
        L.append("    동기화().")
    L.append("}")
    return "\n".join(L)


def source(판들):
    head = ["(* 선형생성.py 가 만든 파일 — 고치지 말 것. 순서의 약속은 선형생성.py 의 설명 그대로. *)", "",
            "외부 [블록안가로]는 -> 정수.", "외부 [블록안세로]는 -> 정수.", "외부 [블록가로]는 -> 정수.", "외부 [블록세로]는 -> 정수.",
            "외부 [큰공유메모리]는 -> 짧은실수 참조.", "외부 [동기화]는.",
            "외부 [짧은실수 x를 짧은실수 y를 짧은실수 z를 곱해더하기]는 -> 짧은실수.",
            "외부 [짧은실수 x를 근사지수]는 -> 짧은실수.", ""]
    body = []
    for p in 판들:
        RM, RN, TX = (int(x) for x in p.split("x"))
        for epi in ("", "_잔차", "_겔루"):
            body += [kernel(RM, RN, TX, epi), ""]
    return "\n".join(head + body)


def main(argv):
    out = os.path.join(HERE, "선형.gl")
    if argv[:1] == ["-o"]:
        out, argv = argv[1], argv[2:]
    open(out, "w", encoding="utf-8").write(source(argv or 기본판))
    print(out)


if __name__ == "__main__":
    main(sys.argv[1:])
