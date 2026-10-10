"""덩이 넣기의 GPU 시간을 커널(함수)마다 — 합성 긴 모델, 문맥 C 에서 덩이 M 의 계획을 커널마다 따로 띄워(이벤트) 함수 이름별 합. 인자: ROOT C M들"""
import sys
import os
import ctypes
import collections
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # 경고 · 오류도 UTF-8 로(한글 경로가 cp949 로 깨지지 않게)
ROOT = sys.argv[1]
C = int(sys.argv[2]) if len(sys.argv) > 2 else 98000
Ms = [int(x) for x in (sys.argv[3] if len(sys.argv) > 3 else "16,64").split(",")]
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
이름 = {}
for n, f in list(m.k.items()) + [(f"{p}{e}", f) for (p, e), f in m.선형.items()] + [(f"로짓{p}", f) for p, f in m.로짓선형.items()]:
    이름.setdefault(getattr(f, "value", f), n)
e0, e1 = ctypes.c_void_p(), ctypes.c_void_p()
cu.cuEventCreate(ctypes.byref(e0), 0); cu.cuEventCreate(ctypes.byref(e1), 0)
for M in Ms:
    ids = [int(x) for x in rng.integers(0, 50257, M)]
    m.토큰넣기(ids)
    for _ in range(3):
        m.계산(1, M, C, "끝", 출력자리=m.생성칸)
    m.dr.맞추기()
    pos, tok, out, L = m._계획[(1, M, "끝")]
    합 = collections.Counter()
    수 = collections.Counter()
    for _ in range(3):
        for x in L:                                # 같은 커널을 20 번 잇달아(동기화 없이) — 띄움 사이의 빈틈만 남는다
            cu.cuEventRecord(e0, None)
            for _ in range(20):
                cu.cuLaunchKernel(x.fn, x.grid[0], x.grid[1], 1, x.block[0], x.block[1], 1, 0, None, x.args, None)
            cu.cuEventRecord(e1, None); cu.cuEventSynchronize(e1)
            ms = ctypes.c_float(); cu.cuEventElapsedTime(ctypes.byref(ms), e0, e1)
            합[이름.get(getattr(x.fn, "value", x.fn), "?")] += ms.value / 60
            수[이름.get(getattr(x.fn, "value", x.fn), "?")] += 1
    전체 = sum(합.values())
    print(f"문맥 {C} 덩이 {M}: 커널 합 {전체:.3f} ms (실행 {len(L)})")
    for n, t in 합.most_common():
        print(f"   {n:24s} {t:8.3f} ms  ×{수[n] // 3}")
m.닫기()
