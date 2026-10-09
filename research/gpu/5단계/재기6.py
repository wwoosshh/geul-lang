#!/usr/bin/env python3
"""5단계 재기 — 양자화: 밝힌 손실만 (docs/17 §7 "5단계" 의 판정 그대로).

  build/감사venv/Scripts/python -I research/gpu/5단계/재기6.py

GGUF 셋(build/gpt2-f16 · q8_0 · q4_0.gguf — llama-quantize 로 만든 것)을 글과 llama.cpp 가 같은 파일로 읽는다. 엔진:
  글 양자 판   — 글GPT2(gguf읽기.gpt2양자(파일), KV형식="반실수"): 커널반F16 · 커널반Q8 · 커널반Q4.gl. 가중치를 GPU 에 블록 그대로 두고
                커널 안에서 풀어(정확) 순서 약속대로 곱해더한다.
  글 참조 판   — 같은 가중치를 미리 풀어 짧은실수로 둔 판(gguf읽기.gpt2가중치, 커널반.gl — 반실수 KV).
  llama.cpp    — b11496 CUDA, 같은 GGUF, 기본 설정(KV F16, 플래시 어텐션 자동) — 4단계의 일꾼(제 프로세스).
5a: 형식마다 3b 의 모든 길(3단계 재기.py 의 글로짓 — 하나씩 · 한번에 · 프롬프트+하나씩 · 두조각 · 세 문장 한 묶음의 한번에 · 하나씩,
    그리고 생성 메가커널이 걸음마다 남긴 로짓 · 토큰)에서 양자 판과 참조 판의 다른 칸. 양자 판 안에서 4c 의 (가)(나)(다), 오류 칸.
5b: 평가글(469토큰)을 한 번에 — 원래 모델 fp64 대비 KL 평균(글 · llama.cpp), 양자화 모델 fp64 대비 KL 평균(글), 고른 토큰 일치(기록).
    세 문장 × 탐욕 64걸음(엔진마다 제 토큰) — 양자화 모델 fp64 참값 대비 상대차 중앙값(글 · llama.cpp).
5c: 생성 토큰당 = (64토큰 − 1토큰) / 63, 형식마다 글과 llama.cpp 를 번갈아 7번(중앙값) — 짧은 문맥(문장 1) · 문맥 960(문장 2 의
    되풀이). 바닥 대비와 프롬프트 처리 + 첫 토큰(128 · 512 · 1024) 은 기록.
5d: 형식마다 세 프롬프트 × 64토큰을 20번 — 토큰과 걸음마다 로짓이 첫 번째와 같은가, 오류 칸, 실패.
결과는 결과/5단계.json 에(단계마다 덮어 쓴다).
"""
import gc
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
sys.path.insert(0, os.path.join(ROOT, "research", "gpu", "3단계"))
import gguf읽기 as GR        # noqa: E402
import 재기4 as R            # noqa: E402  (엔진: 글 · llama.cpp 일꾼, 번갈아, 문장들)
import 재기 as R3            # noqa: E402  (3단계의 글로짓 — 3b 의 길들)
from 재기5 import fp64참값   # noqa: E402
from 양자화기준 import 견줌   # noqa: E402

G = R.G
V = R.V
형식들 = ("f16", "q8_0", "q4_0")
바닥 = {"f16": 0.52, "q8_0": 0.28, "q4_0": 0.19}          # 가중치 바이트 / 475 GB/s (ms — docs/17 의 표)
결과 = os.path.join(HERE, "결과", "5단계.json")


def 다른칸(a, b):
    return int(np.count_nonzero(a.view(np.uint32) != b.view(np.uint32)))


