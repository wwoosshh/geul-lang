#!/usr/bin/env python3
"""2단계 재기 — 타일 행렬곱(2b)·레지스터 타일(2f)이 기준 판과 비트까지 같은가, 얼마나 빠른가 (docs/17 §7 2단계 이정표의 판정 그대로).

  build/감사venv/Scripts/python research/gpu/2단계/재기.py

기준 판은 감사의 행렬곱.gl(출력 칸마다 스레드 하나), 타일 판은 타일행렬곱.gl(32 × 32 블록, 공유 메모리). 둘 다 글ptx.py 로
PTX 를 만들어 드라이버로 돌린다. B 마다 타일 판의 출력 전체를 기준 판과 비트로 견주고, 0번 행이 B = 1 과 같은지(행 불변),
CPU 기준(같은 순서로 연산마다 fp32 반올림)과 같은지 본다. 시간은 B = 4096 에서 첫 실행을 뺀 10회 중앙값.
"""
import ctypes
import json
import os
import subprocess
import sys

import numpy as np
import torch
import torch.nn.functional as F

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
BS = [1, 2, 3, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096]
K, N = 1024, 512
dev = torch.device("cuda")


def load(cu, gl, name):
    ptx = os.path.join(ROOT, "build", name + ".ptx")
    subprocess.run([sys.executable, os.path.join(ROOT, "research", "gpu", "글ptx.py"), gl, "-o", ptx],
                   check=True, capture_output=True)
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
    kernels = {  # 이름 → (함수, 블록 한 변의 스레드 수, 블록이 맡는 출력 한 변의 칸 수)
        "타일 판(2b)": (load(cu, os.path.join(HERE, "타일행렬곱.gl"), "타일행렬곱"), 32, 32),
        "레지스터 타일 판(2f, 4×4)": (load(cu, os.path.join(HERE, "레지스터타일행렬곱.gl"), "레지스터타일행렬곱"), 16, 64),
        "큰 타일 판(2f, 8×8)": (load(cu, os.path.join(HERE, "큰타일행렬곱.gl"), "큰타일행렬곱"), 16, 128),
        "겹친 큰 타일 판(2f, 8×8, 겹쳐 읽기)": (load(cu, os.path.join(HERE, "겹친큰타일행렬곱.gl"), "겹친큰타일행렬곱"), 16, 128),
    }
    g = torch.Generator(device=dev).manual_seed(48)
    x = torch.randn(4096, K, device=dev, generator=g)
    w = torch.randn(K, N, device=dev, generator=g) / K ** 0.5

    def launch(fn, B, threads, tile):
        o = torch.empty(B, N, device=dev)
        ps = [ctypes.c_uint64(x.data_ptr()), ctypes.c_uint64(w.data_ptr()), ctypes.c_uint64(o.data_ptr()),
              ctypes.c_int64(B), ctypes.c_int64(N), ctypes.c_int64(K)]
        args = (ctypes.c_void_p * 6)(*[ctypes.cast(ctypes.byref(p), ctypes.c_void_p) for p in ps])
        if threads:
            r = cu.cuLaunchKernel(fn, (N + tile - 1) // tile, (B + tile - 1) // tile, 1, threads, threads, 1, 0, None, args, None)
        else:
            r = cu.cuLaunchKernel(fn, (B * N + 255) // 256, 1, 1, 256, 1, 1, 0, None, args, None)
        assert r == 0 and cu.cuCtxSynchronize() == 0
        return o

    bits = lambda t: t.contiguous().view(torch.int32)
    x0, wn = x[0].cpu().numpy(), w.cpu().numpy()
    acc = np.zeros(N, dtype=np.float32)
    for kk in range(K):
        acc = (acc + x0[kk] * wn[kk]).astype(np.float32)

    def timed(f):
        f(); torch.cuda.synchronize()
        ts = []
        for _ in range(10):
            s, e = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
            s.record(); f(); e.record(); torch.cuda.synchronize()
            ts.append(s.elapsed_time(e))
        return round(sorted(ts)[5], 3)

    res = {}
    for name, (fn, threads, tile) in kernels.items():
        full_diff, row_diff = [], []
        ref0 = launch(fn, 1, threads, tile)[0].clone()
        for B in BS:
            a, b = launch(naive, B, 0, 0), launch(fn, B, threads, tile)
            if not torch.equal(bits(a), bits(b)):
                full_diff.append(B)
            if not torch.equal(bits(b[0]), bits(ref0)):
                row_diff.append(B)
        cpu_diff = int(np.count_nonzero(ref0.cpu().numpy().view(np.uint32) != acc.view(np.uint32)))
        res[name] = {"기준 판과 출력 전체가 다른 B": full_diff, "0번 행이 B=1 과 다른 B": row_diff,
                     "0번 행과 CPU 기준이 다른 칸": cpu_diff,
                     "시간_ms_B4096": timed(lambda: launch(fn, 4096, threads, tile))}
    wt = w.t().contiguous()
    res["기준 판(행렬곱.gl) 시간_ms_B4096"] = timed(lambda: launch(naive, 4096, 0, 0))
    res["PyTorch F.linear 시간_ms_B4096"] = timed(lambda: F.linear(x, wt))
    os.makedirs(os.path.join(HERE, "결과"), exist_ok=True)
    json.dump(res, open(os.path.join(HERE, "결과", "행렬곱.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for k, v in res.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
