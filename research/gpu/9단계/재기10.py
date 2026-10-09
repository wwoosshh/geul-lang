#!/usr/bin/env python3
"""9단계 재기 — 정수 KV 계약: 어텐션도 정수 텐서 코어로, 긴 문맥까지 (docs/17 §7 "9단계" 의 판정 그대로).

  build/감사venv/Scripts/python -I research/gpu/9단계/재기10.py

정수 KV 판: `글GPT2(gguf읽기.gpt2정수(파일), KV형식="정수", 자리수=2)` — 3단계/커널Q8정수KV · 커널Q4정수KV · 커널XLQ8정수KV · 커널XLQ4정수KV.gl.
비교 대상: llama.cpp(같은 GGUF, 기본 설정 = F16 KV; Q8_0 KV 는 기록), 8단계의 자리 둘 · 반실수 KV 판(기록). 긴 문맥은 합성 긴 모델
(build/gpt2-long/gpt2-long100k-q8_0.gguf — small 모양, 위치 102400, 4단계 gguf쓰기.py --합성 102400 → llama-quantize q8_0).
9a: (1) 어텐션 커널 셋(KV정수로 → 정수어텐션(mma) · 정수조각어텐션 + 정수조각접기(dp4a))이 CPU 참조(6단계/정수계약.py 의 어텐션 — 적힌지수
    포함)와 비트까지 같은가 — 실제 층의 q · k · v(small 층 5 · XL 층 20, 토큰 1024)와 합성 긴 모델 층 0 의 16384. 캐시의 바이트(자리 · 지수)도
    CPU 의 키캐시 · 값캐시와. (2) 끝에서 끝: 8단계 재기9.비트시험(행렬곱 CPU 참조 · 3b 의 길 · 생성 메가커널 · 4c (가)(나)(다) · 오류 칸)에
    더해 캐시 바이트가 프롬프트(타일의 _KV정수 끝손질)로 채운 것과 하나씩(KV정수로)으로 채운 것, 메가커널로 채운 것이 같은가; 합성 긴 모델의
    프롬프트 16384 대 프롬프트 16320 + 하나씩 64 의 로짓 · 캐시. (3) 8단계까지의 모듈 소스(.gl)가 git HEAD 와 같고, 그 PTX 가 HEAD 의
    글ptx.py 로 만든 것과 바이트까지 같은가(글ptx.py 에 바이트고르기가 더해졌다).
9b: 평가글(469토큰)의 양자화 모델 fp64 참값 대비 KL, 세 문장 × 64걸음 상대차 중앙값 — 글 정수 KV · llama.cpp(F16 KV · Q8_0 KV), 8단계 판의 값
    (결과/8단계.json)과의 비.
9c: 프롬프트 처리 + 첫 토큰(128 · 512 · 1024) — 글 정수 KV · 8단계 판 · llama.cpp(F16 · Q8_0 KV)를 번갈아 7번(중앙값). 긴 문맥 4096 ·
    16384 · 32768 은 글 · llama.cpp 를 번갈아 3번, 102400 은 메모리 때문에 따로(둘 다 두 번씩, 중앙값).
9d: 생성 토큰당 = (64 − 1) / 63 — 짧은 문맥 · 문맥 960(같은 넷을 번갈아), 긴 문맥 32768(번갈아) · 102336(따로).
9e: 프롬프트 어텐션 한 층(정수어텐션 커널 하나, CUDA 이벤트) — XL 1024 · 합성 small 16384 — 짝 넷의 int8 바닥 대비. 8단계의 흐름어텐션정수도 기록.
결과는 결과/9단계.json 에(단계마다 덮어 쓴다).
"""
import ctypes
import gc
import json
import os
import subprocess
import sys
import tempfile
import time

import numpy as np
import torch
import torch.nn.functional as F

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
for d in ("8단계", "7단계", "6단계", "5단계", "4단계", "3단계"):
    sys.path.insert(0, os.path.join(ROOT, "research", "gpu", d))
import gguf읽기 as GR         # noqa: E402
import 재기4 as R             # noqa: E402
import 재기 as R3             # noqa: E402
import 재기8 as K8            # noqa: E402
import 재기9 as K9            # noqa: E402
import 정수계약 as C          # noqa: E402
from 양자화기준 import 견줌    # noqa: E402

G = R.G
형식들 = ("q8_0", "q4_0")
크기들 = ("small", "XL")
결과 = os.path.join(HERE, "결과", "9단계.json")
긴GGUF = os.path.join(ROOT, "build", "gpt2-long", "gpt2-long100k-q8_0.gguf")
N = 64
최고치 = 1.6e14                                           # int8 텐서 코어 — 곱(MAC)/s (연산으로는 3.2 × 10¹⁴)
f32, u64, i64 = np.float32, ctypes.c_uint64, ctypes.c_int64
옛모듈 = ["커널.gl", "커널반.gl", "커널반F16.gl", "커널반Q8.gl", "커널반Q4.gl", "커널반Q8정수.gl", "커널반Q4정수.gl", "커널XL.gl",
        "커널XL반F16.gl", "커널XL반Q8정수.gl", "커널XL반Q4정수.gl", "커널반Q8둘자리.gl", "커널반Q4둘자리.gl", "커널XL반Q8둘자리.gl",
        "커널XL반Q4둘자리.gl", "커널프롬.gl", "gpt2XL.gl"]


