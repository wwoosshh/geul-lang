"""12e 의 합성 긴 생성(문맥 C − 64 에서 64 토큰 — 토큰당 ms)을 글만(개발용; 공식은 재기14.py 가 llama.cpp 와). 인자: ROOT [C=102400] [되풀이=3]"""
import sys
import os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # 경고 · 오류도 UTF-8 로(한글 경로가 cp949 로 깨지지 않게)
ROOT = sys.argv[1]
C = int(sys.argv[2]) if len(sys.argv) > 2 else 102400
되풀이 = int(sys.argv[3]) if len(sys.argv) > 3 else 3
for d in ("10단계", "9단계", "8단계", "7단계", "6단계", "5단계", "4단계", "3단계"):
    sys.path.insert(0, os.path.join(ROOT, "research", "gpu", d))
import numpy as np         # noqa: E402
import torch               # noqa: E402,F401
import 재기4 as R          # noqa: E402
import 재기10 as K10       # noqa: E402
import gguf읽기 as GR      # noqa: E402
N = 64
wq = GR.gpt2정수(K10.긴GGUF)
ids = [int(x) for x in np.random.default_rng(1).integers(0, 50257, 102400)][:C]
e = R.글엔진(wq, KV형식="정수", 자리수=2, 최대행=C, 최대문장=1, 최대길이=C, 로짓행=16)
e.생성(ids[:-64], N)
for r in range(되풀이):
    t1 = np.median([e.잰_생성(ids[:-64], 1) for _ in range(3)])
    t64 = np.median([e.잰_생성(ids[:-64], N) for _ in range(3)])
    print(f"[{r}] 문맥 {C - 64}: 토큰당 {(t64 - t1) / (N - 1):.4f} ms (넣기+첫 토큰 {t1:.1f} ms)", flush=True)
print("오류 칸", e.m.오류칸())
e.m.닫기()
