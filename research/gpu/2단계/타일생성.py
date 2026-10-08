#!/usr/bin/env python3
"""레지스터 타일 행렬곱의 글 소스를 만든다 — 스레드 한 칸의 크기(T × T)와 합침(곱해더하기) 여부만 다르다.

  python research/gpu/2단계/타일생성.py

블록은 16 × 16 스레드, 블록이 맡는 출력은 16T × 16T 칸, k 를 KT 칸씩 공유 메모리에 올린다(입력 조각은 [k][행] 으로 전치).
스레드는 행 = 행바탕 + 세로 + 16i, 열 = 열바탕 + 가로 + 16j (i, j < T) 를 맡고, 칸마다 k 를 0 부터 차례로 더한다 — 그래서
합침이 없는 판은 행렬곱.gl 과 비트까지 같고, 합침 판은 정확한 FMA 와 비트까지 같다. 공유 메모리 한 판은 KT × 16T 칸 ≤ 1024.
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
KINDS = {  # 파일 이름: (T, KT, 합침, 커널 이름)
    "레지스터타일행렬곱.gl": (4, 16, False, "레지스터타일행렬곱"),
    "합침행렬곱.gl": (4, 16, True, "합침행렬곱"),
    "큰타일행렬곱.gl": (8, 8, False, "큰타일행렬곱"),
    "큰타일합침행렬곱.gl": (8, 8, True, "큰타일합침행렬곱"),
    "겹친큰타일행렬곱.gl": (8, 8, False, "겹친큰타일행렬곱", True),
    "겹친큰타일합침행렬곱.gl": (8, 8, True, "겹친큰타일합침행렬곱", True),
}
# 직사각형 타일 (블록 16 × 16 스레드, 스레드 TM × TN 칸, 블록 16TM × 16TN, k 를 KT 칸씩) — 겹쳐 읽기, 합침
RECT = {
    "직사각합침_8x4.gl": (8, 4, 8, "직사각합침_8x4"),
    "직사각합침_4x8.gl": (4, 8, 8, "직사각합침_4x8"),
}


def source(T, KT, fused, name, overlap=False):
    if overlap:
        return source_overlap(T, KT, fused, name)
    W = 16 * T                                      # 블록이 맡는 출력 한 변
    per = (W * KT) // 256                           # 스레드 하나가 올리는 조각 칸 수
    L = [f"""(* {name} — 2단계 {'2g (합침)' if fused else '2f'}. 타일생성.py 가 만든다 — 손으로 고치지 않는다.
   블록 16 × 16 스레드가 출력 {W} × {W} 칸을 맡고, 스레드 하나가 {T} × {T} 칸(행 = 행바탕 + 세로 + 16i, 열 = 열바탕 + 가로 + 16j)을
   레지스터에 든다. k 를 {KT} 칸씩 나눠 입력 조각(전치해서 [k][행])과 가중치 조각([k][열])을 공유 메모리에 올리고, 칸마다 k 를
   0 부터 차례로 {'곱해더하기(반올림 한 번)로' if fused else '곱하고 더한다(연산마다 반올림)'}. 깊이는 {KT} 의 배수라고 둔다.
   블록안가로·블록안세로·블록가로·블록세로·공유메모리0·1·동기화{'·곱해더하기' if fused else ''}는 글ptx.py 의 연구용 내장이다. *)

외부 [블록안가로]는 -> 정수.
외부 [블록안세로]는 -> 정수.
외부 [블록가로]는 -> 정수.
외부 [블록세로]는 -> 정수.
외부 [공유메모리0]는 -> 짧은실수 참조.
외부 [공유메모리1]는 -> 짧은실수 참조.
외부 [동기화]는."""]
    if fused:
        L.append("외부 [짧은실수 x를 짧은실수 y를 짧은실수 z를 곱해더하기]는 -> 짧은실수.")
    L.append(f"""