def 글엔진(크기, fmt, **kw):
    e = R.글엔진(GR.gpt2정수(K9.경로(크기, fmt)), KV형식="정수", 자리수=2, **kw)
    e.이름 = f"글 {fmt} 정수 KV"
    return e


def 다른칸(a, b):
    return int((np.asarray(a).view(np.int32) != np.asarray(b).view(np.int32)).sum())


def 어텐션바닥us(NH, n):
    """프롬프트 n 토큰의 어텐션(원인 가림) 한 층 — 자리 짝 넷의 정수 곱을 int8 최고치로 나눈 시간(µs)."""
    return NH * n * (n + 1) / 2 * 64 * 2 * 4 / 최고치 * 1e6


@torch.no_grad()
def 층qkv(w, ids, L, D):
    """fp64 로 층 L 까지 돌려 층 L 의 c_attn 출력 [n][3D] 을 짧은실수로(GPU 가 있으면 GPU 에서)."""
    dev = "cuda"
    W = {k: torch.from_numpy(v.copy()).to(dev).double() for k, v in w.items()}
    NH = D // 64
    n = len(ids)
    x = W["wte.weight"][ids] + W["wpe.weight"][:n]
    for l in range(L + 1):
        p = f"h.{l}."
        h = F.layer_norm(x, (D,), W[p + "ln_1.weight"], W[p + "ln_1.bias"], 1e-5)
        qkv = torch.addmm(W[p + "attn.c_attn.bias"], h, W[p + "attn.c_attn.weight"])
        if l == L:
            break
        q, k, v = (t.view(n, NH, 64).transpose(0, 1) for t in qkv.split(D, dim=1))
        y = F.scaled_dot_product_attention(q[None], k[None], v[None], is_causal=True)[0].transpose(0, 1).reshape(n, D)
        x = x + torch.addmm(W[p + "attn.c_proj.bias"], y, W[p + "attn.c_proj.weight"])
        h = F.layer_norm(x, (D,), W[p + "ln_2.weight"], W[p + "ln_2.bias"], 1e-5)
        x = x + torch.addmm(W[p + "mlp.c_proj.bias"], F.gelu(torch.addmm(W[p + "mlp.c_fc.bias"], h, W[p + "mlp.c_fc.weight"]), approximate="tanh"),
                            W[p + "mlp.c_proj.weight"])
    out = qkv.float().cpu().numpy().astype(f32)
    del W
    torch.cuda.empty_cache()
    return out


어텐션판 = {"정수어텐션": (64, 128), "정수어텐션둘": (64, 256), "흐름어텐션정수": (64, 256)}    # 판 → (블록의 질의 수, 스레드 수)


