#!/usr/bin/env python3
"""2단계 2e 재기 — 정수 폭의 증명이 큰 입력에서도 맞는가: 입력의 원소가 2^31 을 넘어 전역 색인이 32비트를 넘는 행렬곱.

  build/감사venv/Scripts/python research/gpu/2단계/큰색인재기.py

입력 [520, 2^22] (원소 2^31 + 2^22, fp32 8.7 GB), 가중치 [2^22, 64]. 레지스터 타일 판(2e 로 나눗셈을 좁힌 판)과 기준 판(행렬곱.gl)의
출력 전체를 비트로 견주고, 마지막 행(색인 519 × 2^22 + k > 2^31)을 CPU 기준(같은 순서로 연산마다 fp32 반올림)과 견준다.
"""
import ctypes
import json
import os
import subprocess
import sys

import numpy as np
import torch

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
dev = torch.device("cuda")
B, K, N = 520, 2 ** 22, 64


def load(cu, gl, name):
    ptx = os.path.join(ROOT, "build", name + "_큰색인.ptx")
    subprocess.run([sys.executable, os.path.join(ROOT, "research", "gpu", "글ptx.py"), gl, "-o", ptx], check=True, capture_output=True)
    mod, fn = ctypes.c_void_p(), ctypes.c_void_p()
    assert cu.cuModuleLoadData(ctypes.byref(mod), open(ptx, "rb").read() + b"\0") == 0
    assert cu.cuModuleGetFunction(ctypes.byref(fn), mod, ("_G" + name.encode("utf-8").hex()).encode()) == 0
    return fn


def main():
    torch.zeros(1, device=dev)
    cu = ctypes.WinDLL("nvcuda.dll")
    ctx = ctypes.c_void_p()
    assert cu.cuInit(0) == 0 and cu.cuDevicePrimaryCtxRetain(ctypes.byref(ctx), 0) == 0 and cu.cuCtxSetCurrent(ctx) == 0
    naive = load(cu, os.path.join(ROOT, "research", "gpu", "감사", "행렬곱.gl"), "행렬곱")
    reg = load(cu, os.path.join(HERE, "레지스터타일행렬곱.gl"), "레지스터타일행렬곱")
    g = torch.Generator(device=dev).manual_seed(48)
    x = torch.randn(B, K, device=dev, generator=g)
    w = torch.randn(K, N, device=dev, generator=g) / 2048

    def run(fn, tile):
        o = torch.empty(B, N, device=dev)
        ps = [ctypes.c_uint64(x.data_ptr()), ctypes.c_uint64(w.data_ptr()), ctypes.c_uint64(o.data_ptr()),
              ctypes.c_int64(B), ctypes.c_int64(N), ctypes.c_int64(K)]
        args = (ctypes.c_void_p * 6)(*[ctypes.cast(ctypes.byref(p), ctypes.c_void_p) for p in ps])
        if tile:
            r = cu.cuLaunchKernel(fn, (N + 63) // 64, (B + 63) // 64, 1, 16, 16, 1, 0, None, args, None)
        else:
            r = cu.cuLaunchKernel(fn, (B * N + 255) // 256, 1, 1, 256, 1, 1, 0, None, args, None)
        assert r == 0 and cu.cuCtxSynchronize() == 0
        return o

    a, b = run(naive, False), run(reg, True)
    same = torch.equal(a.view(torch.int32), b.view(torch.int32))
    xr = x[-1].cpu().numpy()
    wn = w.cpu().numpy()
    del x
    acc = np.cumsum((xr[:, None] * wn).astype(np.float32), axis=0, dtype=np.float32)[-1]
    cpu_diff = int(np.count_nonzero(b[-1].cpu().numpy().view(np.uint32) != acc.view(np.uint32)))
    res = {"입력 원소": B * K, "마지막 행의 최대 전역 색인": (B - 1) * K + K - 1,
           "레지스터 타일 판과 기준 판의 출력 전체가 비트까지 같음": bool(same), "마지막 행과 CPU 기준이 다른 칸": cpu_diff}
    os.makedirs(os.path.join(HERE, "결과"), exist_ok=True)
    json.dump(res, open(os.path.join(HERE, "결과", "2e_큰색인.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for k, v in res.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
