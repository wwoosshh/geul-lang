#!/usr/bin/env python3
"""8단계 재기 — 자리 둘 계약: 밝힌 정밀도로 프롬프트를 더 빠르게 (docs/17 §7 "8단계" 의 판정 그대로).

  build/감사venv/Scripts/python -I research/gpu/8단계/재기9.py

GPT-2 small(build/gpt2-q8_0 · q4_0.gguf)과 XL(build/gpt2-xl-q8_0 · q4_0.gguf)의 자리 둘 판(`글GPT2(gguf읽기.gpt2정수(파일), KV형식="반실수",
자리수=2)` — 3단계/커널반Q8둘자리 · 커널반Q4둘자리 · 커널XL반Q8둘자리 · 커널XL반Q4둘자리.gl)을 llama.cpp(같은 GGUF, 기본 설정)와 같은
실행에서 번갈아 재고, 자리 넷 판(6 · 7단계의 판)은 같은 실행에서 다시 재어 함께 적는다.
8a: 행렬곱이 CPU 참조 구현(정수계약.py, 자리수=2)과 비트까지 같은가 — 6단계 재기7.행렬곱시험(실제 층 다섯 × 활성값 두 가지 × 행 수 × 판 일곱),
    3b 의 길 · 생성 메가커널 · 4c 의 (가)(나)(다) · 오류 칸. 자리 넷 판의 소스(.gl)와 글ptx.py 가 git 의 HEAD 와 같은가(= PTX 도 같다).
8b: 평가글(469토큰)의 양자화 모델 fp64 참값 대비 KL, 세 문장 × 64걸음 상대차 중앙값(글 자리 둘 · llama.cpp), 자리 넷 판(6단계.json ·
    7단계.json)과의 비. fp64 참값은 7단계 재기8.fp64참값(짧은실수 가중치를 GPU 에 두고 층마다 fp64 로).
8c: 프롬프트 처리 + 첫 토큰(128 · 512 · 1024) — 글 자리 둘 · 자리 넷 · llama.cpp 를 번갈아 7번(중앙값). 바닥(선형 층의 정수 연산을 int8
    최고치 3.2 × 10¹⁴ /s 로 나눈 시간) 대비 배수도 적는다.
8d: 생성 토큰당 = (64 − 1) / 63 — 짧은 문맥(문장 1) · 문맥 960, 같은 셋을 번갈아.
8e: 정수 타일 행렬곱 하나(XL c_fc — 행 1024 · 깊이 1600 · 열 6400)의 가장 빠른 판이 int8 최고치의 몇 % 인가(Q4_0 · Q8_0, 자리 둘 · 넷).
결과는 결과/8단계.json 에(단계마다 덮어 쓴다).
"""
import ctypes
import gc
import json
import os
import subprocess
import sys
import time

import numpy as np
import torch

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
for d in ("7단계", "6단계", "5단계", "4단계", "3단계"):
    sys.path.insert(0, os.path.join(ROOT, "research", "gpu", d))
import gguf읽기 as GR         # noqa: E402
import 재기4 as R             # noqa: E402
import 재기 as R3             # noqa: E402
import 재기7 as K7            # noqa: E402
import 재기8 as K8            # noqa: E402
from 양자화기준 import 견줌    # noqa: E402
from 커널생성 import 정수판표, 정수판모양    # noqa: E402
import 커널생성                               # noqa: E402

G = R.G
형식들 = ("q8_0", "q4_0")
크기들 = ("small", "XL")
결과 = os.path.join(HERE, "결과", "8단계.json")
N = 64
최고치 = 3.2e14                                           # int8 텐서 코어 — 연산(곱 + 합)/s


def 경로(크기, fmt):
    return os.path.join(ROOT, "build", f"gpt2-{fmt}.gguf" if 크기 == "small" else f"gpt2-xl-{fmt}.gguf")


def 모델폴더(크기):
    return os.path.join(ROOT, "build", "gpt2" if 크기 == "small" else "gpt2-xl")


