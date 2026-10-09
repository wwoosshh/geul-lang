"""꼬리 자르기(큰 판 열 [0, Nb) + 작은 판 열 [Nb, N), 실행 둘)가 나누지 않은 판과 비트까지 같은가 — 지금의 정수 KV 모듈(build/*.ptx)로,
XL 행렬곱 넷 × 끝손질 "" · 큰 판 둘 × 작은 판 모두. 인자: ROOT [q8_0|q4_0]"""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import os, ctypes
import numpy as np
ROOT = sys.argv[1]
fmt = sys.argv[2] if len(sys.argv) > 2 else "q8_0"
sys.path.insert(0, os.path.join(ROOT, "research", "gpu", "3단계"))
import 커널생성 as K
import 글gpt2 as G
K.KV = "정수"
Q4 = fmt == "q4_0"
dr = G.드라이버(); cu = dr.cu
mod = dr.모듈(open(os.path.join(ROOT, "build", f"커널XL{'Q4' if Q4 else 'Q8'}정수KV.ptx"), "rb").read())
판표 = K.정수판표(2, True)
fns = {판: dr.함수(mod, 판) for 판 in 판표}
P, I = ctypes.c_uint64, ctypes.c_int64
rng = np.random.default_rng(5)
run = lambda x: dr.확인(cu.cuLaunchKernel(x.fn, x.grid[0], x.grid[1], 1, x.block[0], x.block[1], 1, 0, None, x.args, None))
전체 = 0
for (M, Kd, N) in ((1024, 1600, 6400), (1024, 1600, 4800), (1024, 1600, 1600), (1024, 6400, 1600), (128, 6400, 1600), (469, 1600, 4800)):
    wb = Kd * N // (2 if Q4 else 1)
    big = dr.할당(wb + 4096); dr.올리기(big, rng.integers(0, 256, wb + 4096).astype(np.uint8))
    d0 = rng.integers(-128, 128, (M, Kd)).astype(np.int8); d1 = rng.integers(-64, 65, (M, Kd)).astype(np.int8)
    dig = dr.할당(2 * M * Kd + 4096); dr.올리기(dig, np.concatenate([d0.ravel(), d1.ravel()]).view(np.uint8))
    E = rng.integers(-3, 3, (Kd // 32) * ((M + 63) // 64 * 64))
    inf = dr.할당(E.size * 4 + 4096); dr.올리기(inf, (((137 + E) << 23) + 4194304).astype(np.int32))
    Np = (N + 63) // 64 * 64
    sc = dr.할당((Kd // 32) * Np * 2 + 4096); dr.올리기(sc, (rng.standard_normal((Kd // 32) * Np) * 0.01).astype(np.float16))
    bias = dr.할당(N * 4); dr.올리기(bias, (rng.standard_normal(N) * 0.1).astype(np.float32))
    out = dr.할당(M * N * 4)
    def 띄움(판, gx, gy, r0, c0):
        BM, BN, T = K.정수판모양(판)
        return G._띄움(fns[판], (gx, gy), (T, 1), [P(dig), P(inf), P(big), P(sc), P(bias), P(out), I(M), I(Kd), I(N), I(Np), I(r0), I(c0)])
    def 결과(xs):
        dr.올리기(out, np.full(M * N, np.nan, np.float32))
        for x in xs:
            run(x)
        dr.맞추기()
        return dr.내리기(out, np.empty(M * N, np.float32)).copy()
    BM, BN, T = K.정수판모양("정수깊은타일선형")
    기준 = 결과([띄움("정수깊은타일선형", (M + BM - 1) // BM, (N + BN - 1) // BN, 0, 0)])
    assert not np.isnan(기준).any()
    n시험 = 0
    for 큰 in ("정수세판타일선형", "정수타일선형", "정수깊은타일선형"):
        BM, BN, T = K.정수판모양(큰)
        gx, gy = (M + BM - 1) // BM, (N + BN - 1) // BN
        for ny in sorted({1, gy // 2, gy - 1}):
            if ny < 1 or ny >= gy:
                continue
            Nb = ny * BN
            for 작 in 판표:
                BMs, BNs, Ts = K.정수판모양(작)
                y = 결과([띄움(큰, gx, ny, 0, 0), 띄움(작, (M + BMs - 1) // BMs, (N - Nb + BNs - 1) // BNs, 0, Nb)])
                다른 = int(np.count_nonzero(y.view(np.uint32) != 기준.view(np.uint32)))
                assert 다른 == 0, (M, Kd, N, 큰, 작, Nb, 다른)
                n시험 += 1
    전체 += n시험
    print(f"{fmt} M {M} K {Kd} N {N}: 나눈 실행 {n시험} 가지 모두 나누지 않은 판과 같다", flush=True)
print("전체", 전체, "가지 — 다른 칸 0")
