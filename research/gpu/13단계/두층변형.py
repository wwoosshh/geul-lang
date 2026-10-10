"""정수어텐션두층의 변형(재기 실험 — 값이 틀리는 것도: 두층접기없음 · 두층읽기없음)마다 합성 small n 프롬프트의 어텐션 한 층 시간. 모듈 파일을
잠시 바꾸고 끝에 되돌린다. 인자: ROOT n 변형들(쉼표, 기본은 "기본")"""
import sys
import os
import ctypes
import time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # 경고 · 오류도 UTF-8 로(한글 경로가 cp949 로 깨지지 않게)
ROOT = sys.argv[1]
n = int(sys.argv[2])
변형들 = [frozenset() if v == "기본" else frozenset(v.split("+")) for v in sys.argv[3].split(",")]
for d in ("10단계", "9단계", "8단계", "7단계", "6단계", "5단계", "4단계", "3단계"):
    sys.path.insert(0, os.path.join(ROOT, "research", "gpu", d))
import numpy as np         # noqa: E402
import torch               # noqa: E402,F401
import 커널생성 as K       # noqa: E402
import 글gpt2 as G         # noqa: E402
import 재기10 as K10       # noqa: E402
import gguf읽기 as GR      # noqa: E402
u64, i64 = ctypes.c_uint64, ctypes.c_int64
경로 = os.path.join(ROOT, "research", "gpu", "3단계", "커널Q8정수KV.gl")
원본 = open(경로, encoding="utf-8").read()
wq = GR.gpt2정수(K10.긴GGUF)
ids = [int(x) for x in np.random.default_rng(1).integers(0, 50257, n)]
try:
    for 변형 in 변형들:
        K.어텐션변형 = 변형
        open(경로, "w", encoding="utf-8", newline="\n").write(K.source(*K.모듈들["커널Q8정수KV.gl"]))
        m = G.글GPT2(wq, KV형식="정수", 자리수=2, 최대행=n, 최대문장=1, 최대길이=n, 로짓행=16)
        K.어텐션변형 = frozenset()
        open(경로, "w", encoding="utf-8", newline="\n").write(원본)     # 계산은 기본 모듈과 같은 캐시를 쓰려고 — 아래 재기는 이 엔진의 커널
        m.갈래쓰기 = False
        m.토큰넣기(ids); m.계산(1, n, 0, 1); m.dr.맞추기()
        cu = m.dr.cu
        KV = [u64(m.kc[0]), u64(m.vc[0]), u64(m.ke[0]), u64(m.ve[0])]
        x = G._띄움(m.k["정수어텐션두층"], (m.NH, (n + 63) // 64), (128, 1),
                   [u64(m.자릿값q), u64(m.정보q)] + KV + [u64(m.묶음칸), u64(m.정보), u64(m.자릿값), i64(n), i64(n), i64(0), i64(m.최대길이)])
        y = G._띄움(m.k["정수어텐션"], (m.NH, (n + 63) // 64), (128, 1),
                   [u64(m.자릿값q), u64(m.정보q)] + KV + [u64(m.정보), u64(m.자릿값), i64(n), i64(n), i64(0), i64(m.최대길이)])
        e0, e1 = ctypes.c_void_p(), ctypes.c_void_p()
        cu.cuEventCreate(ctypes.byref(e0), 0); cu.cuEventCreate(ctypes.byref(e1), 0)
        res = {}
        for _ in range(2):
            for nm, z in (("차례", y), ("두층", x)):
                run = lambda: cu.cuLaunchKernel(z.fn, z.grid[0], z.grid[1], 1, z.block[0], z.block[1], 1, 0, None, z.args, None)
                t0 = time.perf_counter()
                while time.perf_counter() - t0 < 0.3:
                    run()
                m.dr.맞추기()
                ts = []
                for _ in range(7):
                    cu.cuEventRecord(e0, None)
                    for _ in range(5):
                        run()
                    cu.cuEventRecord(e1, None); cu.cuEventSynchronize(e1)
                    ms = ctypes.c_float(); cu.cuEventElapsedTime(ctypes.byref(ms), e0, e1)
                    ts.append(ms.value / 5)
                res[nm] = sorted(ts)[3]
        regs = ctypes.c_int(); cu.cuFuncGetAttribute(ctypes.byref(regs), 4, m.k["정수어텐션두층"])
        print(f"{'+'.join(sorted(변형)) or '기본'} (레지스터 {regs.value}): 차례 {res['차례']:.3f} ms  두층 {res['두층']:.3f} ms  ({res['두층'] / res['차례']:.4f}배)", flush=True)
        m.닫기()
finally:
    K.어텐션변형 = frozenset()
    open(경로, "w", encoding="utf-8", newline="\n").write(원본)
