#!/usr/bin/env python3
"""11단계 재기 — 프로파일러가 가리킨 곳 (docs/17 §7 "11단계" 의 판정 그대로 — 10단계의 기준과 같다).

  build/감사venv/Scripts/python -I research/gpu/11단계/재기12.py

11단계가 바꾼 것(정수 KV 모듈만, 값은 그대로): 타일의 A 를 ldmatrix 로(글ptx.py 행렬조각읽기) · π 차례의 B · 척도를 반실수로 미리 읽기 ·
섞기 · Pd 접기 · 비동기 복사의 색인 더하기 · 판 표에 정수세판타일선형 · 꼬리 자르기(호스트가 재서 고름) · 층정규화의 블록 판(호스트가 재서
고름) · 어텐션의 상수 나눗셈을 밀기로. 재는 법은 재기11.py 그대로이고, 11a 의 6단계 행렬곱시험은 모듈의 판 표 전부(전에는 여섯 판만),
옛 모듈의 PTX 는 10단계 끝 커밋(d411536)의 글ptx.py 와 견준다. 아래는 10단계의 설명.

9단계의 정수 KV 판(글GPT2 KV형식="정수", 자리수=2)에 10단계가 더한 것: 타일의 겹침 · 엇갈림 · Pd접기 변형과 판 모양(모두 재서 느리거나 같아
기본으로 두지 않음), 어텐션의 두 번째 판 정수어텐션둘(워프 여덟 — 같은 비트, 같은 속도). 비교 대상: llama.cpp(F16 KV), PyTorch f16(cuBLAS +
SDPA, CUDA 그래프 — 참고선), 8단계 판(기록).
10a: 9단계 재기10.커널대조(정수어텐션 · 정수어텐션둘 둘 다) · 6단계 행렬곱시험(판 모두) · 8단계 비트시험 · 캐시 바이트 · 옛 모듈.
10b: XL 1024 타일 효율 — c_fc(1024 · 1600 · 6400) 와 c_proj(1024 · 1600 · 1600) · mlp c_proj(1024 · 6400 · 1600), Q8_0 · Q4_0 자리 둘(8단계 재기9.타일효율).
10c: 어텐션 한 층 — XL 1024 · 합성 small 16384, 정수어텐션 · 정수어텐션둘.
10d: XL 128 · 512 · 1024 · small 1024 — 글 · 8단계 판 · llama.cpp 를 번갈아 7번; PyTorch f16 참고선은 메모리 때문에 따로(같은 프로세스, 앞서).
10e: 생성 — 같은 실행에서 번갈아 7번(중앙값)을 세 묶음, 세 중앙값의 중앙값; 긴 문맥 32704(번갈아 세 묶음) · 102336(따로, 세 번).
결과는 결과/11단계.json 에(이 스크립트).
"""
import gc
import json
import os
import sys
import time

import numpy as np
import torch

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
for d in ("10단계", "9단계", "8단계", "7단계", "6단계", "5단계", "4단계", "3단계"):
    sys.path.insert(0, os.path.join(ROOT, "research", "gpu", d))
import 커널생성 as K          # noqa: E402
import gguf읽기 as GR         # noqa: E402
import 재기4 as R             # noqa: E402
import 재기7 as K7            # noqa: E402
import 재기9 as K9            # noqa: E402
import 재기10 as K10          # noqa: E402

G = R.G
형식들 = ("q8_0", "q4_0")
결과 = os.path.join(HERE, "결과", "11단계.json")
N = 64
긴GGUF = K10.긴GGUF


