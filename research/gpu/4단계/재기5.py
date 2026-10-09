#!/usr/bin/env python3
"""4단계 2 재기 — 4f 반실수 KV 의 의미, 4g 반실수 KV 의 속도 (docs/17 §7 "4단계 2" 의 판정 그대로). 4e 는 반실수재기.py.

  build/감사venv/Scripts/python -I research/gpu/4단계/재기5.py

글의 반실수 KV 판(`글GPT2(KV형식="반실수")`, 커널반.gl)과 짧은실수 KV 판(기록), llama.cpp 기본 설정(KV F16 — 4단계의 일꾼, 제 프로세스).
4f: 3b 의 모든 길(재기.py 의 글로짓 — 하나씩이 기준: 한 번에 / 프롬프트+하나씩 / 두 조각 / 세 문장 한 묶음 한 번에·하나씩, 그리고 생성
    메가커널이 걸음마다 남긴 로짓)과 4c 의 (가)(나)(다), 20번 되풀이, 오류 칸. 정확도: 엔진마다 제 탐욕 64토큰의 걸음마다 로짓을 반올림 없는
    fp64 참값과 견준 상대차의 중앙값(문장마다) — 판정은 llama.cpp 기본 설정의 4c 값보다 작은가. 같은 실행의 llama.cpp 값, 확률 지표(중심을
    뺀 로짓 · KL · 확률), 밝힌 반올림(K · V 를 f16 으로)을 넣은 fp64 와의 차이는 기록.
4g: 생성 토큰당 = (n토큰 − 1토큰) / (n − 1), 엔진을 번갈아 — 실제 GPT-2 짧은 문맥 · 문맥 960 (7번, n = 64), 합성 문맥 4096 · 16320 (5번,
    n = 33). 프롬프트 처리는 기록. 결과는 결과/4단계2.json 에.
"""
import gc
import json
import os
import sys

import numpy as np
import torch
import torch.nn.functional as F

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import 재기4 as R           # noqa: E402  (엔진: 글 · llama.cpp 일꾼, 합성 모델, 잰다)
import 재기 as R3           # noqa: E402  (3단계의 글로짓 — 3b 의 길들)

G, T = R.G, R.T
V, D, NH, NL = R.V, 768, 12, 12
라마4c = [1.146e-4, 5.536e-5, 1.340e-4]                 # 4c 의 llama.cpp 기본 설정 (결과/4단계.json — 판정의 기준값)
바닥 = {"4096": 1.36, "16320": 2.31}                    # 반실수 KV 생성의 바닥 (ms, docs/17)


def 다른칸(a, b):
    return int(np.count_nonzero(a.view(np.uint32) != b.view(np.uint32)))


def fp64참값(W, ids, kv=None):
    """반올림 없는 fp64 GPT-2 (kv = torch.float16 이면 K · V 를 f16 으로 반올림 — 밝힌 의미를 fp64 로)."""
    x = W["wte.weight"][ids] + W["wpe.weight"][:len(ids)]
    m = len(ids)
    for l in range(NL):
        p = f"h.{l}."
        h = F.layer_norm(x, (D,), W[p + "ln_1.weight"], W[p + "ln_1.bias"], 1e-5)
        q, k, v = torch.addmm(W[p + "attn.c_attn.bias"], h, W[p + "attn.c_attn.weight"]).split(D, dim=1)
        if kv is not None:
            k, v = k.to(kv).double(), v.to(kv).double()
        q, k, v = (t.view(m, NH, 64).transpose(0, 1) for t in (q, k, v))
        y = F.scaled_dot_product_attention(q[None], k[None], v[None], is_causal=True)[0].transpose(0, 1).reshape(m, D)
        x = x + torch.addmm(W[p + "attn.c_proj.bias"], y, W[p + "attn.c_proj.weight"])
        h = F.layer_norm(x, (D,), W[p + "ln_2.weight"], W[p + "ln_2.bias"], 1e-5)
        x = x + torch.addmm(W[p + "mlp.c_proj.bias"], F.gelu(torch.addmm(W[p + "mlp.c_fc.bias"], h, W[p + "mlp.c_fc.weight"]),
                                                              approximate="tanh"), W[p + "mlp.c_proj.weight"])
    x = F.layer_norm(x, (D,), W["ln_f.weight"], W["ln_f.bias"], 1e-5)
    return (x @ W["wte.weight"].T).cpu().numpy()


