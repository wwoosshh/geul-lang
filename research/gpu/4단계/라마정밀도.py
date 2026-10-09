#!/usr/bin/env python3
"""4단계 (기록) — llama.cpp 의 F32 행렬곱은 F32 로 계산되는가. ggml C API 로 mul_mat 하나를 직접 부른다(감사의 라마검사.py 하네스).

  build/감사venv/Scripts/python -I research/gpu/4단계/라마정밀도.py

가중치·활성 모두 F32, GPT-2 의 c_fc 모양(깊이 768, 열 3072), 함께 계산하는 행 수 M 마다 fp64 참값 대비 상대차 ‖y − 참값‖ / ‖참값‖.
눈금: 같은 입력을 TF32(가수 10 비트)로 반올림해 fp64 로 곱한 값의 상대차, 그리고 FP32 로 차례로 더한 값(numpy float32 — 순서는
다르지만 크기는 같은 급)의 상대차. 결과는 결과/라마정밀도.json 에.
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


def tf32(a):
    """float32 를 TF32(가수 10 비트)로 — 가까운 쪽으로 반올림."""
    u = a.astype(np.float32).view(np.uint32).astype(np.uint64)
    return ((u + 0x1000) & 0xFFFFE000).astype(np.uint32).view(np.float32)


def main():
    g = LG.GG()
    K, N = 768, 3072
    rng = np.random.default_rng(48)
    w = (rng.standard_normal((N, K)) * 0.02).astype(np.float32)
    x = rng.standard_normal((512, K)).astype(np.float32)
    ref = x.astype(np.float64) @ w.astype(np.float64).T
    눈금 = {"TF32 로 반올림한 입력": LG.rel(tf32(x).astype(np.float64) @ tf32(w).astype(np.float64).T, ref),
          "FP32 (numpy float32)": LG.rel(x @ w.T, ref)}
    res = {"모양 (깊이, 열)": [K, N], "눈금": 눈금, "llama.cpp mul_mat F32 — M 마다 상대차": {}}
    for M in (1, 2, 4, 8, 16, 32, 64, 128, 512):
        r = LG.Run(g)
        a = g.new2(r.ctx, LG.F32, K, N)
        b = g.new2(r.ctx, LG.F32, K, M)
        o = g.mul_mat(r.ctx, a, b)
        r.compute([o], [(a, w), (b, x[:M])])
        y = r.get(o, 0, N * M, np.float32).reshape(M, N)
        r.close()
        res["llama.cpp mul_mat F32 — M 마다 상대차"][M] = LG.rel(y, ref[:M])
    os.makedirs(os.path.join(HERE, "결과"), exist_ok=True)
    json.dump(res, open(os.path.join(HERE, "결과", "라마정밀도.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
