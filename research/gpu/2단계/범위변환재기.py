#!/usr/bin/env python3
"""2단계 2c 재기 — 범위 검사: 범위 밖 변환은 오류 칸에 보고되고, 범위 안 결과는 비트까지 그대로인가, 검사의 비용은 얼마인가.

  build/감사venv/Scripts/python research/gpu/2단계/범위변환재기.py

범위변환.gl 을 검사를 넣은 판(글ptx.py 그대로)과 뺀 판(RANGE_CHECK = False — 재는 데만 쓴다)으로 만들어 견준다.
오류 칸은 모듈의 전역 __geul_err — 실행 전에 0 으로 두고 실행 뒤에 읽는다. 1 은 정수 변환, 2 는 짧은실수 변환.
"""
import ctypes
import importlib.util
import json
import os
import sys

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
spec = importlib.util.spec_from_file_location("geulptx", os.path.join(ROOT, "research", "gpu", "글ptx.py"))
gp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gp)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
dev = torch.device("cuda")
SRC = os.path.join(HERE, "범위변환.gl")
NAME = "_G" + "범위변환".encode("utf-8").hex()


def build(check):
    gp.RANGE_CHECK = check
    text, _ = gp.translate(SRC)
    gp.RANGE_CHECK = True
    return text.encode("ascii") + b"\0"


def main():
    torch.zeros(1, device=dev)
    cu = ctypes.WinDLL("nvcuda.dll")
    ctx = ctypes.c_void_p()
    assert cu.cuInit(0) == 0 and cu.cuDevicePrimaryCtxRetain(ctypes.byref(ctx), 0) == 0 and cu.cuCtxSetCurrent(ctx) == 0
    mods = {}
    for label, check in (("검사", True), ("검사 없음", False)):
        mod, fn = ctypes.c_void_p(), ctypes.c_void_p()
        assert cu.cuModuleLoadData(ctypes.byref(mod), build(check)) == 0
        assert cu.cuModuleGetFunction(ctypes.byref(fn), mod, NAME.encode()) == 0
        err, size = ctypes.c_uint64(), ctypes.c_size_t()
        assert cu.cuModuleGetGlobal_v2(ctypes.byref(err), ctypes.byref(size), mod, b"__geul_err") == 0
        mods[label] = (fn, err)

    def run(label, x):
        fn, err = mods[label]
        n = x.numel()
        o64 = torch.empty(n, dtype=torch.int64, device=dev)
        o32 = torch.empty(n, dtype=torch.int32, device=dev)
        of = torch.empty(n, dtype=torch.float32, device=dev)
        assert cu.cuMemsetD32_v2(err, 0, 1) == 0
        ps = [ctypes.c_uint64(x.data_ptr()), ctypes.c_uint64(o64.data_ptr()), ctypes.c_uint64(o32.data_ptr()),
              ctypes.c_uint64(of.data_ptr()), ctypes.c_int64(n)]
        args = (ctypes.c_void_p * 5)(*[ctypes.cast(ctypes.byref(p), ctypes.c_void_p) for p in ps])
        assert cu.cuLaunchKernel(fn, (n + 255) // 256, 1, 1, 256, 1, 1, 0, None, args, None) == 0
        assert cu.cuCtxSynchronize() == 0
        e = ctypes.c_uint32()
        assert cu.cuMemcpyDtoH_v2(ctypes.byref(e), err, ctypes.c_size_t(4)) == 0
        return e.value, o64, o32, of

    res = {}
    g = torch.Generator(device=dev).manual_seed(48)
    x = (torch.rand(1 << 20, dtype=torch.float64, device=dev, generator=g) * 4e9 - 2e9)
    e1, a64, a32, af = run("검사", x)
    e0, b64, b32, bf = run("검사 없음", x)
    xn = x.cpu().numpy()
    exact = (np.array_equal(a64.cpu().numpy(), np.trunc(xn).astype(np.int64)) and
             np.array_equal(a32.cpu().numpy(), np.trunc(xn).astype(np.int32)) and
             np.array_equal(af.cpu().numpy().view(np.uint32), xn.astype(np.float32).view(np.uint32)))
    same = torch.equal(a64, b64) and torch.equal(a32, b32) and torch.equal(af.view(torch.int32), bf.view(torch.int32))
    res["범위 안 (|x| < 2e9, 100만 개)"] = {"오류 칸": e1, "정답과 비트 같음": bool(exact), "검사 없는 판과 비트 같음": bool(same)}

    cases = [("x = 3e9 (중간정수 밖)", 3e9, 1), ("x = 2^31 (중간정수 밖)", 2.0 ** 31, 1), ("x = 2^31 − 1", 2.0 ** 31 - 1, 0),
             ("x = −0.5", -0.5, 0), ("x = 1e19 (정수 밖)", 1e19, 1), ("x = NaN", float("nan"), 1),
             ("x = 1e39 (짧은실수 밖)", 1e39, 3), ("x = inf (이미 무한)", float("inf"), 1)]
    for name, v, want in cases:
        xv = torch.full((256,), v, dtype=torch.float64, device=dev)
        e, o64, o32, of = run("검사", xv)
        _, s64, s32, sf = run("검사 없음", xv)
        res[name] = {"오류 칸": e, "기대": want, "맞음": e == want,
                     "검사 없는 판이 조용히 낸 값": [int(s64[0]), int(s32[0]), float(sf[0])]}

    big = (torch.rand(1 << 24, dtype=torch.float64, device=dev, generator=g) * 4e9 - 2e9)

    def timed(label):
        run(label, big)
        ts = []
        for _ in range(10):
            s, t = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
            s.record(); run(label, big); t.record(); torch.cuda.synchronize()
            ts.append(s.elapsed_time(t))
        return round(sorted(ts)[5], 3)

    res["시간_ms (1600만 개, 실행·오류 칸 읽기 포함)"] = {"검사": timed("검사"), "검사 없음": timed("검사 없음")}
    os.makedirs(os.path.join(HERE, "결과"), exist_ok=True)
    json.dump(res, open(os.path.join(HERE, "결과", "2c.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for k, v in res.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
