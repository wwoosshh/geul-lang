#!/usr/bin/env python3
"""2단계 2g 재기 — 밝힌 합침: 곱해더하기(반올림 한 번)로 쓴 합침행렬곱이 정확한 FMA 참값과 비트가 같은가, 같은 의미(FMA)인
PyTorch F.linear 의 2배 안인가 (docs/17 §7 2단계 이정표의 판정 그대로).

  build/감사venv/Scripts/python research/gpu/2단계/합침재기.py

참값: 칸마다 k 를 0 부터 차례로 acc ← round32(x·w + acc) — 분수(Fraction)로 정확히 계산하고 fp32 로 한 번만 반올림한다
(0번 행과 마지막 행의 앞 64칸). 행 불변(B 14가지)도 본다. 시간은 B = 4096 에서 첫 실행을 뺀 10회 중앙값.
"""
import ctypes
import json
import os
import subprocess
import sys
from fractions import Fraction

import numpy as np
import torch
import torch.nn.functional as F

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
BS = [1, 2, 3, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096]
K, N = 1024, 512
dev = torch.device("cuda")


def round_f32(q):
    """분수를 binary32 로 가장 가까운 짝수 쪽 반올림 (비정규수·넘침 포함)."""
    if q == 0:
        return 0.0
    s = -1.0 if q < 0 else 1.0
    q = abs(q)
    e = q.numerator.bit_length() - q.denominator.bit_length()
    while Fraction(2) ** e > q:
        e -= 1
    while Fraction(2) ** (e + 1) <= q:
        e += 1
    quantum = Fraction(1, 2 ** 149) if e < -126 else Fraction(2) ** (e - 23)
    v = round(q / quantum) * quantum
    return s * (float("inf") if v >= Fraction(2) ** 128 else float(v))


def main():
    torch.zeros(1, device=dev)
    cu = ctypes.WinDLL("nvcuda.dll")
    ctx = ctypes.c_void_p()
    assert cu.cuInit(0) == 0 and cu.cuDevicePrimaryCtxRetain(ctypes.byref(ctx), 0) == 0 and cu.cuCtxSetCurrent(ctx) == 0
    def load(name):
        ptx = os.path.join(ROOT, "build", name + ".ptx")
        subprocess.run([sys.executable, os.path.join(ROOT, "research", "gpu", "글ptx.py"), os.path.join(HERE, name + ".gl"),
                        "-o", ptx], check=True, capture_output=True)
        mod, fn = ctypes.c_void_p(), ctypes.c_void_p()
        assert cu.cuModuleLoadData(ctypes.byref(mod), open(ptx, "rb").read() + b"\0") == 0
        assert cu.cuModuleGetFunction(ctypes.byref(fn), mod, ("_G" + name.encode("utf-8").hex()).encode()) == 0
        return fn

    g = torch.Generator(device=dev).manual_seed(48)
    x = torch.randn(4096, K, device=dev, generator=g)
    w = torch.randn(K, N, device=dev, generator=g) / K ** 0.5

    def timed(f):
        f(); torch.cuda.synchronize()
        ts = []
        for _ in range(10):
            s, e = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
            s.record(); f(); e.record(); torch.cuda.synchronize()
            ts.append(s.elapsed_time(e))
        return round(sorted(ts)[5], 3)

    wt = w.t().contiguous()
    xn, wn = x.cpu().numpy(), w.cpu().numpy()
    exact = {}
    for r in (0, 4095):
        for n in range(64):
            acc = 0.0
            for k in range(K):
                acc = round_f32(Fraction(float(xn[r, k])) * Fraction(float(wn[k, n])) + Fraction(acc))
            exact[(r, n)] = np.float32(acc).view(np.uint32)
    bits = lambda t: t.contiguous().view(torch.int32)
    t_torch = timed(lambda: F.linear(x, wt))
    res = {"PyTorch F.linear 시간_ms_B4096": t_torch}
    for name, tile in (("합침행렬곱", 64), ("큰타일합침행렬곱", 128), ("겹친큰타일합침행렬곱", 128)):
        fn = load(name)

        def run(B):
            o = torch.empty(B, N, device=dev)
            ps = [ctypes.c_uint64(x.data_ptr()), ctypes.c_uint64(w.data_ptr()), ctypes.c_uint64(o.data_ptr()),
                  ctypes.c_int64(B), ctypes.c_int64(N), ctypes.c_int64(K)]
            args = (ctypes.c_void_p * 6)(*[ctypes.cast(ctypes.byref(p), ctypes.c_void_p) for p in ps])
            assert cu.cuLaunchKernel(fn, (N + tile - 1) // tile, (B + tile - 1) // tile, 1, 16, 16, 1, 0, None, args, None) == 0
            assert cu.cuCtxSynchronize() == 0
            return o

        ref0 = run(1)[0].clone()
        row_diff = [B for B in BS if not torch.equal(bits(run(B)[0]), bits(ref0))]
        full = run(4096)
        exact_diff = sum(1 for (r, n), v in exact.items() if full[r, n].cpu().numpy().view(np.uint32) != v)
        tg = timed(lambda: run(4096))
        res[name] = {"0번 행이 B=1 과 다른 B": row_diff, "정확한 FMA 참값과 다른 칸 (128칸 중)": exact_diff,
                     "PyTorch 와의 최대 절대차 (더하는 순서가 다름)": float((full - F.linear(x, wt)).abs().max()),
                     "시간_ms_B4096": tg, "PyTorch 대비 배수": round(tg / t_torch, 2)}
    os.makedirs(os.path.join(HERE, "결과"), exist_ok=True)
    json.dump(res, open(os.path.join(HERE, "결과", "2g.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for k, v in res.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
