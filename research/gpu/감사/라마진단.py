#!/usr/bin/env python3
"""감사 A3 진단 — llama.cpp CUDA 의 scale 이 행 간격이 넓은 뷰에서 무엇을 읽는가, 그리고 백엔드가 그 연산을 지원한다고 답하는가.

  build/감사venv/Scripts/python research/gpu/감사/라마진단.py

CPU 백엔드는 같은 그래프를 계산할 때 ggml-cpu/ops.cpp 의 GGML_ASSERT(ggml_is_contiguous(src0)) 로 멈춘다(그래서 여기서는 돌리지 않는다).
"""
import ctypes
import importlib.util
import os
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("lm", os.path.join(HERE, "라마검사.py"))
lm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lm)
g = lm.GG()
cpu = g.init_by_name(b"CPU", None)
sup = g.fn("ggml_backend_supports_op", ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
rng = np.random.default_rng(48)
base = rng.standard_normal((1024, 1024)).astype(np.float32)
for vname, (n0, n1, off) in {"넓은 행 간격": (512, 1024, 0), "어긋난 시작": (1000, 1000, 1027)}.items():
    r = lm.Run(g)
    a = g.new2(r.ctx, lm.F32, 1024, 1024)
    v = g.view2(r.ctx, a, n0, n1, 4096, off * 4)
    o = g.scale(r.ctx, v, 1.7)
    s_cuda, s_cpu = sup(g.cuda, o), sup(cpu, o)
    r.compute([o], [(a, base)])
    got = r.get(o, 0, n0 * n1, np.float32).reshape(n1, n0)
    r.close()
    rr, cc = divmod(off, 1024)
    right = base[rr:rr + n1, cc:cc + n0] * np.float32(1.7)
    front = (base.reshape(-1)[off:off + n0 * n1] * np.float32(1.7)).reshape(n1, n0)
    print(f"scale@{vname}: 지원한다고 답함 CUDA {s_cuda}·CPU {s_cpu} | 맞는 값과 다른 칸 {int((got != right).sum())}/{n0 * n1} | "
          f"'연속이라고 본 앞부분 × 1.7' 과 같음 {bool(np.array_equal(got, front))}", flush=True)