def 참고선(크기, ns):
    """PyTorch f16(cuBLAS 행렬곱 + f16 SDPA, CUDA 그래프) 프롬프트 처리 + 마지막 로짓 — 의미는 지키지 않는 빠른 길의 참고선(ms)."""
    import torch.nn.functional as F
    폴더 = os.path.join(ROOT, "build", "gpt2" if 크기 == "small" else "gpt2-xl")
    w = G.가중치읽기(os.path.join(폴더, "model.safetensors"))
    D = w["wpe.weight"].shape[1]
    NH, NL = D // 64, sum(1 for k in w if k.startswith("h.") and k.endswith(".ln_1.weight"))
    t = lambda a, dt=torch.float32: torch.from_numpy(np.ascontiguousarray(a)).to("cuda", dt)
    층 = []
    for l in range(NL):
        p = f"h.{l}."
        d = {"g1": t(w[p + "ln_1.weight"]), "b1": t(w[p + "ln_1.bias"]), "g2": t(w[p + "ln_2.weight"]), "b2": t(w[p + "ln_2.bias"])}
        for a, h in (("qkv", "attn.c_attn"), ("o", "attn.c_proj"), ("fc", "mlp.c_fc"), ("pr", "mlp.c_proj")):
            d[a + "h"], d[a + "b"] = t(w[p + h + ".weight"], torch.float16), t(w[p + h + ".bias"])
        층.append(d)
    wte_h, wpe_h = t(w["wte.weight"], torch.float16), t(w["wpe.weight"], torch.float16)
    lnf_g, lnf_b = t(w["ln_f.weight"]), t(w["ln_f.bias"])
    del w
    ids = torch.randint(0, 50257, (1024,), device="cuda")

    @torch.no_grad()
    def 앞으로(ids):
        n = len(ids)
        x = (wte_h[ids] + wpe_h[:n]).float()
        for d in 층:
            h = F.layer_norm(x, (D,), d["g1"], d["b1"], 1e-5)
            qkv = (h.half() @ d["qkvh"]).float() + d["qkvb"]
            q, k, v = (a.view(n, NH, 64).transpose(0, 1).half() for a in qkv.split(D, dim=1))
            y = F.scaled_dot_product_attention(q, k, v, is_causal=True).transpose(0, 1).reshape(n, D)
            x = x + (y @ d["oh"]).float() + d["ob"]
            h = F.layer_norm(x, (D,), d["g2"], d["b2"], 1e-5)
            f = F.gelu((h.half() @ d["fch"]).float() + d["fcb"], approximate="tanh")
            x = x + (f.half() @ d["prh"]).float() + d["prb"]
        h = F.layer_norm(x[-1:], (D,), lnf_g, lnf_b, 1e-5)
        return (h.half() @ wte_h.T).argmax()
    out = {}
    for n in ns:
        x_ids = ids[:n]
        s = torch.cuda.Stream()
        s.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(s):
            for _ in range(3):
                앞으로(x_ids)
        torch.cuda.current_stream().wait_stream(s)
        g = torch.cuda.CUDAGraph()
        with torch.cuda.graph(g):
            앞으로(x_ids)
        for _ in range(5):
            g.replay()
        torch.cuda.synchronize()
        ts = []
        for _ in range(7):
            torch.cuda.synchronize(); t0 = time.perf_counter(); g.replay(); torch.cuda.synchronize(); ts.append((time.perf_counter() - t0) * 1000)
        out[str(n)] = round(float(np.median(ts)), 2)
        del g
    del 층, wte_h, wpe_h
    gc.collect()
    torch.cuda.empty_cache()
    return out


def 세묶음(엔진들, 잰일, 실패):
    """번갈아 7번(중앙값)을 세 묶음 — 엔진마다 세 중앙값의 중앙값."""
    묶음 = [R.번갈아(엔진들, 잰일, 7, 실패) for _ in range(3)]
    return {k: round(float(np.median([m[k] for m in 묶음])), 4) for k in 묶음[0]}, 묶음


