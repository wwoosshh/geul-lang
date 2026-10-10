"""정수어텐션(차례 판)과 정수어텐션갈래(갈래 판)의 출력(자리 둘 · 정보)이 비트까지 같은가, 그리고 시간 — 무작위 q · k · v 로 캐시를 위치 0 … C+m−1
까지 채우고(KV정수로) 덩이 m 행(위치 C …)의 어텐션. 인자: ROOT [C들] [m들]"""
import sys, os, ctypes, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = sys.argv[1]
Cs = [int(x) for x in (sys.argv[2] if len(sys.argv) > 2 else "0,100,1000,8192,32768,98000").split(",")]
ms = [int(x) for x in (sys.argv[3] if len(sys.argv) > 3 else "5,16,17,33,64,100,256,512").split(",")]
for d in ("10단계", "9단계", "8단계", "7단계", "6단계", "5단계", "4단계", "3단계"):
    sys.path.insert(0, os.path.join(ROOT, "research", "gpu", d))
import numpy as np
import 글gpt2 as G
import 커널생성 as KG
import 재기10 as K10
import gguf읽기 as GR
u64, i64 = ctypes.c_uint64, ctypes.c_int64
m = G.글GPT2(GR.gpt2정수(K10.긴GGUF), KV형식="정수", 자리수=2, 최대행=1024, 최대문장=1, 최대길이=102400, 로짓행=16)
dr, D, NH, 최대길이 = m.dr, m.D, m.NH, m.최대길이
cu = dr.cu
k = dict(m.k)
k["정수어텐션갈래"] = dr.함수(m.mods[1], "정수어텐션갈래")
for nm in ("정수어텐션", "정수어텐션갈래"):
    regs, loc = ctypes.c_int(), ctypes.c_int()
    cu.cuFuncGetAttribute(ctypes.byref(regs), 4, k[nm]); cu.cuFuncGetAttribute(ctypes.byref(loc), 3, k[nm])
    print(f"{nm}: 레지스터 {regs.value}, 지역 메모리 {loc.value} B")


def zero(nb):
    p = dr.할당(nb)
    dr.확인(cu.cuMemsetD8_v2(u64(p), 0, ctypes.c_size_t(nb)))
    return p


def run(x):
    r = cu.cuLaunchKernel(x.fn, x.grid[0], x.grid[1], 1, x.block[0], x.block[1], 1, 0, None, x.args, None)
    assert r == 0, r


