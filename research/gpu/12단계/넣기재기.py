"""긴 문맥에서 덩이 넣기 시간 — 합성 긴 모델(small 모양, 위치 102400), 글과 llama.cpp 를 번갈아: 문맥을 1024 덩이로 C 까지 채운 뒤 덩이
m 개를 이어 넣는(생성 없이 첫 토큰까지) 시간을 m 마다 세 번(문맥은 m 씩 는다), 세 번의 중앙값. 기록은 build/12단계작업/넣기재기.json.
인자: ROOT [C들=8192,32768,65536,98304] [m들=16,64,256,512,1024]"""
import sys
import os
import json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = sys.argv[1]
os.makedirs(os.path.join(ROOT, "build", "12단계작업"), exist_ok=True)       # 결과 json 은 git 밖에
Cs = [int(x) for x in (sys.argv[2] if len(sys.argv) > 2 else "8192,32768,65536,98304").split(",")]
ms = [int(x) for x in (sys.argv[3] if len(sys.argv) > 3 else "16,64,256,512,1024").split(",")]
for d in ("10단계", "9단계", "8단계", "7단계", "6단계", "5단계", "4단계", "3단계"):
    sys.path.insert(0, os.path.join(ROOT, "research", "gpu", d))
import numpy as np         # noqa: E402
import torch               # noqa: E402,F401
import 재기4 as R          # noqa: E402
import 재기10 as K10       # noqa: E402
import gguf읽기 as GR      # noqa: E402
일 = R.일꾼()
wq = GR.gpt2정수(K10.긴GGUF)
글 = R.글엔진(wq, KV형식="정수", 자리수=2, 최대행=1024, 최대문장=1, 최대길이=102400, 로짓행=16)
글.m.판미리고르기()
라 = R.라마엔진(일, "llama.cpp q8_0", K10.긴GGUF, n_ctx=102400, n_batch=1024)
rng = np.random.default_rng(13)
끝 = {"글": 0, "라": 0}
위치 = 0
처음 = True
기록 = []
for C in Cs:
    while 위치 + 1024 <= C:
        새 = [int(x) for x in rng.integers(0, 50257, 1023)]
        for 이름, e in (("글", 글), ("라", 라)):
            r = e.대화([[끝[이름]] + 새], 1, 처음=처음)[0]
            끝[이름] = r["끝토큰"]
        처음 = False
        위치 += 1024
    for m in ms:
        if 위치 + 3 * m + 8 > 102400:
            break
        for 번 in range(3):
            새 = [int(x) for x in rng.integers(0, 50257, m - 1)]
            줄 = {"문맥": 위치, "덩이": m, "번": 번}
            for 이름, e in (("글", 글), ("라", 라)):
                r = e.대화([[끝[이름]] + 새], 1, 처음=False)[0]
                끝[이름] = r["끝토큰"]
                줄[이름] = round(r["넣기 ms"], 3)
            위치 += m
            기록.append(줄)
        마지막 = 기록[-3:]
        print(f"문맥 {위치:6d} 덩이 {m:5d}: 글 {np.median([x['글'] for x in 마지막]):8.2f} ms  llama.cpp {np.median([x['라'] for x in 마지막]):8.2f} ms", flush=True)
print("오류 칸", 글.m.오류칸())
json.dump(기록, open(os.path.join(ROOT, "build", "12단계작업", "넣기재기.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
라.닫기(); 글.m.닫기(); 일.끝()
