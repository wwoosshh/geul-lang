#!/usr/bin/env python3
"""12단계 재기 — 겹치기 · 어텐션 · 지속 사용 (docs/17 §7 "12단계" 의 판정 그대로).

  build/감사venv/Scripts/python -I research/gpu/12단계/재기13.py [a b c d e f g …] [small XL]

부분을 고르지 않으면 모두. 12단계가 바꾼 것(정수 KV 모듈만, 값은 그대로 — 12a 가 확인한다):
  글ptx.py — 모듈 주석 (* 상수나눗셈 *) 이 있으면 상수로 나누기 · 나머지(64 비트)를 하위 함수 부름 없이(2 의 거듭제곱은 밀기, 아니면
    mul.hi 의 마법수 — div · rem 과 모든 입력에서 같다); 비동기 장벽(mbarrier) 내장.
  어텐션 — 생성 메가커널의 긴 문맥 어텐션에 머리마다 접는 블록(조각 256 개 묶음이 차는 대로 접는다), 조각칸의 새 배치(o 와 m·l 을 따로),
    프롬프트 어텐션의 갈래 판(정수어텐션갈래 — 블록 (머리, 질의 16), 워프마다 키 조각 하나씩 여덟을 함께, 접기는 차례대로; 호스트가 고름),
    정확한 합의 짧은실수 읽기를 변환 명령 없이(|합| < 2²² 의 마법수), 매개변수 나눗셈을 한 번만.
  호스트 — 판 고르기를 모델을 올릴 때 미리 · 처음 쓰는 계획은 그래프 없이 · 그래프의 열쇠에서 위치를 빼고 위치 마디만 고친다.
재는 법은 11단계(재기12.py) 그대로에 12a 의 대화 길과 긴 문맥 대조, 12f · 12g 의 지속 사용을 더했다. 결과는 결과/12단계.json.
"""
import gc
import json
import os
import sys
import time
import ctypes

import numpy as np
import torch

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
for d in ("11단계", "10단계", "9단계", "8단계", "7단계", "6단계", "5단계", "4단계", "3단계"):
    sys.path.insert(0, os.path.join(ROOT, "research", "gpu", d))
import 커널생성 as K          # noqa: E402
import gguf읽기 as GR         # noqa: E402
import 재기4 as R             # noqa: E402
import 재기 as R3             # noqa: E402
import 재기7 as K7            # noqa: E402
import 재기9 as K9            # noqa: E402
import 재기10 as K10          # noqa: E402
import 재기12 as K12          # noqa: E402
import 정수계약 as C          # noqa: E402

G = R.G
형식들 = ("q8_0", "q4_0")
결과 = os.path.join(HERE, "결과", "12단계.json")
N = 64
긴GGUF = K10.긴GGUF
u64, i64, f32 = ctypes.c_uint64, ctypes.c_int64, np.float32
K10.어텐션판["정수어텐션갈래"] = (16, 32 * K.갈래워프)          # 12단계의 갈래 판도 9단계 커널대조로(블록의 질의 16)


# ── 12a 의 더한 것 ─────────────────────────────────────────────────────────────────────────

def 대화대조(e, rng, 차례들):
    """대화 길(이어넣기 · 이어생성 — 길이가 제각각인 덩이, 같은 길이를 다른 위치에서 다시 써 그래프의 위치 마디 고치기까지)이 같은 토큰열을 한
    번에 넣은 것과 토큰 · 캐시 바이트(층 모두, 키 · 값 · 지수)까지 같은가. 차례들: [(덩이 길이, 생성 수)]."""
    m = e.m
    NL = len(m.kc)

    def 비우기():
        for 바탕, 크기 in ((m.kc바탕, len(m.kc) * (m.kc[1] - m.kc[0]) if NL > 1 else 0), (m.vc바탕, len(m.vc) * (m.vc[1] - m.vc[0]) if NL > 1 else 0),
                         (m.ke바탕, NL * (m.ke[1] - m.ke[0]) if NL > 1 else 0), (m.ve바탕, NL * (m.ve[1] - m.ve[0]) if NL > 1 else 0)):
            m.dr.확인(m.dr.cu.cuMemsetD8_v2(u64(바탕), 0, ctypes.c_size_t(크기)))
        m.dr.맞추기()

    def 캐시모두():
        return [x for l in range(NL) for x in K10.캐시(m, l)]
    비우기()
    열 = []                        # 넣은 토큰열(위치 차례)
    생성 = []                      # (위치, 토큰) — 위치의 행에서 고른 다음 토큰
    끝 = int(rng.integers(0, 50257))
    위치 = 0
    for 덩이길이, n in 차례들:
        덩이 = [끝] + [int(x) for x in rng.integers(0, 50257, 덩이길이 - 1)]
        첫 = m.이어넣기(덩이, 위치)
        열 += 덩이
        위치 += len(덩이)
        생성.append((위치 - 1, 첫))
        toks = m.이어생성(첫, 위치, n - 1) if n > 1 else [첫]
        for i, t in enumerate(toks[1:]):
            열.append(toks[i])
            생성.append((위치 + i, t))
        위치 += n - 1
        끝 = toks[-1]
    c대화 = 캐시모두()
    비우기()
    로짓 = R3.글로짓(m, [열], "한번에")[0]
    c한번 = 캐시모두()
    고른 = {p: int(np.argmax(로짓[p])) for p, _ in 생성}
    다른토큰 = sum(1 for p, t in 생성 if 고른[p] != t)
    다른바이트 = int(sum(int((a != b).sum()) for a, b in zip(c대화, c한번)))
    return {"차례 (덩이, 생성)": 차례들, "토큰열 길이": len(열), "생성 토큰": len(생성), "다른 토큰": 다른토큰,
            "캐시 다른 바이트 (층 모두)": 다른바이트, "통과": 다른토큰 == 0 and 다른바이트 == 0}