def 확률지표(x, r):
    """로짓 x 와 참값 r (행마다): 상대차, 중심을 뺀 로짓의 상대차, KL(참값 ‖ x), 확률의 최대 절대차."""
    x, r = x.astype(np.float64), r.astype(np.float64)
    rel = np.linalg.norm(x - r, axis=-1) / np.linalg.norm(r, axis=-1)
    xc, rc = x - x.mean(-1, keepdims=True), r - r.mean(-1, keepdims=True)
    cen = np.linalg.norm(xc - rc, axis=-1) / np.linalg.norm(rc, axis=-1)
    lx = x - x.max(-1, keepdims=True)
    lx = lx - np.log(np.exp(lx).sum(-1, keepdims=True))
    lr = r - r.max(-1, keepdims=True)
    lr = lr - np.log(np.exp(lr).sum(-1, keepdims=True))
    pr = np.exp(lr)
    return rel, cen, (pr * (lr - lx)).sum(-1), np.abs(np.exp(lx) - pr).max(-1)


def main():
    torch.zeros(1, device="cuda")
    res = {"환경": {"torch": torch.__version__, "llama.cpp": "b11496 (000bee54a)", "GPU": torch.cuda.get_device_name(0)}}
    결과 = os.path.join(HERE, "결과", "4단계2.json")

    def 저장():
        json.dump(res, open(결과, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    w = G.가중치읽기(os.path.join(R.MODEL, "model.safetensors"))
    tk = G.토크나이저(R.MODEL)
    prompts = [tk.나누기(s) for s in R.문장들]
    글반 = R.글엔진(w, KV형식="반실수")
    글반.이름 = "글 (반실수 KV)"
    글짧 = R.글엔진(w)
    글짧.이름 = "글 (짧은실수 KV, 기록)"
    m = 글반.m
    일 = R.일꾼()
    라 = R.라마엔진(일, R.라기본, R.GGUF)

    # 4f ── 의미 ──────────────────────────────────────────────────────────────────────────────────
    f = {}
    N = 64
    seqs = [p + m.생성(p, N) for p in prompts]
    b = {}
    for j, S in enumerate(seqs):
        p = len(prompts[j])
        base = R3.글로짓(m, [S], "하나씩")[0]
        for 방식 in ("한번에", "프롬프트+하나씩", "두조각"):
            x = R3.글로짓(m, [S], 방식, p)[0]
            b[f"문장{j + 1} {방식}"] = {"다른 칸": 다른칸(x, base), "칸 수": int(x.size)}
        g = m.생성(prompts[j], N, 기록=True)
        rec = m.기록된로짓(N)
        b[f"문장{j + 1} 생성 메가커널"] = {"다른 칸": 다른칸(rec, base[p:p + N - 1]), "칸 수": int(rec.size), "토큰이 같은가": g == S[p:p + N]}
    L = min(len(S) for S in seqs)
    cut = [S[:L] for S in seqs]
    alone = [R3.글로짓(m, [S], "하나씩")[0] for S in cut]
    for 방식 in ("한번에", "하나씩"):
        x = R3.글로짓(m, cut, 방식)
        b[f"세 문장 한 묶음 {방식}"] = {"다른 칸": sum(다른칸(x[j], alone[j]) for j in range(3)), "칸 수": int(x.size)}
    print("4f 3b 의 길:", {k: v["다른 칸"] for k, v in b.items()}, flush=True)
    f["3b 의 길 (하나씩이 기준)"] = b
    # 4c 의 (가)(나)(다)
    c4 = {}
    긴열 = (tk.나누기(R.문장들[1]) * 40)[:512]
    혼자 = 글반.로짓들([cut[0]])
    묶음 = 글반.로짓들(cut)
    한번 = 글반.로짓들([긴열])
    c4["(가) 혼자 대 세 문장 한 묶음: 다른 칸"] = 다른칸(혼자, 묶음)
    c4["(나) 한 번에 대 64토큰씩: 다른 칸"] = 다른칸(한번, 글반.로짓들([긴열], "조각", 64))
    c4["(나) 한 번에 대 하나씩: 다른 칸"] = 다른칸(한번, 글반.로짓들([긴열], "하나씩"))
    c4["(다) 한 번에를 다섯 번 더: 첫 번째와 다른 칸"] = [다른칸(한번, 글반.로짓들([긴열])) for _ in range(5)]
    print("4f 4c 의 길:", c4, flush=True)
    f["4c 의 (가)(나)(다)"] = c4
    # 20번 되풀이
    첫, 다름토큰, 다름로짓, 실패 = {}, 0, 0, 0
    for _ in range(20):
        for s, ids in zip(R.문장들, prompts):
            try:
                toks, logs = 글반.생성로짓(ids, N)
            except Exception:
                실패 += 1
                continue
            if s not in 첫:
                첫[s] = (toks, logs)
            else:
                다름토큰 += int(toks != 첫[s][0])
                다름로짓 += int(다른칸(logs, 첫[s][1]) > 0)
    f["20번 되풀이"] = {"생성 수": 60, "첫 번째와 토큰이 다른 생성": 다름토큰, "첫 번째와 로짓 비트가 다른 생성": 다름로짓, "실패": 실패}
    print("4f 되풀이:", f["20번 되풀이"], flush=True)
    # 정확도 — 반올림 없는 fp64 (판정), 밝힌 반올림을 넣은 fp64 (기록)
    W = {k: torch.from_numpy(v.copy()).cuda().double() for k, v in w.items()}
    fp64토큰 = []
    for ids in prompts:
        seq = list(ids)
        for _ in range(N):
            seq.append(int(fp64참값(W, seq)[-1].argmax()))
        fp64토큰.append(seq[len(ids):])
    정확 = {}
    for e in (글반, 글짧, 라):
        rows, 모음 = [], [[], [], [], []]
        for ids, ref토큰 in zip(prompts, fp64토큰):
            toks, logs = e.생성로짓(ids, N)
            seq = ids + toks
            ref = fp64참값(W, seq[:-1])[len(ids) - 1:]
            refh = fp64참값(W, seq[:-1], torch.float16)[len(ids) - 1:]
            rel, cen, kl, dp = 확률지표(logs, ref)
            relh = 확률지표(logs, refh)[0]
            for k, v in enumerate((rel, cen, kl, dp)):
                모음[k] += list(v)
            rows.append({"상대차 중앙값": float(np.median(rel)), "상대차 최댓값": float(np.max(rel)),
                         "밝힌 반올림을 넣은 fp64 대비 상대차 중앙값 (기록)": float(np.median(relh)),
                         "fp64 탐욕과 처음 갈린 자리": next((i for i in range(N) if toks[i] != ref토큰[i]), None)})
        정확[e.이름] = {"문장마다": rows, "확률 지표 (걸음 192 개의 중앙값)": {
            "상대차": float(np.median(모음[0])), "중심을 뺀 로짓의 상대차": float(np.median(모음[1])),
            "KL(fp64 ‖ 엔진)": float(np.median(모음[2])), "확률의 최대 절대차": float(np.median(모음[3])),
            "확률의 최대 절대차 (걸음 중 가장 큰)": float(np.max(모음[3]))}}
        print("4f 정확도", e.이름, [f"{r['상대차 중앙값']:.3e}" for r in rows], flush=True)
    del W
    gc.collect()
    torch.cuda.empty_cache()
    f["정확도 (반올림 없는 fp64 대비, 엔진마다 제 탐욕 64토큰)"] = 정확
    f["llama.cpp 기본 설정 (4c — 기준값)"] = 라마4c
    f["오류 칸"] = m.오류칸()
    글정 = [r["상대차 중앙값"] for r in 정확[글반.이름]["문장마다"]]
    f["통과"] = (all(v["다른 칸"] == 0 for v in b.values()) and all(v.get("토큰이 같은가", True) for v in b.values()) and
                c4["(가) 혼자 대 세 문장 한 묶음: 다른 칸"] == 0 and c4["(나) 한 번에 대 64토큰씩: 다른 칸"] == 0 and
                c4["(나) 한 번에 대 하나씩: 다른 칸"] == 0 and all(x == 0 for x in c4["(다) 한 번에를 다섯 번 더: 첫 번째와 다른 칸"]) and
                다름토큰 == 0 and 다름로짓 == 0 and 실패 == 0 and f["오류 칸"] == 0 and all(g < l for g, l in zip(글정, 라마4c)))
    res["4f 반실수 KV 의 의미"] = f
    저장()

    # 4g ── 속도 (실제 GPT-2) ────────────────────────────────────────────────────────────────────────
    g = {"생성 ms/토큰": {}, "프롬프트 처리 + 첫 토큰 ms (기록)": {}, "실패": {}}
    엔진들 = [글반, 라, 글짧]
    짧은 = prompts[0]
    긴 = (tk.나누기(R.문장들[1]) * 40)[:1024]
    for 이름, ids in (("짧은 문맥 (문장 1, 5토큰)", 짧은), ("문맥 960", 긴[:960])):
        R.데우기(엔진들, lambda e: e.생성(ids, 64), g["실패"])
        t1 = R.번갈아(엔진들, lambda e: e.잰_생성(ids, 1), 7, g["실패"])
        t64 = R.번갈아(엔진들, lambda e: e.잰_생성(ids, 64), 7, g["실패"])
        g["생성 ms/토큰"][이름] = {k: round((t64[k] - t1[k]) / 63, 4) for k in t1 if k in t64}
        print("4g 생성", 이름, g["생성 ms/토큰"][이름], flush=True)
    for n in (128, 512, 1024):
        ids = 긴[:n]
        R.데우기(엔진들, lambda e: e.프롬프트(ids), g["실패"])
        g["프롬프트 처리 + 첫 토큰 ms (기록)"][n] = R.번갈아(엔진들, lambda e: e.잰_프롬프트(ids), 7, g["실패"])
        print("4g 프롬프트", n, g["프롬프트 처리 + 첫 토큰 ms (기록)"][n], flush=True)
    라.닫기()
    del 글반, 글짧, 엔진들, m
    gc.collect()
    # 4g ── 속도 (합성 긴 문맥) ──────────────────────────────────────────────────────────────────────
    sw, 합성ids = R.합성가중치(w)
    합반 = R.글엔진(sw, 최대행=R.합성길이, 최대문장=1, 최대길이=R.합성길이, 로짓행=128, KV형식="반실수")
    합반.이름 = "글 (반실수 KV)"
    합짧 = R.글엔진(sw, 최대행=R.합성길이, 최대문장=1, 최대길이=R.합성길이, 로짓행=128)
    합짧.이름 = "글 (짧은실수 KV, 기록)"
    라합 = R.라마엔진(일, R.라기본, R.합성GGUF, n_ctx=R.합성길이, n_batch=2048)
    합엔진 = [합반, 라합, 합짧]
    for P in (4096, 16320):
        ids = 합성ids[:P]
        R.데우기(합엔진, lambda e: e.생성(ids, 33), g["실패"])
        t1 = R.번갈아(합엔진, lambda e: e.잰_생성(ids, 1), 5, g["실패"])
        t33 = R.번갈아(합엔진, lambda e: e.잰_생성(ids, 33), 5, g["실패"])
        g["생성 ms/토큰"][f"합성 문맥 {P}"] = {k: round((t33[k] - t1[k]) / 32, 4) for k in t1 if k in t33}
        print("4g 합성 생성", P, g["생성 ms/토큰"][f"합성 문맥 {P}"], flush=True)
    for n in (4096, 16384):
        ids = 합성ids[:n]
        R.데우기(합엔진, lambda e: e.프롬프트(ids), g["실패"])
        g["프롬프트 처리 + 첫 토큰 ms (기록)"][f"합성 {n}"] = R.번갈아(합엔진, lambda e: e.잰_프롬프트(ids), 3, g["실패"])
        print("4g 합성 프롬프트", n, g["프롬프트 처리 + 첫 토큰 ms (기록)"][f"합성 {n}"], flush=True)
    g["반실수 KV 바닥 (ms) · 1.25배"] = {k: [v, round(1.25 * v, 3)] for k, v in 바닥.items()}
    g["오류 칸"] = 합반.m.오류칸()
    gm = g["생성 ms/토큰"]
    반, 라이름 = "글 (반실수 KV)", R.라기본
    g["통과"] = (all(라이름 in gm[k] and 반 in gm[k] and gm[k][반] < gm[k][라이름] for k in gm) and
                gm["합성 문맥 4096"][반] <= 1.25 * 바닥["4096"] and gm["합성 문맥 16320"][반] <= 1.25 * 바닥["16320"] and
                g["오류 칸"] == 0)
    res["4g 반실수 KV 의 속도"] = g
    라합.닫기()
    일.끝()
    저장()
    print(json.dumps({"4f": f["통과"], "4g": g["통과"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
