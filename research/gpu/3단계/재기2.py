#!/usr/bin/env python3
"""3단계 성능 2 재기 — 길이를 가리지 않고 (docs/17 §7 "3단계 성능 2"의 판정 그대로).

  build/감사venv/Scripts/python -I research/gpu/3단계/재기.py --출력 결과/3단계2_기본.json
  build/감사venv/Scripts/python -I research/gpu/3단계/재기2.py

3h 프롬프트 처리 — 실제 GPT-2, 문장 2 의 토큰을 되풀이한 128·256·512·1024토큰 프롬프트의 처리 + 첫 토큰: 글과 PyTorch eager 를
   번갈아 7번, 중앙값. 같은 길이로 잡은 PyTorch CUDA 그래프 판은 기록한다(판정 밖).
3i 긴 문맥 생성 — 실제 GPT-2, 960토큰 프롬프트 뒤 64토큰 생성의 토큰당 시간 = (64토큰 − 1토큰) / 63: 글(메가커널), PyTorch eager,
   PyTorch CUDA 그래프(정적 캐시 1024). 번갈아 7번, 중앙값. 바닥의 1.25배 = 1.49 ms.
3j 합성 긴 문맥 — 같은 모양의 합성 모델(위치표 16384 줄, 값은 시드 0 의 무작위 — 연산·크기·순서는 GPT-2 그대로): 프롬프트
   2048·4096·8192·16384 의 처리 + 첫 토큰(글과 eager 를 번갈아 3번), 문맥 4096·16320 에서 생성 32걸음의 토큰당 시간(글, eager,
   CUDA 그래프를 번갈아 3번). 바닥의 1.25배 = 2.10 / 4.47 ms.
3k 의미 — 위의 기본 재기(결과/3단계2_기본.json)에서 3b 의 모든 길과 메가커널의 다른 칸 0, 64토큰 같음, 64걸음 상대차 중앙값의
   배수 ≤ 2. 그리고 합성 모델의 4032토큰 프롬프트 + 생성 64토큰: 한 번에 계산한 로짓과 프롬프트 + 메가커널의 로짓이 64행에서 비트까지 같다.
결과는 결과/3단계2.json 에.
"""
import json
import os
import sys
import time

import numpy as np
import torch

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)
import 글gpt2 as G          # noqa: E402
import 토치gpt2 as T        # noqa: E402

MODEL = os.path.join(ROOT, "build", "gpt2")
문장2 = ("In a shocking finding, scientists discovered a herd of unicorns living in a remote, previously unexplored valley "
       "in the Andes Mountains. Even more surprising to the researchers was the fact that the unicorns spoke perfect English.")
합성길이 = 16384
기준 = {"3i": 1.49, "3j 4096": 2.10, "3j 16320": 4.47}


def 맞추기(m):
    torch.cuda.synchronize()
    m.dr.맞추기()


def 잰다(m, f):
    맞추기(m)
    s = time.perf_counter()
    f()
    맞추기(m)
    return (time.perf_counter() - s) * 1000


def 그래프(f):
    s_ = torch.cuda.Stream()
    s_.wait_stream(torch.cuda.current_stream())
    with torch.cuda.stream(s_):
        for _ in range(3):
            f()
    torch.cuda.current_stream().wait_stream(s_)
    g = torch.cuda.CUDAGraph()
    with torch.cuda.graph(g):
        f()
    return g


def 프롬프트들(m, tm, ids_list, 번, 그래프도=True):
    out = {}
    for ids in ids_list:
        tt = torch.tensor([ids], device="cuda")
        m.생성(ids, 1)
        tm.생성(ids, 1)
        pg = 그래프(lambda: tm.계산(tt, 0, 끝만=True).argmax(-1)) if 그래프도 else None
        t = {"글": [], "PyTorch eager": []}
        if pg is not None:
            t["PyTorch CUDA 그래프 (참고)"] = []
        for _ in range(번):
            t["글"].append(잰다(m, lambda: m.생성(ids, 1)))
            t["PyTorch eager"].append(잰다(m, lambda: tm.생성(ids, 1)))
            if pg is not None:
                t["PyTorch CUDA 그래프 (참고)"].append(잰다(m, lambda: pg.replay()))
        del pg
        out[len(ids)] = {k: round(float(np.median(v)), 3) for k, v in t.items()}
        print(f"프롬프트 {len(ids)}: {out[len(ids)]}", flush=True)
    return out


