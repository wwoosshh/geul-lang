#!/usr/bin/env python3
"""2단계 2g 재기 — "PyTorch 의 2배 안" 판정을 흔들림 없이: 글 판과 PyTorch F.linear 를 번갈아 7번씩 재고(각 10회 중앙값),
배수의 중앙값과 범위를 낸다.

  build/감사venv/Scripts/python research/gpu/2단계/배수재기.py
"""
import ctypes
import importlib.util
import json
import os
import statistics
import subprocess
import sys

import numpy as np
import torch
import torch.nn.functional as F
from fractions import Fraction

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
K, N, B = 1024, 512, 4096
dev = torch.device("cuda")


def main():
    torch.zeros(1, device=dev)
    cu = ctypes.WinDLL("nvcuda.dll")
    ctx = ctypes.c_void_p()
    assert cu.cuInit(0) == 0 and cu.cuDevicePrimaryCtxRetain(ctypes.byref(ctx), 0) == 0 and cu.cuCtxSetCurrent(ctx) == 0
    g = torch.Generator(device=dev).manual_seed(48)
    x = torch.randn(B, K, device=dev, generator=g)
    w = torch.randn(K, N, device=dev, generator=g) / K ** 0.5
    wt = w.t().contiguous()

    def load(name):
        ptx = os.path.join(ROOT, "build", name + ".ptx")
        subprocess.run([sys.executable, os.path.join(ROOT, "research", "gpu", "글ptx.py"), os.path.join(HERE, name + ".gl"),
                        "-o", ptx], check=True, capture_output=True)
        mod, fn = ctypes.c_void_p(), ctypes.c_void_p()
        assert cu.cuModuleLoadData(ctypes.byref(mod), open(ptx, "rb").read() + b"\0") == 0
        assert cu.cuModuleGetFunction(ctypes.byref(fn), mod, ("_G" + name.encode("utf-8").hex()).encode()) == 0
        return fn

    def runner(fn, tile, tile_cols=None):
        tile_rows, tile_cols = tile, (tile_cols or tile)
        o = torch.empty(B, N, device=dev)
        ps = [ctypes.c_uint64(x.data_ptr()), ctypes.c_uint64(w.data_ptr()), ctypes.c_uint64(o.data_ptr()),
              ctypes.c_int64(B), ctypes.c_int64(N), ctypes.c_int64(K)]
        args = (ctypes.c_void_p * 6)(*[ctypes.cast(ctypes.byref(p), ctypes.c_void_p) for p in ps])
        keep = (o, ps, args)                  # 출력과 인자 값이 실행 내내 살아 있게 (놓치면 커널이 지워진 주소를 받는다)

        def launch():
            assert keep and cu.cuLaunchKernel(fn, (N + tile_cols - 1) // tile_cols, (B + tile_rows - 1) // tile_rows, 1, 16, 16, 1, 0,
                                              None, args, None) == 0
        return launch

    def timed(f):
        f(); torch.cuda.synchronize()
        ts = []
        for _ in range(10):
            s, e = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
            s.record(); f(); e.record(); torch.cuda.synchronize()
            ts.append(s.elapsed_time(e))
        return sorted(ts)[5]

    res = {}
    spec = importlib.util.spec_from_file_location("hap", os.path.join(HERE, "합침재기.py"))
    hap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hap)
    xn, wn = x.cpu().numpy(), w.cpu().numpy()
    exact0 = []
    for n in range(64):                                          # 0번 행 앞 64칸의 정확한 FMA 참값
        acc = 0.0
        for k in range(K):
            acc = hap.round_f32(Fraction(float(xn[0, k])) * Fraction(float(wn[k, n])) + Fraction(acc))
        exact0.append(np.float32(acc).view(np.uint32))
    cases = (("겹친큰타일합침행렬곱", "합침(FMA) 128×128 타일 — 같은 의미의 PyTorch 와", 128, 128),
             ("직사각합침_8x4", "합침(FMA) 128×64 타일 — 같은 의미의 PyTorch 와", 128, 64),
             ("직사각합침_4x8", "합침(FMA) 64×128 타일 — 같은 의미의 PyTorch 와", 64, 128),
             ("겹친큰타일행렬곱", "연산마다 반올림 128×128 타일 — 의미가 다른 PyTorch 와", 128, 128))
    for name, label, tr, tc in cases:
        fn = load(name)
        out = torch.empty(B, N, device=dev)
        ps = [ctypes.c_uint64(x.data_ptr()), ctypes.c_uint64(w.data_ptr()), ctypes.c_uint64(out.data_ptr()),
              ctypes.c_int64(B), ctypes.c_int64(N), ctypes.c_int64(K)]
        args = (ctypes.c_void_p * 6)(*[ctypes.cast(ctypes.byref(p), ctypes.c_void_p) for p in ps])
        assert cu.cuLaunchKernel(fn, (N + tc - 1) // tc, (B + tr - 1) // tr, 1, 16, 16, 1, 0, None, args, None) == 0
        assert cu.cuCtxSynchronize() == 0
        got0 = out[0, :64].cpu().numpy().view(np.uint32)
        exact_diff = int(sum(1 for a, b in zip(got0, exact0) if a != b)) if "합침" in name else None
        run = runner(fn, tr, tc)
        ratios, tg_all, tt_all = [], [], []
        for _ in range(7):
            tg, tt = timed(run), timed(lambda: F.linear(x, wt))
            ratios.append(tg / tt); tg_all.append(tg); tt_all.append(tt)
        res[label] = {"정확한 FMA 참값과 다른 칸 (0번 행 64칸 중)": exact_diff,
                      "글 ms (중앙값)": round(statistics.median(tg_all), 3), "PyTorch ms (중앙값)": round(statistics.median(tt_all), 3),
                      "배수 중앙값": round(statistics.median(ratios), 2), "배수 범위": [round(min(ratios), 2), round(max(ratios), 2)]}
    os.makedirs(os.path.join(HERE, "결과"), exist_ok=True)
    json.dump(res, open(os.path.join(HERE, "결과", "2g_배수.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for k, v in res.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
