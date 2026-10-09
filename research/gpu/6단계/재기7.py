#!/usr/bin/env python3
"""6단계 재기 — 정수 텐서 코어: 프롬프트 처리를 밝힌 정밀도로 (docs/17 §7 "6단계" 의 판정 그대로).

  build/감사venv/Scripts/python -I research/gpu/6단계/재기7.py

GGUF 둘(build/gpt2-q8_0 · q4_0.gguf — 5단계와 같은 파일)을 글의 정수 블록 계약 판(`글GPT2(gguf읽기.gpt2정수(파일), KV형식="반실수")`
— 3단계/커널반Q8정수 · 커널반Q4정수.gl)과 llama.cpp(같은 GGUF, 기본 설정 — 4단계의 일꾼)로.
6a: 행렬곱이 CPU 참조 구현(정수계약.py)과 비트까지 같은가 — GGUF 의 실제 층 다섯(c_attn · c_proj · c_fc · mlp c_proj · 낱말표)의 가중치와
    무작위 활성값 · 치우침(보통: 이상치를 섞음 · 0 인 블록, 극단: S 가 가장 큰 블록 · E 가 잘리는 블록 · 정규수 끝)을 정수 텐서
    코어 타일 판 모두(커널생성.정수판들 — 프롬프트의 판)와 줄 판(dp4a — 생성 메가커널과 같은 코드)에 넣는다. 그리고 GPT-2 로짓이
    3b 의 모든 길(재기.py 의 글로짓 — 행이 다섯 이상이면 타일 판, 네 자리 바꾸기를 앞 커널에 묶은 길)과 생성 메가커널에서 비트까지
    같은가, 4c 의 (가)(나)(다), 오류 칸.
6b: 평가글(469토큰) — 양자화 모델 fp64 참값 대비 KL, 세 문장 × 64걸음 상대차 중앙값(글 · llama.cpp), 5단계 판(결과/5단계.json)과의
    기하평균 비.
6c: 프롬프트 처리 + 첫 토큰(128 · 512 · 1024) — 글과 llama.cpp 를 번갈아 7번(중앙값). 5단계 판도 기록.
6d: 생성 토큰당 = (64토큰 − 1토큰) / 63 — 짧은 문맥(문장 1) · 문맥 960. 5단계 판도 기록.
결과는 결과/6단계.json 에(단계마다 덮어 쓴다).
"""
import ctypes
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
sys.path.insert(0, os.path.join(ROOT, "research", "gpu", "5단계"))
sys.path.insert(0, os.path.join(ROOT, "research", "gpu", "4단계"))
sys.path.insert(0, os.path.join(ROOT, "research", "gpu", "3단계"))
import 정수계약 as C          # noqa: E402
import gguf읽기 as GR         # noqa: E402
import 재기4 as R             # noqa: E402
import 재기 as R3             # noqa: E402
from 재기5 import fp64참값    # noqa: E402
from 양자화기준 import 견줌    # noqa: E402

G = R.G
형식들 = ("q8_0", "q4_0")
결과 = os.path.join(HERE, "결과", "6단계.json")
c_u64, c_i64 = ctypes.c_uint64, ctypes.c_int64


def 다른칸(a, b):
    return int(np.count_nonzero(np.asarray(a).view(np.uint32) != np.asarray(b).view(np.uint32)))


