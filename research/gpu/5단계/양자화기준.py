#!/usr/bin/env python3
"""5단계 — 판정 전에 재는 비교 대상의 성질: llama.cpp 가 같은 양자화 가중치(F16 · Q8_0 · Q4_0 GGUF)로 얼마나 잃는가.

  build/감사venv/Scripts/python -I research/gpu/5단계/양자화기준.py

잃는 몫을 둘로 나눈다:
  가중치 양자화(밝힌 손실)  — 양자화 모델의 fp64 참값(GGUF 의 가중치를 ggml 과 같게 풀어 fp64 로)과 원래 모델의 fp64 참값의 차이.
  엔진의 숨은 손실          — 엔진의 로짓과 양자화 모델의 fp64 참값의 차이(같은 가중치인데 계산이 더 잃은 몫).
엔진: llama.cpp(기본 설정, 제 프로세스), 그리고 "정확한 엔진"의 흉내 — PyTorch fp32 에 푼 가중치(TF32 꺼짐).
시험: 평가글(5단계/평가글.txt)을 한 번에 넣은 모든 행의 로짓 — 원래 모델 대비 KL · 고른 토큰의 일치, 양자화 모델 대비 KL · 상대차.
그리고 세 문장 × 탐욕 64걸음(엔진 제 토큰) — 양자화 모델 참값 대비 상대차 중앙값. 결과는 결과/양자화기준.json 에.
"""
import json
import os
import sys

import numpy as np
import torch

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "gpu", "4단계"))
import gguf읽기 as GR       # noqa: E402
import 재기4 as R           # noqa: E402
from 재기5 import fp64참값  # noqa: E402

형식들 = ("f16", "q8_0", "q4_0")


def lsm(x):
    x = x.astype(np.float64)
    x = x - x.max(-1, keepdims=True)
    return x - np.log(np.exp(x).sum(-1, keepdims=True))


def 견줌(x, ref):
    """로짓 x 를 참값 ref 와 (행마다): KL(ref ‖ x) 평균, 고른 토큰 일치율, 상대차 중앙값."""
    lx, lr = lsm(x), lsm(ref)
    kl = (np.exp(lr) * (lr - lx)).sum(-1)
    rel = np.linalg.norm(x.astype(np.float64) - ref, axis=-1) / np.linalg.norm(ref, axis=-1)
    return {"KL 평균": float(kl.mean()), "고른 토큰 일치": float((x.argmax(-1) == ref.argmax(-1)).mean()),
            "상대차 중앙값": float(np.median(rel))}


def main():
    torch.zeros(1, device="cuda")
    tk = R.G.토크나이저(R.MODEL)
    글 = tk.나누기(open(os.path.join(HERE, "평가글.txt"), encoding="utf-8").read())[:1024]
    prompts = [tk.나누기(s) for s in R.문장들]
    w0 = R.G.가중치읽기(os.path.join(R.MODEL, "model.safetensors"))
    W0 = {k: torch.from_numpy(v.copy()).cuda().double() for k, v in w0.items()}
    원참 = fp64참값(W0, 글)
    res = {"평가글 토큰 수": len(글), "형식": {}}
    일 = R.일꾼()
    for fmt in 형식들:
        path = os.path.join(ROOT, "build", f"gpt2-{fmt}.gguf")
        g, wq = GR.gpt2가중치(path)
        Wq = {k: torch.from_numpy(v.copy()).cuda().double() for k, v in wq.items()}
        양참 = fp64참값(Wq, 글)
        r = {"텐서 형식": sorted({GR.이름.get(t, t) for t, _, _ in g.tensors.values()}),
             "가중치 양자화 (양자화 모델 fp64 대 원래 fp64)": 견줌(양참, 원참)}
        # 정확한 엔진의 흉내: PyTorch fp32 에 푼 가중치
        tm = R.T.토치GPT2(wq, 최대문장=1)
        f32 = tm.계산(torch.tensor([글], device="cuda"), 0)[0].float().cpu().numpy()
        r["PyTorch fp32 (푼 가중치) — 원래 모델 대비"] = 견줌(f32, 원참)
        r["PyTorch fp32 (푼 가중치) — 양자화 모델 참값 대비 (숨은 손실)"] = 견줌(f32, 양참)
        del tm
        라 = R.라마엔진(일, f"llama.cpp {fmt}", path)
        lx = 라.로짓들([글])
        r["llama.cpp — 원래 모델 대비"] = 견줌(lx, 원참)
        r["llama.cpp — 양자화 모델 참값 대비 (숨은 손실)"] = 견줌(lx, 양참)
        생성 = []
        for ids in prompts:
            toks, logs = 라.생성로짓(ids, 64)
            seq = ids + toks
            ref = fp64참값(Wq, seq[:-1])[len(ids) - 1:]
            rel = np.linalg.norm(logs.astype(np.float64) - ref, axis=-1) / np.linalg.norm(ref, axis=-1)
            생성.append(float(np.median(rel)))
        r["llama.cpp 생성 64걸음 — 양자화 모델 참값 대비 상대차 중앙값 (세 문장)"] = 생성
        라.닫기()
        res["형식"][fmt] = r
        print(fmt, json.dumps(r, ensure_ascii=False), flush=True)
        del Wq
        torch.cuda.empty_cache()
    일.끝()
    os.makedirs(os.path.join(HERE, "결과"), exist_ok=True)
    json.dump(res, open(os.path.join(HERE, "결과", "양자화기준.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
