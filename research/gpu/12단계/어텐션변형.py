"""정수어텐션의 시간 — 어텐션변형(값과 상관없는 것만: "읽기변환" = 11단계까지의 정수→실수 변환)마다, 합성 긴 모델의 프롬프트 n 토큰(위치 0 부터).
모듈 파일(커널Q8정수KV.gl)을 잠시 바꾸고 끝에 되돌린다. 인자: ROOT n 변형들(쉼표, 기본은 "기본")"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = sys.argv[1]
n = int(sys.argv[2])
변형들 = [frozenset() if v == "기본" else frozenset(v.split("+")) for v in sys.argv[3].split(",")]
for d in ("10단계", "9단계", "8단계", "7단계", "6단계", "5단계", "4단계", "3단계"):
    sys.path.insert(0, os.path.join(ROOT, "research", "gpu", d))
import numpy as np
import 커널생성 as K
import 글gpt2 as G
import 재기10 as K10
import gguf읽기 as GR
경로 = os.path.join(ROOT, "research", "gpu", "3단계", "커널Q8정수KV.gl")
원본 = open(경로, encoding="utf-8").read()
wq = GR.gpt2정수(K10.긴GGUF)
ids = [int(x) for x in np.random.default_rng(1).integers(0, 50257, n)]
try:
    for 변형 in 변형들:
        K.어텐션변형 = 변형
        open(경로, "w", encoding="utf-8", newline="\n").write(K.source(*K.모듈들["커널Q8정수KV.gl"]))
        m = G.글GPT2(wq, KV형식="정수", 자리수=2, 최대행=n, 최대문장=1, 최대길이=n, 로짓행=16)
        m.토큰넣기(ids); m.계산(1, n, 0, 1); m.dr.맞추기()
        ts = [K10.어텐션시간us(m, n) for _ in range(3)]
        print(f"{'+'.join(sorted(변형)) or '기본'}: 정수어텐션 {n} — {[round(t, 1) for t in ts]} µs", flush=True)
        m.닫기()
finally:
    K.어텐션변형 = frozenset()
    open(경로, "w", encoding="utf-8", newline="\n").write(원본)
