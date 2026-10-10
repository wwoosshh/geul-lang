"""생성 메가커널의 긴 문맥 어텐션 변형(값이 달라진다 — 재는 데만)마다 층의 어텐션 단계 시간(장벽 시각). 인자: ROOT C 변형들(쉼표, 변형 안은 +)
예: 100000 "기본,접기없음,조각쓰기없음+접기없음,아홉". 모듈 파일(커널Q8정수KV.gl)을 잠시 바꾸고 끝에 되돌린다."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = sys.argv[1]
C = int(sys.argv[2])
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
try:
    for 변형 in 변형들:
        K.메가변형 = frozenset(x for x in 변형 if x not in ("조각미리", "신호뒤"))
        K.조각미리 = "조각미리" in 변형
        K.신호뒤 = "신호뒤" in 변형
        open(경로, "w", encoding="utf-8", newline="\n").write(K.source(*K.모듈들["커널Q8정수KV.gl"]))
        m = G.글GPT2(wq, KV형식="정수", 자리수=2, 최대행=1024, 최대문장=1, 최대길이=102400, 로짓행=16)
        rng = np.random.default_rng(1)
        ids = [int(x) for x in rng.integers(0, 50257, C)]
        for a in range(0, C, 1024):
            m.이어넣기(ids[a:a + 1024], a)
        m.이어생성(ids[-1], C, 3)
        m.시각재기 = 1
        결과 = []
        for _ in range(3):
            m.dr.확인(m.dr.cu.cuMemsetD8_v2(m.시각칸, 0, 8 * 70 * 1100))
            m.이어생성(ids[-1], C, 3)
            t = m.dr.내리기(m.시각칸, np.zeros(8 * 70 * 1100 // 8, np.uint64)).astype(np.int64)
            t = t[:int(np.count_nonzero(t))]
            d = np.diff(t) / 1000.0
            긴 = d[d > 100]
            결과.append((float(np.median(긴)), float(d.sum() / 3)))
        print(f"{'+'.join(sorted(변형)) or '기본'}: 어텐션 단계 중앙값 {np.median([r[0] for r in 결과]):.1f} µs, 걸음 {np.median([r[1] for r in 결과]):.0f} µs", flush=True)
        m.닫기()
finally:
    open(경로, "w", encoding="utf-8", newline="\n").write(원본)