[짧은실수 참조 입력에서 짧은실수 참조 가중치와 짧은실수 참조 출력에 정수 행수로 정수 열수로 정수 깊이로 {name}]는 {{
    정수 가로 = 블록안가로().
    정수 세로 = 블록안세로().
    정수 번호 = 세로 * 16 + 가로.
    정수 행바탕 = 블록세로() * {W}.
    정수 열바탕 = 블록가로() * {W}.
    짧은실수 참조 입력판 = 공유메모리0().
    짧은실수 참조 가중치판 = 공유메모리1().
    짧은실수 영 = 0 으로 짧은실수.""")
    for i in range(T):
        L.append("    " + " ".join(f"짧은실수 누적{i}_{j} = 영." for j in range(T)))
    L.append(f"""    반복 (정수 t는 0부터 깊이 / {KT} 전까지) {{
        반복 (정수 q는 0부터 {per} 전까지) {{
            정수 e = 번호 + 256 * q.
            정수 m = e / {KT}.
            정수 kk = e % {KT}.
            짧은실수 값 = 영.
            행바탕 + m < 행수이면 {{ 값 = 입력[(행바탕 + m) * 깊이 + t * {KT} + kk]. }}
            입력판[kk * {W} + m] = 값.
            정수 kb = e / {W}.
            정수 n = e % {W}.
            짧은실수 무게 = 영.
            열바탕 + n < 열수이면 {{ 무게 = 가중치[(t * {KT} + kb) * 열수 + 열바탕 + n]. }}
            가중치판[kb * {W} + n] = 무게.
        }}
        동기화().
        반복 (정수 kk는 0부터 {KT} 전까지) {{""")
    for i in range(T):
        L.append(f"            짧은실수 a{i} = 입력판[kk * {W} + 세로 + {16 * i}].")
    for j in range(T):
        L.append(f"            짧은실수 b{j} = 가중치판[kk * {W} + 가로 + {16 * j}].")
    for i in range(T):
        if fused:
            L.append("            " + " ".join(f"누적{i}_{j} = 곱해더하기(a{i}, b{j}, 누적{i}_{j})." for j in range(T)))
        else:
            L.append("            " + " ".join(f"누적{i}_{j} += a{i} * b{j}." for j in range(T)))
    L.append("""        }
        동기화().
    }""")
    for i in range(T):
        L.append(f"    정수 r{i} = 행바탕 + 세로 + {16 * i}.")
    for j in range(T):
        L.append(f"    정수 c{j} = 열바탕 + 가로 + {16 * j}.")
    for i in range(T):
        for j in range(T):
            L.append(f"    (r{i} < 행수 그리고 c{j} < 열수)이면 {{ 출력[r{i} * 열수 + c{j}] = 누적{i}_{j}. }}")
    L.append("}")
    return "\n".join(L) + "\n"


def source_overlap(T, KT, fused, name):
    """겹쳐 읽기: 지금 조각을 계산하는 동안 다음 조각을 전역 메모리에서 레지스터로 미리 읽는다. 스레드가 맡는 조각 자리
    (행·k·열)는 반복 밖에서 한 번 계산한다. 더하는 순서는 그대로다."""
    W = 16 * T
    per = (W * KT) // 256
    head = source(T, KT, fused, name).split("\n[짧은실수 참조 입력에서")[0]
    head = head.replace("k 를 0 부터\n   차례로", "k 를 0 부터 차례로", 1)
    head = head.replace(f"(* {name} — 2단계", f"(* {name} — 2단계 (겹쳐 읽기: 지금 조각을 계산하는 동안 다음 조각을 레지스터로 미리 읽는다)", 1)
    L = [head, f"""[짧은실수 참조 입력에서 짧은실수 참조 가중치와 짧은실수 참조 출력에 정수 행수로 정수 열수로 정수 깊이로 {name}]는 {{
    정수 가로 = 블록안가로().
    정수 세로 = 블록안세로().
    정수 번호 = 세로 * 16 + 가로.
    정수 행바탕 = 블록세로() * {W}.
    정수 열바탕 = 블록가로() * {W}.
    짧은실수 참조 입력판 = 공유메모리0().
    짧은실수 참조 가중치판 = 공유메모리1().
    짧은실수 영 = 0 으로 짧은실수.
    정수 판수 = 깊이 / {KT}."""]
    for i in range(T):
        L.append("    " + " ".join(f"짧은실수 누적{i}_{j} = 영." for j in range(T)))
    for q in range(per):
        L.append(f"    정수 m{q} = (번호 + {256 * q}) / {KT}. 정수 k{q} = (번호 + {256 * q}) % {KT}. "
                 f"정수 kb{q} = (번호 + {256 * q}) / {W}. 정수 n{q} = (번호 + {256 * q}) % {W}.")
        L.append(f"    짧은실수 pa{q} = 영. 짧은실수 pb{q} = 영.")
        L.append(f"    행바탕 + m{q} < 행수이면 {{ pa{q} = 입력[(행바탕 + m{q}) * 깊이 + k{q}]. }}")
        L.append(f"    열바탕 + n{q} < 열수이면 {{ pb{q} = 가중치[kb{q} * 열수 + 열바탕 + n{q}]. }}")
    L.append("    반복 (정수 t는 0부터 판수 전까지) {")
    for q in range(per):
        L.append(f"        입력판[k{q} * {W} + m{q}] = pa{q}. 가중치판[kb{q} * {W} + n{q}] = pb{q}.")
    L.append("        동기화().")
    L.append("        t + 1 < 판수이면 {")
    for q in range(per):
        L.append(f"            pa{q} = 영. pb{q} = 영.")
        L.append(f"            행바탕 + m{q} < 행수이면 {{ pa{q} = 입력[(행바탕 + m{q}) * 깊이 + (t + 1) * {KT} + k{q}]. }}")
        L.append(f"            열바탕 + n{q} < 열수이면 {{ pb{q} = 가중치[((t + 1) * {KT} + kb{q}) * 열수 + 열바탕 + n{q}]. }}")
    L.append("        }")
    L.append(f"        반복 (정수 kk는 0부터 {KT} 전까지) {{")
    for i in range(T):
        L.append(f"            짧은실수 a{i} = 입력판[kk * {W} + 세로 + {16 * i}].")
    for j in range(T):
        L.append(f"            짧은실수 b{j} = 가중치판[kk * {W} + 가로 + {16 * j}].")
    for i in range(T):
        if fused:
            L.append("            " + " ".join(f"누적{i}_{j} = 곱해더하기(a{i}, b{j}, 누적{i}_{j})." for j in range(T)))
        else:
            L.append("            " + " ".join(f"누적{i}_{j} += a{i} * b{j}." for j in range(T)))
    L.append("""        }
        동기화().
    }""")
    for i in range(T):
        L.append(f"    정수 r{i} = 행바탕 + 세로 + {16 * i}.")
    for j in range(T):
        L.append(f"    정수 c{j} = 열바탕 + 가로 + {16 * j}.")
    for i in range(T):
        for j in range(T):
            L.append(f"    (r{i} < 행수 그리고 c{j} < 열수)이면 {{ 출력[r{i} * 열수 + c{j}] = 누적{i}_{j}. }}")
    L.append("}")
    return "\n".join(L) + "\n"


def source_rect(TM, TN, KT, name):
    """직사각 타일·겹쳐 읽기·합침. 블록은 출력 16TM 행 × 16TN 열을 맡는다. 공유 메모리 한 판 ≤ 1024 칸."""
    WA, WB = 16 * TM, 16 * TN
    pa, pb = (KT * WA) // 256, (KT * WB) // 256
    assert KT * WA <= 1024 and KT * WB <= 1024 and pa * 256 == KT * WA and pb * 256 == KT * WB
    L = [f"""(* {name} — 2단계 2g. 타일생성.py 가 만든다 — 손으로 고치지 않는다. 블록 16 × 16 스레드가 출력 {WA} 행 × {WB} 열을 맡고,
   스레드 하나가 {TM} × {TN} 칸(행 = 행바탕 + 세로 + 16i, 열 = 열바탕 + 가로 + 16j)을 레지스터에 든다. k 를 {KT} 칸씩 공유 메모리에
   올리며, 지금 조각을 계산하는 동안 다음 조각을 레지스터로 미리 읽는다. 칸마다 k 를 0 부터 차례로 곱해더하기(반올림 한 번)로
   더한다. 깊이는 {KT} 의 배수라고 둔다. *)

외부 [블록안가로]는 -> 정수.
외부 [블록안세로]는 -> 정수.
외부 [블록가로]는 -> 정수.
외부 [블록세로]는 -> 정수.
외부 [공유메모리0]는 -> 짧은실수 참조.
외부 [공유메모리1]는 -> 짧은실수 참조.
외부 [동기화]는.
외부 [짧은실수 x를 짧은실수 y를 짧은실수 z를 곱해더하기]는 -> 짧은실수.

[짧은실수 참조 입력에서 짧은실수 참조 가중치와 짧은실수 참조 출력에 정수 행수로 정수 열수로 정수 깊이로 {name}]는 {{
    정수 가로 = 블록안가로().
    정수 세로 = 블록안세로().
    정수 번호 = 세로 * 16 + 가로.
    정수 행바탕 = 블록세로() * {WA}.
    정수 열바탕 = 블록가로() * {WB}.
    짧은실수 참조 입력판 = 공유메모리0().
    짧은실수 참조 가중치판 = 공유메모리1().
    짧은실수 영 = 0 으로 짧은실수.
    정수 판수 = 깊이 / {KT}."""]
    for i in range(TM):
        L.append("    " + " ".join(f"짧은실수 누적{i}_{j} = 영." for j in range(TN)))
    for q in range(pa):
        L.append(f"    정수 m{q} = (번호 + {256 * q}) / {KT}. 정수 k{q} = (번호 + {256 * q}) % {KT}. 짧은실수 pa{q} = 영.")
        L.append(f"    행바탕 + m{q} < 행수이면 {{ pa{q} = 입력[(행바탕 + m{q}) * 깊이 + k{q}]. }}")
    for q in range(pb):
        L.append(f"    정수 kb{q} = (번호 + {256 * q}) / {WB}. 정수 n{q} = (번호 + {256 * q}) % {WB}. 짧은실수 pb{q} = 영.")
        L.append(f"    열바탕 + n{q} < 열수이면 {{ pb{q} = 가중치[kb{q} * 열수 + 열바탕 + n{q}]. }}")
    L.append("    반복 (정수 t는 0부터 판수 전까지) {")
    for q in range(pa):
        L.append(f"        입력판[k{q} * {WA} + m{q}] = pa{q}.")
    for q in range(pb):
        L.append(f"        가중치판[kb{q} * {WB} + n{q}] = pb{q}.")
    L.append("        동기화().")
    L.append("        t + 1 < 판수이면 {")
    for q in range(pa):
        L.append(f"            pa{q} = 영. 행바탕 + m{q} < 행수이면 {{ pa{q} = 입력[(행바탕 + m{q}) * 깊이 + (t + 1) * {KT} + k{q}]. }}")
    for q in range(pb):
        L.append(f"            pb{q} = 영. 열바탕 + n{q} < 열수이면 {{ pb{q} = 가중치[((t + 1) * {KT} + kb{q}) * 열수 + 열바탕 + n{q}]. }}")
    L.append("        }")
    L.append(f"        반복 (정수 kk는 0부터 {KT} 전까지) {{")
    for i in range(TM):
        L.append(f"            짧은실수 a{i} = 입력판[kk * {WA} + 세로 + {16 * i}].")
    for j in range(TN):
        L.append(f"            짧은실수 b{j} = 가중치판[kk * {WB} + 가로 + {16 * j}].")
    for i in range(TM):
        L.append("            " + " ".join(f"누적{i}_{j} = 곱해더하기(a{i}, b{j}, 누적{i}_{j})." for j in range(TN)))
    L.append("""        }
        동기화().
    }""")
    for i in range(TM):
        L.append(f"    정수 r{i} = 행바탕 + 세로 + {16 * i}.")
    for j in range(TN):
        L.append(f"    정수 c{j} = 열바탕 + 가로 + {16 * j}.")
    for i in range(TM):
        for j in range(TN):
            L.append(f"    (r{i} < 행수 그리고 c{j} < 열수)이면 {{ 출력[r{i} * 열수 + c{j}] = 누적{i}_{j}. }}")
    L.append("}")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    for fname, args in KINDS.items():
        open(os.path.join(HERE, fname), "w", encoding="utf-8", newline="\n").write(source(*args))
        print("만듦:", fname)
    for fname, args in RECT.items():
        open(os.path.join(HERE, fname), "w", encoding="utf-8", newline="\n").write(source_rect(*args))
        print("만듦:", fname)