def main():
    torch.zeros(1, device="cuda")
    res = {"환경": {"torch": torch.__version__, "llama.cpp": "b11496 (000bee54a)", "GPU": torch.cuda.get_device_name(0)},
           "5a 밝힌 손실만 (비트)": {}, "5b 품질": {}, "5c 속도": {}, "5d 안정성": {}}

    def 저장():
        os.makedirs(os.path.dirname(결과), exist_ok=True)
        json.dump(res, open(결과, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    tk = G.토크나이저(R.MODEL)
    prompts = [tk.나누기(s) for s in R.문장들]
    글 = tk.나누기(open(os.path.join(HERE, "평가글.txt"), encoding="utf-8").read())[:1024]
    긴 = (tk.나누기(R.문장들[1]) * 40)[:1024]
    w0 = G.가중치읽기(os.path.join(R.MODEL, "model.safetensors"))
    W0 = {k: torch.from_numpy(v.copy()).cuda().double() for k, v in w0.items()}
    원참 = fp64참값(W0, 글)
    del W0, w0
    gc.collect()
    torch.cuda.empty_cache()
    res["평가글 토큰 수"] = len(글)
    일 = R.일꾼()
    N = 64
    양자엔진, 라마들 = {}, {}

    for fmt in 형식들:
        path = os.path.join(ROOT, "build", f"gpt2-{fmt}.gguf")
        _, wq = GR.gpt2가중치(path)
        글양 = R.글엔진(GR.gpt2양자(path), KV형식="반실수")
        글양.이름 = f"글 {fmt}"
        mq = 글양.m
        mr = G.글GPT2(wq, KV형식="반실수")
        print(fmt, "형식:", mq.층형식, mq.낱말형식, flush=True)

        # 5a ── 밝힌 손실만 (비트) ───────────────────────────────────────────────────────────────────
        a = {}
        seqs = [p + mq.생성(p, N) for p in prompts]
        for j, S in enumerate(seqs):
            p = len(prompts[j])
            for 방식 in ("하나씩", "한번에", "프롬프트+하나씩", "두조각"):
                x = R3.글로짓(mq, [S], 방식, p)[0]
                y = R3.글로짓(mr, [S], 방식, p)[0]
                a[f"문장{j + 1} {방식}"] = {"다른 칸": 다른칸(x, y), "칸 수": int(x.size)}
            gq = mq.생성(prompts[j], N, 기록=True)
            rq = mq.기록된로짓(N).copy()
            gr = mr.생성(prompts[j], N, 기록=True)
            rr = mr.기록된로짓(N).copy()
            a[f"문장{j + 1} 생성 메가커널"] = {"다른 칸": 다른칸(rq, rr), "칸 수": int(rq.size), "토큰이 같은가": gq == gr == S[p:p + N]}
        L = min(len(S) for S in seqs)
        cut = [S[:L] for S in seqs]
        for 방식 in ("한번에", "하나씩"):
            x, y = R3.글로짓(mq, cut, 방식), R3.글로짓(mr, cut, 방식)
            a[f"세 문장 한 묶음 {방식}"] = {"다른 칸": 다른칸(x, y), "칸 수": int(x.size)}
        # 양자 판 안에서 4c 의 (가)(나)(다)
        c4 = {}
        긴열 = 긴[:512]
        혼자, 묶음, 한번 = 글양.로짓들([cut[0]]), 글양.로짓들(cut), 글양.로짓들([긴열])
        c4["(가) 혼자 대 세 문장 한 묶음: 다른 칸"] = 다른칸(혼자, 묶음)
        c4["(나) 한 번에 대 64토큰씩: 다른 칸"] = 다른칸(한번, 글양.로짓들([긴열], "조각", 64))
        c4["(나) 한 번에 대 하나씩: 다른 칸"] = 다른칸(한번, 글양.로짓들([긴열], "하나씩"))
        c4["(다) 한 번에를 다섯 번 더: 첫 번째와 다른 칸"] = [다른칸(한번, 글양.로짓들([긴열])) for _ in range(5)]
        a["4c (양자 판 안)"] = c4
        a["오류 칸 (양자 판 · 참조 판)"] = [mq.오류칸(), mr.오류칸()]
        a["통과"] = (all(v["다른 칸"] == 0 for k, v in a.items() if isinstance(v, dict) and "다른 칸" in v) and
                    all(v.get("토큰이 같은가", True) for v in a.values() if isinstance(v, dict)) and
                    c4["(가) 혼자 대 세 문장 한 묶음: 다른 칸"] == 0 and c4["(나) 한 번에 대 64토큰씩: 다른 칸"] == 0 and
                    c4["(나) 한 번에 대 하나씩: 다른 칸"] == 0 and all(x == 0 for x in c4["(다) 한 번에를 다섯 번 더: 첫 번째와 다른 칸"]) and
                    a["오류 칸 (양자 판 · 참조 판)"] == [0, 0])
        print("5a", fmt, {k: (v["다른 칸"] if isinstance(v, dict) and "다른 칸" in v else v) for k, v in a.items()}, flush=True)
        res["5a 밝힌 손실만 (비트)"][fmt] = a
        mr.닫기()
        del mr
        저장()

        # 5b ── 품질 (같은 GGUF) ─────────────────────────────────────────────────────────────────────
        Wq = {k: torch.from_numpy(v.copy()).cuda().double() for k, v in wq.items()}
        양참 = fp64참값(Wq, 글)
        라 = R.라마엔진(일, f"llama.cpp {fmt}", path)
        b = {"가중치 양자화만 (양자화 모델 fp64 대 원래 fp64) — 기록": 견줌(양참, 원참)}
        gx = 글양.로짓들([글])
        lx = 라.로짓들([글])
        b["글 — 원래 모델 대비"] = 견줌(gx, 원참)
        b["글 — 양자화 모델 참값 대비"] = 견줌(gx, 양참)
        b["llama.cpp — 원래 모델 대비"] = 견줌(lx, 원참)
        b["llama.cpp — 양자화 모델 참값 대비"] = 견줌(lx, 양참)
        생성 = {}
        for e in (글양, 라):
            rel = []
            for ids in prompts:
                toks, logs = e.생성로짓(ids, N)
                seq = ids + toks
                ref = fp64참값(Wq, seq[:-1])[len(ids) - 1:]
                r = np.linalg.norm(logs.astype(np.float64) - ref, axis=-1) / np.linalg.norm(ref, axis=-1)
                rel.append(float(np.median(r)))
            생성[e.이름] = rel
        b["생성 64걸음 — 양자화 모델 참값 대비 상대차 중앙값 (세 문장)"] = 생성
        b["통과"] = (b["글 — 원래 모델 대비"]["KL 평균"] < b["llama.cpp — 원래 모델 대비"]["KL 평균"] and
                    b["글 — 양자화 모델 참값 대비"]["KL 평균"] < 1e-6 and
                    all(g < l for g, l in zip(생성[글양.이름], 생성[라.이름])))
        print("5b", fmt, json.dumps(b, ensure_ascii=False), flush=True)
        res["5b 품질"][fmt] = b
        del Wq
        gc.collect()
        torch.cuda.empty_cache()
        저장()

        # 5d ── 안정성 ──────────────────────────────────────────────────────────────────────────────
        첫, 다름토큰, 다름로짓, 실패 = {}, 0, 0, 0
        for _ in range(20):
            for s, ids in zip(R.문장들, prompts):
                try:
                    toks, logs = 글양.생성로짓(ids, N)
                except Exception:
                    실패 += 1
                    continue
                if s not in 첫:
                    첫[s] = (toks, logs)
                else:
                    다름토큰 += int(toks != 첫[s][0])
                    다름로짓 += int(다른칸(logs, 첫[s][1]) > 0)
        d = {"생성 수": 60, "첫 번째와 토큰이 다른 생성": 다름토큰, "첫 번째와 로짓 비트가 다른 생성": 다름로짓, "실패": 실패,
             "오류 칸": mq.오류칸()}
        d["통과"] = 다름토큰 == 0 and 다름로짓 == 0 and 실패 == 0 and d["오류 칸"] == 0
        print("5d", fmt, d, flush=True)
        res["5d 안정성"][fmt] = d
        저장()
        양자엔진[fmt], 라마들[fmt] = 글양, 라

    # 5c ── 속도 ────────────────────────────────────────────────────────────────────────────────────
    c = {"생성 ms/토큰": {}, "바닥 대비 (글, 기록)": {}, "프롬프트 처리 + 첫 토큰 ms (기록)": {}, "실패": {}}
    짧은 = prompts[0]
    for fmt in 형식들:
        엔진들 = [양자엔진[fmt], 라마들[fmt]]
        c["생성 ms/토큰"][fmt] = {}
        for 이름, ids in (("짧은 문맥 (문장 1, 5토큰)", 짧은), ("문맥 960", 긴[:960])):
            R.데우기(엔진들, lambda e: e.생성(ids, 64), c["실패"])
            t1 = R.번갈아(엔진들, lambda e: e.잰_생성(ids, 1), 7, c["실패"])
            t64 = R.번갈아(엔진들, lambda e: e.잰_생성(ids, 64), 7, c["실패"])
            c["생성 ms/토큰"][fmt][이름] = {k: round((t64[k] - t1[k]) / 63, 4) for k in t1 if k in t64}
            print("5c 생성", fmt, 이름, c["생성 ms/토큰"][fmt][이름], flush=True)
        g = 양자엔진[fmt].이름
        c["바닥 대비 (글, 기록)"][fmt] = {k: round(v[g] / 바닥[fmt], 2) for k, v in c["생성 ms/토큰"][fmt].items() if g in v}
        c["프롬프트 처리 + 첫 토큰 ms (기록)"][fmt] = {}
        for n in (128, 512, 1024):
            ids = 긴[:n]
            R.데우기(엔진들, lambda e: e.프롬프트(ids), c["실패"])
            c["프롬프트 처리 + 첫 토큰 ms (기록)"][fmt][n] = R.번갈아(엔진들, lambda e: e.잰_프롬프트(ids), 7, c["실패"])
            print("5c 프롬프트", fmt, n, c["프롬프트 처리 + 첫 토큰 ms (기록)"][fmt][n], flush=True)
        저장()
    c["오류 칸"] = {fmt: 양자엔진[fmt].m.오류칸() for fmt in 형식들}
    gm = c["생성 ms/토큰"]
    c["통과"] = (not c["실패"] and all(len(v) == 2 and v[양자엔진[f].이름] < v[라마들[f].이름]
                                      for f in 형식들 for v in gm[f].values()) and all(x == 0 for x in c["오류 칸"].values()))
    res["5c 속도"] = c
    for fmt in 형식들:
        라마들[fmt].닫기()
    일.끝()
    res["통과"] = {"5a": all(res["5a 밝힌 손실만 (비트)"][f]["통과"] for f in 형식들),
                  "5b": all(res["5b 품질"][f]["통과"] for f in 형식들), "5c": c["통과"],
                  "5d": all(res["5d 안정성"][f]["통과"] for f in 형식들)}
    저장()
    print(json.dumps(res["통과"], ensure_ascii=False))


if __name__ == "__main__":
    main()
