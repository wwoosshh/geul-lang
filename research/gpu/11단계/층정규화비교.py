"""층정규화정수의 블록당 행(RB)을 바꿔 만들고 같은 입력으로 비트 대조 · 번갈아 재기. 인자: ROOT [행수,…]"""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import os, ctypes, subprocess, time
import numpy as np
ROOT = sys.argv[1]
행수들 = [int(x) for x in (sys.argv[2] if len(sys.argv) > 2 else "128,512,1024").split(",")]
T = os.path.join(ROOT, "build", "11단계작업")                # 만든 .gl · .ptx 는 git 밖에
os.makedirs(T, exist_ok=True)
sys.path.insert(0, os.path.join(ROOT, "research", "gpu", "3단계"))
import 커널생성 as K
import 글gpt2 as G
K.자리수 = 2; K.KV = "정수"; K.지수 = "적힌지수"; K.계약 = "정수"
K.너비, K.머리수, K.층수, K.확장폭, K.낱말수 = K.크기들["XL"]
D = K.너비
dr = G.드라이버(); cu = dr.cu
원래 = K.층정규화정수행
fns = {}
for RB in (1, 2, 4):
    K.층정규화정수행 = lambda D_=None, RB=RB: RB
    src = "\n".join(K.머리줄() + K.정수머리줄() + K.층정규화정수())
    gl = os.path.join(T, f"층11_{RB}.gl"); ptx = gl[:-3] + ".ptx"
    open(gl, "w", encoding="utf-8", newline="\n").write(src)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "research", "gpu", "글ptx.py"), gl, "-o", ptx], capture_output=True)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-800:]
    fns[RB] = dr.함수(dr.모듈(open(ptx, "rb").read()), "층정규화정수")
K.층정규화정수행 = 원래
src = chr(10).join(K.머리줄() + K.정수머리줄() + K.층정규화정수줄())
gl = os.path.join(T, "층11_줄.gl"); ptx = gl[:-3] + ".ptx"
open(gl, "w", encoding="utf-8", newline=chr(10)).write(src)
r = subprocess.run([sys.executable, os.path.join(ROOT, "research", "gpu", "글ptx.py"), gl, "-o", ptx], capture_output=True)
assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-800:]
fns["줄"] = dr.함수(dr.모듈(open(ptx, "rb").read()), "층정규화정수줄")
P, I = ctypes.c_uint64, ctypes.c_int64
rng = np.random.default_rng(3)
Mx = max(행수들)
h = dr.할당(Mx * D * 4); dr.올리기(h, (rng.standard_normal(Mx * D) * 3).astype(np.float32))
g = dr.할당(D * 4); dr.올리기(g, (1 + rng.standard_normal(D) * 0.1).astype(np.float32))
b = dr.할당(D * 4); dr.올리기(b, (rng.standard_normal(D) * 0.1).astype(np.float32))
자 = dr.할당(2 * Mx * D + 4096)
정 = dr.할당((D // 32) * ((Mx + 63) // 64 * 64) * 4 + 4096)
e0, e1 = ctypes.c_void_p(), ctypes.c_void_p()
cu.cuEventCreate(ctypes.byref(e0), 0); cu.cuEventCreate(ctypes.byref(e1), 0)
for M in 행수들:
    runs, outs = {}, {}
    for RB, fn in fns.items():
        x = G._띄움(fn, (M, 1), (256, 1), [P(h), P(g), P(b), P(자), P(정), I(M)]) if RB == "줄" else             G._띄움(fn, ((M + RB - 1) // RB, 1), (32 * RB, 1), [P(h), P(g), P(b), P(자), P(정), I(M)])
        runs[RB] = x
        dr.확인(cu.cuLaunchKernel(x.fn, *x.grid, 1, *x.block, 1, 0, None, x.args, None)); dr.맞추기()
        a1 = dr.내리기(자, np.empty(2 * M * D // 4, np.int32)); a2 = dr.내리기(정, np.empty((D // 32) * ((M + 63) // 64 * 64), np.int32))
        outs[RB] = (a1.copy(), a2.copy())
    같음 = all(np.array_equal(outs[1][0], o[0]) and np.array_equal(outs[1][1], o[1]) for o in outs.values())
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 0.2:
        for x in runs.values():
            cu.cuLaunchKernel(x.fn, *x.grid, 1, *x.block, 1, 0, None, x.args, None)
        dr.맞추기()
    ts = {RB: [] for RB in runs}
    for _ in range(7):
        for RB, x in runs.items():
            cu.cuEventRecord(e0, None)
            for _ in range(20):
                cu.cuLaunchKernel(x.fn, *x.grid, 1, *x.block, 1, 0, None, x.args, None)
            cu.cuEventRecord(e1, None); cu.cuEventSynchronize(e1)
            ms = ctypes.c_float(); cu.cuEventElapsedTime(ctypes.byref(ms), e0, e1)
            ts[RB].append(ms.value / 20 * 1000)
    print(f"행 {M}: 비트 {'같음' if 같음 else '다름!'} — " + ", ".join(f"RB {RB} {sorted(v)[3]:.1f} µs" for RB, v in ts.items()))
