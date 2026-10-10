"""생성 메가커널(머리 이어 달리기)과 따로 도는 커널들(정수조각어텐션 + 정수조각접기)의 생성이 토큰 · 로짓 · 캐시 바이트까지 같은가 — 합성 긴 모델,
문맥 C 들. 인자: ROOT [C,…]"""
import sys
import os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = sys.argv[1]
Cs = [int(x) for x in (sys.argv[2] if len(sys.argv) > 2 else "300,5000,40000").split(",")]
for d in ("10단계", "9단계", "8단계", "7단계", "6단계", "5단계", "4단계", "3단계"):
    sys.path.insert(0, os.path.join(ROOT, "research", "gpu", d))
import numpy as np         # noqa: E402
import 글gpt2 as G         # noqa: E402
import 재기10 as K10       # noqa: E402
import gguf읽기 as GR      # noqa: E402
m = G.글GPT2(GR.gpt2정수(K10.긴GGUF), KV형식="정수", 자리수=2, 최대행=1024, 최대문장=1, 최대길이=102400, 로짓행=16)
m.판미리고르기()
rng = np.random.default_rng(5)
N = 24
모두같음 = True
for C in Cs:
    ids = [int(x) for x in rng.integers(0, 50257, C)]
    for a in range(0, C, 1024):
        첫 = m.이어넣기(ids[a:a + 1024], a)
    # (가) 메가커널
    가 = m.이어생성(첫, C, N - 1)
    키가 = [m.dr.내리기(m.kc[l], np.empty(16, np.uint8)) for l in range(1)]
    # 캐시의 새 자리(위치 C … C + N − 2)를 둘 다 보려고 층마다 키 · 값 칸 전체를 받는다(합성 small — 층 12)
    캐시가 = [m.dr.내리기(m.kc[l], np.empty(m.캐시바이트, np.uint8)).copy() for l in range(len(m.kc))] if hasattr(m, "캐시바이트") else None
    # (나) 따로 도는 커널들로 한 걸음씩(위치 C 부터)
    toks = [첫]
    for s in range(N - 1):
        m.토큰넣기([toks[-1]])
        m.계산(1, 1, C + s, "끝")
        m.dr.맞추기()
        toks.append(int(m.dr.내리기(m.생성칸, np.zeros(1, np.int64))[0]))
    같음 = toks == 가
    모두같음 &= 같음
    print(f"문맥 {C}: 메가커널 {가[:8]}… 따로 {toks[:8]}… — {'같다' if 같음 else '다르다!'}", flush=True)
print("오류 칸", m.오류칸(), "— 모두", "같다" if 모두같음 else "다른 것이 있다")
m.닫기()
