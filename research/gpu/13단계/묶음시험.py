"""13단계: 두 층 접기의 프롬프트 판 — 묶음 판(정수어텐션묶음 + 정수묶음접기)과 두 층 차례 판(정수어텐션두층), 그리고 생성 판(정수조각어텐션 +
정수조각접기)이 새 CPU 참조(정수계약.어텐션 — 두 층)와 비트까지 같은가, 그리고 시간. 합성 긴 모델의 엔진 커널로: 무작위 q · k · v 로 캐시를
위치 0 … C+M−1 까지 채우고(KV정수로) 덩이 M 행(위치 C …)의 어텐션.
  (1) 묶음 판 대 두 층 차례 판 — 모든 머리, 출력 자리 · 정보
  (2) 머리 둘(참조머리)의 CPU 참조 대비 — 묶음 판 · 두 층 판의 출력 자리 · 정보, 생성 판의 O/L(행 64 개씩 나눠 — 조각칸이 행마다 크다)
  (3) C + M ≤ 1024 이면 12단계의 차례 판(정수어텐션)과 — 모든 머리(묶음 하나라 같아야 한다)
인자: ROOT [C들] [M들] [참조할까 0|1] [시간 0|1]"""
import sys
import os
import ctypes
import time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # 경고 · 오류도 UTF-8 로(한글 경로가 cp949 로 깨지지 않게)
ROOT = sys.argv[1]
Cs = [int(x) for x in (sys.argv[2] if len(sys.argv) > 2 else "100,2048,8192,32768,98000").split(",")]
Ms = [int(x) for x in (sys.argv[3] if len(sys.argv) > 3 else "5,16,64,128,192,512,1024").split(",")]
참조할까 = (sys.argv[4] if len(sys.argv) > 4 else "1") == "1"
시간잴까 = (sys.argv[5] if len(sys.argv) > 5 else "1") == "1"
for d in ("10단계", "9단계", "8단계", "7단계", "6단계", "5단계", "4단계", "3단계"):
    sys.path.insert(0, os.path.join(ROOT, "research", "gpu", d))
import numpy as np
import 글gpt2 as G
import 재기10 as K10
import gguf읽기 as GR
import 정수계약 as C
u64, i64, f32 = ctypes.c_uint64, ctypes.c_int64, np.float32
최대길이 = 102400
참조머리 = (0, 7)
m = G.글GPT2(GR.gpt2정수(K10.긴GGUF), KV형식="정수", 자리수=2, 최대행=max(Ms), 최대문장=1, 최대길이=최대길이, 로짓행=16, 묶음판행=max(Ms))
dr, D, NH = m.dr, m.D, m.NH
cu = dr.cu
k = m.k
for nm in ("정수어텐션", "정수어텐션묶음", "정수어텐션갈래묶음", "정수묶음접기", "정수어텐션두층"):
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