def main():
    고름 = [a for a in sys.argv[1:] if a in ("small", "XL", "긴")]
    크기들 = tuple(k for k in ("small", "XL") if not 고름 or k in 고름)
    긴도 = not 고름 or "긴" in 고름
    torch.zeros(1, device="cuda")
    res = {"환경": {"torch": torch.__version__, "llama.cpp": "b11496 (000bee54a)", "GPU": torch.cuda.get_device_name(0)},
           "11a 계약 (비트)": {}, "11b 타일 효율": {}, "11c 어텐션 효율": {}, "11d 프롬프트 속도": {"실패": {}}, "11e 생성 속도": {"실패": {}}}
    if 고름 and os.path.exists(결과):
        res = json.load(open(결과, encoding="utf-8"))

    def 저장():
        os.makedirs(os.path.dirname(결과), exist_ok=True)
        json.dump(res, open(결과, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    평가글 = open(os.path.join(ROOT, "research", "gpu", "5단계", "평가글.txt"), encoding="utf-8").read()
    res["11a 계약 (비트)"]["8단계까지의 모듈"] = K10.옛모듈같은가("d411536")
    print("11a 옛 모듈", res["11a 계약 (비트)"]["8단계까지의 모듈"], flush=True)
    # 참고선(PyTorch f16) — 메모리 때문에 엔진들보다 먼저, 따로
    for 크기 in 크기들:
        res["11d 프롬프트 속도"][f"PyTorch f16 참고선 {크기}"] = 참고선(크기, (128, 512, 1024))
        print("참고선", 크기, res["11d 프롬프트 속도"][f"PyTorch f16 참고선 {크기}"], flush=True)
    저장()
    # 10b 타일 효율 (XL, Q8_0 · Q4_0)
    if "XL" in 크기들:
        dr = G.드라이버()
        K.KV = "정수"
        for fmt in 형식들:
            ptx = os.path.join(ROOT, "build", f"커널XL{'Q8' if fmt == 'q8_0' else 'Q4'}정수KV.ptx")
            b = {}
            for 이름, (M, Kd, Nn) in (("c_fc", (1024, 1600, 6400)), ("c_proj", (1024, 1600, 1600)), ("mlp c_proj", (1024, 6400, 1600))):
                b[이름] = K9.타일효율(dr, ptx, 2, M, Kd, Nn)
                print("11b", fmt, 이름, b[이름]["가장 빠른 판"], b[이름]["µs"], b[이름]["int8 최고치 대비 %"], flush=True)
            b["통과"] = b["c_fc"]["int8 최고치 대비 %"] >= 60 and b["c_proj"]["int8 최고치 대비 %"] >= 55 and b["mlp c_proj"]["int8 최고치 대비 %"] >= 55
            res["11b 타일 효율"][fmt] = b
        K.KV = "짧은실수"
        dr.놓기()
        저장()
    일 = R.일꾼()
    rng = np.random.default_rng(110)
    for 크기 in 크기들:
        tk = G.토크나이저(K9.모델폴더(크기))
        prompts = [tk.나누기(s) for s in R.문장들]
        평가 = tk.나누기(평가글)[:1024]
        긴 = (tk.나누기(R.문장들[1]) * 40)[:1024]
        D = 768 if 크기 == "small" else 1600
        for fmt in 형식들:
            열쇠 = f"{크기} {fmt}"
            path = K9.경로(크기, fmt)
            e9 = K10.글엔진(크기, fmt)
            a = {}
            if fmt == "q8_0":
                w = G.가중치읽기(os.path.join(K9.모델폴더(크기), "model.safetensors"))
                qkv = K10.층qkv(w, 긴[:1024], 5 if 크기 == "small" else 20, D)
                del w
                gc.collect()
                a["어텐션 커널 대 CPU 참조 (정수어텐션)"] = K10.커널대조(e9.m, qkv, 1024)
                a["어텐션 커널 대 CPU 참조 (정수어텐션둘)"] = K10.커널대조(e9.m, qkv, 1024, 커널="정수어텐션둘")
                print("11a", 열쇠, "커널 대 CPU 참조", a["어텐션 커널 대 CPU 참조 (정수어텐션)"]["통과"], a["어텐션 커널 대 CPU 참조 (정수어텐션둘)"]["통과"], flush=True)
            a["행렬곱 — CPU 참조 대비 (판 모두)"] = K7.행렬곱시험(e9.m, GR.GGUF(path), rng)
            a["끝에서 끝 (8단계 비트시험)"] = K9.비트시험(e9, path, rng, prompts, 긴)
            a["캐시 바이트 — 프롬프트 · 두조각 · 메가커널 대 하나씩"] = K10.끝끝(e9, 평가[:469])
            a["오류 칸"] = e9.m.오류칸()
            a["통과"] = (all(v["다른 칸"] == 0 for v in a["행렬곱 — CPU 참조 대비 (판 모두)"].values()) and
                        all(v["통과"] for k_, v in a.items() if isinstance(v, dict) and "통과" in v) and a["오류 칸"] == 0)
            print("11a", 열쇠, "통과", a["통과"], "오류 칸", a["오류 칸"], flush=True)
            res["11a 계약 (비트)"][열쇠] = a
            저장()
            # 10d · 10e — 같은 실행에서 번갈아
            e8 = K9.글엔진(크기, fmt, 2, 최대문장=1)
            라 = R.라마엔진(일, f"llama.cpp {fmt}", path)
            엔진들 = [e9, e8, 라]
            c, d = {}, {}
            for n in ((128, 512, 1024) if 크기 == "XL" else (1024,)):
                ids = 긴[:n]
                R.데우기(엔진들, lambda e: e.프롬프트(ids), res["11d 프롬프트 속도"]["실패"])
                c[str(n)] = R.번갈아(엔진들, lambda e: e.잰_프롬프트(ids), 7, res["11d 프롬프트 속도"]["실패"])
                바닥 = K9.바닥ms(크기, n, 2) + (12 if 크기 == "small" else 48) * K10.어텐션바닥us(D // 64, n) / 1000
                c[str(n)]["바닥 ms"] = round(바닥, 2)
                c[str(n)]["바닥 대비"] = round(c[str(n)][e9.이름] / 바닥, 2)
                print("11d", 열쇠, n, c[str(n)], flush=True)
            for 이름, ids in (("짧은 문맥 (문장 1)", prompts[0]), ("문맥 960", 긴[:960])):
                R.데우기(엔진들, lambda e: e.생성(ids, N), res["11e 생성 속도"]["실패"])
                t1, _ = 세묶음(엔진들, lambda e: e.잰_생성(ids, 1), res["11e 생성 속도"]["실패"])
                t64, 묶 = 세묶음(엔진들, lambda e: e.잰_생성(ids, N), res["11e 생성 속도"]["실패"])
                d[이름] = {k: round((t64[k] - t1[k]) / (N - 1), 4) for k in t1 if k in t64}
                print("11e", 열쇠, 이름, d[이름], flush=True)
            # 10c — XL 1024 어텐션 한 층(채워진 캐시로), 두 판
            if 크기 == "XL" and fmt == "q8_0":
                e9.m.토큰넣기(긴[:1024]); e9.m.계산(1, 1024, 0, "끝"); e9.m.dr.맞추기()
                t1_ = K10.어텐션시간us(e9.m, 1024)
                t2_ = K10.어텐션시간us(e9.m, 1024, "정수어텐션둘")
                바닥 = K10.어텐션바닥us(25, 1024)
                res["11c 어텐션 효율"]["XL 1024 (머리 25)"] = {"정수어텐션 µs": round(t1_, 1), "정수어텐션둘 µs": round(t2_, 1), "바닥 µs": round(바닥, 1),
                                                        "바닥 대비": round(min(t1_, t2_) / 바닥, 2), "통과": min(t1_, t2_) <= 2 * 바닥}
                print("11c", res["11c 어텐션 효율"]["XL 1024 (머리 25)"], flush=True)
            d["오류 칸"] = e9.m.오류칸()
            res["11d 프롬프트 속도"][열쇠], res["11e 생성 속도"][열쇠] = c, d
            라.닫기(); e8.m.닫기(); e9.m.닫기()
            del e8, e9, 라
            K9.비우기()
            저장()
    if not 긴도:
        일.끝(); 저장(); return
    # ── 긴 문맥 ──
    rng2 = np.random.default_rng(1)
    ids전체 = [int(x) for x in rng2.integers(0, 50257, 102400)]
    wq = GR.gpt2정수(긴GGUF)
    e긴 = R.글엔진(wq, KV형식="정수", 자리수=2, 최대행=16384, 최대문장=1, 최대길이=16384, 로짓행=16)
    e긴.이름 = "글 q8_0 정수 KV (합성 긴)"
    m = e긴.m
    m.토큰넣기(ids전체[:16384]); m.계산(1, 16384, 0, 1); m.dr.맞추기()
    t1_ = K10.어텐션시간us(m, 16384)
    t2_ = K10.어텐션시간us(m, 16384, "정수어텐션둘")
    바닥 = K10.어텐션바닥us(12, 16384)
    res["11c 어텐션 효율"]["합성 small 16384 (머리 12)"] = {"정수어텐션 µs": round(t1_, 1), "정수어텐션둘 µs": round(t2_, 1), "바닥 µs": round(바닥, 1),
                                                        "바닥 대비": round(min(t1_, t2_) / 바닥, 2), "통과": min(t1_, t2_) <= 2 * 바닥}
    print("11c", res["11c 어텐션 효율"]["합성 small 16384 (머리 12)"], flush=True)
    m.닫기()
    del e긴, m
    K9.비우기()
    저장()
    d긴 = {}
    e긴 = R.글엔진(wq, KV형식="정수", 자리수=2, 최대행=32768, 최대문장=1, 최대길이=32768, 로짓행=16)
    e긴.이름 = "글 q8_0 정수 KV (합성 긴)"
    라긴 = R.라마엔진(일, "llama.cpp q8_0 (합성 긴)", 긴GGUF, n_ctx=32768, n_batch=2048)
    엔진들 = [e긴, 라긴]
    ids = ids전체[:32768 - 64]
    R.데우기(엔진들, lambda e: e.생성(ids, N), res["11e 생성 속도"]["실패"])
    t1, _ = 세묶음(엔진들, lambda e: e.잰_생성(ids, 1), res["11e 생성 속도"]["실패"])
    t64, 묶 = 세묶음(엔진들, lambda e: e.잰_생성(ids, N), res["11e 생성 속도"]["실패"])
    d긴["문맥 32704"] = {k: round((t64[k] - t1[k]) / (N - 1), 4) for k in t1 if k in t64}
    print("11e 긴 32704", d긴["문맥 32704"], flush=True)
    라긴.닫기(); e긴.m.닫기()
    del e긴, 라긴
    K9.비우기()
    ids = ids전체[:102400]
    라긴 = R.라마엔진(일, "llama.cpp q8_0 (합성 긴)", 긴GGUF, n_ctx=102400, n_batch=2048)
    라긴.생성(ids[:-64], N)
    t1 = np.median([라긴.잰_생성(ids[:-64], 1) for _ in range(3)]); t64 = np.median([라긴.잰_생성(ids[:-64], N) for _ in range(3)])
    d긴["문맥 102336 (따로)"] = {라긴.이름: round(float((t64 - t1) / (N - 1)), 4)}
    라긴.닫기()
    del 라긴
    e긴 = R.글엔진(wq, KV형식="정수", 자리수=2, 최대행=102400, 최대문장=1, 최대길이=102400, 로짓행=16)
    e긴.이름 = "글 q8_0 정수 KV (합성 긴)"
    e긴.생성(ids[:-64], N)
    t1 = np.median([e긴.잰_생성(ids[:-64], 1) for _ in range(3)]); t64 = np.median([e긴.잰_생성(ids[:-64], N) for _ in range(3)])
    d긴["문맥 102336 (따로)"][e긴.이름] = round(float((t64 - t1) / (N - 1)), 4)
    d긴["오류 칸"] = e긴.m.오류칸()
    print("11e 긴 102336", d긴["문맥 102336 (따로)"], flush=True)
    e긴.m.닫기()
    del e긴
    K9.비우기()
    res["11e 생성 속도"]["합성 긴"] = d긴
    일.끝()
    # ── 판정 ──
    c, d = res["11d 프롬프트 속도"], res["11e 생성 속도"]
    열쇠들 = [f"{크기} {fmt}" for 크기 in ("small", "XL") for fmt in 형식들 if f"{크기} {fmt}" in c]
    글 = lambda k: f"글 {k.split()[1]} 정수 KV"
    옛 = lambda k: f"글 {k.split()[1]} 자리 둘"
    라 = lambda k: f"llama.cpp {k.split()[1]}"
    참 = lambda k: res["11d 프롬프트 속도"].get(f"PyTorch f16 참고선 {k.split()[0]}", {})
    c["통과"] = (not c["실패"] and all(c[k][n][글(k)] < c[k][n][라(k)] and c[k][n][글(k)] < 참(k).get(n, 1e9) for k in 열쇠들 for n in c[k]
                                   if n not in ("바닥 ms", "바닥 대비")) and
               all(c[k]["1024"][글(k)] < 4.0 for k in 열쇠들 if k.startswith("small")))
    긴글, 긴라 = "글 q8_0 정수 KV (합성 긴)", "llama.cpp q8_0 (합성 긴)"
    d["통과"] = (not d["실패"] and all(v[글(k)] < v[라(k)] and v[글(k)] <= 1.03 * v[옛(k)] for k in 열쇠들 for kk, v in d[k].items() if kk != "오류 칸") and
               ("합성 긴" not in d or all(d["합성 긴"][kk][긴글] < d["합성 긴"][kk][긴라] for kk in ("문맥 32704", "문맥 102336 (따로)"))))
    res["통과"] = {"11a": all(v["통과"] for k, v in res["11a 계약 (비트)"].items()),
                  "11b": all(v["통과"] for v in res["11b 타일 효율"].values()) if res["11b 타일 효율"] else None,
                  "11c": all(v["통과"] for v in res["11c 어텐션 효율"].values()) if res["11c 어텐션 효율"] else None,
                  "11d": c["통과"], "11e": d["통과"]}
    저장()
    print(json.dumps(res["통과"], ensure_ascii=False))


if __name__ == "__main__":
    main()
