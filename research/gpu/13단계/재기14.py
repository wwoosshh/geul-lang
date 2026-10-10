#!/usr/bin/env python3
"""13단계 재기 — 두 층 접기: 긴 문맥의 짧은 덩이까지 (docs/17 §7 "13단계" 의 판정 그대로).

  build/감사venv/Scripts/python -I research/gpu/13단계/재기14.py [a b c d e p …] [small XL]

부분을 고르지 않으면 모두. 13단계가 바꾼 것(정수 KV 모듈만):
  계약 — 접기를 두 층으로(묶음 = 조각 16 = 위치 1024): 묶음 안에서 조각을, 그다음 묶음들을 차례로 같은 식으로. 위치 1024 이하에서는
    9~12단계와 비트까지 같다(묶음 하나).
  커널 — 정수접기(생성: 정수조각접기 · 생성 메가커널의 접는 블록)를 두 층으로; 새 프롬프트 판 넷: 정수어텐션묶음(질의 64) ·
    정수어텐션갈래묶음(질의 16) — 블록이 (머리, 질의 조각, 묶음) 하나의 묶음 상태를 묶음칸에, 정수묶음접기 — (행, 머리)마다 묶음 상태를
    접어 출력 자리로, 정수어텐션두층 — 블록이 (머리, 질의 64)의 조각을 차례로 돌며 묶음 끝마다 누적 상태(두층칸)와 접는다.
  호스트 — 최대길이가 1024 를 넘는 엔진만 새 판(행 ≤ 묶음판행 이면 묶음 판 — 위치마다 질의 16/64 판과 격자를 고른다, 아니면 두 층 판);
    조각칸을 행 넷 이상으로(행 넷까지의 생성 판이 행마다 쓴다 — 최대문장 1 엔진에서 덩이 2 ~ 4 가 넘쳤다).
판정 13a ~ 13e 는 docs/17 의 13단계 표. 결과는 결과/13단계.json.
"""
import gc
import json
import os
import shutil
import subprocess
import sys
import time
import ctypes

import numpy as np
import torch

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # 경고 · 오류도 UTF-8 로(한글 경로가 cp949 로 깨지지 않게)
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
for d in ("12단계", "11단계", "10단계", "9단계", "8단계", "7단계", "6단계", "5단계", "4단계", "3단계"):
    sys.path.insert(0, os.path.join(ROOT, "research", "gpu", d))
import 커널생성 as K          # noqa: E402
import gguf읽기 as GR         # noqa: E402
import 재기4 as R             # noqa: E402
import 재기 as R3             # noqa: E402
import 재기7 as K7            # noqa: E402
import 재기9 as K9            # noqa: E402
import 재기10 as K10          # noqa: E402
import 재기12 as K12          # noqa: E402
import 재기13 as K13          # noqa: E402
import 정수계약 as C          # noqa: E402

G = R.G
형식들 = ("q8_0", "q4_0")
결과 = os.path.join(HERE, "결과", "13단계.json")
N = 64
긴GGUF = K10.긴GGUF
긴F32 = os.path.join(ROOT, "build", "gpt2-long", "gpt2-long100k-f32.gguf")
u64, i64, f32 = ctypes.c_uint64, ctypes.c_int64, np.float32
옛커밋 = "2256b39"                                   # 12단계의 커밋 — 13a(1)의 견줄 판
옛나무 = os.path.join(ROOT, "build", "13단계작업", "옛판")


# ── 13a (1): 12단계 모듈과 같은 출력 ─────────────────────────────────────────────────────────────

def 옛나무만들기():
    """커밋 옛커밋 의 research/gpu · ref 를 build/13단계작업/옛판 에 풀고, 모델 파일을 이어 둔다(하드 링크 · 정션 — build 의 것과 같은 파일)."""
    if os.path.isdir(옛나무):
        # 이어 둔 것(정션 · 하드 링크)을 먼저 링크만 지운다 — 지우기가 정션을 따라가 build 의 모델 폴더를 건드리지 않게
        b = os.path.join(옛나무, "build")
        for 이름 in os.listdir(b):
            p = os.path.join(b, 이름)
            if os.path.isjunction(p) or os.path.islink(p):
                os.rmdir(p) if os.path.isjunction(p) else os.unlink(p)
            elif os.path.isfile(p):
                os.unlink(p)
        assert not any(os.path.isjunction(os.path.join(b, x)) for x in os.listdir(b))
        shutil.rmtree(옛나무)
    os.makedirs(os.path.join(옛나무, "build"))
    tar = subprocess.run(["git", "archive", 옛커밋, "research/gpu", "ref"], cwd=ROOT, capture_output=True, check=True).stdout
    import io
    import tarfile
    tarfile.open(fileobj=io.BytesIO(tar)).extractall(옛나무, filter="data")
    for f in ("gpt2-q8_0.gguf", "gpt2-q4_0.gguf", "gpt2-xl-q8_0.gguf", "gpt2-xl-q4_0.gguf"):
        os.link(os.path.join(ROOT, "build", f), os.path.join(옛나무, "build", f))
    for d in ("gpt2", "gpt2-xl", "gpt2-long"):
        subprocess.run(["cmd", "/c", "mklink", "/J", os.path.join(옛나무, "build", d), os.path.join(ROOT, "build", d)], check=True,
                       capture_output=True)