def 커널대조(m, 입력, 최대길이, 참조머리=None, 커널="정수어텐션"):
    """엔진 m 의 어텐션 커널 셋을 입력 [n][3D](짧은실수 q · k · v)에 — KV정수로 의 캐시 바이트 · 정수어텐션(mma)의 출력 자리 · 정수조각어텐션 +
    정수조각접기(dp4a)의 출력 O/L 을 CPU 참조와 비트 대조. 참조머리: CPU 참조를 할 머리들(없으면 모두). 생성 판은 모든 행을 한 번에(행 r 의
    위치 = r) 돌리느라 조각칸이 n² — 4096 까지만(긴 것은 끝에서 끝의 프롬프트 대 하나씩 대조가 맡는다). 칸은 엔진의 닫기가 놓는다."""
    dr, D, NH = m.dr, m.D, m.NH
    n = 입력.shape[0]
    정보폭 = (n + 63) // 64 * 64

    def up(a):
        p = dr.할당(a.nbytes)
        dr.올리기(p, a)
        return p

    def zero(nb):
        p = dr.할당(nb)
        dr.확인(dr.cu.cuMemsetD8_v2(u64(p), 0, ctypes.c_size_t(nb)))
        return p

    def down(p, shape, dt):
        return dr.내리기(p, np.empty(shape, dt)).copy()

    g입력 = up(입력)
    자릿값q, 정보q = zero(2 * n * D), zero(D // 32 * 정보폭 * 4)
    키칸, 값칸 = zero(NH * 2 * 최대길이 * 64), zero(NH * 최대길이 * 128)
    키지수, 값지수 = zero(NH * 최대길이 * 2), zero(NH * 최대길이 * 2)
    자릿값, 정보 = zero(2 * n * D), zero(D // 32 * 정보폭 * 4)
    생성판 = n <= 4096
    조각칸, 출력 = (zero(n * NH * (최대길이 // 64) * 68 * 4), zero(n * D * 4)) if 생성판 else (0, 0)
    launch = dr.cu.cuLaunchKernel

    def run(x):
        r = launch(x.fn, x.grid[0], x.grid[1], 1, x.block[0], x.block[1], 1, 0, None, x.args, None)
        assert r == 0, r
    k = m.k
    KV = [u64(키칸), u64(값칸), u64(키지수), u64(값지수)]
    run(G._띄움(k["KV정수로"], ((3 * D // 32 + 31) // 32, n), (256, 1), [u64(g입력), u64(자릿값q), u64(정보q)] + KV + [i64(n), i64(n), i64(0), i64(최대길이)]))
    Q, 스 = 어텐션판[커널]
    run(G._띄움(k[커널], (NH, (n + Q - 1) // Q), (스, 1), [u64(자릿값q), u64(정보q)] + KV + [u64(정보), u64(자릿값), i64(n), i64(n), i64(0), i64(최대길이)]))
    if 생성판:
        run(G._띄움(k["정수조각어텐션"], (((n - 1) // 64 + 1 + 7) // 8, n * NH), (256, 1), [u64(자릿값q), u64(정보q)] + KV + [u64(조각칸), i64(n), i64(n), i64(0), i64(최대길이)]))
        run(G._띄움(k["정수조각접기"], (n * NH, 1), (256, 1), [u64(조각칸), u64(출력), i64(n), i64(n), i64(0), i64(최대길이)]))
    dr.맞추기()
    q, kk, v = 입력[:, :D], 입력[:, D:2 * D], 입력[:, 2 * D:]
    out = {}
    Dq, Eq = C.자리로(q, 2)
    out["q 자리 다른 칸"] = int((down(자릿값q, (2, n, D), np.int8) != C.낱말차례(Dq.reshape(2, n, D // 32, 32)).reshape(2, n, D).astype(np.int8)).sum())
    out["q 정보 다른 칸"] = int((down(정보q, (D // 32, 정보폭), np.int32)[:, :n] != (((137 + Eq.T) << 23) + 0x400000).astype(np.int32)).sum())
    gk, gke = down(키칸, (NH, 2, 최대길이, 64), np.int8), down(키지수, (NH, 최대길이, 2), np.uint8)
    gv, gve = down(값칸, (NH, 최대길이 // 32, 2, 64, 32), np.int8), down(값지수, (NH, 최대길이, 2), np.uint8)
    dk = dv = dke = dve = 0
    for h in range(NH):
        kc, ke = C.키캐시(kk[:, 64 * h:64 * h + 64], 최대길이)
        vc, ve = C.값캐시(v[:, 64 * h:64 * h + 64], 최대길이)
        dk += int((gk[h] != kc).sum()); dke += int((gke[h] != ke).sum()); dv += int((gv[h] != vc).sum()); dve += int((gve[h] != ve).sum())
    out.update({"키 캐시 다른 바이트": dk, "키 지수 다른 바이트": dke, "값 캐시 다른 바이트": dv, "값 지수 다른 바이트": dve})
    머리들 = list(range(NH)) if 참조머리 is None else list(참조머리)
    t0 = time.time()
    ref = np.zeros((n, D), f32)
    for h in 머리들:
        ref[:, 64 * h:64 * h + 64] = C.어텐션(q[:, 64 * h:64 * h + 64], kk[:, 64 * h:64 * h + 64], v[:, 64 * h:64 * h + 64])
    out["CPU 참조 초"] = round(time.time() - t0, 1)
    Do, Eo = C.자리로(ref, 2)
    ga = down(자릿값, (2, n, D), np.int8)
    rb = C.낱말차례(Do.reshape(2, n, D // 32, 32)).reshape(2, n, D).astype(np.int8)
    cols = np.zeros(D, bool)
    for h in 머리들:
        cols[64 * h:64 * h + 64] = True
    out["정수어텐션 출력 자리 다른 칸 (mma)"] = int((ga[:, :, cols] != rb[:, :, cols]).sum())
    gi = down(정보, (D // 32, 정보폭), np.int32)[:, :n]
    bl = np.zeros(D // 32, bool)
    for h in 머리들:
        bl[2 * h:2 * h + 2] = True
    out["정수어텐션 출력 정보 다른 칸 (mma)"] = int((gi[bl] != (((137 + Eo.T) << 23) + 0x400000).astype(np.int32)[bl]).sum())
    if 생성판:
        go = down(출력, (n, D), f32)
        out["정수조각어텐션 출력 O/L 다른 칸 (dp4a)"] = 다른칸(go[:, cols], ref[:, cols])
    out["칸 수"] = int(n * 64 * len(머리들))
    out["오류 칸"] = m.오류칸()
    out["통과"] = all(v == 0 for kk_, v in out.items() if "다른" in kk_) and out["오류 칸"] == 0
    return out


def 캐시(m, l=0):
    D, NH, L = m.D, m.NH, m.최대길이
    return [m.dr.내리기(p, np.empty(nb, dt)).copy() for p, nb, dt in
            ((m.kc[l], NH * 2 * L * 64, np.int8), (m.vc[l], NH * L * 128, np.int8), (m.ke[l], NH * L * 2, np.uint8), (m.ve[l], NH * L * 2, np.uint8))]


def 끝끝(e, ids):
    """프롬프트(타일 — _KV정수 · 정수어텐션) · 두조각 · 메가커널로 채운 캐시 바이트가 하나씩(KV정수로 · 정수조각어텐션)으로 채운 것과 같은가."""
    m = e.m
    b = {}
    base = R3.글로짓(m, [ids], "하나씩")[0]
    c하나 = 캐시(m)
    for 방식 in ("한번에", "두조각"):
        x = R3.글로짓(m, [ids], 방식)[0]
        c = 캐시(m)
        b[f"{방식} 대 하나씩"] = {"로짓 다른 칸": 다른칸(x, base), "캐시 다른 바이트 (키·값·키지수·값지수)": [int((p != q).sum()) for p, q in zip(c, c하나)]}
    p = 48
    S = ids[:p] + m.생성(ids[:p], N)
    base2 = R3.글로짓(m, [S], "하나씩", p)[0]
    g = m.생성(ids[:p], N, 기록=True)
    rec = m.기록된로짓(N)
    c메가 = 캐시(m)
    R3.글로짓(m, [S[:p + N - 1]], "하나씩")
    b["생성 메가커널 대 하나씩"] = {"로짓 다른 칸": 다른칸(rec, base2[p:p + N - 1]), "토큰이 같은가": g == S[p:p + N],
                             "캐시 다른 바이트 (키·값·키지수·값지수)": [int((p_ != q).sum()) for p_, q in zip(c메가, 캐시(m))]}
    b["통과"] = all(all(x == 0 for x in v["캐시 다른 바이트 (키·값·키지수·값지수)"]) and v["로짓 다른 칸"] == 0 and v.get("토큰이 같은가", True)
                  for v in b.values() if isinstance(v, dict))
    return b


def 옛모듈같은가():
    """8단계까지의 모듈 소스가 HEAD 와 같은가(git), 그리고 대표 모듈 넷의 PTX 가 HEAD 의 글ptx.py 로 만든 것과 같은가."""
    경로들 = [f"research/gpu/3단계/{f}" for f in 옛모듈]
    소스 = K9.git같은가(경로들)
    옛 = subprocess.run(["git", "show", "HEAD:research/gpu/글ptx.py"], cwd=ROOT, capture_output=True).stdout
    같음 = {}
    옛파일 = os.path.join(ROOT, "research", "gpu", "옛글ptx_임시.py")      # 글ptx.py 는 제 자리에서 ref/ 를 찾는다 — 같은 폴더에 잠시 둔다
    open(옛파일, "wb").write(옛)
    try:
        with tempfile.TemporaryDirectory() as td:
            for f in ("커널반Q8둘자리.gl", "커널XL반Q4둘자리.gl", "커널반Q8정수.gl", "커널반.gl"):
                gl = os.path.join(ROOT, "research", "gpu", "3단계", f)
                a, b = os.path.join(td, "a.ptx"), os.path.join(td, "b.ptx")
                subprocess.run([sys.executable, 옛파일, gl, "-o", a], check=True, capture_output=True)
                subprocess.run([sys.executable, os.path.join(ROOT, "research", "gpu", "글ptx.py"), gl, "-o", b], check=True, capture_output=True)
                같음[f] = open(a, "rb").read() == open(b, "rb").read()
    finally:
        os.remove(옛파일)
    return {"소스가 HEAD 와 같다": 소스, "PTX 가 HEAD 의 글ptx.py 와 같다": 같음, "통과": 소스 and all(같음.values())}


def 어텐션시간us(m, n, 커널="정수어텐션"):
    """엔진 m 의 (채워진) 층 0 캐시로 프롬프트 어텐션 커널 하나의 시간(µs, CUDA 이벤트 — 다섯 번씩 일곱 묶음의 중앙값)."""
    dr, cu = m.dr, m.dr.cu
    k = m.k
    P, I = u64, i64
    Q, 스 = 어텐션판[커널]
    if 커널 in ("정수어텐션", "정수어텐션둘"):
        x = G._띄움(k[커널], (m.NH, (n + Q - 1) // Q), (스, 1),
                   [P(m.자릿값q), P(m.정보q), P(m.kc[0]), P(m.vc[0]), P(m.ke[0]), P(m.ve[0]), P(m.정보), P(m.자릿값), I(n), I(n), I(0), I(m.최대길이)])
    else:                                                 # 8단계 흐름어텐션정수 (반실수 KV)
        x = G._띄움(k[커널], (m.NH, (n + 63) // 64), (256, 1),
                   [P(m.q), P(m.kc[0]), P(m.vc[0]), P(m.정보), P(m.자릿값), I(n), I(n), I(0), I(m.최대길이)])
    run = lambda: cu.cuLaunchKernel(x.fn, x.grid[0], x.grid[1], 1, x.block[0], x.block[1], 1, 0, None, x.args, None)
    e0, e1 = ctypes.c_void_p(), ctypes.c_void_p()
    cu.cuEventCreate(ctypes.byref(e0), 0)
    cu.cuEventCreate(ctypes.byref(e1), 0)
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 0.05:
        run()
    dr.맞추기()
    ts = []
    for _ in range(7):
        cu.cuEventRecord(e0, None)
        for _ in range(5):
            run()
        cu.cuEventRecord(e1, None)
        cu.cuEventSynchronize(e1)
        ms = ctypes.c_float()
        cu.cuEventElapsedTime(ctypes.byref(ms), e0, e1)
        ts.append(ms.value * 1000 / 5)
    cu.cuEventDestroy_v2(e0)
    cu.cuEventDestroy_v2(e1)
    return float(np.median(ts))


def main():
    """인자 없이 모두. 인자로 small · XL · 긴 중 고르면 그것만(디버그용 — 판정은 모두 돌린 것으로)."""
    고름 = [a for a in sys.argv[1:] if a in ("small", "XL", "긴")]
    크기들_ = tuple(k for k in 크기들 if not 고름 or k in 고름)
    긴도 = not 고름 or "긴" in 고름
    torch.zeros(1, device="cuda")
    res = {"환경": {"torch": torch.__version__, "llama.cpp": "b11496 (000bee54a)", "GPU": torch.cuda.get_device_name(0)},
           "9a 계약 (비트)": {}, "9b 정확도": {}, "9c 프롬프트 속도": {"실패": {}}, "9d 생성 속도": {"실패": {}}, "9e 어텐션 효율": {}}
    if 고름 and os.path.exists(결과):                      # 일부만 다시 돌릴 때는 있던 결과에 덧쓴다(판정은 모두 돌린 것으로)
        res = json.load(open(결과, encoding="utf-8"))

    def 저장():
        os.makedirs(os.path.dirname(결과), exist_ok=True)
        json.dump(res, open(결과, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    평가글 = open(os.path.join(ROOT, "research", "gpu", "5단계", "평가글.txt"), encoding="utf-8").read()
    옛 = json.load(open(os.path.join(ROOT, "research", "gpu", "8단계", "결과", "8단계.json"), encoding="utf-8"))
    res["9a 계약 (비트)"]["8단계까지의 모듈"] = 옛모듈같은가()
    print("9a 옛 모듈", res["9a 계약 (비트)"]["8단계까지의 모듈"], flush=True)
    저장()
    일 = R.일꾼()
    rng = np.random.default_rng(109)
    for 크기 in 크기들_:
        tk = G.토크나이저(K9.모델폴더(크기))
        prompts = [tk.나누기(s) for s in R.문장들]
        평가 = tk.나누기(평가글)[:1024]
        긴 = (tk.나누기(R.문장들[1]) * 40)[:1024]
        D = 768 if 크기 == "small" else 1600
        for fmt in 형식들:
            열쇠 = f"{크기} {fmt}"
            path = K9.경로(크기, fmt)
            e9 = 글엔진(크기, fmt)
            # ── 9a ──
            a = {}
            if fmt == "q8_0":                             # 어텐션 커널 대 CPU 참조 — 실제 층의 q · k · v (가중치는 짧은실수 safetensors; 층은 q8_0 · q4_0 과 무관)
                w = G.가중치읽기(os.path.join(K9.모델폴더(크기), "model.safetensors"))
                qkv = 층qkv(w, 긴[:1024], 5 if 크기 == "small" else 20, D)
                del w
                gc.collect()
                a[f"어텐션 커널 대 CPU 참조 (층 {5 if 크기 == 'small' else 20}, 토큰 1024)"] = 커널대조(e9.m, qkv, 1024)
                print("9a", 열쇠, "커널 대 CPU 참조", a[f"어텐션 커널 대 CPU 참조 (층 {5 if 크기 == 'small' else 20}, 토큰 1024)"], flush=True)
            a["끝에서 끝 (8단계 비트시험)"] = K9.비트시험(e9, path, rng, prompts, 긴)
            a["캐시 바이트 — 프롬프트 · 두조각 · 메가커널 대 하나씩"] = 끝끝(e9, 평가[:469])
            a["오류 칸"] = e9.m.오류칸()
            a["통과"] = all(v["통과"] for kk, v in a.items() if isinstance(v, dict)) and a["오류 칸"] == 0
            print("9a", 열쇠, "통과", a["통과"], "오류 칸", a["오류 칸"], flush=True)
            res["9a 계약 (비트)"][열쇠] = a
            저장()
            평가로짓 = e9.로짓들([평가])
            생성9 = [e9.생성로짓(ids, N) for ids in prompts]
            # ── 9c · 9d (같은 실행에서 번갈아) ──
            e8 = K9.글엔진(크기, fmt, 2, 최대문장=1)
            라 = R.라마엔진(일, f"llama.cpp {fmt}", path)
            라8 = R.라마엔진(일, f"llama.cpp {fmt} Q8_0 KV", path, kv형식=8)
            엔진들 = [e9, e8, 라, 라8]
            c, d = {}, {}
            for n in (128, 512, 1024):
                ids = 긴[:n]
                R.데우기(엔진들, lambda e: e.프롬프트(ids), res["9c 프롬프트 속도"]["실패"])
                c[str(n)] = R.번갈아(엔진들, lambda e: e.잰_프롬프트(ids), 7, res["9c 프롬프트 속도"]["실패"])
                바닥 = K9.바닥ms(크기, n, 2) + (12 if 크기 == "small" else 48) * 어텐션바닥us(D // 64, n) / 1000
                c[str(n)]["바닥 ms (선형 자리 둘 + 어텐션 짝 넷)"] = round(바닥, 2)
                c[str(n)]["바닥 대비"] = round(c[str(n)][e9.이름] / 바닥, 2)
                print("9c", 열쇠, n, c[str(n)], flush=True)
            for 이름, ids in (("짧은 문맥 (문장 1)", prompts[0]), ("문맥 960", 긴[:960])):
                R.데우기(엔진들, lambda e: e.생성(ids, N), res["9d 생성 속도"]["실패"])
                t1 = R.번갈아(엔진들, lambda e: e.잰_생성(ids, 1), 7, res["9d 생성 속도"]["실패"])
                t64 = R.번갈아(엔진들, lambda e: e.잰_생성(ids, N), 7, res["9d 생성 속도"]["실패"])
                d[이름] = {k: round((t64[k] - t1[k]) / (N - 1), 4) for k in t1 if k in t64}
                print("9d", 열쇠, 이름, d[이름], flush=True)
            라로짓 = {라.이름: [라.생성로짓(ids, N) for ids in prompts], 라8.이름: [라8.생성로짓(ids, N) for ids in prompts]}
            라평가 = {라.이름: 라.로짓들([평가]), 라8.이름: 라8.로짓들([평가])}
            d["오류 칸"] = e9.m.오류칸()
            res["9c 프롬프트 속도"][열쇠], res["9d 생성 속도"][열쇠] = c, d
            # ── 9e (XL 1024: 채워진 캐시로 커널 하나) ──
            if 크기 == "XL" and fmt == "q8_0":
                e9.m.토큰넣기(긴[:1024]); e9.m.계산(1, 1024, 0, "끝"); e9.m.dr.맞추기()
                e8.m.토큰넣기(긴[:1024]); e8.m.계산(1, 1024, 0, "끝"); e8.m.dr.맞추기()
                t9, t8 = 어텐션시간us(e9.m, 1024), 어텐션시간us(e8.m, 1024, "흐름어텐션정수")
                바닥 = 어텐션바닥us(25, 1024)
                res["9e 어텐션 효율"]["XL 1024 (머리 25)"] = {"정수어텐션 µs": round(t9, 1), "바닥 µs": round(바닥, 1), "바닥 대비": round(t9 / 바닥, 2),
                                                        "8단계 흐름어텐션정수 µs (기록)": round(t8, 1), "통과": t9 <= 2 * 바닥}
                print("9e", res["9e 어텐션 효율"]["XL 1024 (머리 25)"], flush=True)
            라.닫기(); 라8.닫기()
            e8.m.닫기(); e9.m.닫기()
            del e8, e9, 라, 라8
            K9.비우기()
            저장()
            # ── 9b ──
            _, wq = GR.gpt2가중치(path)
            W = {k: torch.from_numpy(v.copy()).cuda() for k, v in wq.items()}
            del wq
            gc.collect()
            참값 = K8.fp64참값(W, 평가)
            bb = {"KL 평균 — 양자화 모델 참값 대비 (평가글)": {e9이름: 견줌(평가로짓, 참값)["KL 평균"] for e9이름 in [f"글 {fmt} 정수 KV"]}}
            for 이름, 로짓 in 라평가.items():
                bb["KL 평균 — 양자화 모델 참값 대비 (평가글)"][이름] = 견줌(로짓, 참값)["KL 평균"]
            생성 = {}
            for 이름, 모음 in [(f"글 {fmt} 정수 KV", 생성9)] + list(라로짓.items()):
                rel = []
                for ids, (toks, logs) in zip(prompts, 모음):
                    seq = ids + toks
                    ref = K8.fp64참값(W, seq[:-1])[len(ids) - 1:]
                    rel.append(float(np.median(K8.걸음상대차(logs, ref))))
                생성[이름] = rel
            bb["생성 64걸음 — 양자화 모델 참값 대비 상대차 중앙값 (세 문장)"] = 생성
            옛b = 옛["8b 정확도"][열쇠]
            옛KL, 옛생성 = 옛b["글 — 양자화 모델 참값 대비 (평가글)"]["KL 평균"], 옛b["생성 64걸음 — 양자화 모델 참값 대비 상대차 중앙값 (세 문장)"][f"글 {fmt} 자리 둘"]
            bb["8단계 자리 둘 판 (기록)"] = {"KL 평균": 옛KL, "생성 64걸음": 옛생성}
            내KL, 내생성 = bb["KL 평균 — 양자화 모델 참값 대비 (평가글)"][f"글 {fmt} 정수 KV"], 생성[f"글 {fmt} 정수 KV"]
            bb["8단계 판 대비 비"] = {"KL": round(내KL / 옛KL, 3), "생성 64걸음": [round(a_ / b_, 3) for a_, b_ in zip(내생성, 옛생성)]}
            bb["통과"] = (내KL <= 1.25 * 옛KL and all(a_ <= 1.25 * b_ for a_, b_ in zip(내생성, 옛생성)) and
                         all(내KL < bb["KL 평균 — 양자화 모델 참값 대비 (평가글)"][k] for k in 라평가) and
                         all(g < l for k in 라로짓 for g, l in zip(내생성, 생성[k])))
            print("9b", 열쇠, json.dumps(bb, ensure_ascii=False), flush=True)
            res["9b 정확도"][열쇠] = bb
            del W, 평가로짓, 생성9, 라로짓, 라평가
            K9.비우기()
            저장()
    # ── 긴 문맥 (합성 small 모양 · 위치 102400) ──
    if not 긴도:
        일.끝(); 저장(); return
    tk = G.토크나이저(K9.모델폴더("small"))
    rng2 = np.random.default_rng(1)
    ids전체 = [int(x) for x in rng2.integers(0, 50257, 102400)]
    wq = GR.gpt2정수(긴GGUF)
    긴a = {}
    # 9a: 커널 대 CPU 참조 (층 0, 16384 — 합성 가중치의 fp64) · 프롬프트 16384 대 16320 + 하나씩 64
    e긴 = R.글엔진(wq, KV형식="정수", 자리수=2, 최대행=16384, 최대문장=1, 최대길이=16384, 로짓행=16)
    e긴.이름 = "글 q8_0 정수 KV (합성 긴)"
    w합 = GR.gpt2가중치(긴GGUF)[1]
    qkv = 층qkv(w합, ids전체[:16384], 0, 768)
    del w합
    gc.collect()
    긴a["어텐션 커널 대 CPU 참조 (합성 층 0, 토큰 16384)"] = 커널대조(e긴.m, qkv, 16384, 참조머리=range(0, 12, 3))   # CPU 참조는 머리 넷(시간)
    print("9a 긴 커널 대 CPU 참조", 긴a["어텐션 커널 대 CPU 참조 (합성 층 0, 토큰 16384)"], flush=True)
    del qkv
    m = e긴.m
    ids = ids전체[:16384]
    m.토큰넣기(ids); m.계산(1, 16384, 0, 1); m.dr.맞추기()
    로짓한번 = m.로짓(1).copy()
    c한번 = 캐시(m)
    m.토큰넣기(ids[:16320]); m.계산(1, 16320, 0, 1); m.dr.맞추기()
    for s in range(64):
        m.토큰넣기([ids[16320 + s]]); m.계산(1, 1, 16320 + s, 1); m.dr.맞추기()
    로짓하나 = m.로짓(1).copy()
    긴a["프롬프트 16384 대 16320 + 하나씩 64"] = {"마지막 로짓 다른 칸": 다른칸(로짓한번, 로짓하나),
                                        "캐시 다른 바이트 (키·값·키지수·값지수)": [int((p != q).sum()) for p, q in zip(c한번, 캐시(m))], "오류 칸": m.오류칸()}
    print("9a 긴", 긴a["프롬프트 16384 대 16320 + 하나씩 64"], flush=True)
    긴a["통과"] = 긴a["어텐션 커널 대 CPU 참조 (합성 층 0, 토큰 16384)"]["통과"] and 긴a["프롬프트 16384 대 16320 + 하나씩 64"]["마지막 로짓 다른 칸"] == 0 and \
        all(x == 0 for x in 긴a["프롬프트 16384 대 16320 + 하나씩 64"]["캐시 다른 바이트 (키·값·키지수·값지수)"]) and 긴a["프롬프트 16384 대 16320 + 하나씩 64"]["오류 칸"] == 0
    res["9a 계약 (비트)"]["합성 긴"] = 긴a
    # 9e: 합성 small 16384 어텐션 한 층
    t9 = 어텐션시간us(m, 16384)
    바닥 = 어텐션바닥us(12, 16384)
    res["9e 어텐션 효율"]["합성 small 16384 (머리 12)"] = {"정수어텐션 µs": round(t9, 1), "바닥 µs": round(바닥, 1), "바닥 대비": round(t9 / 바닥, 2), "통과": t9 <= 2 * 바닥}
    print("9e", res["9e 어텐션 효율"]["합성 small 16384 (머리 12)"], flush=True)
    m.닫기()
    del e긴, m
    K9.비우기()
    저장()
    # 9c · 9d 긴: 4096 · 16384 · 32768 은 번갈아, 102400 은 따로
    c긴, d긴 = {}, {}
    e긴 = R.글엔진(wq, KV형식="정수", 자리수=2, 최대행=32768, 최대문장=1, 최대길이=32768, 로짓행=16)
    e긴.이름 = "글 q8_0 정수 KV (합성 긴)"
    라긴 = R.라마엔진(일, "llama.cpp q8_0 (합성 긴)", 긴GGUF, n_ctx=32768, n_batch=2048)
    엔진들 = [e긴, 라긴]
    for n in (4096, 16384, 32768):
        ids = ids전체[:n]
        R.데우기(엔진들, lambda e: e.프롬프트(ids), res["9c 프롬프트 속도"]["실패"])
        c긴[str(n)] = R.번갈아(엔진들, lambda e: e.잰_프롬프트(ids), 3, res["9c 프롬프트 속도"]["실패"])
        바닥 = K9.바닥ms("small", n, 2) + 12 * 어텐션바닥us(12, n) / 1000
        c긴[str(n)]["바닥 ms (선형 자리 둘 + 어텐션 짝 넷)"] = round(바닥, 1)
        c긴[str(n)]["바닥 대비"] = round(c긴[str(n)][e긴.이름] / 바닥, 2)
        print("9c 긴", n, c긴[str(n)], flush=True)
    ids = ids전체[:32768 - 64]
    R.데우기(엔진들, lambda e: e.생성(ids, N), res["9d 생성 속도"]["실패"])
    t1 = R.번갈아(엔진들, lambda e: e.잰_생성(ids, 1), 3, res["9d 생성 속도"]["실패"])
    t64 = R.번갈아(엔진들, lambda e: e.잰_생성(ids, N), 3, res["9d 생성 속도"]["실패"])
    d긴["문맥 32704"] = {k: round((t64[k] - t1[k]) / (N - 1), 4) for k in t1 if k in t64}
    print("9d 긴 32704", d긴["문맥 32704"], flush=True)
    라긴.닫기(); e긴.m.닫기()
    del e긴, 라긴
    K9.비우기()
    # 102400 — 따로
    ids = ids전체[:102400]
    긴2 = {}
    라긴 = R.라마엔진(일, "llama.cpp q8_0 (합성 긴)", 긴GGUF, n_ctx=102400, n_batch=2048)
    라긴.프롬프트(ids)
    긴2[라긴.이름] = float(np.median([라긴.잰_프롬프트(ids) for _ in range(2)]))
    라긴.생성(ids[:-64], N)
    t1 = np.median([라긴.잰_생성(ids[:-64], 1) for _ in range(2)]); t64 = np.median([라긴.잰_생성(ids[:-64], N) for _ in range(2)])
    d긴["문맥 102336 (따로)"] = {라긴.이름: round(float((t64 - t1) / (N - 1)), 4)}
    라긴.닫기()
    del 라긴
    e긴 = R.글엔진(wq, KV형식="정수", 자리수=2, 최대행=102400, 최대문장=1, 최대길이=102400, 로짓행=16)
    e긴.이름 = "글 q8_0 정수 KV (합성 긴)"
    e긴.프롬프트(ids)
    긴2[e긴.이름] = float(np.median([e긴.잰_프롬프트(ids) for _ in range(2)]))
    바닥 = K9.바닥ms("small", 102400, 2) + 12 * 어텐션바닥us(12, 102400) / 1000
    긴2["바닥 ms (선형 자리 둘 + 어텐션 짝 넷)"] = round(바닥, 1)
    긴2["바닥 대비"] = round(긴2[e긴.이름] / 바닥, 2)
    c긴["102400 (따로)"] = 긴2
    e긴.생성(ids[:-64], N)                               # 데우기 — 첫 실행에서 이것을 빼먹어 값이 음수로 나왔다(판 고르기 · 그래프 만들기가 1 토큰 재기에 섞임)
    t1 = np.median([e긴.잰_생성(ids[:-64], 1) for _ in range(2)]); t64 = np.median([e긴.잰_생성(ids[:-64], N) for _ in range(2)])
    d긴["문맥 102336 (따로)"][e긴.이름] = round(float((t64 - t1) / (N - 1)), 4)
    d긴["오류 칸"] = e긴.m.오류칸()
    print("9c 긴 102400", 긴2, "9d 긴 102336", d긴["문맥 102336 (따로)"], flush=True)
    e긴.m.닫기()
    del e긴
    K9.비우기()
    res["9c 프롬프트 속도"]["합성 긴"], res["9d 생성 속도"]["합성 긴"] = c긴, d긴
    일.끝()
    # ── 판정 ──
    c, d = res["9c 프롬프트 속도"], res["9d 생성 속도"]
    열쇠들 = [f"{크기} {fmt}" for 크기 in 크기들_ for fmt in 형식들]
    글 = lambda k: f"글 {k.split()[1]} 정수 KV"
    옛판 = lambda k: f"글 {k.split()[1]} 자리 둘"
    라 = lambda k: f"llama.cpp {k.split()[1]}"
    긴글, 긴라 = "글 q8_0 정수 KV (합성 긴)", "llama.cpp q8_0 (합성 긴)"
    c["통과"] = (not c["실패"] and all(c[k][n][글(k)] < c[k][n][라(k)] for k in 열쇠들 for n in ("128", "512", "1024")) and
               all(c["합성 긴"][n][긴글] < c["합성 긴"][n][긴라] for n in ("4096", "16384", "32768", "102400 (따로)")))
    d["통과"] = (not d["실패"] and all(v[글(k)] < v[라(k)] and v[글(k)] <= 1.03 * v[옛판(k)] for k in 열쇠들 for kk, v in d[k].items() if kk != "오류 칸") and
               all(d["합성 긴"][kk][긴글] < d["합성 긴"][kk][긴라] for kk in ("문맥 32704", "문맥 102336 (따로)")))
    res["통과"] = {"9a": all(res["9a 계약 (비트)"][k]["통과"] for k in 열쇠들 + ["8단계까지의 모듈", "합성 긴"]),
                  "9b": all(res["9b 정확도"][k]["통과"] for k in 열쇠들), "9c": c["통과"], "9d": d["통과"],
                  "9e": all(v["통과"] for v in res["9e 어텐션 효율"].values())}
    저장()
    print(json.dumps(res["통과"], ensure_ascii=False))


if __name__ == "__main__":
    main()
