#!/usr/bin/env python3
"""감사 A1 — 행 불변: 0번 행의 결과가 함께 계산한 행의 수(B)에 따라 바뀌는가 (README 의 방법 그대로).

  build/감사venv/Scripts/python research/gpu/감사/행불변.py

PyTorch 연산과 글로 쓴 행렬곱 커널(행렬곱.gl → 글ptx.py → PTX)을 같은 PC 에서 돌려, B 마다 0번 행을 B = 1 일 때와 비트로
견준다. 글 커널은 같은 순서로 연산마다 반올림한 CPU 값과도 견준다. 결과는 결과/행불변.json 에 쓴다.
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
DTYPES = {"fp32": torch.float32, "bf16": torch.bfloat16, "fp16": torch.float16}
INT_VIEW = {torch.float32: torch.int32, torch.bfloat16: torch.int16, torch.float16: torch.int16}
dev = torch.device("cuda")


def same_bits(a, b):
    return torch.equal(a.contiguous().view(INT_VIEW[a.dtype]), b.contiguous().view(INT_VIEW[b.dtype]))


def maxdiff(a, b):
    return float((a.double() - b.double()).abs().max())


def sweep(name, dtype_name, make, bs):
    """make(B) -> 0번 행의 결과. B 마다 B = 1 의 결과와 비트로 견준다."""
    ref = make(1)
    torch.cuda.synchronize()
    differ = []
    worst = 0.0
    for B in bs:
        r = make(B)
        if not same_bits(r, ref):
            differ.append(B)
            worst = max(worst, maxdiff(r, ref))
    return {"연산": name, "타입": dtype_name, "B": bs, "비트가_다른_B": differ, "최대_절대차": worst}


def pytorch_rows():
    out = []
    g = torch.Generator(device=dev).manual_seed(48)
    for dn, dt in DTYPES.items():
        for K, N in ((4096, 4096), (1024, 512)):
            x = torch.randn(4096, K, device=dev, dtype=dt, generator=g)
            w = (torch.randn(N, K, device=dev, dtype=torch.float32, generator=g) / K ** 0.5).to(dt)
            out.append(sweep(f"linear K={K} N={N}", dn, lambda B: F.linear(x[:B], w)[0], BS))
            del x, w
        x = torch.randn(4096, 4096, device=dev, dtype=dt, generator=g)
        out.append(sweep("sum(dim=-1)", dn, lambda B: x[:B].sum(-1)[:1], BS))
        out.append(sweep("softmax", dn, lambda B: F.softmax(x[:B], -1)[0], BS))
        out.append(sweep("rms_norm", dn, lambda B: F.rms_norm(x[:B], (4096,))[0], BS))
        out.append(sweep("layer_norm", dn, lambda B: F.layer_norm(x[:B], (4096,))[0], BS))
        del x
        sb = [b for b in BS if b <= 512]          # 메모리: fp32 에서 4096 시퀀스는 12 GB 를 넘는다
        q, k, v = (torch.randn(512, 8, 512, 64, device=dev, dtype=dt, generator=g) for _ in range(3))
        out.append(sweep("scaled_dot_product_attention", dn,
                         lambda B: F.scaled_dot_product_attention(q[:B], k[:B], v[:B])[0], sb))
        del q, k, v
        torch.cuda.empty_cache()
    return out


def geul_rows():
    ptx = os.path.join(ROOT, "build", "행렬곱.ptx")
    subprocess.run([sys.executable, os.path.join(ROOT, "research", "gpu", "글ptx.py"),
                    os.path.join(HERE, "행렬곱.gl"), "-o", ptx], check=True, capture_output=True)
    torch.zeros(1, device=dev)                                   # PyTorch 가 기본 문맥을 먼저 만든다
    cu = ctypes.WinDLL("nvcuda.dll")
    ctx = ctypes.c_void_p()
    assert cu.cuInit(0) == 0 and cu.cuDevicePrimaryCtxRetain(ctypes.byref(ctx), 0) == 0
    assert cu.cuCtxSetCurrent(ctx) == 0
    mod, fn = ctypes.c_void_p(), ctypes.c_void_p()
    assert cu.cuModuleLoadData(ctypes.byref(mod), open(ptx, "rb").read() + b"\0") == 0
    name = "_G" + "행렬곱".encode("utf-8").hex()
    assert cu.cuModuleGetFunction(ctypes.byref(fn), mod, name.encode()) == 0

    K, N = 1024, 512
    g = torch.Generator(device=dev).manual_seed(48)
    x = torch.randn(4096, K, device=dev, generator=g)
    w = torch.randn(K, N, device=dev, generator=g) / K ** 0.5   # 가중치[k * 열수 + 열] — [K, N] 행 우선

    def run(B):
        o = torch.empty(B, N, device=dev)
        params = [ctypes.c_uint64(x.data_ptr()), ctypes.c_uint64(w.data_ptr()), ctypes.c_uint64(o.data_ptr()),
                  ctypes.c_int64(B), ctypes.c_int64(N), ctypes.c_int64(K)]
        args = (ctypes.c_void_p * 6)(*[ctypes.cast(ctypes.byref(p), ctypes.c_void_p) for p in params])
        assert cu.cuLaunchKernel(fn, (B * N + 255) // 256, 1, 1, 256, 1, 1, 0, None, args, None) == 0
        assert cu.cuCtxSynchronize() == 0
        return o[0]

    row = sweep("글 행렬곱 K=1024 N=512 (출력 칸마다 k 차례, .rn)", "fp32", run, BS)
    # 속도 (참고): B = 4096 에서 글 커널과 PyTorch F.linear(같은 모양, fp32), 첫 실행을 뺀 10회 중앙값
    def timed(f):
        f(); torch.cuda.synchronize()
        ts = []
        for _ in range(10):
            s, e = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
            s.record(); f(); e.record(); torch.cuda.synchronize()
            ts.append(s.elapsed_time(e))
        return sorted(ts)[5]
    wt = w.t().contiguous()
    row["시간_ms_B4096"] = {"글": round(timed(lambda: run(4096)), 3), "PyTorch_linear": round(timed(lambda: F.linear(x, wt)), 3)}
    # CPU 기준: 같은 순서로 연산마다 fp32 반올림
    x0 = x[0].cpu().numpy()
    wn = w.cpu().numpy()
    acc = np.zeros(N, dtype=np.float32)
    for kk in range(K):
        acc = (acc + x0[kk] * wn[kk]).astype(np.float32)
    got = run(1).cpu().numpy()
    row["CPU_기준과_비트가_다른_칸"] = int(np.count_nonzero(got.view(np.uint32) != acc.view(np.uint32)))
    cu.cuModuleUnload(mod)
    return [row]


def main():
    env = {"torch": torch.__version__, "cuda": torch.version.cuda, "gpu": torch.cuda.get_device_name(0),
           "matmul.allow_tf32": torch.backends.cuda.matmul.allow_tf32,
           "cudnn.allow_tf32": torch.backends.cudnn.allow_tf32,
           "float32_matmul_precision": torch.get_float32_matmul_precision(),
           "fp16_reduced_precision_reduction": torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction,
           "bf16_reduced_precision_reduction": torch.backends.cuda.matmul.allow_bf16_reduced_precision_reduction}
    rows = geul_rows() + pytorch_rows()
    os.makedirs(os.path.join(HERE, "결과"), exist_ok=True)
    json.dump({"환경": env, "결과": rows}, open(os.path.join(HERE, "결과", "행불변.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(env, ensure_ascii=False))
    for r in rows:
        extra = f"  CPU 기준과 다른 칸 {r['CPU_기준과_비트가_다른_칸']}" if "CPU_기준과_비트가_다른_칸" in r else ""
        if "시간_ms_B4096" in r:
            extra += f"  시간(B=4096) {r['시간_ms_B4096']}"
        print(f"{r['연산']:<52} {r['타입']:<5} 비트가 다른 B: {r['비트가_다른_B'] or '없음'}"
              f"  최대차 {r['최대_절대차']:.3g}{extra}")


if __name__ == "__main__":
    main()
