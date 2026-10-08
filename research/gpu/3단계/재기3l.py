#!/usr/bin/env python3
"""3l 재기 — 프롬프트 메가커널 (docs/17 §7 "3단계 성능 3"의 판정 그대로).

  build/감사venv/Scripts/python -I research/gpu/3단계/재기3l.py

실제 GPT-2, 문장 2 의 토큰을 되풀이한 128·256·512·1024토큰 프롬프트의 처리 + 첫 토큰: 글(프롬프트 메가커널), 글(따로 도는 커널들 —
3h 의 판), PyTorch eager, PyTorch CUDA 그래프를 번갈아 7번, 중앙값. 비트: 길이마다 마지막 행의 로짓이 메가커널과 따로 도는 커널들에서
같은가, 그리고 세 프롬프트를 메가커널 프롬프트 + 생성 메가커널로 64토큰 만들 때 걸음마다의 로짓이 따로 도는 커널들로 하나씩 계산한
것과 같은가. 결과는 결과/3단계3l.json 에.
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
문장들 = ["The meaning of life is",
        "In a shocking finding, scientists discovered a herd of unicorns living in a remote, previously unexplored valley "
        "in the Andes Mountains. Even more surprising to the researchers was the fact that the unicorns spoke perfect English.",
        "Alan Turing was a"]


def main():
    torch.zeros(1, device="cuda")
    w = G.가중치읽기(os.path.join(MODEL, "model.safetensors"))
    tk = G.토크나이저(MODEL)
    m = G.글GPT2(w, 프롬메가=True)
    tm = T.토치GPT2(w, 최대문장=1, 최대길이=1024)
    긴 = (tk.나누기(문장들[1]) * 40)[:1024]

    def 잰다(f):
        torch.cuda.synchronize()
        m.dr.맞추기()
        s = time.perf_counter()
        f()
        torch.cuda.synchronize()
        m.dr.맞추기()
        return (time.perf_counter() - s) * 1000

    def 따로(ids):
        m.토큰넣기(ids)
        m.계산(1, len(ids), 0, "끝", 출력자리=m.생성칸)

    res = {"프롬프트 처리 + 첫 토큰 ms": {}, "마지막 행 로짓 다른 칸 (메가 대 따로)": {}}
    for n in (128, 256, 512, 1024):
        ids = 긴[:n]
        tt = torch.tensor([ids], device="cuda")
        따로(ids)
        m.dr.맞추기()
        a = m.로짓(1).copy()
        m.프롬메가로(ids)
        m.dr.맞추기()
        b = m.로짓(1).copy()
        res["마지막 행 로짓 다른 칸 (메가 대 따로)"][n] = int((a.view(np.uint32) != b.view(np.uint32)).sum())
        s_ = torch.cuda.Stream()
        s_.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(s_):
            for _ in range(3):
                tm.계산(tt, 0, 끝만=True).argmax(-1)
        torch.cuda.current_stream().wait_stream(s_)
        pg = torch.cuda.CUDAGraph()
        with torch.cuda.graph(pg):
            tm.계산(tt, 0, 끝만=True).argmax(-1)
        t = {"글 메가커널": [], "글 따로 도는 커널 (3h)": [], "PyTorch eager": [], "PyTorch CUDA 그래프": []}
        for _ in range(7):
            t["글 메가커널"].append(잰다(lambda: m.프롬메가로(ids)))
            t["글 따로 도는 커널 (3h)"].append(잰다(lambda: 따로(ids)))
            t["PyTorch eager"].append(잰다(lambda: tm.생성(ids, 1)))
            t["PyTorch CUDA 그래프"].append(잰다(lambda: pg.replay()))
        del pg
        res["프롬프트 처리 + 첫 토큰 ms"][n] = {k: round(float(np.median(v)), 3) for k, v in t.items()}
        print(n, res["프롬프트 처리 + 첫 토큰 ms"][n], "다른 칸", res["마지막 행 로짓 다른 칸 (메가 대 따로)"][n], flush=True)
    # 생성: 메가커널 프롬프트 + 생성 메가커널 대 따로 도는 커널들로 하나씩
    생성다른 = {}
    for s in 문장들:
        ids = tk.나누기(s)
        gen = m.생성(ids, 64, 기록=True)
        mega = m.기록된로짓(64).copy()
        m.프롬메가쓰기 = False
        gen2 = m.생성_여러커널(ids, 64)
        m.프롬메가쓰기 = True
        seq = ids + gen
        m.토큰넣기(seq[:len(ids)])
        m.계산(1, len(ids), 0, "끝")
        rows = []
        for i in range(len(ids), len(seq) - 1):
            m.토큰넣기([seq[i]])
            m.계산(1, 1, i, "전부")
            rows.append(m.로짓(1).copy())
        ref = np.concatenate(rows, 0)
        생성다른[s[:24]] = {"토큰 같음": gen == gen2, "걸음마다 로짓 다른 칸": int((ref.view(np.uint32) != mega.view(np.uint32)).sum())}
    res["생성 (메가 프롬프트 + 생성 메가커널 대 하나씩)"] = 생성다른
    p = res["프롬프트 처리 + 첫 토큰 ms"]
    res["통과"] = (all(v["글 메가커널"] < v["글 따로 도는 커널 (3h)"] for v in p.values()) and
                 all(p[n]["글 메가커널"] < p[n]["PyTorch CUDA 그래프"] for n in (128, 256, 512)) and
                 all(v == 0 for v in res["마지막 행 로짓 다른 칸 (메가 대 따로)"].values()) and
                 all(v["토큰 같음"] and v["걸음마다 로짓 다른 칸"] == 0 for v in 생성다른.values()))
    res["오류 칸 (__geul_err)"] = m.오류칸()
    json.dump(res, open(os.path.join(HERE, "결과", "3단계3l.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"3l": res["통과"], "생성": 생성다른, "오류 칸": res["오류 칸 (__geul_err)"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