최대행 = max(Cs) + max(ms)
rng = np.random.default_rng(21)
입력 = (rng.standard_normal((최대행, 3 * D)) * rng.uniform(0.3, 3.0, (최대행, 1))).astype(np.float32)
g입력 = dr.할당(입력.nbytes); dr.올리기(g입력, 입력)
키칸, 값칸 = zero(NH * 2 * 최대길이 * 64), zero(NH * 최대길이 * 128)
키지수, 값지수 = zero(NH * 최대길이 * 2), zero(NH * 최대길이 * 2)
KV = [u64(키칸), u64(값칸), u64(키지수), u64(값지수)]
덩큰 = 32768                                   # 격자 y 의 한도(65535) 안 — 덩이마다 캐시만 채운다
자q큰, 정q큰 = zero(2 * 덩큰 * D), zero(D // 32 * 덩큰 * 4)
for a in range(0, 최대행, 덩큰):
    n = min(덩큰, 최대행 - a)
    run(G._띄움(k["KV정수로"], ((3 * D // 32 + 31) // 32, n), (256, 1),
                [u64(g입력 + a * 3 * D * 4), u64(자q큰), u64(정q큰)] + KV + [i64(n), i64(n), i64(a), i64(최대길이)]))
dr.맞추기()
M최대 = max(ms)
폭 = (M최대 + 63) // 64 * 64
자q, 정q = zero(2 * M최대 * D), zero(D // 32 * 폭 * 4)
출 = {nm: (zero(2 * M최대 * D), zero(D // 32 * 폭 * 4)) for nm in ("정수어텐션", "정수어텐션갈래")}
e0, e1 = ctypes.c_void_p(), ctypes.c_void_p()
cu.cuEventCreate(ctypes.byref(e0), 0); cu.cuEventCreate(ctypes.byref(e1), 0)
모두같음 = True
for C in Cs:
    for M in ms:
        정보폭 = (M + 63) // 64 * 64
        # 덩이의 q 자리(행 0 … M−1 = 위치 C …) — 캐시는 같은 값으로 다시 쓴다
        run(G._띄움(k["KV정수로"], ((3 * D // 32 + 31) // 32, M), (256, 1),
                    [u64(g입력 + C * 3 * D * 4), u64(자q), u64(정q)] + KV + [i64(M), i64(M), i64(C), i64(최대길이)]))
        띄움 = {}
        for nm, (Q, T) in (("정수어텐션", (64, 128)), ("정수어텐션갈래", (16, 32 * KG.갈래워프))):
            자, 정 = 출[nm]
            dr.확인(cu.cuMemsetD8_v2(u64(자), 0x5A, ctypes.c_size_t(2 * M최대 * D)))
            dr.확인(cu.cuMemsetD8_v2(u64(정), 0x5A, ctypes.c_size_t(D // 32 * 폭 * 4)))
            x = G._띄움(k[nm], (NH, (M + Q - 1) // Q), (T, 1), [u64(자q), u64(정q)] + KV + [u64(정), u64(자), i64(M), i64(M), i64(C), i64(최대길이)])
            띄움[nm] = x
            run(x)
        dr.맞추기()
        a자 = dr.내리기(출["정수어텐션"][0], np.empty(2 * M * D, np.int8)).reshape(2, M, D)
        b자 = dr.내리기(출["정수어텐션갈래"][0], np.empty(2 * M * D, np.int8)).reshape(2, M, D)
        a정 = dr.내리기(출["정수어텐션"][1], np.empty(D // 32 * 폭, np.int32)).reshape(D // 32, 폭)
        b정 = dr.내리기(출["정수어텐션갈래"][1], np.empty(D // 32 * 폭, np.int32)).reshape(D // 32, 폭)
        # 출력 버퍼의 정보폭은 M 의 것(커널이 정보폭 = (행수+63)/64*64 로 쓴다) — 같은 자리끼리
        a정 = dr.내리기(출["정수어텐션"][1], np.empty(D // 32 * 정보폭, np.int32)).reshape(D // 32, 정보폭)[:, :M]
        b정 = dr.내리기(출["정수어텐션갈래"][1], np.empty(D // 32 * 정보폭, np.int32)).reshape(D // 32, 정보폭)[:, :M]
        다른자리, 다른정보 = int((a자 != b자).sum()), int((a정 != b정).sum())
        같음 = 다른자리 == 0 and 다른정보 == 0
        모두같음 &= 같음
        ts = {}
        for nm, x in 띄움.items():
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < 0.15:      # 클럭을 올려 둔다
                for _ in range(4):
                    run(x)
                dr.맞추기()
            시 = []
            for _ in range(5):
                cu.cuEventRecord(e0, None)
                for _ in range(3):
                    run(x)
                cu.cuEventRecord(e1, None); cu.cuEventSynchronize(e1)
                ms_ = ctypes.c_float(); cu.cuEventElapsedTime(ctypes.byref(ms_), e0, e1)
                시.append(ms_.value * 1000 / 3)
            ts[nm] = sorted(시)[2]
        print(f"C {C:6d} m {M:4d}: 다른 자리 {다른자리} 다른 정보 {다른정보} {'같다' if 같음 else '다르다!'} — 차례 {ts['정수어텐션']:9.1f} µs  갈래 {ts['정수어텐션갈래']:9.1f} µs  ({ts['정수어텐션'] / ts['정수어텐션갈래']:.2f}배)", flush=True)
print("모두", "같다" if 모두같음 else "다른 것이 있다", "— 오류 칸", m.오류칸())
m.닫기()
