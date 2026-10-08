#!/usr/bin/env python3
"""3단계 재기 — GPT-2 small: 글 커널 대 PyTorch eager fp32 (docs/17 §7 "3단계 시작"의 판정 그대로).

  build/감사venv/Scripts/python -I research/gpu/3단계/재기.py

3a 정확성 — 프롬프트 3개에서 탐욕 생성 64토큰이 PyTorch 와 같은가. 마지막 로짓(64번째 토큰을 고른 로짓)이 fp64 참값(같은
   모델을 PyTorch fp64 로)과 얼마나 다른가 — 상대차 = ‖x − 참값‖₂ / ‖참값‖₂. 글의 상대차가 PyTorch 의 2배 안이면 통과.
3b 의미(행 불변) — 같은 토큰열의 로짓을 여러 길로 계산해 "하나씩"(decode 만, 기준)과 비트가 다른 칸을 센다:
   한 번에(prefill) / 프롬프트는 한 번에·나머지는 하나씩(생성할 때의 길) / 두 조각 / 세 문장 한 묶음으로 한 번에 / 한 묶음으로 하나씩.
   묶음은 길이가 같아야 해서 세 토큰열을 가장 짧은 길이로 자른다. 글은 모두 0 이어야 통과. PyTorch 의 같은 비교는 기록만 한다.
3c 속도 — 배치 1 탐욕 생성에서 토큰당 시간 = (64토큰 생성 시간 − 1토큰 생성 시간) / 63. 1토큰 생성 시간(= 프롬프트 처리)도 적는다.
   글·PyTorch 를 번갈아 7번 재서 중앙값. 글의 생성은 메가커널(협력 실행 한 번에 토큰 63 개), 참고로 따로 도는 커널들의 판과
   PyTorch 의 decode 를 CUDA 그래프로 잡은 판도 잰다(판정 밖). 3b 에는 메가커널이 걸음마다 남긴 로짓도 넣는다.
3단계 성능(docs/17 §7 "3단계 성능")의 판정도 같은 실행에서 —
3e 생성의 바닥 — 토큰당 시간이 바닥(494 MB / 475 GB/s = 1.04 ms)의 1.15배(1.20 ms) 안이고 PyTorch CUDA 그래프 판보다 짧은가.
3f 긴 프롬프트 — 문장 2 의 토큰을 되풀이해 만든 128토큰·512토큰 프롬프트의 처리(+첫 토큰) 시간이 PyTorch eager 보다 짧은가.
   같은 길이로 잡은 PyTorch CUDA 그래프 판의 시간은 기록만 한다.
3g 의미를 지킨 채 — 3b 가 통과하고, 세 프롬프트 모두 64토큰이 같고, 64걸음 상대차의 중앙값이 프롬프트마다 PyTorch 의 2배 안인가.
--출력 <결과/파일.json> 을 주면 그 파일에 적는다(3단계 성능 2 의 3k 가 새 판으로 같은 것을 다시 잴 때 — 재기2.py).
"""
import ctypes
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
PROMPTS = [
    "The meaning of life is",
    "In a shocking finding, scientists discovered a herd of unicorns living in a remote, previously unexplored valley "
    "in the Andes Mountains. Even more surprising to the researchers was the fact that the unicorns spoke perfect English.",
    "Alan Turing was a",
]
N = 64
V = G.V


def 다른칸(a, b):
    return int(np.count_nonzero(a.view(np.uint32) != b.view(np.uint32)))


def 상대차(x, ref):
    x, ref = x.astype(np.float64), ref.astype(np.float64)
    return float(np.linalg.norm(x - ref) / np.linalg.norm(ref))


# ── 로짓을 여러 길로 ──

def 글로짓(m, seqs, 방식, p=None):
    B, n = len(seqs), len(seqs[0])
    out = np.empty((B, n, V), np.float32)
    if 방식 == "하나씩":
        for t in range(n):
            m.토큰넣기([s[t] for s in seqs])
            m.계산(B, 1, t)
            out[:, t] = m.로짓(B)
    elif 방식 == "한번에":
        m.토큰넣기([x for s in seqs for x in s])
        m.계산(B, n, 0)
        out[:] = m.로짓(B * n).reshape(B, n, V)
    elif 방식 in ("프롬프트+하나씩", "두조각"):
        assert B == 1
        k = p if 방식 == "프롬프트+하나씩" else n // 2
        m.토큰넣기(seqs[0][:k])
        m.계산(1, k, 0)
        out[0, :k] = m.로짓(k)
        if 방식 == "두조각":
            m.토큰넣기(seqs[0][k:])
            m.계산(1, n - k, k)
            out[0, k:] = m.로짓(n - k)
        else:
            for t in range(k, n):
                m.토큰넣기([seqs[0][t]])
                m.계산(1, 1, t)
                out[0, t] = m.로짓(1)
    return out