def 어텐션끝행(q, k, v, C0):
    """정수계약.어텐션(머리 하나)의 행 C0 … n − 1 만 — 긴 문맥의 짧은 덩이를 CPU 로 대조할 때(앞 행은 계산하지 않는다). 같은 식 · 같은 차례."""
    q, k, v = (np.asarray(x, f32) for x in (q, k, v))
    n = q.shape[0]
    (Dq, Eq), (Dk, Ek), (Dv, Ev) = C.자리로(q, 2), C.자리로(k, 2), C.자리로(v, 2)
    nq, nk, nv = (D[1] * 256 + D[0] for D in (Dq, Dk, Dv))
    Pq, Pk, Pv = C.거듭제곱(Eq), C.거듭제곱(Ek), C.거듭제곱(Ev)
    R_ = np.arange(C0, n)
    M = np.full(len(R_), -np.inf, f32)
    L = np.zeros(len(R_), f32)
    O = np.zeros((len(R_), 64), f32)
    for 시작 in range(0, n, 64):
        sel = R_ >= 시작
        Rr = R_[sel]
        keys = np.arange(시작, min(시작 + 64, n))
        valid = keys[None, :] <= Rr[:, None]
        s = None
        for b in range(2):
            sl = slice(32 * b, 32 * b + 32)
            u = (nq[Rr][:, sl] @ nk[keys][:, sl].T).astype(f32)
            부분 = (u * Pq[Rr, b][:, None]).astype(f32)
            s = (부분 * Pk[keys, b][None, :]).astype(f32) if b == 0 else C.fma32(부분, np.broadcast_to(Pk[keys, b][None, :], 부분.shape), s)
        s = (s * f32(0.125)).astype(f32)
        s = np.where(valid, s, f32(-3.0e38)).astype(f32)
        mm = s.max(1)
        e = np.where(valid, C.적힌지수((s - mm[:, None]).astype(f32)), f32(0)).astype(f32)
        l = (np.rint((e * f32(8388608.0)).astype(f32)).astype(np.int64).sum(1).astype(f32) * f32(2.0 ** -23)).astype(f32)
        o = np.zeros((len(Rr), 64), f32)
        for b in range(2):
            ep = (e * Pv[keys, b][None, :]).astype(f32)
            uj = []
            for j in range(0, len(keys), 32):
                epj = np.zeros((len(Rr), 32), f32)
                epj[:, :min(32, len(keys) - j)] = ep[:, j:j + 32]
                ne, Ee = C.e자리(epj)
                nvj = np.zeros((32, 32), np.int64)
                nvj[:min(32, len(keys) - j)] = nv[keys[j:j + 32]][:, 32 * b:32 * b + 32]
                uj.append(((ne @ nvj).astype(f32), C.거듭제곱(Ee[:, 0])))
            if len(uj) == 1:
                uj.append((np.zeros_like(uj[0][0]), C.거듭제곱(np.full(len(Rr), -98))))
            (u0, P0), (u1, P1) = uj
            o[:, 32 * b:32 * b + 32] = C.fma32(u1, P1[:, None], (u0 * P0[:, None]).astype(f32))
        if 시작 == 0:
            M[sel], L[sel], O[sel] = mm, l, o
        else:
            M2 = np.maximum(M[sel], mm)
            가 = C.적힌지수((M[sel] - M2).astype(f32))
            나 = C.적힌지수((mm - M2).astype(f32))
            L[sel] = C.fma32(l, 나, (L[sel] * 가).astype(f32))
            O[sel] = C.fma32(o, 나[:, None], (O[sel] * 가[:, None]).astype(f32))
            M[sel] = M2
    return (O / L[:, None]).astype(f32)


