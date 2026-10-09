#!/usr/bin/env python3
"""4단계 (기록, 판정 뒤의 분석) — 4c 의 정확도를 확률로도 본다.

  build/감사venv/Scripts/python -I research/gpu/4단계/확률차.py

4c 의 판정 지표(로짓의 상대차 ‖x − 참값‖ / ‖참값‖)는 로짓을 고르게 미는 오차도 센다. 고르게 민 로짓은 softmax 의 확률을 바꾸지 않는다 —
그래서 엔진마다 같은 64걸음(세 문장, 제 탐욕 토큰)에서 확률 쪽 지표를 더 잰다: 중심을 뺀 로짓의 상대차, KL(참값 ‖ 엔진), 확률의 최대
절대차. 참값은 PyTorch fp64. 그리고 4c 의 (가)·(나) — 같은 토큰열을 혼자 / 묶음으로, 한 번에 / 64토큰씩 / 하나씩 — 의 차이도 행마다
확률로(가장 큰 행). 결과는 결과/확률차.json 에. llama.cpp 의 "KV F32 (플래시 자동)" 판은 기본과 비트가 같아 뺐다(4c).
"""
import json
import os
import sys

import numpy as np
import torch

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import 재기4 as R          # noqa: E402


def 로그확률(x):
    x = x.astype(np.float64)
    x = x - x.max()
    return x - np.log(np.exp(x).sum())


def 행로그확률(x):
    x = x.astype(np.float64)
    x = x - x.max(-1, keepdims=True)
    return x - np.log(np.exp(x).sum(-1, keepdims=True))


def 행차이(a, b):
    """두 로짓 판 [행][어휘] 의 차이를 행마다 확률로 — 가장 큰 행의 값."""
    la, lb = 행로그확률(a), 행로그확률(b)
    pa, pb = np.exp(la), np.exp(lb)
    ac, bc = a - a.mean(-1, keepdims=True), b - b.mean(-1, keepdims=True)
    return {"확률의 최대 절대차": float(np.abs(pa - pb).max()), "KL 최대 (행마다)": float((pa * (la - lb)).sum(-1).max()),
            "중심을 뺀 로짓의 상대차 최대": float((np.linalg.norm(ac - bc, axis=-1) / np.linalg.norm(ac, axis=-1)).max()),
            "로짓의 최대 절대차": float(np.abs(a - b).max())}


def main():
    torch.zeros(1, device="cuda")
    w = R.G.가중치읽기(os.path.join(R.MODEL, "model.safetensors"))
    tk = R.G.토크나이저(R.MODEL)
    tm64 = R.T.토치GPT2(w, dtype=torch.float64, 최대문장=1)
    일 = R.일꾼()
    라 = R.라마엔진(일, R.라기본, R.GGUF)
    라정 = R.라마엔진(일, R.라정이름, R.GGUF, kv형식=0, 모델원=라, flash=0)
    엔진들 = [R.글엔진(w), 라, 라정, R.HF엔진()]
    res = {}
    for e in 엔진들:
        rel, cen, kl, pmax = [], [], [], []
        for s in R.문장들:
            ids = tk.나누기(s)
            toks, logs = e.생성로짓(ids, 64)
            seq = ids + toks
            ref = tm64.계산(torch.tensor([seq[:-1]], device="cuda"), 0)[0, len(ids) - 1:].cpu().numpy()
            for i in range(64):
                x, r = logs[i].astype(np.float64), ref[i]
                rel.append(np.linalg.norm(x - r) / np.linalg.norm(r))
                xc, rc = x - x.mean(), r - r.mean()
                cen.append(np.linalg.norm(xc - rc) / np.linalg.norm(rc))
                lx, lr = 로그확률(x), 로그확률(r)
                pr = np.exp(lr)
                kl.append(float((pr * (lr - lx)).sum()))
                pmax.append(float(np.abs(np.exp(lx) - pr).max()))
        res[e.이름] = {k: {"중앙값": float(np.median(v)), "최댓값": float(np.max(v))}
                      for k, v in (("로짓 상대차 (4c 의 지표)", rel), ("중심을 뺀 로짓의 상대차", cen),
                                   ("KL(fp64 ‖ 엔진)", kl), ("확률의 최대 절대차", pmax))}
        print(e.이름, json.dumps(res[e.이름], ensure_ascii=False), flush=True)
    # 4c 의 (가)·(나) 를 확률로
    글 = 엔진들[0]
    seqs = [tk.나누기(s) for s in R.문장들]
    seqs = [s + 글.생성(s, 64) for s in seqs]
    L = min(len(s) for s in seqs)
    seqs = [s[:L] for s in seqs]
    긴열 = (tk.나누기(R.문장들[1]) * 40)[:512]
    라묶음 = R.라마엔진(일, R.라기본, R.GGUF, n_seq_max=4, 모델원=라)
    라묶음정 = R.라마엔진(일, R.라정이름, R.GGUF, kv형식=0, n_seq_max=4, 모델원=라, flash=0)
    나눔 = {}
    for e, eb in ((글, 글), (라, 라묶음), (라정, 라묶음정), (엔진들[3], 엔진들[3])):
        한번 = e.로짓들([긴열])
        나눔[e.이름] = {"(가) 혼자 대 세 문장 한 묶음": 행차이(eb.로짓들([seqs[0]]), eb.로짓들(seqs)),
                       "(나) 한 번에 대 64토큰씩": 행차이(한번, e.로짓들([긴열], "조각", 64)),
                       "(나) 한 번에 대 하나씩": 행차이(한번, e.로짓들([긴열], "하나씩"))}
        print(e.이름, json.dumps(나눔[e.이름], ensure_ascii=False), flush=True)
    라묶음.닫기()
    라묶음정.닫기()
    hf = res[R.HF이름]
    res["HF fp32 대비 배수 (중앙값)"] = {k: {kk: round(v[kk]["중앙값"] / hf[kk]["중앙값"], 2) for kk in v} for k, v in res.items()
                                     if k != R.HF이름 and not k.startswith("HF fp32")}
    라정.닫기()
    라.닫기()
    일.끝()
    res["4c 의 (가)·(나) 를 확률로 (가장 큰 행)"] = 나눔
    json.dump(res, open(os.path.join(HERE, "결과", "확률차.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(res["HF fp32 대비 배수 (중앙값)"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