def 글엔진(크기, fmt, 자리수, **kw):
    e = R.글엔진(GR.gpt2정수(경로(크기, fmt)), KV형식="반실수", 자리수=자리수, **kw)
    e.이름 = f"글 {fmt} 자리 {'둘' if 자리수 == 2 else '넷'}"
    return e


def 바닥ms(크기, n, 자리수):
    """프롬프트 n 토큰의 선형 층 정수 연산(곱 + 합, 자리마다)을 int8 최고치로 나눈 시간."""
    D, NL = (768, 12) if 크기 == "small" else (1600, 48)
    return 자리수 * 24 * n * D * D * NL / 최고치 * 1000


def 다른칸(a, b):
    return int(np.count_nonzero(np.asarray(a).view(np.uint32) != np.asarray(b).view(np.uint32)))


def 비우기():
    gc.collect()
    torch.cuda.empty_cache()


def git같은가(경로들):
    r = subprocess.run(["git", "diff", "--quiet", "HEAD", "--"] + 경로들, cwd=ROOT)
    return r.returncode == 0


def 비트시험(e, path, rng, prompts, 긴):
    m = e.m
    a = {"행렬곱 — CPU 참조 대비": K7.행렬곱시험(m, GR.GGUF(path), rng)}
    b = {}
    seqs = [p + m.생성(p, N) for p in prompts]
    for j, S in enumerate(seqs):
        p = len(prompts[j])
        base = R3.글로짓(m, [S], "하나씩", p)[0]
        for 방식 in ("한번에", "프롬프트+하나씩", "두조각"):
            x = R3.글로짓(m, [S], 방식, p)[0]
            b[f"문장{j + 1} {방식} (하나씩 대비)"] = {"다른 칸": 다른칸(x, base), "칸 수": int(x.size)}
        g = m.생성(prompts[j], N, 기록=True)
        rec = m.기록된로짓(N)
        b[f"문장{j + 1} 생성 메가커널 (하나씩 대비)"] = {"다른 칸": 다른칸(rec, base[p:p + N - 1]), "칸 수": int(rec.size),
                                                "토큰이 같은가": g == S[p:p + N]}
    L = min(len(S) for S in seqs)
    cut = [S[:L] for S in seqs]
    alone = [R3.글로짓(m, [S], "하나씩")[0] for S in cut]
    for 방식 in ("한번에", "하나씩"):
        x = R3.글로짓(m, cut, 방식)
        b[f"세 문장 한 묶음 {방식} (혼자 하나씩 대비)"] = {"다른 칸": sum(다른칸(x[j], alone[j]) for j in range(3)), "칸 수": int(x.size)}
    a["3b 의 길"] = b
    c4 = {}
    긴열 = 긴[:512]
    한번 = e.로짓들([긴열])
    c4["(가) 혼자 대 세 문장 한 묶음: 다른 칸"] = 다른칸(e.로짓들([cut[0]]), e.로짓들(cut))
    c4["(나) 한 번에 대 64토큰씩: 다른 칸"] = 다른칸(한번, e.로짓들([긴열], "조각", 64))
    c4["(나) 한 번에 대 하나씩: 다른 칸"] = 다른칸(한번, e.로짓들([긴열], "하나씩"))
    c4["(다) 한 번에를 다섯 번 더: 첫 번째와 다른 칸"] = [다른칸(한번, e.로짓들([긴열])) for _ in range(5)]
    a["4c 의 (가)(나)(다)"] = c4
    a["오류 칸"] = m.오류칸()
    a["통과"] = (all(v["다른 칸"] == 0 for v in a["행렬곱 — CPU 참조 대비"].values()) and
                all(v["다른 칸"] == 0 and v.get("토큰이 같은가", True) for v in b.values()) and
                c4["(가) 혼자 대 세 문장 한 묶음: 다른 칸"] == 0 and c4["(나) 한 번에 대 64토큰씩: 다른 칸"] == 0 and
                c4["(나) 한 번에 대 하나씩: 다른 칸"] == 0 and all(x == 0 for x in c4["(다) 한 번에를 다섯 번 더: 첫 번째와 다른 칸"]) and
                a["오류 칸"] == 0)
    return a


