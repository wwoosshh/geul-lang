"""긴 문맥의 덩이 넣기 시간 — 글만(개발용; 공식 13c 는 재기14.py 가 llama.cpp 와 번갈아): 합성 긴 모델, 문맥을 1024 덩이로 C 까지 채운 뒤 덩이
m 을 세 번(문맥은 m 씩 는다), 중앙값 ms. 인자: ROOT [C들] [m들] [묶음판 1|0]"""
import sys
import os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # 경고 · 오류도 UTF-8 로(한글 경로가 cp949 로 깨지지 않게)
ROOT = sys.argv[1]
Cs = [int(x) for x in (sys.argv[2] if len(sys.argv) > 2 else "8192,32768,65536,98304").split(",")]
ms = [int(x) for x in (sys.argv[3] if len(sys.argv) > 3 else "16,64,128,256,512,1024").split(",")]
묶음판 = (sys.argv[4] if len(sys.argv) > 4 else "1") == "1"
for d in ("10단계", "9단계", "8단계", "7단계", "6단계", "5단계", "4단계", "3단계"):
    sys.path.insert(0, os.path.join(ROOT, "research", "gpu", d))
import numpy as np         # noqa: E402
import torch               # noqa: E402,F401
import 재기4 as R          # noqa: E402
import 재기10 as K10       # noqa: E402
import gguf읽기 as GR      # noqa: E402
wq = GR.gpt2정수(K10.긴GGUF)
글 = R.글엔진(wq, KV형식="정수", 자리수=2, 최대행=1024, 최대문장=1, 최대길이=102400, 로짓행=16)
글.m.판미리고르기()
글.m.묶음판쓰기 = 묶음판
rng = np.random.default_rng(13)
끝 = 0
위치 = 0
처음 = True
for C in Cs:
    while 위치 + 1024 <= C:
        새 = [int(x) for x in rng.integers(0, 50257, 1023)]
        r = 글.대화([[끝] + 새], 1, 처음=처음)[0]
        끝 = r["끝토큰"]
        처음 = False
        위치 += 1024
    for m in ms:
        if 위치 + 3 * m + 8 > 102400:
            break
        ts = []
        for 번 in range(3):
            새 = [int(x) for x in rng.integers(0, 50257, m - 1)]
            r = 글.대화([[끝] + 새], 1, 처음=False)[0]
            끝 = r["끝토큰"]
            ts.append(r["넣기 ms"])
            위치 += m
        print(f"문맥 {위치:6d} 덩이 {m:5d}: 글 {np.median(ts):8.2f} ms  ({' '.join(f'{t:.2f}' for t in ts)})", flush=True)
print("오류 칸", 글.m.오류칸())
글.m.닫기()
