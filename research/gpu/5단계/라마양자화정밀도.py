#!/usr/bin/env python3
"""5단계 (기록) — llama.cpp 의 양자화 행렬곱은 무엇을 더 잃는가. ggml 의 mul_mat 하나를 CUDA 로 직접 부른다(감사의 라마검사.py 하네스).

  build/감사venv/Scripts/python -I research/gpu/5단계/라마양자화정밀도.py

가중치(깊이 768 × 열 3072, GPT-2 의 c_fc 모양)를 F16 · Q8_0 · Q4_0 으로 둔다. 참값은 **그 형식의 가중치를 정확히 푼 값**과 활성값의
fp64 곱이다 — 가중치 양자화는 밝힌 손실이니 참값에 넣고, 그 위에 계산이 더 잃은 몫만 잰다. 함께 계산하는 행 M 마다 상대차. 눈금:
활성값을 f16 으로 반올림한 곱, 활성값을 32 개씩 묶어 8 비트로 양자화(q8_1 꼴 — 묶음의 최댓값 / 127 을 척도로)한 곱. 결과는
결과/라마양자화정밀도.json 에.
"""
import json
import os
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "research", "gpu", "감사"))
import 라마검사 as LG       # noqa: E402

F16, Q4_0, Q8_0 = 1, 2, 8


def q8_1꼴(x):
    """활성값을 32 개씩: d = max|x| / 127, q = round(x / d) — llama.cpp 의 q8_1 과 같은 꼴(눈금용)."""
    b = x.reshape(-1, 32).astype(np.float64)
    d = np.abs(b).max(1, keepdims=True) / 127
    d[d == 0] = 1
    return (np.round(b / d) * d).reshape(x.shape)


def main():
    g = LG.GG()
    K, N = 768, 3072
    rng = np.random.default_rng(48)
    w = (rng.standard_normal((N, K)) * 0.02).astype(np.float32)
    x = rng.standard_normal((512, K)).astype(np.float32)
    res = {"모양 (깊이, 열)": [K, N], "형식": {}}
    for 이름, t in (("F16", F16), ("Q8_0", Q8_0), ("Q4_0", Q4_0)):
        if t == F16:
            wq = w.astype(np.float16)
            wd = wq.astype(np.float64)
            data = wq
        else:
            data = np.empty(g.row_size(t, K) * N, dtype=np.uint8)
            g.quantize(t, w.ctypes.data, data.ctypes.data, 0, N, K, None)
            wd = np.empty(N * K, np.float32)               # 정확히 푼 가중치 (ggml 의 풀기)
            fn = {Q4_0: "dequantize_row_q4_0", Q8_0: "dequantize_row_q8_0"}[t]
            f = getattr(g.libs[0], fn)
            f.argtypes = [LG.P, LG.P, LG.I64]
            f(data.ctypes.data, wd.ctypes.data, N * K)
            wd = wd.reshape(N, K).astype(np.float64)
        ref = x.astype(np.float64) @ wd.T
        r = {"눈금: 활성값을 f16 으로": LG.rel(x.astype(np.float16).astype(np.float64) @ wd.T, ref),
             "눈금: 활성값을 32 개씩 8 비트로 (q8_1 꼴)": LG.rel(q8_1꼴(x) @ wd.T, ref),
             "llama.cpp mul_mat — M 마다 상대차": {}}
        for M in (1, 2, 4, 8, 16, 32, 64, 128, 512):
            run = LG.Run(g)
            a = g.new2(run.ctx, t, K, N)
            b = g.new2(run.ctx, LG.F32, K, M)
            o = g.mul_mat(run.ctx, a, b)
            run.compute([o], [(a, data), (b, x[:M])])
            y = run.get(o, 0, N * M, np.float32).reshape(M, N)
            run.close()
            r["llama.cpp mul_mat — M 마다 상대차"][M] = LG.rel(y, ref[:M])
        res["형식"][이름] = r
        print(이름, json.dumps(r, ensure_ascii=False), flush=True)
    os.makedirs(os.path.join(HERE, "결과"), exist_ok=True)
    json.dump(res, open(os.path.join(HERE, "결과", "라마양자화정밀도.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
