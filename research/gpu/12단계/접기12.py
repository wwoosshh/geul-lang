"""정수조각접기: 접기미리(다음 묶음 미리 읽기) 켬 · 끔을 같은 조각칸(무작위 m · l · o)으로 비트 대조 · 번갈아 재기. 인자: ROOT [위치=100000]"""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import os, ctypes, subprocess, time
import numpy as np
ROOT = sys.argv[1]
위치 = int(sys.argv[2]) if len(sys.argv) > 2 else 100000
T = os.path.join(ROOT, "build", "12단계작업")            # 만든 .gl · .ptx 는 git 밖에
os.makedirs(T, exist_ok=True)
sys.path.insert(0, os.path.join(ROOT, "research", "gpu", "3단계"))
import 커널생성 as K
import 글gpt2 as G
K.자리수 = 2; K.KV = "정수"; K.지수 = "적힌지수"; K.계약 = "정수"
K.너비, K.머리수 = 768, 12
최대길이 = 102400
dr = G.드라이버(); cu = dr.cu
fns = {}
for 미리 in (False, True):
    K.접기미리 = 미리
    src = "\n".join(K.머리줄() + K.정수머리줄() + K.정수조각접기())
    gl = os.path.join(T, f"접기12_{int(미리)}.gl"); ptx = gl[:-3] + ".ptx"
    open(gl, "w", encoding="utf-8", newline="\n").write(src)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "research", "gpu", "글ptx.py"), gl, "-o", ptx], capture_output=True)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-800:]
    fn = dr.함수(dr.모듈(open(ptx, "rb").read()), "정수조각접기")
    regs, loc = ctypes.c_int(), ctypes.c_int()
    cu.cuFuncGetAttribute(ctypes.byref(regs), 4, fn); cu.cuFuncGetAttribute(ctypes.byref(loc), 3, fn)
    fns[미리] = (fn, regs.value, loc.value)
K.접기미리 = True
rng = np.random.default_rng(7)
S = 최대길이 // 64
칸 = np.zeros((12, S, 68), np.float32)
칸[:, :, 0] = rng.uniform(-8, 8, (12, S))
칸[:, :, 1] = rng.uniform(1, 64, (12, S))
칸[:, :, 4:] = rng.standard_normal((12, S, 64)) * 3
조각칸 = dr.할당(칸.nbytes); dr.올리기(조각칸, 칸)
출력 = dr.할당(768 * 4)
P, I = ctypes.c_uint64, ctypes.c_int64
runs, outs = {}, {}
for 미리, (fn, regs, loc) in fns.items():
    x = G._띄움(fn, (12, 1), (256, 1), [P(조각칸), P(출력), I(1), I(1), I(위치), I(최대길이)])
    runs[미리] = x
    dr.확인(cu.cuLaunchKernel(x.fn, *x.grid, 1, *x.block, 1, 0, None, x.args, None)); dr.맞추기()
    outs[미리] = dr.내리기(출력, np.empty(768, np.float32)).copy()
print("비트:", "같다" if np.array_equal(outs[False].view(np.uint32), outs[True].view(np.uint32)) else "다르다!", "유한:", bool(np.isfinite(outs[True]).all()))
t0 = time.perf_counter()
while time.perf_counter() - t0 < 0.2:
    for x in runs.values():
        cu.cuLaunchKernel(x.fn, *x.grid, 1, *x.block, 1, 0, None, x.args, None)
    dr.맞추기()
e0, e1 = ctypes.c_void_p(), ctypes.c_void_p()
cu.cuEventCreate(ctypes.byref(e0), 0); cu.cuEventCreate(ctypes.byref(e1), 0)
ts = {k: [] for k in runs}
for _ in range(7):
    for k, x in runs.items():
        cu.cuEventRecord(e0, None)
        for _ in range(10):
            cu.cuLaunchKernel(x.fn, *x.grid, 1, *x.block, 1, 0, None, x.args, None)
        cu.cuEventRecord(e1, None); cu.cuEventSynchronize(e1)
        ms = ctypes.c_float(); cu.cuEventElapsedTime(ctypes.byref(ms), e0, e1); ts[k].append(ms.value * 100)
for k, (fn, regs, loc) in fns.items():
    print(f"접기미리 {k}: {sorted(ts[k])[3]:.1f} µs  regs {regs} local {loc}")
