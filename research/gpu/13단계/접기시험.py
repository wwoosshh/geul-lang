"""13단계: 두 층 정수접기(정수조각접기 커널)가 numpy 의 두 층 접기(정수계약._접기 — 같은 식)와 비트까지 같은가 — 무작위 조각 몫
(m, l, o)으로, 위치마다(묶음 하나 · 경계 · 여럿). 그리고 시간. 인자: ROOT [위치들]"""
import sys
import os
import ctypes
import subprocess
import time
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # 경고 · 오류도 UTF-8 로(한글 경로가 cp949 로 깨지지 않게)
import numpy as np
ROOT = sys.argv[1]
위치들 = [int(x) for x in (sys.argv[2] if len(sys.argv) > 2 else "0,100,1023,1024,1087,5000,16383,16384,65535,100000").split(",")]
T = os.path.join(ROOT, "build", "13단계작업")
os.makedirs(T, exist_ok=True)
sys.path.insert(0, os.path.join(ROOT, "research", "gpu", "3단계"))
sys.path.insert(0, os.path.join(ROOT, "research", "gpu", "6단계"))
import 커널생성 as K
import 글gpt2 as G
import 정수계약 as C
K.자리수 = 2; K.KV = "정수"; K.지수 = "적힌지수"; K.계약 = "정수"
K.너비, K.머리수 = 768, 12
최대길이 = 102400
src = "\n".join(K.머리줄() + K.정수머리줄() + K.정수조각접기())
gl = os.path.join(T, "접기시험.gl"); ptx = gl[:-3] + ".ptx"
open(gl, "w", encoding="utf-8", newline="\n").write(src)
r = subprocess.run([sys.executable, os.path.join(ROOT, "research", "gpu", "글ptx.py"), gl, "-o", ptx], capture_output=True)
assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-1500:]
dr = G.드라이버(); cu = dr.cu
fn = dr.함수(dr.모듈(open(ptx, "rb").read()), "정수조각접기")
regs, loc = ctypes.c_int(), ctypes.c_int()
cu.cuFuncGetAttribute(ctypes.byref(regs), 4, fn); cu.cuFuncGetAttribute(ctypes.byref(loc), 3, fn)
print(f"정수조각접기: 레지스터 {regs.value}, 지역 메모리 {loc.value} B")
f32 = np.float32
S = 최대길이 // 64
rng = np.random.default_rng(13)
NH = 12
m = rng.uniform(-8, 8, (NH, S)).astype(f32)
l = rng.uniform(1, 64, (NH, S)).astype(f32)
o = (rng.standard_normal((NH, S, 64)) * 3).astype(f32)
칸 = np.zeros((NH, S * 68), f32)                      # 쌍마다 o [조각][64] 다음 m·l [조각][2]
칸[:, :S * 64] = o.reshape(NH, S * 64)
ml = np.stack([m, l], -1).reshape(NH, S * 2)
칸[:, S * 64:S * 66] = ml
조각칸 = dr.할당(칸.nbytes); dr.올리기(조각칸, 칸)
출력 = dr.할당(NH * 64 * 4)
P, I = ctypes.c_uint64, ctypes.c_int64


def 참(h, 끝):
    """두 층 접기(numpy) — 머리 h 의 조각 0 … 끝."""
    M = L_ = O = None
    for g0 in range(0, 끝 + 1, 16):
        Mg, Lg, Og = m[h, g0:g0 + 1], l[h, g0:g0 + 1], o[h, g0:g0 + 1]
        for c in range(g0 + 1, min(g0 + 16, 끝 + 1)):
            Mg, Lg, Og = C._접기(Mg, Lg, Og, m[h, c:c + 1], l[h, c:c + 1], o[h, c:c + 1])
        if g0 == 0:
            M, L_, O = Mg, Lg, Og
        else:
            M, L_, O = C._접기(M, L_, O, Mg, Lg, Og)
    return (O / L_[:, None]).astype(f32)[0]


e0, e1 = ctypes.c_void_p(), ctypes.c_void_p()
cu.cuEventCreate(ctypes.byref(e0), 0); cu.cuEventCreate(ctypes.byref(e1), 0)
모두 = True
for 위치 in 위치들:
    x = G._띄움(fn, (NH, 1), (256, 1), [P(조각칸), P(출력), I(1), I(1), I(위치), I(최대길이)])
    dr.확인(cu.cuLaunchKernel(x.fn, *x.grid, 1, *x.block, 1, 0, None, x.args, None)); dr.맞추기()
    got = dr.내리기(출력, np.empty(NH * 64, f32)).reshape(NH, 64)
    끝 = 위치 // 64
    want = np.stack([참(h, 끝) for h in range(NH)])
    다른 = int((got.view(np.int32) != want.view(np.int32)).sum())
    모두 &= 다른 == 0
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 0.4:
        cu.cuLaunchKernel(x.fn, *x.grid, 1, *x.block, 1, 0, None, x.args, None); dr.맞추기()
    cu.cuEventRecord(e0, None)
    for _ in range(10):
        cu.cuLaunchKernel(x.fn, *x.grid, 1, *x.block, 1, 0, None, x.args, None)
    cu.cuEventRecord(e1, None); cu.cuEventSynchronize(e1)
    ms = ctypes.c_float(); cu.cuEventElapsedTime(ctypes.byref(ms), e0, e1)
    print(f"위치 {위치:6d} (조각 {끝 + 1:5d}, 묶음 {끝 // 16 + 1:3d}): 다른 칸 {다른} — {ms.value * 100:.1f} µs", flush=True)
print("모두", "같다" if 모두 else "다른 것이 있다")
