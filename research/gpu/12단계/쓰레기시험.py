"""대화의 차례 넣기 시간에 파이썬 쓰레기 수거(gc)가 끼는가 — 합성 긴 모델, 무작위 덩이(16~1024)·생성(16~128) 차례를 문맥 3만까지,
차례마다 넣기 ms 와 그 사이 gc 의 세대 · 시간. 인자: ROOT [최대=30000]"""
import sys, os, gc, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = sys.argv[1]
최대 = int(sys.argv[2]) if len(sys.argv) > 2 else 30000
for d in ("10단계", "9단계", "8단계", "7단계", "6단계", "5단계", "4단계", "3단계"):
    sys.path.insert(0, os.path.join(ROOT, "research", "gpu", d))
import numpy as np
import 재기4 as R
import 재기10 as K10
import gguf읽기 as GR
기록gc = []
_시작 = {}


def cb(phase, info):
    if phase == "start":
        _시작["t"] = time.perf_counter()
    else:
        기록gc.append((info["generation"], (time.perf_counter() - _시작["t"]) * 1000, info.get("collected", 0)))


gc.callbacks.append(cb)
wq = GR.gpt2정수(K10.긴GGUF)
글 = R.글엔진(wq, KV형식="정수", 자리수=2, 최대행=1024, 최대문장=1, 최대길이=102400, 로짓행=16)
글.m.판미리고르기()
print("gc 객체 수(시작)", len(gc.get_objects()), "임계", gc.get_threshold(), flush=True)
rng = np.random.default_rng(12)
위치, 끝, 차례 = 0, 0, 0
while True:
    덩이길이, n = int(rng.integers(16, 1025)), int(rng.integers(16, 129))
    if 위치 + 덩이길이 + n > 최대:
        break
    새 = [int(x) for x in rng.integers(0, 50257, 덩이길이 - 1)]
    k = len(기록gc)
    r = 글.대화([[끝] + 새], n, 처음=(차례 == 0))[0]
    끝 = r["끝토큰"]
    gcs = 기록gc[k:]
    큰 = [g for g in gcs if g[1] > 1.0]
    print(f"차례 {차례:3d} 문맥 {위치:6d} 덩이 {덩이길이:4d}: 넣기 {r['넣기 ms']:7.2f} ms 생성 {r['생성 ms']:7.1f} ms — gc {len(gcs)} 번" +
          (f", 1 ms 넘는 것 {[(g[0], round(g[1], 1)) for g in 큰]}" if 큰 else ""), flush=True)
    위치 += 덩이길이 + n - 1
    차례 += 1
print("gc 객체 수(끝)", len(gc.get_objects()))
gen2 = [g for g in 기록gc if g[0] == 2]
print("세대 2 수거", len(gen2), "시간 ms", [round(g[1], 1) for g in gen2])
글.m.닫기()
