"""생성 메가커널의 장벽 시각(블록 0)으로 단계마다의 시간 — 합성 긴 모델, 문맥 C. 인자: ROOT [C=100000]"""
import sys
import os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = sys.argv[1]
C = int(sys.argv[2]) if len(sys.argv) > 2 else 100000
for d in ("10단계", "9단계", "8단계", "7단계", "6단계", "5단계", "4단계", "3단계"):
    sys.path.insert(0, os.path.join(ROOT, "research", "gpu", d))
import numpy as np         # noqa: E402
import 글gpt2 as G         # noqa: E402
import 재기10 as K10       # noqa: E402
import gguf읽기 as GR      # noqa: E402
m = G.글GPT2(GR.gpt2정수(K10.긴GGUF), KV형식="정수", 자리수=2, 최대행=1024, 최대문장=1, 최대길이=102400, 로짓행=16)
m.판미리고르기()
rng = np.random.default_rng(1)
ids = [int(x) for x in rng.integers(0, 50257, C)]
for a in range(0, C, 1024):
    m.이어넣기(ids[a:a + 1024], a)
m.이어생성(ids[-1], C, 3)
m.시각재기 = 1
m.dr.확인(m.dr.cu.cuMemsetD8_v2(m.시각칸, 0, 8 * 70 * 1100))
m.이어생성(ids[-1], C, 3)          # 걸음 셋
t = m.dr.내리기(m.시각칸, np.zeros(8 * 70 * 1100 // 8, np.uint64)).astype(np.int64)
n = int(np.count_nonzero(t))
t = t[:n]
d = np.diff(t) / 1000.0              # µs
print("장벽 수", n, "걸음마다", (n - 1) / 3)
per = (n - 1) // 3
걸음 = d[:per * 3].reshape(3, per)
print("걸음 셋의 합 µs:", [round(float(x), 1) for x in 걸음.sum(1)])
층단계 = (per - 2) // 12 if per > 12 else per
print("걸음 하나의 장벽 사이(µs, 둘째 걸음):")
row = 걸음[1]
print(" ".join(f"{x:.1f}" for x in row[:20]), "…")
# 층마다 같은 꼴이면 단계별 평균
for 시작 in range(0, 3):
    pass
k = None
for cand in (4, 5, 6, 7):
    if (per - 2) % cand == 0 or (per - 1) % cand == 0 or per % cand == 0:
        k = cand
        break
print("주기 후보", k)
if k:
    body = row[1:1 + 12 * k] if len(row) >= 1 + 12 * k else row
    if len(body) >= 12 * k:
        b = body[:12 * k].reshape(12, k)
        print("단계마다(12 층 평균, µs):", [round(float(x), 1) for x in b.mean(0)], "층 합", round(float(b.sum()), 1))
m.닫기()