def 층정수(g, name):
    """GGUF 텐서 → (q [K][N] int64, d [KB][N] float32 — 반실수 값)."""
    t, (K, N), raw = g.원(name)
    bl = raw.reshape(N, K // 32, GR.블록[t][1])
    d = np.ascontiguousarray(bl[:, :, :2]).view(np.float16).reshape(N, K // 32).T.astype(np.float32)
    if t == GR.Q8_0:
        q = bl[:, :, 2:].view(np.int8).astype(np.int64)
    else:
        qs = bl[:, :, 2:]
        q = np.concatenate([(qs & 15).astype(np.int64) - 8, (qs >> 4).astype(np.int64) - 8], 2)
    return np.ascontiguousarray(q.reshape(N, K).T), d


def 활성값(rng, M, K, 종류):
    """무작위 활성값 [M][K]: "보통"(정규분포, 1% 를 40 배), "극단"(블록마다 S 가 가장 커지는 값 · E 가 잘리는 값 · 정규수 끝)."""
    x = rng.standard_normal((M, K)).astype(np.float32) * np.where(rng.random((M, K)) < 0.01, 40, 1).astype(np.float32)
    if 종류 == "극단":
        for r in range(M):
            k = int(rng.integers(-20, 20))
            v = np.float32(np.nextafter(np.float32(2), np.float32(0))) * np.float32(2.0 ** k) * (-1 if r % 2 else 1)
            x[r, 64:96], x[r, 96:128] = v, -v                  # 칸 모두 ±(2 − 2⁻²³)·2^k — 자리 D₃ = ±64 (S₃ 가 가장 크다)
        x[1 % M, 128:160] = np.float32(1e-35)                 # E 가 −98 로 잘리는 블록
        x[2 % M, 160:192] = np.float32(3e29)                  # E = 98
        x[3 % M, 192:224] = np.float32(-2.0 ** -126)          # 정규수 끝
    x[0, 32:64] = 0                                           # 0 인 블록
    return x


def 행렬곱시험(m, g, rng):
    """6a 의 앞쪽: GGUF 의 실제 층 다섯의 가중치(극단 시험은 앞 두 블록의 가중치를 가장 작은 값으로) · 무작위 활성값 · 무작위
    치우침으로, 정수 텐서 코어 타일 판 모두(커널생성.정수판들 — 프롬프트의 판)와 dp4a 줄 판(정수줄선형 — 생성 메가커널과 같은
    코드)을 CPU 참조 구현(정수계약.py)과 대조한다. 타일 판은 정수로(활성값 바꾸기)를 거친다."""
    dr, out = m.dr, {}
    층 = {"c_attn": ("blk.3.attn_qkv.weight", "attn.c_attn.weight", 3),
         "c_proj": ("blk.5.attn_output.weight", "attn.c_proj.weight", 5),
         "c_fc": ("blk.7.ffn_up.weight", "mlp.c_fc.weight", 7),
         "mlp c_proj": ("blk.9.ffn_down.weight", "mlp.c_proj.weight", 9),
         "로짓 (낱말표)": ("token_embd.weight", None, None)}
    입력 = dr.할당(1024 * 3072 * 4)
    출력 = dr.할당(1024 * 50257 * 4)
    가중칸 = dr.할당(50304 * 768 * 2)
    치우칸 = dr.할당(50304 * 4)
    for 이름, (gname, wname, l) in 층.items():
        로짓 = wname is None
        wt0 = m.wteT if 로짓 else m.층[l][wname]
        q0, d0 = 층정수(g, gname)
        K, N = q0.shape
        for 종류 in ("보통", "극단"):
            q, d, wt = q0, d0, wt0
            if 종류 == "극단":                                 # 앞 두 블록의 가중치를 가장 작은 값(Q8_0 −128 · Q4_0 −8)으로, 척도 1
                형식 = m.낱말형식 if 로짓 else m.층형식
                q, d = q0.copy(), d0.copy()
                q[64:128, :] = -128 if 형식 == "Q8_0" else -8
                d[2:4, :] = 1.0
                Np = (N + 63) // 64 * 64
                sc = np.zeros((K // 32, Np), np.float16)
                sc[:, :N] = d
                qb = q.reshape(K // 32, 32, N).transpose(0, 2, 1)
                if 형식 == "Q8_0":
                    v = qb.astype(np.int8).reshape(-1).view(np.uint8)
                else:
                    u = (qb + 8).astype(np.uint8).reshape(K // 32, N, 4, 2, 4)
                    v = (u[:, :, :, 0, :] | (u[:, :, :, 1, :] << 4)).astype(np.uint8).reshape(-1)
                dr.올리기(가중칸, np.concatenate([v, sc.reshape(-1).view(np.uint8)]))
                wt = (가중칸, 가중칸 + v.nbytes)
            for M in ((1, 3, 37, 200) if not 로짓 else (1, 3, 70)):
                x = 활성값(rng, M, K, 종류)
                bias = (rng.standard_normal(N) * 0.1).astype(np.float32)
                ref = C.행렬곱(x, q, d, bias)
                dr.올리기(입력, x)
                dr.올리기(치우칸, bias)
                for 판 in ["정수줄선형"] + list(G.정수판들):
                    fn = m.로짓선형[판] if 로짓 else m.선형[(판, "")]
                    if 판 == "정수줄선형":
                        ps = [c_u64(입력)] + G._가중인자(wt) + [c_u64(치우칸), c_u64(출력), c_i64(M), c_i64(K), c_i64(N)]
                    else:
                        x0 = G._띄움(m.k["정수로"], ((K // 32 + 31) // 32, M), (256, 1),
                                    [c_u64(입력), c_u64(m.자릿값), c_u64(m.정보), c_i64(M), c_i64(K)])
                        dr.확인(dr.cu.cuLaunchKernel(x0.fn, *x0.grid, 1, *x0.block, 1, 0, None, x0.args, None))
                        ps = [c_u64(m.자릿값), c_u64(m.정보)] + G._가중인자(wt) + [c_u64(치우칸), c_u64(출력), c_i64(M), c_i64(K),
                                                                              c_i64(N), c_i64((N + 63) // 64 * 64)]
                    dr.확인(dr.cu.cuMemsetD8_v2(c_u64(출력), 0xFF, M * N * 4))
                    y = G._띄움(fn, *m._격자(판, M, N), ps)
                    dr.확인(dr.cu.cuLaunchKernel(y.fn, *y.grid, 1, *y.block, 1, 0, None, y.args, None))
                    dr.맞추기()
                    got = dr.내리기(출력, np.empty((M, N), np.float32))
                    out[f"{이름} {종류} 행 {M} {판}"] = {"다른 칸": 다른칸(got, ref), "칸 수": M * N}
    return out


def main():
    torch.zeros(1, device="cuda")
    res = {"환경": {"torch": torch.__version__, "llama.cpp": "b11496 (000bee54a)", "GPU": torch.cuda.get_device_name(0)},
           "6a 계약 (비트)": {}, "6b 정확도": {}, "6c 프롬프트 속도": {}, "6d 생성 속도": {}}

    def 저장():
        os.makedirs(os.path.dirname(결과), exist_ok=True)
        json.dump(res, open(결과, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    tk = G.토크나이저(R.MODEL)
    prompts = [tk.나누기(s) for s in R.문장들]
    글 = tk.나누기(open(os.path.join(ROOT, "research", "gpu", "5단계", "평가글.txt"), encoding="utf-8").read())[:1024]
    긴 = (tk.나누기(R.문장들[1]) * 40)[:1024]
    다섯 = json.load(open(os.path.join(ROOT, "research", "gpu", "5단계", "결과", "5단계.json"), encoding="utf-8"))
    일 = R.일꾼()
    N = 64
    rng = np.random.default_rng(67)
    엔진 = {}
    for fmt in 형식들:
        path = os.path.join(ROOT, "build", f"gpt2-{fmt}.gguf")
        글정 = R.글엔진(GR.gpt2정수(path), KV형식="반실수")
        글정.이름 = f"글 {fmt} 정수 계약"
        m = 글정.m
        # 6a ── 계약 (비트) ──────────────────────────────────────────────────────────────────────────
        a = {"행렬곱 — CPU 참조 대비": 행렬곱시험(m, GR.GGUF(path), rng)}
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
        한번 = 글정.로짓들([긴열])
        c4["(가) 혼자 대 세 문장 한 묶음: 다른 칸"] = 다른칸(글정.로짓들([cut[0]]), 글정.로짓들(cut))
        c4["(나) 한 번에 대 64토큰씩: 다른 칸"] = 다른칸(한번, 글정.로짓들([긴열], "조각", 64))
        c4["(나) 한 번에 대 하나씩: 다른 칸"] = 다른칸(한번, 글정.로짓들([긴열], "하나씩"))
        c4["(다) 한 번에를 다섯 번 더: 첫 번째와 다른 칸"] = [다른칸(한번, 글정.로짓들([긴열])) for _ in range(5)]
        a["4c 의 (가)(나)(다)"] = c4
        a["오류 칸"] = m.오류칸()
        a["통과"] = (all(v["다른 칸"] == 0 for v in a["행렬곱 — CPU 참조 대비"].values()) and
                    all(v["다른 칸"] == 0 and v.get("토큰이 같은가", True) for v in b.values()) and
                    c4["(가) 혼자 대 세 문장 한 묶음: 다른 칸"] == 0 and c4["(나) 한 번에 대 64토큰씩: 다른 칸"] == 0 and
                    c4["(나) 한 번에 대 하나씩: 다른 칸"] == 0 and all(x == 0 for x in c4["(다) 한 번에를 다섯 번 더: 첫 번째와 다른 칸"]) and
                    a["오류 칸"] == 0)
        print("6a", fmt, json.dumps({k: (v if not isinstance(v, dict) else {kk: (vv["다른 칸"] if isinstance(vv, dict) else vv)
                                                                         for kk, vv in v.items()}) for k, v in a.items()},
                                     ensure_ascii=False), flush=True)
        res["6a 계약 (비트)"][fmt] = a
        저장()
        # 6b ── 정확도 ─────────────────────────────────────────────────────────────────────────────
        _, wq = GR.gpt2가중치(path)
        Wq = {k: torch.from_numpy(v.copy()).cuda().double() for k, v in wq.items()}
        양참 = fp64참값(Wq, 글)
        라 = R.라마엔진(일, f"llama.cpp {fmt}", path)
        bb = {"글 — 양자화 모델 참값 대비": 견줌(글정.로짓들([글]), 양참)}
        생성 = {}
        for e in (글정, 라):
            rel = []
            for ids in prompts:
                toks, logs = e.생성로짓(ids, N)
                seq = ids + toks
                ref = fp64참값(Wq, seq[:-1])[len(ids) - 1:]
                r = np.linalg.norm(logs.astype(np.float64) - ref, axis=-1) / np.linalg.norm(ref, axis=-1)
                rel.append(float(np.median(r)))
            생성[e.이름] = rel
        bb["생성 64걸음 — 양자화 모델 참값 대비 상대차 중앙값 (세 문장)"] = 생성
        옛 = 다섯["5b 품질"][fmt]["생성 64걸음 — 양자화 모델 참값 대비 상대차 중앙값 (세 문장)"][f"글 {fmt}"]
        비 = float(np.exp(np.mean(np.log(np.array(생성[글정.이름]) / np.array(옛)))))
        bb["5단계 판 대비 기하평균 비"] = 비
        bb["5단계 판의 값 (기록)"] = 옛
        bb["통과"] = (bb["글 — 양자화 모델 참값 대비"]["KL 평균"] < 1e-6 and all(g < l for g, l in zip(생성[글정.이름], 생성[라.이름])) and
                     비 <= 1.1)
        print("6b", fmt, json.dumps(bb, ensure_ascii=False), flush=True)
        res["6b 정확도"][fmt] = bb
        del Wq
        gc.collect()
        torch.cuda.empty_cache()
        저장()
        엔진[fmt] = (글정, 라)
    # 6c · 6d ── 속도 ─────────────────────────────────────────────────────────────────────────────────
    c, d = {"실패": {}}, {"실패": {}}
    for fmt in 형식들:
        옛판 = R.글엔진(GR.gpt2양자(os.path.join(ROOT, "build", f"gpt2-{fmt}.gguf")), KV형식="반실수")
        옛판.이름 = f"글 {fmt} 5단계 판 (기록)"
        엔진들 = [엔진[fmt][0], 엔진[fmt][1], 옛판]
        c[fmt], d[fmt] = {}, {}
        for n in (128, 512, 1024):
            ids = 긴[:n]
            R.데우기(엔진들, lambda e: e.프롬프트(ids), c["실패"])
            c[fmt][n] = R.번갈아(엔진들, lambda e: e.잰_프롬프트(ids), 7, c["실패"])
            print("6c", fmt, n, c[fmt][n], flush=True)
        for 이름, ids in (("짧은 문맥 (문장 1, 5토큰)", prompts[0]), ("문맥 960", 긴[:960])):
            R.데우기(엔진들, lambda e: e.생성(ids, 64), d["실패"])
            t1 = R.번갈아(엔진들, lambda e: e.잰_생성(ids, 1), 7, d["실패"])
            t64 = R.번갈아(엔진들, lambda e: e.잰_생성(ids, 64), 7, d["실패"])
            d[fmt][이름] = {k: round((t64[k] - t1[k]) / 63, 4) for k in t1 if k in t64}
            print("6d", fmt, 이름, d[fmt][이름], flush=True)
        옛판.m.닫기()
        저장()
    g이름 = {f: 엔진[f][0].이름 for f in 형식들}
    l이름 = {f: 엔진[f][1].이름 for f in 형식들}
    c["통과"] = not c["실패"] and all(c[f][n][g이름[f]] < c[f][n][l이름[f]] for f in 형식들 for n in (128, 512, 1024))
    d["통과"] = not d["실패"] and all(v[g이름[f]] < v[l이름[f]] for f in 형식들 for v in d[f].values())
    d["오류 칸"] = {f: 엔진[f][0].m.오류칸() for f in 형식들}
    res["6c 프롬프트 속도"], res["6d 생성 속도"] = c, d
    for f in 형식들:
        엔진[f][1].닫기()
    일.끝()
    res["통과"] = {"6a": all(res["6a 계약 (비트)"][f]["통과"] for f in 형식들), "6b": all(res["6b 정확도"][f]["통과"] for f in 형식들),
                  "6c": c["통과"], "6d": d["통과"]}
    저장()
    print(json.dumps(res["통과"], ensure_ascii=False))


if __name__ == "__main__":
    main()