def 타일효율(dr, ptx, 자리수, M, K, N_):
    """정수 타일 판들(정수판들)의 행렬곱 하나 — 무작위 자리 · 가중치(시간만). (가장 빠른 판, µs, 최고치 대비 %)."""
    cu = dr.cu
    mod = dr.모듈(open(ptx, "rb").read())
    P, I = ctypes.c_uint64, ctypes.c_int64
    rng = np.random.default_rng(1)
    big = dr.할당(K * N_ + 1024)
    dr.올리기(big, rng.integers(0, 255, K * N_ + 1024).astype(np.uint8))
    dig = dr.할당(4 * M * K)
    dr.올리기(dig, rng.integers(0, 255, 4 * M * K).astype(np.uint8))
    E = rng.integers(-3, 3, M * (K // 32))
    inf = dr.할당(M * (K // 32) * 4 + 4096)
    dr.올리기(inf, (((153 - 8 * 자리수 + E) << 23) + 4194304).astype(np.int32))
    out, bias = dr.할당(M * N_ * 4), dr.할당(N_ * 4)
    scale = dr.할당((K // 32) * (N_ + 64) * 2)
    dr.올리기(scale, (rng.standard_normal((K // 32) * (N_ + 64)) * 0.01).astype(np.float16))
    e0, e1 = ctypes.c_void_p(), ctypes.c_void_p()
    cu.cuEventCreate(ctypes.byref(e0), 0)
    cu.cuEventCreate(ctypes.byref(e1), 0)
    runs = {}
    for 판 in 정수판표(자리수):
        행, 열, 스 = 정수판모양(판)
        ps = [P(dig), P(inf), P(big), P(scale), P(bias), P(out), I(M), I(K), I(N_), I((N_ + 63) // 64 * 64)] +             ([I(0), I(0)] if 커널생성.KV == "정수" else [])     # 11단계: 정수 KV 판의 타일은 행 · 열 시작을 받는다
        x = G._띄움(dr.함수(mod, 판), ((M + 행 - 1) // 행, (N_ + 열 - 1) // 열), (스, 1), ps)
        runs[판] = (x, lambda x=x: cu.cuLaunchKernel(x.fn, x.grid[0], x.grid[1], 1, x.block[0], x.block[1], 1, 0, None, x.args, None))
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 0.3:                 # 데우기(클럭)
        for _, run in runs.values():
            run()
        dr.맞추기()
    ts = {판: [] for 판 in runs}
    for _ in range(7):
        for 판, (_, run) in runs.items():
            cu.cuEventRecord(e0, None)
            for _ in range(10):
                run()
            cu.cuEventRecord(e1, None)
            cu.cuEventSynchronize(e1)
            ms = ctypes.c_float()
            cu.cuEventElapsedTime(ctypes.byref(ms), e0, e1)
            ts[판].append(ms.value / 10 * 1000)
    out_ = {판: round(sorted(v)[3], 1) for 판, v in ts.items()}
    best = min(out_, key=out_.get)
    eff = 2 * M * K * N_ * 자리수 / (out_[best] * 1e-6) / 최고치 * 100
    return {"판마다 µs": out_, "가장 빠른 판": best, "µs": out_[best], "int8 최고치 대비 %": round(eff, 1)}


def main():
    torch.zeros(1, device="cuda")
    res = {"환경": {"torch": torch.__version__, "llama.cpp": "b11496 (000bee54a)", "GPU": torch.cuda.get_device_name(0)},
           "8a 계약 (비트)": {}, "8b 정확도": {}, "8c 프롬프트 속도": {"실패": {}}, "8d 생성 속도": {"실패": {}}, "8e 타일 효율": {}}

    def 저장():
        os.makedirs(os.path.dirname(결과), exist_ok=True)
        json.dump(res, open(결과, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    평가글 = open(os.path.join(ROOT, "research", "gpu", "5단계", "평가글.txt"), encoding="utf-8").read()
    옛 = {"small": json.load(open(os.path.join(ROOT, "research", "gpu", "6단계", "결과", "6단계.json"), encoding="utf-8")),
         "XL": json.load(open(os.path.join(ROOT, "research", "gpu", "7단계", "결과", "7단계.json"), encoding="utf-8"))}
    res["8a 계약 (비트)"]["자리 넷 판의 소스가 HEAD 와 같다"] = git같은가(
        [f"research/gpu/3단계/{f}" for f in ("커널반Q8정수.gl", "커널반Q4정수.gl", "커널XL반Q8정수.gl", "커널XL반Q4정수.gl")] +
        ["research/gpu/글ptx.py"])
    일 = R.일꾼()
    rng = np.random.default_rng(89)
    for 크기 in 크기들:
        tk = G.토크나이저(모델폴더(크기))
        prompts = [tk.나누기(s) for s in R.문장들]
        평가 = tk.나누기(평가글)[:1024]
        긴 = (tk.나누기(R.문장들[1]) * 40)[:1024]
        for fmt in 형식들:
            열쇠 = f"{크기} {fmt}"
            path = 경로(크기, fmt)
            e2 = 글엔진(크기, fmt, 2)
            # ── 8a ──
            a = 비트시험(e2, path, rng, prompts, 긴)
            print("8a", 열쇠, "통과", a["통과"], "행렬곱 시험", len(a["행렬곱 — CPU 참조 대비"]), "오류 칸", a["오류 칸"], flush=True)
            res["8a 계약 (비트)"][열쇠] = a
            저장()
            평가로짓 = e2.로짓들([평가])
            생성2 = [e2.생성로짓(ids, N) for ids in prompts]
            # ── 8c · 8d (같은 실행에서 번갈아) ──
            e4 = 글엔진(크기, fmt, 4, 최대문장=1)
            라 = R.라마엔진(일, f"llama.cpp {fmt}", path)
            엔진들 = [e2, e4, 라]
            c, d = {}, {}
            for n in (128, 512, 1024):
                ids = 긴[:n]
                R.데우기(엔진들, lambda e: e.프롬프트(ids), res["8c 프롬프트 속도"]["실패"])
                c[str(n)] = R.번갈아(엔진들, lambda e: e.잰_프롬프트(ids), 7, res["8c 프롬프트 속도"]["실패"])
                c[str(n)]["바닥 ms (자리 둘)"] = round(바닥ms(크기, n, 2), 2)
                c[str(n)]["바닥 대비 (자리 둘)"] = round(c[str(n)][e2.이름] / 바닥ms(크기, n, 2), 2)
                print("8c", 열쇠, n, c[str(n)], flush=True)
            for 이름, ids in (("짧은 문맥 (문장 1)", prompts[0]), ("문맥 960", 긴[:960])):
                R.데우기(엔진들, lambda e: e.생성(ids, N), res["8d 생성 속도"]["실패"])
                t1 = R.번갈아(엔진들, lambda e: e.잰_생성(ids, 1), 7, res["8d 생성 속도"]["실패"])
                t64 = R.번갈아(엔진들, lambda e: e.잰_생성(ids, N), 7, res["8d 생성 속도"]["실패"])
                d[이름] = {k: round((t64[k] - t1[k]) / (N - 1), 4) for k in t1 if k in t64}
                print("8d", 열쇠, 이름, d[이름], flush=True)
            라로짓 = [라.생성로짓(ids, N) for ids in prompts]
            d["오류 칸"] = e2.m.오류칸()
            res["8c 프롬프트 속도"][열쇠], res["8d 생성 속도"][열쇠] = c, d
            라.닫기()
            e4.m.닫기()
            e2.m.닫기()
            del e2, e4, 라
            비우기()
            저장()
            # ── 8b ──
            _, wq = GR.gpt2가중치(path)
            W = {k: torch.from_numpy(v.copy()).cuda() for k, v in wq.items()}
            del wq
            gc.collect()
            bb = {"글 — 양자화 모델 참값 대비 (평가글)": 견줌(평가로짓, K8.fp64참값(W, 평가))}
            생성 = {}
            for 이름, 모음 in ((f"글 {fmt} 자리 둘", 생성2), (f"llama.cpp {fmt}", 라로짓)):
                rel = []
                for ids, (toks, logs) in zip(prompts, 모음):
                    seq = ids + toks
                    ref = K8.fp64참값(W, seq[:-1])[len(ids) - 1:]
                    rel.append(float(np.median(K8.걸음상대차(logs, ref))))
                생성[이름] = rel
            bb["생성 64걸음 — 양자화 모델 참값 대비 상대차 중앙값 (세 문장)"] = 생성
            if 크기 == "small":
                넷 = 옛["small"]["6b 정확도"][fmt]
                넷생성 = 넷["생성 64걸음 — 양자화 모델 참값 대비 상대차 중앙값 (세 문장)"][f"글 {fmt} 정수 계약"]
                넷KL = 넷["글 — 양자화 모델 참값 대비"]["KL 평균"]
            else:
                넷 = 옛["XL"]["7b 정확도"][fmt]
                넷생성 = 넷["생성 64걸음 — 양자화 모델 참값 대비 상대차 중앙값 (세 문장)"][f"글 {fmt}"]
                넷KL = 넷["글 — 양자화 모델 참값 대비 (평가글)"]["KL 평균"]
            bb["자리 넷 판 (기록)"] = {"KL 평균": 넷KL, "생성 64걸음": 넷생성}
            bb["자리 넷 판 대비 기하평균 비"] = float(np.exp(np.mean(np.log(np.array(생성[f"글 {fmt} 자리 둘"]) / np.array(넷생성)))))
            bb["통과"] = (bb["글 — 양자화 모델 참값 대비 (평가글)"]["KL 평균"] < 1e-5 and
                         all(g < l for g, l in zip(생성[f"글 {fmt} 자리 둘"], 생성[f"llama.cpp {fmt}"])))
            print("8b", 열쇠, json.dumps(bb, ensure_ascii=False), flush=True)
            res["8b 정확도"][열쇠] = bb
            del W, 평가로짓, 생성2, 라로짓
            비우기()
            저장()
    일.끝()
    # ── 8e ──
    dr = G.드라이버()
    for fmt, 자리 in (("q4_0", 2), ("q8_0", 2), ("q4_0", 4), ("q8_0", 4)):
        ptx = os.path.join(ROOT, "build", f"커널XL반{'Q4' if fmt == 'q4_0' else 'Q8'}{'둘자리' if 자리 == 2 else '정수'}.ptx")
        r = 타일효율(dr, ptx, 자리, 1024, 1600, 6400)
        res["8e 타일 효율"][f"XL c_fc {fmt} 자리 {'둘' if 자리 == 2 else '넷'}"] = r
        print("8e", fmt, 자리, r["가장 빠른 판"], r["µs"], r["int8 최고치 대비 %"], flush=True)
    res["8e 타일 효율"]["통과"] = all(res["8e 타일 효율"][f"XL c_fc {f} 자리 둘"]["int8 최고치 대비 %"] >= 55 for f in 형식들)
    c, d = res["8c 프롬프트 속도"], res["8d 생성 속도"]
    열쇠들 = [f"{크기} {fmt}" for 크기 in 크기들 for fmt in 형식들]
    둘 = lambda k: f"글 {k.split()[1]} 자리 둘"
    넷 = lambda k: f"글 {k.split()[1]} 자리 넷"
    라 = lambda k: f"llama.cpp {k.split()[1]}"
    c["통과"] = not c["실패"] and all(c[k][n][둘(k)] < c[k][n][라(k)] for k in 열쇠들 for n in ("128", "512", "1024"))
    d["통과"] = not d["실패"] and all(v[둘(k)] < v[라(k)] and v[둘(k)] <= 1.02 * v[넷(k)] for k in 열쇠들
                                    for kk, v in d[k].items() if kk != "오류 칸")
    res["통과"] = {"8a": all(res["8a 계약 (비트)"][k]["통과"] for k in 열쇠들) and res["8a 계약 (비트)"]["자리 넷 판의 소스가 HEAD 와 같다"],
                  "8b": all(res["8b 정확도"][k]["통과"] for k in 열쇠들), "8c": c["통과"], "8d": d["통과"], "8e": res["8e 타일 효율"]["통과"]}
    저장()
    print(json.dumps(res["통과"], ensure_ascii=False))


if __name__ == "__main__":
    main()