def 토치생성걸음(tm, ids, 걸음):
    """프롬프트를 처리한 뒤 eager 로 걸음 수만큼 — 그 시간 / 걸음."""
    p = len(ids)
    nxt = tm.계산(torch.tensor([ids], device="cuda"), 0, 끝만=True).argmax(-1, keepdim=True)

    def run():
        x = nxt
        for s in range(걸음):
            x = tm.계산(x, p + s, 끝만=True).argmax(-1, keepdim=True)
    return run


def 그래프생성걸음(tm, ids, 걸음):
    p = len(ids)
    gg = T.토치그래프생성(tm, 최대길이=p + 걸음 + 1)
    nxt = tm.계산(torch.tensor([ids], device="cuda"), 0, 끝만=True).argmax(-1, keepdim=True)
    gg.tok.copy_(nxt)

    def run():
        gg.pos.fill_(p)
        for _ in range(걸음):
            gg.g.replay()
    return run, gg


def main():
    torch.zeros(1, device="cuda")
    res = {"환경": {"torch": torch.__version__, "allow_tf32(matmul)": torch.backends.cuda.matmul.allow_tf32}}
    w = G.가중치읽기(os.path.join(MODEL, "model.safetensors"))
    tk = G.토크나이저(MODEL)
    긴 = (tk.나누기(문장2) * 40)[:1024]

    # 3h·3i ── 실제 GPT-2 ───────────────────────────────────────────────────────────────────────
    m = G.글GPT2(w)
    tm = T.토치GPT2(w, 최대문장=1, 최대길이=1024)
    h = 프롬프트들(m, tm, [긴[:n] for n in (128, 256, 512, 1024)], 7)
    res["3h 프롬프트 처리 + 첫 토큰 ms"] = h
    res["3h 통과"] = all(v["글"] < v["PyTorch eager"] for v in h.values())

    ids = 긴[:960]
    gg = T.토치그래프생성(tm, 최대길이=1024)
    runners = {"글": m.생성, "PyTorch eager": tm.생성, "PyTorch CUDA 그래프": gg.생성}
    toks = {k: f(ids, 64) for k, f in runners.items()}
    t1 = {k: [] for k in runners}
    t64 = {k: [] for k in runners}
    for _ in range(7):
        for k, f in runners.items():
            t1[k].append(잰다(m, lambda: f(ids, 1)))
            t64[k].append(잰다(m, lambda: f(ids, 64)))
    i = {k: round((float(np.median(t64[k])) - float(np.median(t1[k]))) / 63, 4) for k in runners}
    res["3i 문맥 960 생성 ms/토큰"] = i
    res["3i 바닥의 1.25배 ms"] = 기준["3i"]
    res["3i 64토큰이 PyTorch eager 와 같은가"] = toks["글"] == toks["PyTorch eager"]
    res["3i 통과"] = i["글"] < i["PyTorch eager"] and i["글"] < i["PyTorch CUDA 그래프"] and i["글"] <= 기준["3i"]
    print("3i:", i, "같은 토큰:", res["3i 64토큰이 PyTorch eager 와 같은가"], flush=True)
    del gg, tm
    torch.cuda.empty_cache()

    # 3j ── 합성 모델 ──────────────────────────────────────────────────────────────────────────────
    rng = np.random.default_rng(0)
    sw = {}
    for k, v in w.items():
        if k == "wpe.weight":
            sw[k] = (rng.standard_normal((합성길이, 768)) * 0.01).astype(np.float32)
        elif k.endswith(".weight") and v.ndim == 2:
            sw[k] = (rng.standard_normal(v.shape) * 0.02).astype(np.float32)
        elif k.endswith(".weight"):
            sw[k] = np.ones_like(v)
        else:
            sw[k] = np.zeros_like(v)
    합성ids = [int(x) for x in rng.integers(0, 50257, 합성길이)]
    ms = G.글GPT2(sw, 최대행=합성길이, 최대문장=1, 최대길이=합성길이, 로짓행=128)
    tms = T.토치GPT2(sw, 최대문장=1, 최대길이=합성길이)
    j = 프롬프트들(ms, tms, [합성ids[:n] for n in (2048, 4096, 8192, 16384)], 3, 그래프도=False)
    res["3j 합성 프롬프트 처리 + 첫 토큰 ms"] = j
    jg = {}
    for P in (4096, 16320):
        ids = 합성ids[:P]
        ms.생성(ids, 33)
        er = 토치생성걸음(tms, ids, 32)
        gr, gobj = 그래프생성걸음(tms, ids, 32)
        er(); gr()
        t = {"글": [], "PyTorch eager": [], "PyTorch CUDA 그래프": []}
        for _ in range(3):
            a1 = 잰다(ms, lambda: ms.생성(ids, 1))
            a33 = 잰다(ms, lambda: ms.생성(ids, 33))
            t["글"].append((a33 - a1) / 32)
            t["PyTorch eager"].append(잰다(ms, er) / 32)
            t["PyTorch CUDA 그래프"].append(잰다(ms, gr) / 32)
        del gobj
        jg[P] = {k: round(float(np.median(v)), 4) for k, v in t.items()}
        jg[P]["바닥의 1.25배 ms"] = 기준[f"3j {4096 if P == 4096 else 16320}"]
        print(f"합성 문맥 {P}: {jg[P]}", flush=True)
    res["3j 합성 문맥 생성 ms/토큰"] = jg
    res["3j 통과"] = (all(v["글"] < v["PyTorch eager"] for v in j.values()) and
                    all(v["글"] < v["PyTorch eager"] and v["글"] < v["PyTorch CUDA 그래프"] and v["글"] <= v["바닥의 1.25배 ms"]
                        for v in jg.values()))

    # 3k ── 합성 모델의 비트 (4032 + 64) ────────────────────────────────────────────────────────────
    P = 4032
    gen = ms.생성(합성ids[:P], 64, 기록=True)
    mega = ms.기록된로짓(64).copy()                  # 행 P .. P+62
    ms.토큰넣기(합성ids[:P])
    ms.계산(1, P, 0, "끝")
    첫 = ms.로짓(1).copy()                            # 행 P−1
    열 = 합성ids[:P] + gen
    ms.토큰넣기(열)
    ms.계산(1, len(열), 0, 65)                       # 행 P−1 .. P+63
    한번 = ms.로짓(65).copy()
    다른 = int((한번[:1].view(np.uint32) != 첫.view(np.uint32)).sum()) + int((한번[1:64].view(np.uint32) != mega.view(np.uint32)).sum())
    res["3k 합성 4032+64: 한 번에 vs 프롬프트+메가커널 다른 칸"] = 다른
    res["3k 합성 비교한 칸"] = int(64 * G.V)
    print("3k 합성 다른 칸:", 다른, flush=True)
    기본 = os.path.join(HERE, "결과", "3단계2_기본.json")
    if os.path.exists(기본):
        b = json.load(open(기본, encoding="utf-8"))
        g3 = b["3g 의미를 지킨 채"]
        res["3k 실제 GPT-2 (3단계2_기본.json)"] = {"3b 다른 칸 0": b["3b 의미"]["통과"], "64토큰이 같은가": g3["64토큰이 같은가"],
                                                "64걸음 상대차 중앙값의 배수": g3["64걸음 상대차 중앙값의 배수"]}
        res["3k 통과"] = bool(g3["통과"]) and 다른 == 0
    res["오류 칸 (__geul_err)"] = max(m.오류칸(), ms.오류칸())
    json.dump(res, open(os.path.join(HERE, "결과", "3단계2.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in res.items() if k.endswith("통과")} | {"오류 칸": res["오류 칸 (__geul_err)"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
