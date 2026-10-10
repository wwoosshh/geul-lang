"""12단계 판정 전에 잰 것 — 지속 사용(문맥이 자라는 대화): 합성 긴 모델(small 모양, 위치 102400)로 차례마다 덩이 1024 토큰(앞 차례의
마지막 생성 토큰 + 새 토큰 1023)을 이어 넣고 64 토큰을 생성. 글과 llama.cpp 를 차례마다 번갈아. 인자: ROOT [최대문맥=32768] [그래프=1]"""
import sys
import os
import json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = sys.argv[1]
os.makedirs(os.path.join(ROOT, "build", "12단계작업"), exist_ok=True)       # 결과 json 은 git 밖에
최대 = int(sys.argv[2]) if len(sys.argv) > 2 else 32768
그래프 = (sys.argv[3] if len(sys.argv) > 3 else "1") == "1"
무작위 = len(sys.argv) > 4 and sys.argv[4] == "무작위"
for d in ("10단계", "9단계", "8단계", "7단계", "6단계", "5단계", "4단계", "3단계"):
    sys.path.insert(0, os.path.join(ROOT, "research", "gpu", d))
import numpy as np         # noqa: E402
import torch               # noqa: E402,F401
import 재기4 as R          # noqa: E402
import 재기10 as K10       # noqa: E402
import gguf읽기 as GR      # noqa: E402
덩이길이, N = 1024, 64
일 = R.일꾼()
wq = GR.gpt2정수(K10.긴GGUF)
글 = R.글엔진(wq, KV형식="정수", 자리수=2, 최대행=덩이길이, 최대문장=1, 최대길이=102400, 로짓행=16)
글.m.그래프쓰기 = 그래프
import time as _t
_t0 = _t.perf_counter(); 글.m.판미리고르기(); print('판미리고르기', round((_t.perf_counter() - _t0) * 1000), 'ms', flush=True)
라 = R.라마엔진(일, "llama.cpp q8_0", K10.긴GGUF, n_ctx=102400, n_batch=덩이길이)
rng = np.random.default_rng(12)
끝 = {"글": 0, "라": 0}
기록 = []
차례 = 0
위치 = 0
while 위치 + 덩이길이 + N <= 최대:
    if 무작위:
        덩이길이, N = int(rng.integers(16, 1025)), int(rng.integers(16, 129))
    새 = [int(x) for x in rng.integers(0, 50257, 덩이길이 - 1)]
    줄 = {"차례": 차례, "앞 문맥": 위치, "덩이": 덩이길이, "생성": N}
    for 이름, e in (("글", 글), ("라", 라)):
        r = e.대화([[끝[이름]] + 새], N, 처음=(차례 == 0))[0]
        끝[이름] = r["끝토큰"]
        줄[이름] = {"넣기 ms": round(r["넣기 ms"], 3), "토큰당 ms": round(r["생성 ms"] / (N - 1), 4), "끝토큰": r["끝토큰"]}
    위치 = 위치 + 덩이길이 + N - 1
    기록.append(줄)
    print(json.dumps(줄, ensure_ascii=False), flush=True)
    차례 += 1
print("오류 칸", 글.m.오류칸())
json.dump(기록, open(os.path.join(ROOT, "build", "12단계작업", f"대화12_{최대}_{int(그래프)}{'_무작위' if 무작위 else ''}.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
라.닫기(); 글.m.닫기(); 일.끝()