def 긴대조(m, rng, 맥락들, 덩이들, 참조머리=(0, 7)):
    """합성 긴 모델의 엔진 m 의 커널로, 무작위 q · k · v 로 캐시를 위치 0 … C+덩이 − 1 까지 채우고(KV정수로) 덩이 행(위치 C …)의 어텐션:
    (1) 갈래 판 대 차례 판(출력 자리 · 정보 — 모든 맥락 × 덩이), (2) CPU 참조(머리 둘, 첫 맥락의 덩이마다 — 갈래 판의 출력 자리 · 정보와
    생성 판(정수조각어텐션 + 정수조각접기)의 O/L)."""
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
    최대행 = max(맥락들) + max(덩이들)
    입력 = (rng.standard_normal((최대행, 3 * D)) * rng.uniform(0.3, 3.0, (최대행, 1))).astype(f32)
    g입력 = dr.할당(입력.nbytes)
    dr.올리기(g입력, 입력)
    KV = [u64(m.kc[0]), u64(m.vc[0]), u64(m.ke[0]), u64(m.ve[0])]
    덩큰 = 16384
    자q큰, 정q큰 = zero(2 * 덩큰 * D), zero(D // 32 * 덩큰 * 4)
    for a in range(0, 최대행, 덩큰):
        n = min(덩큰, 최대행 - a)
        run(G._띄움(k["KV정수로"], ((3 * D // 32 + 31) // 32, n), (256, 1),
                    [u64(g입력 + a * 3 * D * 4), u64(자q큰), u64(정q큰)] + KV + [i64(n), i64(n), i64(a), i64(최대길이)]))
    dr.맞추기()
    M최대 = max(덩이들)
    폭 = (M최대 + 63) // 64 * 64
    자q, 정q = zero(2 * M최대 * D), zero(D // 32 * 폭 * 4)
    출 = {nm: (zero(2 * M최대 * D), zero(D // 32 * 폭 * 4)) for nm in ("정수어텐션", "정수어텐션갈래")}
    조각칸, 출력 = zero(M최대 * NH * (최대길이 // 64) * 68 * 4), zero(M최대 * D * 4)
    out = {"갈래 대 차례": {}, "CPU 참조": {}}
    for C0 in 맥락들:
        for M in 덩이들:
            정보폭 = (M + 63) // 64 * 64
            run(G._띄움(k["KV정수로"], ((3 * D // 32 + 31) // 32, M), (256, 1),
                        [u64(g입력 + C0 * 3 * D * 4), u64(자q), u64(정q)] + KV + [i64(M), i64(M), i64(C0), i64(최대길이)]))
            for nm, (Q, T) in (("정수어텐션", (64, 128)), ("정수어텐션갈래", K10.어텐션판["정수어텐션갈래"])):
                자, 정 = 출[nm]
                run(G._띄움(k[nm], (NH, (M + Q - 1) // Q), (T, 1), [u64(자q), u64(정q)] + KV + [u64(정), u64(자), i64(M), i64(M), i64(C0), i64(최대길이)]))
            dr.맞추기()
            # 출력 자리는 [자리 2][행수 M][너비] — 자리 1 의 자리는 M 에 따른다(버퍼의 앞 2·M·너비 바이트)
            a자, b자 = (dr.내리기(출[nm][0], np.empty(2 * M * D, np.int8)).reshape(2, M, D) for nm in ("정수어텐션", "정수어텐션갈래"))
            a정, b정 = (dr.내리기(출[nm][1], np.empty(D // 32 * 정보폭, np.int32)).reshape(D // 32, 정보폭)[:, :M] for nm in ("정수어텐션", "정수어텐션갈래"))
            out["갈래 대 차례"][f"맥락 {C0} 덩이 {M}"] = {"다른 자리": int((a자 != b자).sum()), "다른 정보": int((a정 != b정).sum())}
            if C0 == 맥락들[0]:
                run(G._띄움(k["정수조각어텐션"], (((C0 + M - 1) // 64 + 1 + 7) // 8, M * NH), (256, 1),
                            [u64(자q), u64(정q)] + KV + [u64(조각칸), i64(M), i64(M), i64(C0), i64(최대길이)]))
                run(G._띄움(k["정수조각접기"], (M * NH, 1), (256, 1), [u64(조각칸), u64(출력), i64(M), i64(M), i64(C0), i64(최대길이)]))
                dr.맞추기()
                go = dr.내리기(출력, np.empty(M최대 * D, f32)).reshape(M최대, D)[:M]
                q_, kk_, v_ = 입력[:C0 + M, :D], 입력[:C0 + M, D:2 * D], 입력[:C0 + M, 2 * D:]
                ref = np.zeros((M, D), f32)
                for h in 참조머리:
                    ref[:, 64 * h:64 * h + 64] = 어텐션끝행(q_[:, 64 * h:64 * h + 64], kk_[:, 64 * h:64 * h + 64], v_[:, 64 * h:64 * h + 64], C0)
                Do, Eo = C.자리로(ref, 2)
                rb = C.낱말차례(Do.reshape(2, M, D // 32, 32)).reshape(2, M, D).astype(np.int8)
                cols = np.zeros(D, bool)
                bl = np.zeros(D // 32, bool)
                for h in 참조머리:
                    cols[64 * h:64 * h + 64] = True
                    bl[2 * h:2 * h + 2] = True
                ri = ((((137 + Eo.T) << 23) + 0x400000).astype(np.int32))
                out["CPU 참조"][f"맥락 {C0} 덩이 {M} (머리 {list(참조머리)})"] = {
                    "갈래 판 출력 자리 다른 칸": int((b자[:, :, cols] != rb[:, :, cols]).sum()),
                    "갈래 판 출력 정보 다른 칸": int((b정[bl] != ri[bl]).sum()),
                    "생성 판 O/L 다른 칸": int((go[:, cols].view(np.int32) != ref[:, cols].view(np.int32)).sum())}
            print("12a 긴 문맥", C0, M, out["갈래 대 차례"][f"맥락 {C0} 덩이 {M}"], flush=True)
    out["통과"] = (all(v["다른 자리"] == 0 and v["다른 정보"] == 0 for v in out["갈래 대 차례"].values()) and
                 all(all(x == 0 for x in v.values()) for v in out["CPU 참조"].values()))
    return out


def 메가대조(m, rng, 맥락들, 걸음=24):
    """생성 메가커널(머리마다 접는 블록) 대 따로 도는 커널(정수조각어텐션 + 정수조각접기)의 생성 — 토큰이 같은가(합성 긴 모델)."""
    out = {}
    for C0 in 맥락들:
        ids = [int(x) for x in rng.integers(0, 50257, C0)]
        첫 = None
        for a in range(0, C0, 1024):
            첫 = m.이어넣기(ids[a:a + 1024], a)
        가 = m.이어생성(첫, C0, 걸음 - 1)
        toks = [첫]
        for s in range(걸음 - 1):
            m.토큰넣기([toks[-1]])
            m.계산(1, 1, C0 + s, "끝")
            m.dr.맞추기()
            toks.append(int(m.dr.내리기(m.생성칸, np.zeros(1, np.int64))[0]))
        out[f"맥락 {C0}"] = {"같은가": toks == 가}
        print("12a 메가커널 대 따로", C0, toks == 가, flush=True)
    out["통과"] = all(v["같은가"] for v in out.values())
    return out


# ── 12f · 12g ─────────────────────────────────────────────────────────────────────────────

def 자라는대화(일, 최대=100000, 씨=12):
    """12f: 합성 긴 모델 — 차례마다 덩이 16~1024 · 생성 16~128(무작위, 같은 씨앗 — 두 엔진 같은 길이 · 같은 토큰), 문맥 10만까지, 차례마다
    번갈아. 문맥 구간(12800 씩 여덟 — 차례가 시작할 때의 문맥)마다 넣기 ms 의 중앙값과 생성 토큰당 ms 의 중앙값."""
    wq = GR.gpt2정수(긴GGUF)
    글 = R.글엔진(wq, KV형식="정수", 자리수=2, 최대행=1024, 최대문장=1, 최대길이=102400, 로짓행=16)
    글.이름 = "글 q8_0 정수 KV (합성 긴)"
    t0 = time.perf_counter()
    글.m.판미리고르기()
    고르기ms = (time.perf_counter() - t0) * 1000
    라 = R.라마엔진(일, "llama.cpp q8_0 (합성 긴)", 긴GGUF, n_ctx=102400, n_batch=1024)
    rng = np.random.default_rng(씨)
    끝 = {"글": 0, "라": 0}
    기록, 위치, 차례 = [], 0, 0
    while True:
        덩이길이, n = int(rng.integers(16, 1025)), int(rng.integers(16, 129))
        if 위치 + 덩이길이 + n > 최대:
            break
        새 = [int(x) for x in rng.integers(0, 50257, 덩이길이 - 1)]
        줄 = {"차례": 차례, "앞 문맥": 위치, "덩이": 덩이길이, "생성": n}
        for 이름, e in (("글", 글), ("라", 라)):
            r = e.대화([[끝[이름]] + 새], n, 처음=(차례 == 0))[0]
            끝[이름] = r["끝토큰"]
            줄[이름] = {"넣기 ms": round(r["넣기 ms"], 3), "생성 ms": round(r["생성 ms"], 3), "토큰당 ms": round(r["생성 ms"] / (n - 1), 4)}
        줄["같은 끝토큰"] = 끝["글"] == 끝["라"]
        기록.append(줄)
        위치 += 덩이길이 + n - 1
        차례 += 1
        if 차례 % 20 == 0:
            print("12f", 차례, 위치, 줄, flush=True)
    오류 = 글.m.오류칸()
    라.닫기()
    글.m.닫기()
    구간 = {}
    for b in range(8):
        r = [x for x in 기록 if b * 12800 <= x["앞 문맥"] < (b + 1) * 12800]
        if not r:
            continue
        g넣, l넣 = float(np.median([x["글"]["넣기 ms"] for x in r])), float(np.median([x["라"]["넣기 ms"] for x in r]))
        g생, l생 = float(np.median([x["글"]["토큰당 ms"] for x in r])), float(np.median([x["라"]["토큰당 ms"] for x in r]))
        구간[f"{b * 12800}~{(b + 1) * 12800}"] = {"차례 수": len(r), "넣기 ms 중앙값 (글 · llama.cpp)": [round(g넣, 3), round(l넣, 3)],
                                                "토큰당 ms 중앙값 (글 · llama.cpp)": [round(g생, 4), round(l생, 4)],
                                                "통과": g넣 < l넣 and g생 < l생}
    첫 = 기록[0]
    첫통과 = 첫["글"]["넣기 ms"] + 첫["글"]["생성 ms"] < 첫["라"]["넣기 ms"] + 첫["라"]["생성 ms"]
    return {"판미리고르기 ms": round(고르기ms), "차례 수": len(기록), "마지막 문맥": 위치, "구간": 구간,
            "첫 차례 (넣기 + 생성 ms, 글 · llama.cpp)": [round(첫["글"]["넣기 ms"] + 첫["글"]["생성 ms"], 2), round(첫["라"]["넣기 ms"] + 첫["라"]["생성 ms"], 2)],
            "오류 칸": 오류, "차례들": 기록,
            "통과": all(v["통과"] for v in 구간.values()) and len(구간) == 8 and 첫통과 and 오류 == 0}


def 오래돌리기(일, 창초=10.0, 창수=6, 씨=13):
    """12g: XL Q8_0(실제 모델) — 문맥 1024 안의 대화(덩이 16~256 · 생성 16~128 무작위, 차면 새 대화)를 창초 초 창으로 두 엔진 번갈아(llama.cpp
    창 다음 글 창) 창수 쌍. 모든 창이 같은 차례열(같은 씨앗)로 시작한다 — 창끼리의 차이가 일감이 아니라 시간이 지나며 생긴 것이게(첫 실행은
    창마다 씨앗 (씨, i) 이라 창끼리 일감이 달랐다 — README). 처리량 = (넣은 토큰 + 생성 토큰) / 창의 벽시계. 창마다 GPU 클럭 · 온도도."""
    path = K9.경로("XL", "q8_0")
    글 = K10.글엔진("XL", "q8_0", 최대문장=1)
    글.m.판미리고르기()
    라 = R.라마엔진(일, "llama.cpp q8_0", path)

    def 창(e, i):
        rng = np.random.default_rng(씨)
        위치, 처음, 끝, 토큰, 차례 = 0, True, int(rng.integers(0, 50257)), 0, 0
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 창초:
            덩이길이, n = int(rng.integers(16, 257)), int(rng.integers(16, 129))
            if 위치 + 덩이길이 + n > 1024:
                위치, 처음 = 0, True
            새 = [int(x) for x in rng.integers(0, 50257, 덩이길이 - 1)]
            r = e.대화([[끝] + 새], n, 처음=처음)[0]
            끝, 처음 = r["끝토큰"], False
            위치 += 덩이길이 + n - 1
            토큰 += 덩이길이 + n - 1
            차례 += 1
        초 = time.perf_counter() - t0
        import subprocess
        q = subprocess.run(["nvidia-smi", "--query-gpu=clocks.sm,temperature.gpu,power.draw", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True).stdout.strip()
        return {"차례": 차례, "토큰": 토큰, "초": round(초, 3), "토큰/초": round(토큰 / 초, 1), "GPU (MHz, °C, W)": q}
    창들 = []
    for i in range(창수):
        l = 창(라, i)
        g = 창(글, i)
        창들.append({"창": i, "llama.cpp": l, "글": g})
        print("12g", 창들[-1], flush=True)
    오류 = 글.m.오류칸()
    라.닫기()
    글.m.닫기()
    앞섬 = all(c["글"]["토큰/초"] > c["llama.cpp"]["토큰/초"] for c in 창들)
    유지 = 창들[-1]["글"]["토큰/초"] >= 0.95 * 창들[0]["글"]["토큰/초"]
    return {"창": 창들, "글이 모든 창에서 앞섬": 앞섬, "글의 마지막 창 / 첫 창": round(창들[-1]["글"]["토큰/초"] / 창들[0]["글"]["토큰/초"], 3),
            "오류 칸": 오류, "통과": 앞섬 and 유지 and 오류 == 0}


# ── 본체 ─────────────────────────────────────────────────────────────────────────────────

def main():
    긴만 = "a긴" in sys.argv[1:]                     # 12a 의 합성 긴 대조만(크기마다의 대조는 건너뛴다)
    부분 = {a for a in sys.argv[1:] if a in tuple("abcdefg")} | ({"a"} if 긴만 else set())
    부분 = 부분 or set("abcdefg")
    고름 = [a for a in sys.argv[1:] if a in ("small", "XL")]
    크기들 = tuple(k for k in ("small", "XL") if not 고름 or k in 고름)
    torch.zeros(1, device="cuda")
    res = {"환경": {"torch": torch.__version__, "llama.cpp": "b11496 (000bee54a)", "GPU": torch.cuda.get_device_name(0)},
           "12a 계약 (비트)": {}, "12b 타일 효율": {}, "12c 어텐션 효율": {}, "12d 프롬프트 속도": {"실패": {}}, "12e 생성 속도": {"실패": {}},
           "12f 지속 사용 — 자라는 대화": {}, "12g 지속 사용 — 오래 돌리기": {}}
    if os.path.exists(결과):
        res.update(json.load(open(결과, encoding="utf-8")))

    def 저장():
        os.makedirs(os.path.dirname(결과), exist_ok=True)
        json.dump(res, open(결과, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if "a" in 부분 and not 긴만:
        res["12a 계약 (비트)"]["8단계까지의 모듈"] = K10.옛모듈같은가("HEAD")
        print("12a 옛 모듈", res["12a 계약 (비트)"]["8단계까지의 모듈"], flush=True)
        저장()
    if "d" in 부분:
        for 크기 in 크기들:
            res["12d 프롬프트 속도"][f"PyTorch f16 참고선 {크기}"] = K12.참고선(크기, (128, 512, 1024))
            print("참고선", 크기, res["12d 프롬프트 속도"][f"PyTorch f16 참고선 {크기}"], flush=True)
        저장()
    if "b" in 부분 and "XL" in 크기들:
        dr = G.드라이버()
        K.KV = "정수"
        for fmt in 형식들:
            ptx = os.path.join(ROOT, "build", f"커널XL{'Q8' if fmt == 'q8_0' else 'Q4'}정수KV.ptx")
            b = {}
            for 이름, (M, Kd, Nn) in (("c_fc", (1024, 1600, 6400)), ("c_proj", (1024, 1600, 1600)), ("mlp c_proj", (1024, 6400, 1600))):
                b[이름] = K9.타일효율(dr, ptx, 2, M, Kd, Nn)
                print("12b", fmt, 이름, b[이름]["가장 빠른 판"], b[이름]["µs"], b[이름]["int8 최고치 대비 %"], flush=True)
            b["통과"] = b["c_fc"]["int8 최고치 대비 %"] >= 60 and b["c_proj"]["int8 최고치 대비 %"] >= 55 and b["mlp c_proj"]["int8 최고치 대비 %"] >= 55
            res["12b 타일 효율"][fmt] = b
        K.KV = "짧은실수"
        dr.놓기()
        저장()
    일 = R.일꾼() if 부분 & set("defg") else None
    평가글 = open(os.path.join(ROOT, "research", "gpu", "5단계", "평가글.txt"), encoding="utf-8").read()
    rng = np.random.default_rng(120)
    if (부분 & set("cde")) or ("a" in 부분 and not 긴만):
        for 크기 in 크기들:
            tk = G.토크나이저(K9.모델폴더(크기))
            prompts = [tk.나누기(s) for s in R.문장들]
            평가 = tk.나누기(평가글)[:1024]
            긴 = (tk.나누기(R.문장들[1]) * 40)[:1024]
            D = 768 if 크기 == "small" else 1600
            for fmt in 형식들:
                열쇠 = f"{크기} {fmt}"
                path = K9.경로(크기, fmt)
                e9 = K10.글엔진(크기, fmt)
                if "a" in 부분 and not 긴만:
                    a = {}
                    if fmt == "q8_0":
                        w = G.가중치읽기(os.path.join(K9.모델폴더(크기), "model.safetensors"))
                        qkv = K10.층qkv(w, 긴[:1024], 5 if 크기 == "small" else 20, D)
                        del w
                        gc.collect()
                        for 판 in ("정수어텐션", "정수어텐션둘", "정수어텐션갈래"):
                            a[f"어텐션 커널 대 CPU 참조 ({판})"] = K10.커널대조(e9.m, qkv, 1024, 커널=판)
                            print("12a", 열쇠, 판, a[f"어텐션 커널 대 CPU 참조 ({판})"]["통과"], flush=True)
                    a["행렬곱 — CPU 참조 대비 (판 모두)"] = K7.행렬곱시험(e9.m, GR.GGUF(path), rng)
                    a["끝에서 끝 (8단계 비트시험)"] = K9.비트시험(e9, path, rng, prompts, 긴)
                    a["캐시 바이트 — 프롬프트 · 두조각 · 메가커널 대 하나씩"] = K10.끝끝(e9, 평가[:469])
                    a["대화 길 대 한 번에"] = 대화대조(e9, rng, [(37, 6), (5, 3), (120, 12), (16, 1), (200, 9), (1, 2), (64, 5), (33, 4), (120, 7), (16, 3), (200, 1)])
                    a["오류 칸"] = e9.m.오류칸()
                    a["통과"] = (all(v["다른 칸"] == 0 for v in a["행렬곱 — CPU 참조 대비 (판 모두)"].values()) and
                                all(v["통과"] for k_, v in a.items() if isinstance(v, dict) and "통과" in v) and a["오류 칸"] == 0)
                    print("12a", 열쇠, "통과", a["통과"], "대화", a["대화 길 대 한 번에"]["통과"], "오류 칸", a["오류 칸"], flush=True)
                    res["12a 계약 (비트)"][열쇠] = a
                    저장()
                if 부분 & set("de"):
                    e8 = K9.글엔진(크기, fmt, 2, 최대문장=1)
                    라 = R.라마엔진(일, f"llama.cpp {fmt}", path)
                    엔진들 = [e9, e8, 라]
                    c, d = {}, {}
                    if "d" in 부분:
                        for n in ((128, 512, 1024) if 크기 == "XL" else (1024,)):
                            ids = 긴[:n]
                            R.데우기(엔진들, lambda e: e.프롬프트(ids), res["12d 프롬프트 속도"]["실패"])
                            c[str(n)] = R.번갈아(엔진들, lambda e: e.잰_프롬프트(ids), 7, res["12d 프롬프트 속도"]["실패"])
                            바닥 = K9.바닥ms(크기, n, 2) + (12 if 크기 == "small" else 48) * K10.어텐션바닥us(D // 64, n) / 1000
                            c[str(n)]["바닥 ms"] = round(바닥, 2)
                            c[str(n)]["바닥 대비"] = round(c[str(n)][e9.이름] / 바닥, 2)
                            print("12d", 열쇠, n, c[str(n)], flush=True)
                        res["12d 프롬프트 속도"][열쇠] = c
                    if "e" in 부분:
                        for 이름, ids in (("짧은 문맥 (문장 1)", prompts[0]), ("문맥 960", 긴[:960])):
                            R.데우기(엔진들, lambda e: e.생성(ids, N), res["12e 생성 속도"]["실패"])
                            t1, _ = K12.세묶음(엔진들, lambda e: e.잰_생성(ids, 1), res["12e 생성 속도"]["실패"])
                            t64, 묶 = K12.세묶음(엔진들, lambda e: e.잰_생성(ids, N), res["12e 생성 속도"]["실패"])
                            d[이름] = {k: round((t64[k] - t1[k]) / (N - 1), 4) for k in t1 if k in t64}
                            print("12e", 열쇠, 이름, d[이름], flush=True)
                        d["오류 칸"] = e9.m.오류칸()
                        res["12e 생성 속도"][열쇠] = d
                    라.닫기(); e8.m.닫기()
                    del e8, 라
                if "c" in 부분 and 크기 == "XL" and fmt == "q8_0":
                    e9.m.토큰넣기(긴[:1024]); e9.m.계산(1, 1024, 0, "끝"); e9.m.dr.맞추기()
                    t1_ = K10.어텐션시간us(e9.m, 1024)
                    t2_ = K10.어텐션시간us(e9.m, 1024, "정수어텐션둘")
                    바닥 = K10.어텐션바닥us(25, 1024)
                    res["12c 어텐션 효율"]["XL 1024 (머리 25)"] = {"정수어텐션 µs": round(t1_, 1), "정수어텐션둘 µs": round(t2_, 1), "바닥 µs": round(바닥, 1),
                                                            "바닥 대비": round(min(t1_, t2_) / 바닥, 2), "통과": min(t1_, t2_) <= 2 * 바닥}
                    print("12c", res["12c 어텐션 효율"]["XL 1024 (머리 25)"], flush=True)
                e9.m.닫기()
                del e9
                K9.비우기()
                저장()
    # ── 긴 문맥 (합성) ──
    rng2 = np.random.default_rng(1)
    wq = GR.gpt2정수(긴GGUF) if 부분 & set("ace") else None
    if "a" in 부분:
        e긴 = R.글엔진(wq, KV형식="정수", 자리수=2, 최대행=1024, 최대문장=1, 최대길이=102400, 로짓행=16)
        res["12a 계약 (비트)"]["합성 긴 — 갈래 판 · 생성 판 대 CPU 참조와 차례 판"] = 긴대조(e긴.m, np.random.default_rng(121), (98000, 32768, 8192, 100),
                                                                                    (5, 16, 64, 128, 192))
        res["12a 계약 (비트)"]["합성 긴 — 생성 메가커널 대 따로"] = 메가대조(e긴.m, np.random.default_rng(122), (300, 5000, 70000, 100000))
        res["12a 계약 (비트)"]["합성 긴 — 오류 칸"] = e긴.m.오류칸()
        e긴.m.닫기()
        del e긴
        K9.비우기()
        저장()
    if "c" in 부분:
        e긴 = R.글엔진(wq, KV형식="정수", 자리수=2, 최대행=16384, 최대문장=1, 최대길이=16384, 로짓행=16)
        m = e긴.m
        ids전체 = [int(x) for x in rng2.integers(0, 50257, 16384)]
        m.토큰넣기(ids전체); m.계산(1, 16384, 0, 1); m.dr.맞추기()
        t1_ = K10.어텐션시간us(m, 16384)
        t2_ = K10.어텐션시간us(m, 16384, "정수어텐션둘")
        바닥 = K10.어텐션바닥us(12, 16384)
        res["12c 어텐션 효율"]["합성 small 16384 (머리 12)"] = {"정수어텐션 µs": round(t1_, 1), "정수어텐션둘 µs": round(t2_, 1), "바닥 µs": round(바닥, 1),
                                                            "바닥 대비": round(min(t1_, t2_) / 바닥, 2), "통과": min(t1_, t2_) <= 2 * 바닥}
        print("12c", res["12c 어텐션 효율"]["합성 small 16384 (머리 12)"], flush=True)
        m.닫기()
        del e긴, m
        K9.비우기()
        저장()
    if "e" in 부분:
        d긴 = {}
        ids전체 = [int(x) for x in np.random.default_rng(1).integers(0, 50257, 102400)]
        e긴 = R.글엔진(wq, KV형식="정수", 자리수=2, 최대행=32768, 최대문장=1, 최대길이=32768, 로짓행=16)
        e긴.이름 = "글 q8_0 정수 KV (합성 긴)"
        라긴 = R.라마엔진(일, "llama.cpp q8_0 (합성 긴)", 긴GGUF, n_ctx=32768, n_batch=2048)
        엔진들 = [e긴, 라긴]
        ids = ids전체[:32768 - 64]
        R.데우기(엔진들, lambda e: e.생성(ids, N), res["12e 생성 속도"]["실패"])
        t1, _ = K12.세묶음(엔진들, lambda e: e.잰_생성(ids, 1), res["12e 생성 속도"]["실패"])
        t64, 묶 = K12.세묶음(엔진들, lambda e: e.잰_생성(ids, N), res["12e 생성 속도"]["실패"])
        d긴["문맥 32704"] = {k: round((t64[k] - t1[k]) / (N - 1), 4) for k in t1 if k in t64}
        print("12e 긴 32704", d긴["문맥 32704"], flush=True)
        라긴.닫기(); e긴.m.닫기()
        del e긴, 라긴
        K9.비우기()
        ids = ids전체[:102400]
        라긴 = R.라마엔진(일, "llama.cpp q8_0 (합성 긴)", 긴GGUF, n_ctx=102400, n_batch=2048)
        라긴.생성(ids[:-64], N)
        t1 = np.median([라긴.잰_생성(ids[:-64], 1) for _ in range(3)]); t64 = np.median([라긴.잰_생성(ids[:-64], N) for _ in range(3)])
        d긴["문맥 102336 (따로)"] = {라긴.이름: round(float((t64 - t1) / (N - 1)), 4)}
        라긴.닫기()
        del 라긴
        e긴 = R.글엔진(wq, KV형식="정수", 자리수=2, 최대행=102400, 최대문장=1, 최대길이=102400, 로짓행=16)
        e긴.이름 = "글 q8_0 정수 KV (합성 긴)"
        e긴.생성(ids[:-64], N)
        t1 = np.median([e긴.잰_생성(ids[:-64], 1) for _ in range(3)]); t64 = np.median([e긴.잰_생성(ids[:-64], N) for _ in range(3)])
        d긴["문맥 102336 (따로)"][e긴.이름] = round(float((t64 - t1) / (N - 1)), 4)
        d긴["오류 칸"] = e긴.m.오류칸()
        print("12e 긴 102336", d긴["문맥 102336 (따로)"], flush=True)
        e긴.m.닫기()
        del e긴
        K9.비우기()
        res["12e 생성 속도"]["합성 긴"] = d긴
        저장()
    if "f" in 부분:
        res["12f 지속 사용 — 자라는 대화"] = 자라는대화(일)
        print("12f", {k: v for k, v in res["12f 지속 사용 — 자라는 대화"].items() if k != "차례들"}, flush=True)
        K9.비우기()
        저장()
    if "g" in 부분:
        res["12g 지속 사용 — 오래 돌리기"] = 오래돌리기(일)
        print("12g", res["12g 지속 사용 — 오래 돌리기"]["통과"], flush=True)
        K9.비우기()
        저장()
    if 일 is not None:
        일.끝()
    # ── 판정 ──
    통과 = {}
    a = res["12a 계약 (비트)"]
    if a:
        통과["12a"] = all(v["통과"] for k, v in a.items() if isinstance(v, dict) and "통과" in v) and a.get("합성 긴 — 오류 칸", 0) == 0
    if res["12b 타일 효율"]:
        통과["12b"] = all(v["통과"] for v in res["12b 타일 효율"].values())
    if res["12c 어텐션 효율"]:
        통과["12c"] = all(v["통과"] for v in res["12c 어텐션 효율"].values())
    c, d = res["12d 프롬프트 속도"], res["12e 생성 속도"]
    열쇠들 = [f"{크기} {fmt}" for 크기 in ("small", "XL") for fmt in 형식들]
    글 = lambda k: f"글 {k.split()[1]} 정수 KV"
    옛 = lambda k: f"글 {k.split()[1]} 자리 둘"
    라 = lambda k: f"llama.cpp {k.split()[1]}"
    참 = lambda k: c.get(f"PyTorch f16 참고선 {k.split()[0]}", {})
    if all(k in c for k in 열쇠들):
        통과["12d"] = (not c["실패"] and all(c[k][n][글(k)] < c[k][n][라(k)] and c[k][n][글(k)] < 참(k).get(n, 1e9) for k in 열쇠들 for n in c[k]
                                          if n not in ("바닥 ms", "바닥 대비")) and all(c[k]["1024"][글(k)] < 4.0 for k in 열쇠들 if k.startswith("small")))
    긴글, 긴라 = "글 q8_0 정수 KV (합성 긴)", "llama.cpp q8_0 (합성 긴)"
    if all(k in d for k in 열쇠들) and "합성 긴" in d:
        통과["12e"] = (not d["실패"] and all(v[글(k)] < v[라(k)] and v[글(k)] <= 1.03 * v[옛(k)] for k in 열쇠들 for kk, v in d[k].items() if kk != "오류 칸") and
                      all(d["합성 긴"][kk][긴글] < d["합성 긴"][kk][긴라] for kk in ("문맥 32704", "문맥 102336 (따로)")))
    if res["12f 지속 사용 — 자라는 대화"]:
        통과["12f"] = res["12f 지속 사용 — 자라는 대화"]["통과"]
    if res["12g 지속 사용 — 오래 돌리기"]:
        통과["12g"] = res["12g 지속 사용 — 오래 돌리기"]["통과"]
    res["통과"] = 통과
    저장()
    print(json.dumps(통과, ensure_ascii=False))


if __name__ == "__main__":
    main()
