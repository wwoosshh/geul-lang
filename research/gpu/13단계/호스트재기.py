"""덩이 넣기의 시간 나누기(개발용) — 합성 긴 모델, 문맥 C 에서 덩이 M: (1) 계산(그래프, 위치가 바뀜 — 위치 마디 고치기 포함)의 호스트 시간,
(2) 같은 위치로 다시(고치기 없음), (3) GPU 이벤트로 그래프 실행만, (4) 이어넣기 전체(토큰 올리기 · 계산 · 내리기). 인자: ROOT C M"""
import sys
import os
import time
import ctypes
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # 경고 · 오류도 UTF-8 로(한글 경로가 cp949 로 깨지지 않게)
ROOT = sys.argv[1]
C = int(sys.argv[2]) if len(sys.argv) > 2 else 98000
M = int(sys.argv[3]) if len(sys.argv) > 3 else 16
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
앞 = [int(x) for x in rng.integers(0, 50257, C)]
for a in range(0, C, 1024):
    m.이어넣기(앞[a:a + 1024], a)
cu = m.dr.cu
ids = [int(x) for x in rng.integers(0, 50257, M)]
m.토큰넣기(ids)
for i in range(4):
    m.계산(1, M, C + i, "끝", 출력자리=m.생성칸); m.dr.맞추기()
e0, e1 = ctypes.c_void_p(), ctypes.c_void_p()
cu.cuEventCreate(ctypes.byref(e0), 0); cu.cuEventCreate(ctypes.byref(e1), 0)
호바, 호같, 지, 전 = [], [], [], []
for i in range(10):
    t0 = time.perf_counter(); cu.cuEventRecord(e0, None)
    m.계산(1, M, C + 10 + i, "끝", 출력자리=m.생성칸)
    t1 = time.perf_counter(); cu.cuEventRecord(e1, None); cu.cuEventSynchronize(e1); t2 = time.perf_counter()
    ms = ctypes.c_float(); cu.cuEventElapsedTime(ctypes.byref(ms), e0, e1)
    호바.append((t1 - t0) * 1000); 지.append(ms.value)
    t0 = time.perf_counter()
    m.계산(1, M, C + 10 + i, "끝", 출력자리=m.생성칸)
    t1 = time.perf_counter(); m.dr.맞추기()
    호같.append((t1 - t0) * 1000)
    t0 = time.perf_counter()
    m.이어넣기(ids, C + 30 + i)
    전.append((time.perf_counter() - t0) * 1000)
key = (1, M, "끝")
있던 = [v for k, v in m._그래프.items() if k[0] == key][0]
print(f"문맥 {C} 덩이 {M}: 위치 마디 {len(있던[3])} 개")
print(f"  계산 호스트 시간(위치 바뀜) 중앙값 {np.median(호바):.3f} ms, (같은 위치) {np.median(호같):.3f} ms")
print(f"  이벤트(계산 호출 시작 → 끝) {np.median(지):.3f} ms, 이어넣기 전체 {np.median(전):.3f} ms")
m.닫기()
