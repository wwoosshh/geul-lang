"""13e 미리 보기(개발용): 합성 small 16384 프롬프트의 어텐션 한 층 — 12단계 차례 판(정수어텐션, 한 층 접기)과 두 층 차례 판(정수어텐션두층) ·
비트 대조(위치 1024 까지의 행은 같아야, 넘는 행은 달라도 된다 — 계약이 다르다). 인자: ROOT [n] [되풀이]"""
import sys
import os
import ctypes
import time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # 경고 · 오류도 UTF-8 로(한글 경로가 cp949 로 깨지지 않게)
ROOT = sys.argv[1]
n = int(sys.argv[2]) if len(sys.argv) > 2 else 16384
되풀이 = int(sys.argv[3]) if len(sys.argv) > 3 else 3
for d in ("10단계", "9단계", "8단계", "7단계", "6단계", "5단계", "4단계", "3단계"):
    sys.path.insert(0, os.path.join(ROOT, "research", "gpu", d))
import numpy as np         # noqa: E402
import torch               # noqa: E402,F401
import 글gpt2 as G         # noqa: E402
import 재기10 as K10       # noqa: E402
import gguf읽기 as GR      # noqa: E402
u64, i64 = ctypes.c_uint64, ctypes.c_int64
wq = GR.gpt2정수(K10.긴GGUF)
m = G.글GPT2(wq, KV형식="정수", 자리수=2, 최대행=n, 최대문장=1, 최대길이=n, 로짓행=16)
ids = [int(x) for x in np.random.default_rng(1).integers(0, 50257, n)]
m.토큰넣기(ids); m.계산(1, n, 0, 1); m.dr.맞추기()
cu = m.dr.cu
k = m.k
D = m.D
out = {nm: (m.dr.할당(2 * n * D), m.dr.할당(D // 32 * ((n + 63) // 64 * 64) * 4)) for nm in ("차례", "두층")}
KV = [u64(m.kc[0]), u64(m.vc[0]), u64(m.ke[0]), u64(m.ve[0])]
xs = {"차례": G._띄움(k["정수어텐션"], (m.NH, (n + 63) // 64), (128, 1),
                    [u64(m.자릿값q), u64(m.정보q)] + KV + [u64(out["차례"][1]), u64(out["차례"][0]), i64(n), i64(n), i64(0), i64(m.최대길이)]),
      "두층": G._띄움(k["정수어텐션두층"], (m.NH, (n + 63) // 64), (128, 1),
                    [u64(m.자릿값q), u64(m.정보q)] + KV + [u64(m.묶음칸), u64(out["두층"][1]), u64(out["두층"][0]), i64(n), i64(n), i64(0), i64(m.최대길이)])}
e0, e1 = ctypes.c_void_p(), ctypes.c_void_p()
cu.cuEventCreate(ctypes.byref(e0), 0); cu.cuEventCreate(ctypes.byref(e1), 0)


def 재기(x):
    run = lambda: cu.cuLaunchKernel(x.fn, x.grid[0], x.grid[1], 1, x.block[0], x.block[1], 1, 0, None, x.args, None)
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
        ts.append(ms.value * 1000 / 5)
    return sorted(ts)[3]


for nm, x in xs.items():
    cu.cuLaunchKernel(x.fn, x.grid[0], x.grid[1], 1, x.block[0], x.block[1], 1, 0, None, x.args, None)
m.dr.맞추기()
a = m.dr.내리기(out["차례"][0], np.empty(2 * n * D, np.int8)).reshape(2, n, D)
b = m.dr.내리기(out["두층"][0], np.empty(2 * n * D, np.int8)).reshape(2, n, D)
print(f"위치 1024 까지의 행: 다른 자리 {int((a[:, :1024] != b[:, :1024]).sum())}, 그 뒤 행: 다른 자리 {int((a[:, 1024:] != b[:, 1024:]).sum())} (계약이 달라 다를 수 있다)")
for r in range(되풀이):
    ts = {nm: 재기(x) for nm, x in xs.items()}
    print(f"[{r}] 차례 {ts['차례'] / 1000:.3f} ms  두층 {ts['두층'] / 1000:.3f} ms  ({ts['두층'] / ts['차례']:.4f}배; 12단계 기록 11.68, 13e 기준 ≤ {1.03 * 11.68:.2f})", flush=True)
print("오류 칸", m.오류칸())
m.닫기()