def 옛판비교():
    """평가글 469 행의 로짓 전부와 64 걸음 생성(토큰 · 걸음마다의 로짓)을 12단계의 나무(커밋 2256b39 의 글gpt2 · .gl)와 이 나무에서 따로 계산해
    (옛판출력.py — 프로세스 따로) 비트 대조. small · XL × Q8_0 · Q4_0."""
    옛나무만들기()
    py = sys.executable
    출 = {}
    for 이름, 나무 in (("12단계", 옛나무), ("13단계", ROOT)):
        f = os.path.join(ROOT, "build", "13단계작업", f"옛판출력_{이름}.npz")
        subprocess.run([py, "-I", os.path.join(HERE, "옛판출력.py"), 나무, f, "small,XL", "q8_0,q4_0"], check=True)
        출[이름] = np.load(f)
    a, b = 출["12단계"], 출["13단계"]
    out = {}
    for k in a.files:
        x, y = a[k], b[k]
        out[k] = int((x.view(np.int32) != y.view(np.int32)).sum()) if x.dtype == np.float32 else int((x != y).sum())
    out["통과"] = all(v == 0 for k, v in out.items() if "오류 칸" not in k) and all(int(b[k]) == 0 for k in b.files if "오류 칸" in k)
    return out


# ── 13a (2): 합성 긴 모델의 새 판 대 새 CPU 참조 ──────────────────────────────────────────────────

