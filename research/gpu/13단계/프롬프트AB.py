"""small 1024 프롬프트 시간을 코드 나무(ROOT)마다 — 12단계 나무와 13단계 나무를 번갈아 프로세스로 돌려 견준다(판정 뒤의 원인 보기).
12d 와 같은 재는 법(엔진을 만들고 데운 뒤 잰_프롬프트 일곱 번의 중앙값)에 고른 타일 판을 함께 적는다. 인자: ROOT 형식들(쉼표)"""
import os
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
ROOT = sys.argv[1]
형식들 = sys.argv[2].split(",") if len(sys.argv) > 2 else ["q8_0", "q4_0"]
for d in ("10단계", "9단계", "8단계", "7단계", "6단계", "5단계", "4단계", "3단계"):
    sys.path.insert(0, os.path.join(ROOT, "research", "gpu", d))
import numpy as np         # noqa: E402
import torch               # noqa: E402,F401
import 재기4 as R          # noqa: E402
import 재기9 as K9         # noqa: E402
import 재기10 as K10       # noqa: E402
G = R.G
tk = G.토크나이저(K9.모델폴더("small"))
긴 = (tk.나누기(R.문장들[1]) * 40)[:1024]
for fmt in 형식들:
    e = K10.글엔진("small", fmt)
    for _ in range(3):
        e.프롬프트(긴)
    ts = sorted(e.잰_프롬프트(긴) for _ in range(7))
    판 = {f"{k[3]}×{k[4]}{k[6] if len(k) > 6 else ''}": v for k, v in sorted(e.m._고른판.items(), key=str) if isinstance(k, tuple) and len(k) > 4 and k[0] == 1024} \
        if hasattr(e.m, "_고른판") else {}
    print(f"{os.path.basename(ROOT.rstrip('/'))} {fmt}: 중앙값 {ts[3]:.3f} ms (최소 {ts[0]:.3f}, 최대 {ts[-1]:.3f}) 판 {판}", flush=True)
    e.m.닫기()
    K9.비우기()