최대행 = max(Cs) + max(Ms)
assert 최대행 <= 최대길이
rng = np.random.default_rng(131)
입력 = (rng.standard_normal((최대행, 3 * D)) * rng.uniform(0.3, 3.0, (최대행, 1))).astype(f32)
g입력 = dr.할당(입력.nbytes)
dr.올리기(g입력, 입력)
KV = [u64(m.kc[0]), u64(m.vc[0]), u64(m.ke[0]), u64(m.ve[0])]
덩큰 = 16384
자q큰, 정q큰 = zero(2 * 덩큰 * D), zero(D // 32 * 덩큰 * 4)


def kv정수로(a, n, 자q, 정q):
    run(G._띄움(k["KV정수로"], ((3 * D // 32 + 31) // 32, n), (256, 1),
                [u64(g입력 + a * 3 * D * 4), u64(자q), u64(정q)] + KV + [i64(n), i64(n), i64(a), i64(최대길이)]))


for a in range(0, 최대행, 덩큰):
    kv정수로(a, min(덩큰, 최대행 - a), 자q큰, 정q큰)
dr.맞추기()
M최대 = max(Ms)
폭 = (M최대 + 63) // 64 * 64
자q, 정q = zero(2 * M최대 * D), zero(D // 32 * 폭 * 4)
출 = {nm: (zero(2 * M최대 * D), zero(D // 32 * 폭 * 4)) for nm in ("묶음", "갈묶", "두층", "차례", "갈래")}
조각칸 = zero(64 * NH * (최대길이 // 64) * 68 * 4)
출력 = zero(64 * D * 4)
e0, e1 = ctypes.c_void_p(), ctypes.c_void_p()
cu.cuEventCreate(ctypes.byref(e0), 0); cu.cuEventCreate(ctypes.byref(e1), 0)


def 띄움들(판, C0, M):
    자, 정 = 출[판]
    질 = (M + 63) // 64
    if 판 == "묶음":
        G묶 = (C0 + M - 1) // 1024 + 1
        return [G._띄움(k["정수어텐션묶음"], (질 * NH * G묶, 1), (128, 1),
                        [u64(자q), u64(정q)] + KV + [u64(m.묶음칸), i64(M), i64(M), i64(C0), i64(최대길이)]),
                G._띄움(k["정수묶음접기"], (NH, M), (64, 1), [u64(m.묶음칸), u64(정), u64(자), i64(M), i64(M), i64(C0), i64(최대길이)])]
    if 판 == "갈묶":                                    # 갈래 묶음 판(질의 16) + 묶음 접기
        G묶 = (C0 + M - 1) // 1024 + 1
        return [G._띄움(k["정수어텐션갈래묶음"], ((M + 15) // 16 * NH * G묶, 1), (256, 1),
                        [u64(자q), u64(정q)] + KV + [u64(m.묶음칸), i64(M), i64(M), i64(C0), i64(최대길이)]),
                G._띄움(k["정수묶음접기"], (NH, M), (64, 1), [u64(m.묶음칸), u64(정), u64(자), i64(M), i64(M), i64(C0), i64(최대길이)])]
    if 판 == "두층":
        return [G._띄움(k["정수어텐션두층"], (NH, 질), (128, 1),
                        [u64(자q), u64(정q)] + KV + [u64(m.묶음칸), u64(정), u64(자), i64(M), i64(M), i64(C0), i64(최대길이)])]
    if 판 == "갈래":                                    # 12단계의 갈래 판(한 층 — 시간만 견준다)
        return [G._띄움(k["정수어텐션갈래"], (NH, (M + 15) // 16), (256, 1),
                        [u64(자q), u64(정q)] + KV + [u64(정), u64(자), i64(M), i64(M), i64(C0), i64(최대길이)])]
    return [G._띄움(k["정수어텐션"], (NH, 질), (128, 1), [u64(자q), u64(정q)] + KV + [u64(정), u64(자), i64(M), i64(M), i64(C0), i64(최대길이)])]


def 내려(판, M):
    정보폭 = (M + 63) // 64 * 64
    a = dr.내리기(출[판][0], np.empty(2 * M * D, np.int8)).reshape(2, M, D)
    b = dr.내리기(출[판][1], np.empty(D // 32 * 정보폭, np.int32)).reshape(D // 32, 정보폭)[:, :M]
    return a, b


def 재기(xs):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 0.15:
        for x in xs:
            run(x)
        dr.맞추기()
    시 = []
    for _ in range(5):
        cu.cuEventRecord(e0, None)
        for _ in range(3):
            for x in xs:
                run(x)
        cu.cuEventRecord(e1, None); cu.cuEventSynchronize(e1)
        ms_ = ctypes.c_float(); cu.cuEventElapsedTime(ctypes.byref(ms_), e0, e1)
        시.append(ms_.value * 1000 / 3)
    return sorted(시)[2]


모두 = True
for C0 in Cs:
    for M in Ms:
        if C0 + M > 최대길이:
            continue
        kv정수로(C0, M, 자q, 정q)
        판들 = ["묶음", "갈묶", "두층"] + (["차례"] if C0 + M <= 1024 else [])
        for 판 in 판들:
            dr.확인(cu.cuMemsetD8_v2(u64(출[판][0]), 0x5A, ctypes.c_size_t(2 * M최대 * D)))
            dr.확인(cu.cuMemsetD8_v2(u64(출[판][1]), 0x5A, ctypes.c_size_t(D // 32 * 폭 * 4)))
            for x in 띄움들(판, C0, M):
                run(x)
        dr.맞추기()
        out = {판: 내려(판, M) for 판 in 판들}
        줄 = f"C {C0:6d} M {M:5d}:"
        같음 = True
        for 판 in ("두층", "갈묶"):
            d자 = int((out["묶음"][0] != out[판][0]).sum()); d정 = int((out["묶음"][1] != out[판][1]).sum())
            줄 += f" 묶음 대 {판} {d자}/{d정}"
            같음 &= d자 == 0 and d정 == 0
        if "차례" in out:
            d자 = int((out["묶음"][0] != out["차례"][0]).sum()); d정 = int((out["묶음"][1] != out["차례"][1]).sum())
            줄 += f" · 대 차례(12단계) {d자}/{d정}"
            같음 &= d자 == 0 and d정 == 0
        if 참조할까:
            q_, kk_, v_ = 입력[:C0 + M, :D], 입력[:C0 + M, D:2 * D], 입력[:C0 + M, 2 * D:]
            ref = np.zeros((M, D), f32)
            t0 = time.perf_counter()
            for h in 참조머리:
                sl = slice(64 * h, 64 * h + 64)
                ref[:, sl] = C.어텐션(q_[:, sl], kk_[:, sl], v_[:, sl], 첫행=C0)
            참초 = time.perf_counter() - t0
            Do, Eo = C.자리로(ref, 2)
            rb = C.낱말차례(Do.reshape(2, M, D // 32, 32)).reshape(2, M, D).astype(np.int8)
            ri = ((((137 + Eo.T) << 23) + 0x400000).astype(np.int32))
            cols = np.zeros(D, bool)
            bl = np.zeros(D // 32, bool)
            for h in 참조머리:
                cols[64 * h:64 * h + 64] = True
                bl[2 * h:2 * h + 2] = True
            for 판 in ("묶음", "갈묶", "두층"):
                d자 = int((out[판][0][:, :, cols] != rb[:, :, cols]).sum()); d정 = int((out[판][1][bl] != ri[bl]).sum())
                줄 += f" · {판} 대 CPU {d자}/{d정}"
                같음 &= d자 == 0 and d정 == 0
            # 생성 판(행 64 개씩 — 그 행들의 q 를 다시 만들어)
            go = np.zeros((M, D), f32)
            for a in range(0, M, 64):
                n = min(64, M - a)
                kv정수로(C0 + a, n, 자q, 정q)
                run(G._띄움(k["정수조각어텐션"], (((C0 + a + n - 1) // 64 + 1 + 7) // 8, n * NH), (256, 1),
                            [u64(자q), u64(정q)] + KV + [u64(조각칸), i64(n), i64(n), i64(C0 + a), i64(최대길이)]))
                run(G._띄움(k["정수조각접기"], (n * NH, 1), (256, 1), [u64(조각칸), u64(출력), i64(n), i64(n), i64(C0 + a), i64(최대길이)]))
                dr.맞추기()
                go[a:a + n] = dr.내리기(출력, np.empty(64 * D, f32)).reshape(64, D)[:n]
            kv정수로(C0, M, 자q, 정q)                  # 시간 재기용으로 덩이 전체의 q 를 되돌린다
            dg = int((go[:, cols].view(np.int32) != ref[:, cols].view(np.int32)).sum())
            줄 += f" · 생성 판 대 CPU {dg} (참조 {참초:.1f} s)"
            같음 &= dg == 0
        if 시간잴까:
            dr.맞추기()
            for 판 in ("묶음", "갈묶", "두층", "차례", "갈래"):        # 클럭을 올려 둔다(CPU 참조 뒤 GPU 가 쉬었다)
                재기(띄움들(판, C0, M))
            ts = {판: 재기(띄움들(판, C0, M)) for 판 in ("묶음", "갈묶", "두층", "차례", "갈래")}     # 차례 · 갈래(12단계 — 한 층)는 1024 넘어서 시간만
            줄 += " — " + "  ".join(f"{판} {t:8.1f} µs" for 판, t in ts.items())
        모두 &= 같음
        print(줄, "같다" if 같음 else "다르다!", flush=True)
print("모두", "같다" if 모두 else "다른 것이 있다", "— 오류 칸", m.오류칸())
m.닫기()