def 긴대조14(m, rng, 맥락들, 덩이들, 참조머리=(0, 7)):
    """합성 긴 모델의 엔진 m 의 커널로, 무작위 q · k · v 로 캐시를 위치 0 … C+M−1 까지 채우고(KV정수로) 덩이 M 행(위치 C …)의 어텐션을 새 판
    모두로: 묶음 판 둘(질의 64 · 질의 16) + 묶음 접기, 두 층 차례 판 — (1) 모든 머리에서 서로 같은가(출력 자리 · 정보), (2) 머리 둘의 CPU 참조
    (정수계약.어텐션 — 두 층)와 같은가, 생성 판(정수조각어텐션 + 정수조각접기 — 행 64 개씩)의 O/L 도, (3) C + M ≤ 1024 면 12단계 차례 판과."""
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

    def kv정수로(a, n, 자q, 정q):
        run(G._띄움(k["KV정수로"], ((3 * D // 32 + 31) // 32, n), (256, 1),
                    [u64(g입력 + a * 3 * D * 4), u64(자q), u64(정q)] + KV + [i64(n), i64(n), i64(a), i64(최대길이)]))
    for a in range(0, 최대행, 덩큰):
        kv정수로(a, min(덩큰, 최대행 - a), 자q큰, 정q큰)
    dr.맞추기()
    M최대 = max(덩이들)
    폭 = (M최대 + 63) // 64 * 64
    자q, 정q = zero(2 * M최대 * D), zero(D // 32 * 폭 * 4)
    판이름 = ("묶음64", "묶음16", "두층", "차례")
    출 = {nm: (zero(2 * M최대 * D), zero(D // 32 * 폭 * 4)) for nm in 판이름}
    조각칸, 출력 = zero(64 * NH * (최대길이 // 64) * 68 * 4), zero(64 * D * 4)

    def 띄움들(판, C0, M):
        자, 정 = 출[판]
        G묶 = (C0 + M - 1) // 1024 + 1
        접기 = G._띄움(k["정수묶음접기"], (NH, M), (64, 1), [u64(m.묶음칸), u64(정), u64(자), i64(M), i64(M), i64(C0), i64(최대길이)])
        if 판 == "묶음64":
            return [G._띄움(k["정수어텐션묶음"], ((M + 63) // 64 * NH * G묶, 1), (128, 1),
                            [u64(자q), u64(정q)] + KV + [u64(m.묶음칸), i64(M), i64(M), i64(C0), i64(최대길이)]), 접기]
        if 판 == "묶음16":
            return [G._띄움(k["정수어텐션갈래묶음"], ((M + 15) // 16 * NH * G묶, 1), (256, 1),
                            [u64(자q), u64(정q)] + KV + [u64(m.묶음칸), i64(M), i64(M), i64(C0), i64(최대길이)]), 접기]
        if 판 == "두층":
            return [G._띄움(k["정수어텐션두층"], (NH, (M + 63) // 64), (128, 1),
                            [u64(자q), u64(정q)] + KV + [u64(m.묶음칸), u64(정), u64(자), i64(M), i64(M), i64(C0), i64(최대길이)])]
        return [G._띄움(k["정수어텐션"], (NH, (M + 63) // 64), (128, 1),
                        [u64(자q), u64(정q)] + KV + [u64(정), u64(자), i64(M), i64(M), i64(C0), i64(최대길이)])]
    out = {"새 판끼리 (모든 머리)": {}, "CPU 참조 (머리 둘)": {}, "12단계 차례 판과 (위치 1024 이하)": {}}
    for C0 in 맥락들:
        for M in 덩이들:
            if C0 + M > 최대길이:
                continue
            kv정수로(C0, M, 자q, 정q)
            판들 = ["묶음64", "묶음16", "두층"] + (["차례"] if C0 + M <= 1024 else [])
            for 판 in 판들:
                dr.확인(cu.cuMemsetD8_v2(u64(출[판][0]), 0x5A, ctypes.c_size_t(2 * M최대 * D)))
                dr.확인(cu.cuMemsetD8_v2(u64(출[판][1]), 0x5A, ctypes.c_size_t(D // 32 * 폭 * 4)))
                for x in 띄움들(판, C0, M):
                    run(x)
            dr.맞추기()
            정보폭 = (M + 63) // 64 * 64
            o = {판: (dr.내리기(출[판][0], np.empty(2 * M * D, np.int8)).reshape(2, M, D),
                     dr.내리기(출[판][1], np.empty(D // 32 * 정보폭, np.int32)).reshape(D // 32, 정보폭)[:, :M]) for 판 in 판들}
            칸 = f"맥락 {C0} 덩이 {M}"
            out["새 판끼리 (모든 머리)"][칸] = {f"묶음64 대 {판}": [int((o["묶음64"][0] != o[판][0]).sum()), int((o["묶음64"][1] != o[판][1]).sum())]
                                          for 판 in ("묶음16", "두층")}
            if "차례" in o:
                out["12단계 차례 판과 (위치 1024 이하)"][칸] = [int((o["묶음64"][0] != o["차례"][0]).sum()), int((o["묶음64"][1] != o["차례"][1]).sum())]
            q_, kk_, v_ = 입력[:C0 + M, :D], 입력[:C0 + M, D:2 * D], 입력[:C0 + M, 2 * D:]
            ref = np.zeros((M, D), f32)
            t0 = time.time()
            for h in 참조머리:
                sl = slice(64 * h, 64 * h + 64)
                ref[:, sl] = C.어텐션(q_[:, sl], kk_[:, sl], v_[:, sl], 첫행=C0)
            초 = round(time.time() - t0, 1)
            Do, Eo = C.자리로(ref, 2)
            rb = C.낱말차례(Do.reshape(2, M, D // 32, 32)).reshape(2, M, D).astype(np.int8)
            ri = ((((137 + Eo.T) << 23) + 0x400000).astype(np.int32))
            cols = np.zeros(D, bool)
            bl = np.zeros(D // 32, bool)
            for h in 참조머리:
                cols[64 * h:64 * h + 64] = True
                bl[2 * h:2 * h + 2] = True
            r = {판: [int((o[판][0][:, :, cols] != rb[:, :, cols]).sum()), int((o[판][1][bl] != ri[bl]).sum())] for 판 in ("묶음64", "묶음16", "두층")}
            go = np.zeros((M, D), f32)
            for a in range(0, M, 64):                     # 생성 판 — 행 64 개씩(그 행들의 q 를 다시 만들어 — 캐시는 같은 값으로 다시 쓴다)
                n = min(64, M - a)
                kv정수로(C0 + a, n, 자q, 정q)
                run(G._띄움(k["정수조각어텐션"], (((C0 + a + n - 1) // 64 + 1 + 7) // 8, n * NH), (256, 1),
                            [u64(자q), u64(정q)] + KV + [u64(조각칸), i64(n), i64(n), i64(C0 + a), i64(최대길이)]))
                run(G._띄움(k["정수조각접기"], (n * NH, 1), (256, 1), [u64(조각칸), u64(출력), i64(n), i64(n), i64(C0 + a), i64(최대길이)]))
                dr.맞추기()
                go[a:a + n] = dr.내리기(출력, np.empty(64 * D, f32)).reshape(64, D)[:n]
            r["생성 판 O/L"] = int((go[:, cols].view(np.int32) != ref[:, cols].view(np.int32)).sum())
            r["CPU 참조 초"] = 초
            out["CPU 참조 (머리 둘)"][칸] = r
            print("13a 긴", 칸, out["새 판끼리 (모든 머리)"][칸], r, flush=True)
    out["오류 칸"] = m.오류칸()
    out["통과"] = (all(x == 0 for v in out["새 판끼리 (모든 머리)"].values() for p in v.values() for x in p) and
                 all(x == 0 for v in out["12단계 차례 판과 (위치 1024 이하)"].values() for x in v) and
                 all((x == 0 if not isinstance(x, list) else all(y == 0 for y in x))
                     for v in out["CPU 참조 (머리 둘)"].values() for kk, x in v.items() if kk != "CPU 참조 초") and out["오류 칸"] == 0)
    return out


def 캐시앞(m, l, n):
    """층 l 의 캐시 중 위치 0 … n−1 의 바이트(키 · 값 · 지수) — [머리] 마다 이어 붙인 것."""
    D, NH, L = m.D, m.NH, m.최대길이
    dr = m.dr
    키, 값, 키지, 값지 = [], [], [], []
    for h in range(NH):
        for j in range(2):                                  # 키 [머리][자리 2][L][64]
            키.append(dr.내리기(m.kc[l] + ((h * 2 + j) * L) * 64, np.empty(n * 64, np.int8)).copy())
        값.append(dr.내리기(m.vc[l] + h * (L // 32) * 4096, np.empty(n // 32 * 4096, np.int8)).copy())     # 값 [머리][L/32][2][64][32]
        키지.append(dr.내리기(m.ke[l] + h * L * 2, np.empty(n * 2, np.uint8)).copy())
        값지.append(dr.내리기(m.ve[l] + h * L * 2, np.empty(n * 2, np.uint8)).copy())
    return [np.concatenate(x) for x in (키, 값, 키지, 값지)]


def 나눠넣기대조(wq, rng, n=8192):
    """덩이를 여러 길이로 나눠 넣은 것(이어넣기 — 생성 판(행 넷까지 — 덩이 1 ~ 4), 묶음 판(질의 16 · 64 — 같은 덩이 48 을 위치 4096 너머까지
    되풀이해 그래프의 위치 마디가 판 · 격자를 바꾸게), 그리고 1024 까지의 덩이)과 한 번에 넣은 것(두 층 차례 판)이 위치 n 의 마지막 행 로짓 ·
    캐시 바이트(층 모두, 위치 0 … n−1)까지 같은가 — 합성 긴 모델(최대길이 102400)."""
    m = G.글GPT2(wq, KV형식="정수", 자리수=2, 최대행=n, 최대문장=1, 최대길이=102400, 로짓행=16)
    m.판미리고르기()
    ids = [int(x) for x in rng.integers(0, 50257, n)]
    덩이들 = [1000, 1, 2, 3, 4, 5, 16, 17, 32, 33] + [48] * 70 + [64, 100, 128, 192, 256, 300, 512, 1024, 1024]
    덩이들.append(n - sum(덩이들))
    assert 덩이들[-1] > 0

    def 비우기():
        NL = len(m.kc)
        for 바탕, 크기 in ((m.kc바탕, NL * (m.kc[1] - m.kc[0])), (m.vc바탕, NL * (m.vc[1] - m.vc[0])),
                         (m.ke바탕, NL * (m.ke[1] - m.ke[0])), (m.ve바탕, NL * (m.ve[1] - m.ve[0]))):
            m.dr.확인(m.dr.cu.cuMemsetD8_v2(u64(바탕), 0, ctypes.c_size_t(크기)))
        m.dr.맞추기()
    비우기()
    m.토큰넣기(ids)
    m.계산(1, n, 0, "끝", 출력자리=m.생성칸)
    한번 = m.로짓(1).copy()
    c한번 = [캐시앞(m, l, n) for l in range(len(m.kc))]
    비우기()
    a = 0
    for L_ in 덩이들:
        m.이어넣기(ids[a:a + L_], a)
        a += L_
    나눔 = m.로짓(1).copy()
    c나눔 = [캐시앞(m, l, n) for l in range(len(m.kc))]
    out = {"덩이 수": len(덩이들), "덩이들": 덩이들, "마지막 행 로짓 다른 칸": int((한번.view(np.int32) != 나눔.view(np.int32)).sum()),
           "캐시 다른 바이트 (층 모두)": int(sum(int((x != y).sum()) for a_, b_ in zip(c한번, c나눔) for x, y in zip(a_, b_))),
           "오류 칸": m.오류칸()}
    out["통과"] = out["마지막 행 로짓 다른 칸"] == 0 and out["캐시 다른 바이트 (층 모두)"] == 0 and out["오류 칸"] == 0
    m.닫기()
    return out


# ── 13b 정확도 ───────────────────────────────────────────────────────────────────────────────

@torch.no_grad()
def 정확도(위치들=(16384, 65536), 머리들=(0, 7), 씨=14):
    """합성 긴 모델 층 0 의 q · k · v 를 fp64 로(임베딩 → 층정규화 → c_attn — F32 GGUF), 위치 n 의 마지막 64 행 × 머리들: 어텐션 출력의 fp64
    참값 대비 행 상대차 ‖출력 − 참‖ / ‖참‖ — 새 계약(두 층) · 옛 계약(한 층)의 CPU 참조(정수계약.어텐션, 짧은실수 q · k · v)."""
    g = GR.GGUF(긴F32)
    dev = "cuda"
    W = {k_: torch.from_numpy(g.풀기(n_)).to(dev).double() for k_, n_ in
         (("wte", "token_embd.weight"), ("wpe", "position_embd.weight"), ("lw", "blk.0.attn_norm.weight"), ("lb", "blk.0.attn_norm.bias"),
          ("W", "blk.0.attn_qkv.weight"), ("b", "blk.0.attn_qkv.bias"))}
    del g
    D = 768
    out = {}
    rng = np.random.default_rng(씨)
    for n in 위치들:
        ids = torch.from_numpy(rng.integers(0, 50257, n)).to(dev)
        x = W["wte"][ids] + W["wpe"][:n]
        h = torch.nn.functional.layer_norm(x, (D,), W["lw"], W["lb"], 1e-5)
        qkv = torch.addmm(W["b"], h, W["W"].T)                      # GGUF 의 attn_qkv 는 [출력][입력]
        q, k_, v = qkv[:, :D], qkv[:, D:2 * D], qkv[:, 2 * D:]
        상대 = {"새 계약 (두 층)": [], "옛 계약 (한 층)": []}
        for hd in 머리들:
            sl = slice(64 * hd, 64 * hd + 64)
            Q, Kh, V = q[:, sl], k_[:, sl], v[:, sl]
            S = (Q[n - 64:] @ Kh.T) * 0.125                           # [64][n] — 행 r 은 키 0 … r
            r = torch.arange(n - 64, n, device=dev)[:, None]
            S = S.masked_fill(torch.arange(n, device=dev)[None, :] > r, float("-inf"))
            참 = (torch.softmax(S, 1) @ V).cpu().numpy()
            Q32, K32, V32 = (t.float().cpu().numpy() for t in (Q, Kh, V))
            for 이름, 묶음 in (("새 계약 (두 층)", 16), ("옛 계약 (한 층)", None)):
                o = C.어텐션(Q32, K32, V32, 묶음=묶음, 첫행=n - 64).astype(np.float64)
                상대[이름] += list(np.linalg.norm(o - 참, axis=1) / np.linalg.norm(참, axis=1))
        a_, b_ = float(np.median(상대["새 계약 (두 층)"])), float(np.median(상대["옛 계약 (한 층)"]))
        out[f"위치 {n}"] = {"새 계약 중앙값": a_, "옛 계약 중앙값": b_, "새 / 옛": round(a_ / b_, 4), "새 최대": float(np.max(상대["새 계약 (두 층)"])),
                          "옛 최대": float(np.max(상대["옛 계약 (한 층)"])), "통과": a_ <= b_ * 1.05}
        print("13b", n, out[f"위치 {n}"], flush=True)
    del W
    torch.cuda.empty_cache()
    out["통과"] = all(v["통과"] for v in out.values() if isinstance(v, dict))
    return out


# ── 13c 긴 문맥의 넣기 ───────────────────────────────────────────────────────────────────────────

def 바닥ms(C_):
    """짧은 덩이 넣기의 바닥(docs/17 13단계 — K · V 를 한 번 읽기: 층 12 × 머리 12 × 위치 × 256 바이트 / 504 GB/s, 가중치 0.17 ms 더해)."""
    return 12 * 12 * C_ * 256 / 504e9 * 1000 + 0.17


def 넣기재기(일, Cs=(8192, 32768, 65536, 98304), ms=(16, 64, 128, 256, 512, 1024), 씨=13):
    """12단계/넣기재기.py 와 같은 재는 법 — 합성 긴 모델, 글과 llama.cpp 를 번갈아: 문맥을 1024 덩이로 C 까지 채운 뒤 덩이 m 을 세 번(문맥은 m 씩
    는다), 세 번의 중앙값. 위치가 넘치는 칸은 뺀다(23 칸)."""
    wq = GR.gpt2정수(긴GGUF)
    글 = R.글엔진(wq, KV형식="정수", 자리수=2, 최대행=1024, 최대문장=1, 최대길이=102400, 로짓행=16)
    글.m.판미리고르기()
    라 = R.라마엔진(일, "llama.cpp q8_0", 긴GGUF, n_ctx=102400, n_batch=1024)
    rng = np.random.default_rng(씨)
    끝 = {"글": 0, "라": 0}
    위치, 처음 = 0, True
    칸들, 기록 = {}, []
    for C_ in Cs:
        while 위치 + 1024 <= C_:
            새 = [int(x) for x in rng.integers(0, 50257, 1023)]
            for 이름, e in (("글", 글), ("라", 라)):
                r = e.대화([[끝[이름]] + 새], 1, 처음=처음)[0]
                끝[이름] = r["끝토큰"]
            처음 = False
            위치 += 1024
        for m_ in ms:
            if 위치 + 3 * m_ + 8 > 102400:
                break
            줄들 = []
            for 번 in range(3):
                새 = [int(x) for x in rng.integers(0, 50257, m_ - 1)]
                줄 = {"문맥": 위치, "덩이": m_, "번": 번}
                for 이름, e in (("글", 글), ("라", 라)):
                    r = e.대화([[끝[이름]] + 새], 1, 처음=False)[0]
                    끝[이름] = r["끝토큰"]
                    줄[이름] = round(r["넣기 ms"], 3)
                위치 += m_
                줄들.append(줄)
            기록 += 줄들
            g_, l_ = float(np.median([x["글"] for x in 줄들])), float(np.median([x["라"] for x in 줄들]))
            칸 = {"문맥(재기 시작)": 줄들[0]["문맥"], "글 ms": round(g_, 2), "llama.cpp ms": round(l_, 2), "글 / llama.cpp": round(g_ / l_, 3),
                 "통과": g_ < l_}
            if m_ == 16:
                칸["바닥 ms"] = round(바닥ms(줄들[0]["문맥"]), 2)
                칸["글 / 바닥"] = round(g_ / 칸["바닥 ms"], 2)
                칸["llama.cpp / 바닥"] = round(l_ / 칸["바닥 ms"], 2)
            칸들[f"{C_} × {m_}"] = 칸
            print("13c", C_, m_, 칸, flush=True)
    오류 = 글.m.오류칸()
    라.닫기()
    글.m.닫기()
    return {"칸": 칸들, "칸 수": len(칸들), "오류 칸": 오류, "기록": 기록,
            "통과": len(칸들) == 23 and all(v["통과"] for v in 칸들.values()) and 오류 == 0}


# ── 13e 프롬프트 어텐션 ──────────────────────────────────────────────────────────────────────────

def 두층시간(n=16384):
    """합성 small n 프롬프트의 어텐션 한 층(층 0 캐시) — 두 층 차례 판(정수어텐션두층)과 12단계 차례 판(정수어텐션 — 같은 실행에서 견주기용).
    CUDA 이벤트 — 다섯 번씩 일곱 묶음의 중앙값(K10.어텐션시간us 와 같은 재는 법)."""
    wq = GR.gpt2정수(긴GGUF)
    e = R.글엔진(wq, KV형식="정수", 자리수=2, 최대행=n, 최대문장=1, 최대길이=n, 로짓행=16)
    m = e.m
    ids = [int(x) for x in np.random.default_rng(1).integers(0, 50257, n)]
    m.토큰넣기(ids); m.계산(1, n, 0, 1); m.dr.맞추기()
    cu = m.dr.cu
    KV = [u64(m.kc[0]), u64(m.vc[0]), u64(m.ke[0]), u64(m.ve[0])]
    xs = {"정수어텐션두층": G._띄움(m.k["정수어텐션두층"], (m.NH, (n + 63) // 64), (128, 1),
                                 [u64(m.자릿값q), u64(m.정보q)] + KV + [u64(m.묶음칸), u64(m.정보), u64(m.자릿값), i64(n), i64(n), i64(0), i64(m.최대길이)]),
          "정수어텐션 (12단계 판 — 견주기용)": G._띄움(m.k["정수어텐션"], (m.NH, (n + 63) // 64), (128, 1),
                                            [u64(m.자릿값q), u64(m.정보q)] + KV + [u64(m.정보), u64(m.자릿값), i64(n), i64(n), i64(0), i64(m.최대길이)])}
    e0, e1 = ctypes.c_void_p(), ctypes.c_void_p()
    cu.cuEventCreate(ctypes.byref(e0), 0); cu.cuEventCreate(ctypes.byref(e1), 0)
    out = {}
    for _ in range(2):                                     # 두 바퀴 — 둘째 바퀴를 적는다(클럭이 오른 뒤)
        for 이름, x in xs.items():
            run = lambda: cu.cuLaunchKernel(x.fn, x.grid[0], x.grid[1], 1, x.block[0], x.block[1], 1, 0, None, x.args, None)
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < 0.3:
                run()
            m.dr.맞추기()
            ts = []
            for _ in range(7):
                cu.cuEventRecord(e0, None)
                for _ in range(5):
                    run()
                cu.cuEventRecord(e1, None); cu.cuEventSynchronize(e1)
                ms_ = ctypes.c_float(); cu.cuEventElapsedTime(ctypes.byref(ms_), e0, e1)
                ts.append(ms_.value / 5)
            out[이름] = round(sorted(ts)[3], 3)
    out["오류 칸"] = m.오류칸()
    m.닫기()
    a_ = out["정수어텐션두층"]
    out.update({"12단계 기록 ms": 11.68, "두층 / 12단계 기록": round(a_ / 11.68, 4), "기준 (≤ 1.03 × 11.68)": round(1.03 * 11.68, 2),
                "11c · 12c 의 기준 10.3 ms 와의 거리": round(a_ / 10.3, 3), "통과": a_ <= 1.03 * 11.68 and out["오류 칸"] == 0})
    return out


# ── 본체 ─────────────────────────────────────────────────────────────────────────────────────

def main():
    부분 = {a for a in sys.argv[1:] if a in tuple("abcdep")}
    부분 = 부분 or set("abcdep")                # p — 12d 의 PyTorch f16 참고선(공식 실행에서 빠뜨려 뒤에 따로 쟀다 — docs/17 진행 기록)
    고름 = [a for a in sys.argv[1:] if a in ("small", "XL")]
    크기들 = tuple(k for k in ("small", "XL") if not 고름 or k in 고름)
    torch.zeros(1, device="cuda")
    res = {"환경": {"torch": torch.__version__, "llama.cpp": "b11496 (000bee54a)", "GPU": torch.cuda.get_device_name(0)},
           "13a 계약 (비트)": {}, "13b 정확도": {}, "13c 긴 문맥의 넣기": {}, "13d 되돌아가지 않음": {"12d 프롬프트 속도": {"실패": {}},
                                                                                "12e 생성 속도": {"실패": {}}},
           "13e 프롬프트 어텐션": {}}
    if os.path.exists(결과):
        res.update(json.load(open(결과, encoding="utf-8")))

    def 저장():
        os.makedirs(os.path.dirname(결과), exist_ok=True)
        json.dump(res, open(결과, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if "a" in 부분:
        res["13a 계약 (비트)"]["8단계까지의 모듈"] = K10.옛모듈같은가("HEAD")
        print("13a 옛 모듈", res["13a 계약 (비트)"]["8단계까지의 모듈"], flush=True)
        res["13a 계약 (비트)"]["12단계 모듈과 같은 출력 (로짓 469 행 · 64 걸음 생성)"] = 옛판비교()
        print("13a 12단계 모듈과", res["13a 계약 (비트)"]["12단계 모듈과 같은 출력 (로짓 469 행 · 64 걸음 생성)"], flush=True)
        저장()
    if "p" in 부분:                                        # 12d 의 PyTorch f16 참고선 — 의미를 지키지 않는 빠른 길(우리 코드와 상관없다)
        dd = res["13d 되돌아가지 않음"]
        for 크기 in 크기들:
            dd["12d 프롬프트 속도"][f"PyTorch f16 참고선 {크기}"] = K12.참고선(크기, (128, 512, 1024))
            print("13d (12d) 참고선", 크기, dd["12d 프롬프트 속도"][f"PyTorch f16 참고선 {크기}"], flush=True)
        저장()
    일 = R.일꾼() if 부분 & set("cd") else None
    평가글 = open(os.path.join(ROOT, "research", "gpu", "5단계", "평가글.txt"), encoding="utf-8").read()
    rng = np.random.default_rng(130)
    if 부분 & set("ad"):
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
                if "a" in 부분:                            # 13a (1) — 12a 그대로(위치 1024 이하의 엔진)
                    a = {}
                    if fmt == "q8_0":
                        w = G.가중치읽기(os.path.join(K9.모델폴더(크기), "model.safetensors"))
                        qkv = K10.층qkv(w, 긴[:1024], 5 if 크기 == "small" else 20, D)
                        del w
                        gc.collect()
                        for 판 in ("정수어텐션", "정수어텐션둘", "정수어텐션갈래"):
                            a[f"어텐션 커널 대 CPU 참조 ({판})"] = K10.커널대조(e9.m, qkv, 1024, 커널=판)
                            print("13a", 열쇠, 판, a[f"어텐션 커널 대 CPU 참조 ({판})"]["통과"], flush=True)
                    a["행렬곱 — CPU 참조 대비 (판 모두)"] = K7.행렬곱시험(e9.m, GR.GGUF(path), rng)
                    a["끝에서 끝 (8단계 비트시험)"] = K9.비트시험(e9, path, rng, prompts, 긴)
                    a["캐시 바이트 — 프롬프트 · 두조각 · 메가커널 대 하나씩"] = K10.끝끝(e9, 평가[:469])
                    a["대화 길 대 한 번에"] = K13.대화대조(e9, rng, [(37, 6), (5, 3), (120, 12), (16, 1), (200, 9), (1, 2), (64, 5), (33, 4), (120, 7),
                                                              (16, 3), (200, 1)])
                    # 13단계에서 고친 조각칸(행 넷까지의 생성 판) — 덩이 2 · 3 · 4 를 섞은 대화(12a 의 목록에 더한 것)
                    a["대화 길 대 한 번에 — 덩이 2 · 3 · 4 (13단계에서 더함)"] = K13.대화대조(e9, rng, [(37, 2), (2, 3), (3, 1), (4, 2), (16, 1), (4, 1), (2, 2),
                                                                                          (3, 4), (64, 1)])
                    a["오류 칸"] = e9.m.오류칸()
                    a["통과"] = (all(v["다른 칸"] == 0 for v in a["행렬곱 — CPU 참조 대비 (판 모두)"].values()) and
                                all(v["통과"] for k_, v in a.items() if isinstance(v, dict) and "통과" in v) and a["오류 칸"] == 0)
                    print("13a", 열쇠, "통과", a["통과"], "대화", a["대화 길 대 한 번에"]["통과"],
                          a["대화 길 대 한 번에 — 덩이 2 · 3 · 4 (13단계에서 더함)"]["통과"], "오류 칸", a["오류 칸"], flush=True)
                    res["13a 계약 (비트)"][열쇠] = a
                    저장()
                if "d" in 부분:                            # 13d — 12d · 12e 그대로(실제 모델)
                    e8 = K9.글엔진(크기, fmt, 2, 최대문장=1)
                    라 = R.라마엔진(일, f"llama.cpp {fmt}", path)
                    엔진들 = [e9, e8, 라]
                    c, d = {}, {}
                    dd = res["13d 되돌아가지 않음"]
                    for n in ((128, 512, 1024) if 크기 == "XL" else (1024,)):
                        ids = 긴[:n]
                        R.데우기(엔진들, lambda e: e.프롬프트(ids), dd["12d 프롬프트 속도"]["실패"])
                        c[str(n)] = R.번갈아(엔진들, lambda e: e.잰_프롬프트(ids), 7, dd["12d 프롬프트 속도"]["실패"])
                        바닥 = K9.바닥ms(크기, n, 2) + (12 if 크기 == "small" else 48) * K10.어텐션바닥us(D // 64, n) / 1000
                        c[str(n)]["바닥 ms"] = round(바닥, 2)
                        c[str(n)]["바닥 대비"] = round(c[str(n)][e9.이름] / 바닥, 2)
                        print("13d (12d)", 열쇠, n, c[str(n)], flush=True)
                    dd["12d 프롬프트 속도"][열쇠] = c
                    for 이름, ids in (("짧은 문맥 (문장 1)", prompts[0]), ("문맥 960", 긴[:960])):
                        R.데우기(엔진들, lambda e: e.생성(ids, N), dd["12e 생성 속도"]["실패"])
                        t1, _ = K12.세묶음(엔진들, lambda e: e.잰_생성(ids, 1), dd["12e 생성 속도"]["실패"])
                        t64, 묶 = K12.세묶음(엔진들, lambda e: e.잰_생성(ids, N), dd["12e 생성 속도"]["실패"])
                        d[이름] = {k_: round((t64[k_] - t1[k_]) / (N - 1), 4) for k_ in t1 if k_ in t64}
                        print("13d (12e)", 열쇠, 이름, d[이름], flush=True)
                    d["오류 칸"] = e9.m.오류칸()
                    dd["12e 생성 속도"][열쇠] = d
                    라.닫기(); e8.m.닫기()
                    del e8, 라
                e9.m.닫기()
                del e9
                K9.비우기()
                저장()
    # ── 합성 긴 모델 ──
    wq = GR.gpt2정수(긴GGUF) if 부분 & set("ad") else None
    if "a" in 부분:
        e긴 = R.글엔진(wq, KV형식="정수", 자리수=2, 최대행=1024, 최대문장=1, 최대길이=102400, 로짓행=16)
        res["13a 계약 (비트)"]["합성 긴 — 새 판 대 새 CPU 참조"] = 긴대조14(e긴.m, np.random.default_rng(131), (100, 2048, 8192, 32768, 98000),
                                                                    (5, 16, 64, 128, 192, 512, 1024))
        저장()
        res["13a 계약 (비트)"]["합성 긴 — 생성 메가커널 대 따로"] = K13.메가대조(e긴.m, np.random.default_rng(132), (300, 5000, 70000, 100000))
        res["13a 계약 (비트)"]["합성 긴 — 오류 칸"] = e긴.m.오류칸()
        e긴.m.닫기()
        del e긴
        K9.비우기()
        res["13a 계약 (비트)"]["합성 긴 — 나눠 넣기 대 한 번에 (위치 8192)"] = 나눠넣기대조(wq, np.random.default_rng(133))
        print("13a 나눠 넣기", {k_: v for k_, v in res["13a 계약 (비트)"]["합성 긴 — 나눠 넣기 대 한 번에 (위치 8192)"].items() if k_ != "덩이들"},
              flush=True)
        K9.비우기()
        저장()
    if "b" in 부분:
        res["13b 정확도"] = 정확도()
        저장()
    if "c" in 부분:
        res["13c 긴 문맥의 넣기"] = 넣기재기(일)
        print("13c 통과", res["13c 긴 문맥의 넣기"]["통과"], flush=True)
        K9.비우기()
        저장()
    if "d" in 부분:                                        # 13d — 12e 의 합성 긴 · 12f · 12g
        d긴 = {}
        dd = res["13d 되돌아가지 않음"]
        ids전체 = [int(x) for x in np.random.default_rng(1).integers(0, 50257, 102400)]
        e긴 = R.글엔진(wq, KV형식="정수", 자리수=2, 최대행=32768, 최대문장=1, 최대길이=32768, 로짓행=16)
        e긴.이름 = "글 q8_0 정수 KV (합성 긴)"
        라긴 = R.라마엔진(일, "llama.cpp q8_0 (합성 긴)", 긴GGUF, n_ctx=32768, n_batch=2048)
        엔진들 = [e긴, 라긴]
        ids = ids전체[:32768 - 64]
        R.데우기(엔진들, lambda e: e.생성(ids, N), dd["12e 생성 속도"]["실패"])
        t1, _ = K12.세묶음(엔진들, lambda e: e.잰_생성(ids, 1), dd["12e 생성 속도"]["실패"])
        t64, 묶 = K12.세묶음(엔진들, lambda e: e.잰_생성(ids, N), dd["12e 생성 속도"]["실패"])
        d긴["문맥 32704"] = {k_: round((t64[k_] - t1[k_]) / (N - 1), 4) for k_ in t1 if k_ in t64}
        print("13d (12e) 긴 32704", d긴["문맥 32704"], flush=True)
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
        print("13d (12e) 긴 102336", d긴["문맥 102336 (따로)"], flush=True)
        e긴.m.닫기()
        del e긴
        K9.비우기()
        dd["12e 생성 속도"]["합성 긴"] = d긴
        저장()
        dd["12f 지속 사용 — 자라는 대화"] = K13.자라는대화(일)
        print("13d (12f)", {k_: v for k_, v in dd["12f 지속 사용 — 자라는 대화"].items() if k_ != "차례들"}, flush=True)
        K9.비우기()
        저장()
        dd["12g 지속 사용 — 오래 돌리기"] = K13.오래돌리기(일)
        print("13d (12g)", {k_: v for k_, v in dd["12g 지속 사용 — 오래 돌리기"].items() if k_ != "창"}, flush=True)
        K9.비우기()
        저장()
    if "e" in 부분:
        res["13e 프롬프트 어텐션"] = 두층시간()
        print("13e", res["13e 프롬프트 어텐션"], flush=True)
        K9.비우기()
        저장()
    if 일 is not None:
        일.끝()
    print("끝 —", 결과)


if __name__ == "__main__":
    main()
