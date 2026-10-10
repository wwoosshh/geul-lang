"""짧은 덩이의 넣기 시간 나누기: 계획 만들기(파이썬) · 처음 띄우기(그래프 없음) · 두 번째(그래프) · GPU 커널 합. 인자: ROOT"""
import sys
import os
import time
import ctypes
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = sys.argv[1]
for d in ("10단계", "9단계", "8단계", "7단계", "6단계", "5단계", "4단계", "3단계"):
    sys.path.insert(0, os.path.join(ROOT, "research", "gpu", d))
import numpy as np         # noqa: E402
import torch               # noqa: E402,F401
import 재기4 as R          # noqa: E402
import 재기10 as K10       # noqa: E402
import gguf읽기 as GR      # noqa: E402
wq = GR.gpt2정수(K10.긴GGUF)
글 = R.글엔진(wq, KV형식="정수", 자리수=2, 최대행=1024, 최대문장=1, 최대길이=102400, 로짓행=16)
m = 글.m
m.판미리고르기()
rng = np.random.default_rng(3)
위치 = int(sys.argv[2]) if len(sys.argv) > 2 else 7000
앞 = [int(x) for x in rng.integers(0, 50257, 위치)]
for a in range(0, 위치, 1000):
    m.이어넣기(앞[a:a + 1000], a)
cu = m.dr.cu
for M in ([int(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else (8, 32, 33, 100, 160, 300, 600, 1000)):
    ids = [int(x) for x in rng.integers(0, 50257, M)]
    t0 = time.perf_counter(); 계획 = m._만들기(1, M, "끝"); t1 = time.perf_counter()
    m._계획[(1, M, "끝")] = 계획
    m.토큰넣기(ids)
    m.dr.맞추기()
    t2 = time.perf_counter(); m.계산(1, M, 위치, "끝", 출력자리=m.생성칸); m.dr.맞추기(); t3 = time.perf_counter()   # 처음 — 그래프 없이
    t4 = time.perf_counter(); m.계산(1, M, 위치, "끝", 출력자리=m.생성칸); m.dr.맞추기(); t5 = time.perf_counter()   # 둘째 — 그래프를 만든다
    t6 = time.perf_counter(); m.계산(1, M, 위치, "끝", 출력자리=m.생성칸); m.dr.맞추기(); t7 = time.perf_counter()   # 셋째 — 그래프
    pos, tok, out, L = 계획
    e0, e1 = ctypes.c_void_p(), ctypes.c_void_p()
    cu.cuEventCreate(ctypes.byref(e0), 0); cu.cuEventCreate(ctypes.byref(e1), 0)
    합 = 0.0
    for x in L:
        cu.cuEventRecord(e0, None)
        cu.cuLaunchKernel(x.fn, x.grid[0], x.grid[1], 1, x.block[0], x.block[1], 1, 0, None, x.args, None)
        cu.cuEventRecord(e1, None); cu.cuEventSynchronize(e1)
        ms = ctypes.c_float(); cu.cuEventElapsedTime(ctypes.byref(ms), e0, e1); 합 += ms.value
    print(f"덩이 {M:5d}: 계획 만들기 {1000 * (t1 - t0):6.2f} ms · 처음(바로) {1000 * (t3 - t2):6.2f} · 둘째(그래프 만듦) {1000 * (t5 - t4):6.2f} · "
          f"셋째(그래프) {1000 * (t7 - t6):6.2f} · 커널 합(따로) {합:6.2f} ms · 실행 {len(L)}", flush=True)
m.닫기()
