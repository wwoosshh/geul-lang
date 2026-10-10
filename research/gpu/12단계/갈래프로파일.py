"""ncu 대상: 문맥 C 의 캐시(무작위)로 덩이 m 의 정수어텐션갈래 · 정수어텐션을 한 번씩 cuProfilerStart/Stop 사이에. 인자: ROOT [C=32768] [m=16]"""
import sys, os, ctypes
ROOT = sys.argv[1]
C = int(sys.argv[2]) if len(sys.argv) > 2 else 32768
M = int(sys.argv[3]) if len(sys.argv) > 3 else 16
for d in ("10단계", "9단계", "8단계", "7단계", "6단계", "5단계", "4단계", "3단계"):
    sys.path.insert(0, os.path.join(ROOT, "research", "gpu", d))
import numpy as np
import 글gpt2 as G
import 재기10 as K10
import gguf읽기 as GR
u64, i64 = ctypes.c_uint64, ctypes.c_int64
m = G.글GPT2(GR.gpt2정수(K10.긴GGUF), KV형식="정수", 자리수=2, 최대행=1024, 최대문장=1, 최대길이=102400, 로짓행=16)
dr, D, NH, 최대길이 = m.dr, m.D, m.NH, m.최대길이
cu = dr.cu
k = m.k


def zero(nb):
    p = dr.할당(nb)
    dr.확인(cu.cuMemsetD8_v2(u64(p), 0, ctypes.c_size_t(nb)))
    return p


def run(x):
    r = cu.cuLaunchKernel(x.fn, x.grid[0], x.grid[1], 1, x.block[0], x.block[1], 1, 0, None, x.args, None)
    assert r == 0, r


n총 = C + M
rng = np.random.default_rng(21)
입력 = (rng.standard_normal((n총, 3 * D)) * rng.uniform(0.3, 3.0, (n총, 1))).astype(np.float32)
g입력 = dr.할당(입력.nbytes); dr.올리기(g입력, 입력)
키칸, 값칸 = zero(NH * 2 * 최대길이 * 64), zero(NH * 최대길이 * 128)
키지수, 값지수 = zero(NH * 최대길이 * 2), zero(NH * 최대길이 * 2)
KV = [u64(키칸), u64(값칸), u64(키지수), u64(값지수)]
덩 = 32768
자q큰, 정q큰 = zero(2 * 덩 * D), zero(D // 32 * 덩 * 4)
for a in range(0, n총, 덩):
    n = min(덩, n총 - a)
    run(G._띄움(k["KV정수로"], ((3 * D // 32 + 31) // 32, n), (256, 1), [u64(g입력 + a * 3 * D * 4), u64(자q큰), u64(정q큰)] + KV + [i64(n), i64(n), i64(a), i64(최대길이)]))
폭 = (M + 63) // 64 * 64
자q, 정q = zero(2 * M * D), zero(D // 32 * 폭 * 4)
run(G._띄움(k["KV정수로"], ((3 * D // 32 + 31) // 32, M), (256, 1), [u64(g입력 + C * 3 * D * 4), u64(자q), u64(정q)] + KV + [i64(M), i64(M), i64(C), i64(최대길이)]))
자, 정 = zero(2 * M * D), zero(D // 32 * 폭 * 4)
xs = [G._띄움(k["정수어텐션갈래"], (NH, (M + 15) // 16), (256, 1), [u64(자q), u64(정q)] + KV + [u64(정), u64(자), i64(M), i64(M), i64(C), i64(최대길이)]),
      G._띄움(k["정수어텐션"], (NH, (M + 63) // 64), (128, 1), [u64(자q), u64(정q)] + KV + [u64(정), u64(자), i64(M), i64(M), i64(C), i64(최대길이)])]
for x in xs:
    run(x)
dr.맞추기()
cu.cuProfilerStart()
for x in xs:
    run(x)
dr.맞추기()
cu.cuProfilerStop()
print("끝")
m.닫기()
