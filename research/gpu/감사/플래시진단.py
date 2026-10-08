#!/usr/bin/env python3
"""감사 A3 진단 — llama.cpp CUDA 의 flash_attn_ext: 가리개가 2^31 원소를 넘을 때 먼 행을 맞게 읽는가, 그리고 같은 질의의 정확도가
함께 계산하는 질의 수에 따라 바뀌는가.

  build/감사venv/Scripts/python research/gpu/감사/플래시진단.py

(c) 모든 질의가 같고 가리개가 모두 0 인 한 번의 실행에서 행마다 비트를 견준다. (d) 같은 질의를 질의 1·2·8·64·512·2048 개로 돌려
fp64 참값과 견준다.
"""
import os, sys, importlib.util
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
spec = importlib.util.spec_from_file_location("lm", os.path.join(os.path.dirname(os.path.abspath(__file__)), "라마검사.py"))
lm = importlib.util.module_from_spec(spec); spec.loader.exec_module(lm)
g = lm.GG(); F32, F16 = lm.F32, lm.F16
D, NKV, NQ = 128, 262144, 8256
rng = np.random.default_rng(48)
q = rng.standard_normal((NQ, D), dtype=np.float32)
k = rng.standard_normal((NKV, D), dtype=np.float32).astype(np.float16)
v = rng.standard_normal((NKV, D), dtype=np.float32).astype(np.float16)
scale = 1.0 / np.sqrt(D)
def fa(qs, mask):
    nq = qs.shape[0]
    r = lm.Run(g)
    tq = g.new3(r.ctx, F32, D, nq, 1); tk = g.new3(r.ctx, F16, D, NKV, 1); tv = g.new3(r.ctx, F16, D, NKV, 1)
    tm = g.new2(r.ctx, F16, NKV, nq)
    o = g.flash(r.ctx, tq, tk, tv, tm, scale, 0.0, 0.0)
    r.compute([o], [(tq, qs), (tk, k), (tv, v), (tm, mask)])
    out = r.get(o, 0, D * nq, np.float32).reshape(nq, D); r.close(); return out
s = (k.astype(np.float64) @ q[8192].astype(np.float64)) * scale
p = np.exp(s - s.max()); ref = (p / p.sum()) @ v.astype(np.float64)
# (c) 모든 질의가 같고 가리개가 모두 0: 같은 실행 안에서 0번 행과 먼 행(오프셋 ≥ 2^31)이 같은가
same_q = np.tile(q[8192], (NQ, 1)).astype(np.float32)
allz = np.zeros((NQ, NKV), np.float16)
o = fa(same_q, allz)
for j in (0, 1, 63, 64, 4000, 8127, 8128, 8191, 8192, 8255):
    print(f"(c) 행 {j}: 0번 행과 비트 같음 {np.array_equal(o[j].view(np.uint32), o[0].view(np.uint32))}, fp64 대비 상대차 {lm.rel(o[j], ref):.3g}", flush=True)
for nq in (1, 2, 8, 64, 512, 2048):
    oo = fa(same_q[:nq], np.zeros((nq, NKV), np.float16))
    print(f"(d) 질의 {nq}개로 돌린 0번 행: fp64 대비 상대차 {lm.rel(oo[0], ref):.3g}", flush=True)