def 토치로짓(tm, seqs, 방식, p=None):
    B, n = len(seqs), len(seqs[0])
    dev = tm.dev
    out = np.empty((B, n, V), np.float64 if tm.dtype == torch.float64 else np.float32)
    tt = lambda rows: torch.tensor(rows, device=dev)
    if 방식 == "하나씩":
        for t in range(n):
            out[:, t] = tm.계산(tt([[s[t]] for s in seqs]), t)[:, 0].cpu().numpy()
    elif 방식 == "한번에":
        out[:] = tm.계산(tt(seqs), 0).cpu().numpy()
    elif 방식 in ("프롬프트+하나씩", "두조각"):
        k = p if 방식 == "프롬프트+하나씩" else n // 2
        out[0, :k] = tm.계산(tt([seqs[0][:k]]), 0)[0].cpu().numpy()
        if 방식 == "두조각":
            out[0, k:] = tm.계산(tt([seqs[0][k:]]), k)[0].cpu().numpy()
        else:
            for t in range(k, n):
                out[0, t] = tm.계산(tt([[seqs[0][t]]]), t)[0, 0].cpu().numpy()
    return out


def main():
    torch.zeros(1, device="cuda")
    w = G.가중치읽기(os.path.join(MODEL, "model.safetensors"))
    tk = G.토크나이저(MODEL)
    m = G.글GPT2(w)
    tm = T.토치GPT2(w)
    tm64 = T.토치GPT2(w, dtype=torch.float64, 최대문장=1)
    prompts = [tk.나누기(s) for s in PROMPTS]
    name = ctypes.create_string_buffer(256)
    m.dr.cu.cuDeviceGetName(name, 256, 0)
    res = {"환경": {"GPU": name.value.decode(), "torch": torch.__version__,
                   "allow_tf32(matmul)": torch.backends.cuda.matmul.allow_tf32,
                   "프롬프트 토큰 수": [len(p) for p in prompts]}}

    # 3a ─────────────────────────────────────────────────────────────────────────────────────
    a = []
    seqs = []
    for ids, text in zip(prompts, PROMPTS):
        p = len(ids)
        g_tok, t_tok = m.생성(ids, N), tm.생성(ids, N)
        S_g, S_t = ids + g_tok, ids + t_tok
        seqs.append(S_g)
        gl = 글로짓(m, [S_g], "프롬프트+하나씩", p)[0]       # 생성할 때의 길 — 행 p−1 … p+62 가 64번의 고르기
        tl = 토치로짓(tm, [S_t], "프롬프트+하나씩", p)[0]
        r64_g = 토치로짓(tm64, [S_g[:p + N - 1]], "한번에")[0]
        r64_t = r64_g if S_t[:p + N - 1] == S_g[:p + N - 1] else 토치로짓(tm64, [S_t[:p + N - 1]], "한번에")[0]
        steps = range(p - 1, p + N - 1)
        rel_g = [상대차(gl[i], r64_g[i]) for i in steps]
        rel_t = [상대차(tl[i], r64_t[i]) for i in steps]
        same = next((i for i in range(N) if g_tok[i] != t_tok[i]), None)
        a.append({"프롬프트": text[:40] + ("…" if len(text) > 40 else ""), "프롬프트 토큰": p,
                  "글 생성": tk.잇기(g_tok), "PyTorch 생성": tk.잇기(t_tok),
                  "64토큰이 같은가": same is None, "처음 갈린 자리": same,
                  "호스트에서 다시 고른 토큰이 GPU 와 같은가(글)": [int(gl[i].argmax()) for i in steps] == g_tok,
                  "fp64 참값이 고른 토큰과 같은가(글 / PyTorch)": [
                      [int(r64_g[i].argmax()) for i in steps] == g_tok, [int(r64_t[i].argmax()) for i in steps] == t_tok],
                  "마지막 로짓 상대차 (글)": rel_g[-1], "마지막 로짓 상대차 (PyTorch)": rel_t[-1],
                  "배수 (글 / PyTorch)": rel_g[-1] / rel_t[-1],
                  "64걸음 상대차 중앙값 (글 / PyTorch)": [float(np.median(rel_g)), float(np.median(rel_t))],
                  "64걸음 상대차 최댓값 (글 / PyTorch)": [max(rel_g), max(rel_t)],
                  "사후: 글 ≤ PyTorch 인 걸음 (64 중)": sum(x <= y for x, y in zip(rel_g, rel_t)),
                  "사후: 글이 PyTorch 의 2배 안인 걸음 (64 중)": sum(x <= 2 * y for x, y in zip(rel_g, rel_t)),
                  "사후: 걸음별 배수의 기하평균": float(np.exp(np.mean(np.log(np.array(rel_g) / np.array(rel_t))))),
                  "통과": same is None and rel_g[-1] <= 2 * rel_t[-1]})
        print(f"3a {a[-1]['프롬프트']}: 같음={same is None}, 상대차 글 {rel_g[-1]:.3e} / PyTorch {rel_t[-1]:.3e}", flush=True)
    res["3a 정확성"] = a

    # 3b ─────────────────────────────────────────────────────────────────────────────────────
    b = {"글": {}, "PyTorch": {}}
    for 이름, f, mod in (("글", 글로짓, m), ("PyTorch", 토치로짓, tm)):
        for j, S in enumerate(seqs):
            p = len(prompts[j])
            base = f(mod, [S], "하나씩")[0]
            for 방식 in ("한번에", "프롬프트+하나씩", "두조각"):
                x = f(mod, [S], 방식, p)[0]
                b[이름][f"문장{j + 1} {방식}"] = {"다른 칸": 다른칸(x, base), "다른 행": int(sum(다른칸(x[i], base[i]) > 0 for i in range(len(S)))),
                                              "최대 절대차": float(np.abs(x - base).max()), "행 수": len(S),
                                              "고른 토큰이 다른 행": int((x.argmax(-1) != base.argmax(-1)).sum())}
            if 이름 == "글":                       # 생성 메가커널(토큰 생성의 길): 걸음마다의 로짓 — 위치 p … p + N − 2
                g = m.생성(prompts[j], N, 기록=True)
                rec = m.기록된로짓(N)
                ref = base[p:p + N - 1]
                b[이름][f"문장{j + 1} 생성 메가커널"] = {"다른 칸": 다른칸(rec, ref), "행 수": N - 1,
                                                       "토큰이 같은가": g == S[p:p + N],
                                                       "최대 절대차": float(np.abs(rec - ref).max())}
        L = min(len(S) for S in seqs)
        cut = [S[:L] for S in seqs]
        alone = [f(mod, [S], "하나씩")[0] for S in cut]
        for 방식 in ("한번에", "하나씩"):
            x = f(mod, cut, 방식)
            b[이름][f"세 문장 한 묶음 {방식}"] = {"다른 칸": sum(다른칸(x[j], alone[j]) for j in range(3)),
                                            "최대 절대차": float(max(np.abs(x[j] - alone[j]).max() for j in range(3))),
                                            "행 수": 3 * L,
                                            "고른 토큰이 다른 행": int(sum((x[j].argmax(-1) != alone[j].argmax(-1)).sum() for j in range(3)))}
        print(f"3b {이름}: " + ", ".join(f"{k} {v['다른 칸']}" for k, v in b[이름].items()), flush=True)
    b["통과"] = all(v["다른 칸"] == 0 for v in b["글"].values())
    res["3b 의미"] = b

    # 3c ─────────────────────────────────────────────────────────────────────────────────────
    graph = T.토치그래프생성(tm, 최대길이=max(len(p) for p in prompts) + N)
    def 잰다(f, ids, n):
        torch.cuda.synchronize()
        m.dr.맞추기()
        s = time.perf_counter()
        f(ids, n)
        torch.cuda.synchronize()
        m.dr.맞추기()
        return (time.perf_counter() - s) * 1000
    runners = {"글": m.생성, "PyTorch eager": tm.생성, "PyTorch CUDA 그래프 (참고)": graph.생성,
               "글 여러 커널 (참고)": m.생성_여러커널}
    for ids in prompts:                     # 데우기 + 같은 토큰인지
        outs = {k: f(ids, N) for k, f in runners.items()}
        assert outs["PyTorch CUDA 그래프 (참고)"] == outs["PyTorch eager"], "그래프 판의 토큰이 eager 와 다르다"
        assert outs["글 여러 커널 (참고)"] == outs["글"], "글의 두 생성 길의 토큰이 다르다"
    c = {}
    for j, ids in enumerate(prompts):
        t1 = {k: [] for k in runners}
        tn = {k: [] for k in runners}
        for _ in range(7):
            for k, f in runners.items():
                t1[k].append(잰다(f, ids, 1))
                tn[k].append(잰다(f, ids, N))
        row = {}
        for k in runners:
            a1, an = float(np.median(t1[k])), float(np.median(tn[k]))
            row[k] = {"프롬프트 처리 + 첫 토큰 ms": round(a1, 3), f"{N}토큰 생성 ms": round(an, 3),
                      "토큰당 ms": round((an - a1) / (N - 1), 4)}
        c[f"문장{j + 1} ({len(ids)}토큰)"] = row
        print(f"3c 문장{j + 1}: " + ", ".join(f"{k} {v['토큰당 ms']} ms/토큰" for k, v in row.items()), flush=True)
    # 긴 프롬프트의 처리 시간 (3f) — PyTorch CUDA 그래프 판(같은 길이로 잡은 그래프)은 기록만
    long_ids = (prompts[1] * 40)
    for n in (128, 512):
        ids = long_ids[:n]
        tt = torch.tensor([ids], device="cuda")
        s_ = torch.cuda.Stream()
        s_.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(s_):
            for _ in range(3):
                tm.계산(tt, 0, 끝만=True).argmax(-1)
        torch.cuda.current_stream().wait_stream(s_)
        pg = torch.cuda.CUDAGraph()
        with torch.cuda.graph(pg):
            tm.계산(tt, 0, 끝만=True).argmax(-1)
        t = {"글": [], "PyTorch eager": [], "PyTorch CUDA 그래프 (참고)": []}
        for _ in range(7):
            for k in ("글", "PyTorch eager"):
                t[k].append(잰다(runners[k], ids, 1))
            t["PyTorch CUDA 그래프 (참고)"].append(잰다(lambda *_: pg.replay(), ids, 1))
        c[f"긴 프롬프트 {n}토큰 처리 + 첫 토큰 ms"] = {k: round(float(np.median(v)), 3) for k, v in t.items()}
        print(f"3c 프롬프트 {n}: {c[f'긴 프롬프트 {n}토큰 처리 + 첫 토큰 ms']}", flush=True)
    per = [v["글"]["토큰당 ms"] / v["PyTorch eager"]["토큰당 ms"] for k, v in c.items() if k.startswith("문장")]
    c["글 / PyTorch eager 토큰당 시간 (문장별)"] = [round(x, 3) for x in per]
    c["통과"] = all(x <= 1 for x in per)
    # 3단계 성능의 판정 (docs/17 §7 "3단계 성능")
    toks = [v["글"]["토큰당 ms"] for k, v in c.items() if k.startswith("문장")]
    graphs = [v["PyTorch CUDA 그래프 (참고)"]["토큰당 ms"] for k, v in c.items() if k.startswith("문장")]
    c["3e 생성의 바닥"] = {"글 토큰당 ms": toks, "바닥 ms (494 MB / 475 GB/s)": 1.04, "기준 ms (바닥 × 1.15)": 1.20,
                       "PyTorch CUDA 그래프 ms": graphs,
                       "통과": all(x <= 1.20 for x in toks) and all(x < y for x, y in zip(toks, graphs))}
    c["3f 긴 프롬프트"] = {n: c[f"긴 프롬프트 {n}토큰 처리 + 첫 토큰 ms"] for n in (128, 512)}
    c["3f 긴 프롬프트"]["통과"] = all(c[f"긴 프롬프트 {n}토큰 처리 + 첫 토큰 ms"]["글"] < c[f"긴 프롬프트 {n}토큰 처리 + 첫 토큰 ms"]["PyTorch eager"]
                                 for n in (128, 512))
    res["3c 속도"] = c
    res["오류 칸 (__geul_err)"] = m.오류칸()

    meds = [x["64걸음 상대차 중앙값 (글 / PyTorch)"] for x in a]
    res["3g 의미를 지킨 채"] = {"3b 다른 칸 0": b["통과"], "64토큰이 같은가": [x["64토큰이 같은가"] for x in a],
                             "64걸음 상대차 중앙값의 배수": [round(g / t, 3) for g, t in meds],
                             "통과": b["통과"] and all(x["64토큰이 같은가"] for x in a) and all(g <= 2 * t for g, t in meds)}
    os.makedirs(os.path.join(HERE, "결과"), exist_ok=True)
    출력 = os.path.join(HERE, "결과", "3단계.json")
    if "--출력" in sys.argv:                  # 기록된 결과를 덮어쓰지 않고 다른 판으로 다시 잴 때 (3단계 성능 2 의 3k)
        출력 = os.path.join(HERE, sys.argv[sys.argv.index("--출력") + 1])
    json.dump(res, open(출력, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"3a": [x["통과"] for x in a], "3b": b["통과"], "3c": c["통과"], "3e": c["3e 생성의 바닥"]["통과"],
                      "3f": c["3f 긴 프롬프트"]["통과"], "3g": res["3g 의미를 지킨 채"]["통과"],
                      "오류 칸": res["오류 칸 (__geul_err)"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
