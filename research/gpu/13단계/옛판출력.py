"""13a(1): 위치 1024 이하 엔진(실제 GPT-2)의 출력을 npz 로 — 평가글 469 행의 로짓 전부와, 그 469 토큰에서 이어 64 걸음 생성(토큰 · 걸음마다의
로짓, 생성 메가커널). 코드 나무(ROOT)를 인자로 받아 그 나무의 글gpt2 · 모듈로 계산한다 — 12단계(커밋 2256b39 를 풀어 둔 나무, 재기14.py 가
만든다)와 13단계를 같은 스크립트로. 실행: build/감사venv/Scripts/python -I 옛판출력.py ROOT 출력.npz small,XL q8_0,q4_0"""
import os
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # 경고 · 오류도 UTF-8 로(한글 경로가 cp949 로 깨지지 않게)
ROOT, 출력 = sys.argv[1], sys.argv[2]
크기들 = sys.argv[3].split(",") if len(sys.argv) > 3 else ["small", "XL"]
형식들 = sys.argv[4].split(",") if len(sys.argv) > 4 else ["q8_0", "q4_0"]
for d in ("10단계", "9단계", "8단계", "7단계", "6단계", "5단계", "4단계", "3단계"):
    sys.path.insert(0, os.path.join(ROOT, "research", "gpu", d))
import numpy as np         # noqa: E402
import torch               # noqa: E402,F401
import 재기4 as R          # noqa: E402
import 재기 as R3          # noqa: E402
import 재기9 as K9         # noqa: E402
import 재기10 as K10       # noqa: E402
G = R.G
평가글 = open(os.path.join(ROOT, "research", "gpu", "5단계", "평가글.txt"), encoding="utf-8").read()
out = {}
for 크기 in 크기들:
    tk = G.토크나이저(K9.모델폴더(크기))
    평가 = tk.나누기(평가글)[:1024]
    for fmt in 형식들:
        e = K10.글엔진(크기, fmt)
        m = e.m
        로짓 = R3.글로짓(m, [평가[:469]], "한번에")[0]
        toks = m.생성(평가[:469], 64, 기록=True)
        기록 = m.기록된로짓(64)
        out[f"{크기} {fmt} 로짓"] = np.asarray(로짓, np.float32)
        out[f"{크기} {fmt} 생성"] = np.asarray(toks, np.int64)
        out[f"{크기} {fmt} 생성 로짓"] = np.asarray(기록, np.float32)
        out[f"{크기} {fmt} 오류 칸"] = np.asarray(m.오류칸())
        print(크기, fmt, "로짓", 로짓.shape, "생성", toks[:8], "…", flush=True)
        m.닫기()
        del e, m
        K9.비우기()
np.savez(출력, **out)
print("씀", 출력)
