#!/usr/bin/env python3
"""7단계 재기 — 큰 모델: GPT-2 XL (15억) 에서 다시 견주기 (docs/17 §7 "7단계" 의 판정 그대로).

  build/감사venv/Scripts/python -I research/gpu/7단계/재기8.py

모델: build/gpt2-xl (Hugging Face openai-community/gpt2-xl — 사용자 허락으로 내려받음, 저장소에 넣지 않는다). GGUF 셋은 4단계의 gguf쓰기.py
(--모델 build/gpt2-xl, F32)와 llama-quantize 로 만든 build/gpt2-xl-f16 · q8_0 · q4_0.gguf (Q4_0 파일의 낱말표는 Q8_0).
판 넷: 짧은실수(safetensors 그대로, 짧은실수 KV — 3단계/커널XL.gl), F16(5단계 가닥 약속 — 커널XL반F16.gl), Q8_0 · Q4_0(6단계 정수 블록
계약 — 커널XL반Q8정수.gl · 커널XL반Q4정수.gl). 양자 판의 KV 는 반실수(4단계 2).
7a: 판마다 3b 의 길(문장 셋 × 한 번에 · 프롬프트+하나씩 · 두 조각 · 생성 메가커널 — 하나씩 대비, 세 문장 한 묶음의 한 번에 · 하나씩 —
    혼자 하나씩 대비), 4c 의 (가)(나)(다)(512 토큰), 세 프롬프트 × 64토큰 20번 되풀이(토큰 · 걸음마다 로짓), 오류 칸.
7b: 짧은실수 판 — 세 문장 × 64걸음(엔진마다 제 토큰)의 fp64 참값 대비 상대차 중앙값을 HF fp32 와(문장마다 배수 ≤ 2). 양자 판 — 평가글
    (5단계, 469토큰)의 양자화 모델 fp64 참값 대비 KL < 10⁻⁶, 64걸음 상대차 중앙값이 llama.cpp 보다 작다. fp64 참값은 층마다 GPU 에서 fp64
    로 올려 계산한다(모델 전체의 fp64 는 12.8 GB 로 GPU 에 다 들어가지 않는다).
7c: 생성 토큰당 = (64토큰 − 1토큰) / 63 — 짧은 문맥(문장 1) · 문맥 960. 7d: 프롬프트 처리 + 첫 토큰 128 · 512 · 1024.
    양자 판은 llama.cpp(같은 GGUF, 기본 설정)와 같은 실행에서 번갈아 7번(중앙값). 짧은실수 판 · PyTorch eager · HF 는 GPU 메모리(12 GB)에
    둘이 함께 올라가지 않아 차례로 하나씩 7번(중앙값) — 앞에서 데운다.
결과는 결과/7단계.json 에(단계마다 덮어 쓴다).
"""
import gc
import json
import os
import sys
import traceback

import numpy as np
import torch
import torch.nn.functional as F

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
for d in ("6단계", "5단계", "4단계", "3단계"):
    sys.path.insert(0, os.path.join(ROOT, "research", "gpu", d))
import gguf읽기 as GR         # noqa: E402
import 재기4 as R             # noqa: E402
import 재기 as R3             # noqa: E402
import 토치gpt2 as TG         # noqa: E402
from 양자화기준 import 견줌    # noqa: E402

G = R.G
XL = os.path.join(ROOT, "build", "gpt2-xl")
형식들 = ("f32", "f16", "q8_0", "q4_0")
결과 = os.path.join(HERE, "결과", "7단계.json")
N = 64
되풀이 = 20


def 다른칸(a, b):
    return int(np.count_nonzero(np.asarray(a).view(np.uint32) != np.asarray(b).view(np.uint32)))


def 가중치(fmt):
    """판의 가중치와 KV 형식."""
    if fmt == "f32":
        return G.가중치읽기(os.path.join(XL, "model.safetensors")), "짧은실수"
    path = os.path.join(ROOT, "build", f"gpt2-xl-{fmt}.gguf")
    return (GR.gpt2양자(path) if fmt == "f16" else GR.gpt2정수(path)), "반실수"


def 글엔진(fmt, **kw):
    w, kv = 가중치(fmt)
    e = R.글엔진(w, KV형식=kv, **kw)
    e.이름 = f"글 {fmt}"
    del w
    gc.collect()
    return e


def 비우기():
    gc.collect()
    torch.cuda.empty_cache()


@torch.no_grad()
def fp64참값(W, ids):
    """반올림 없는 fp64 GPT-2 — W 는 GPU 의 짧은실수 텐서(이름 → [입력][출력]), 층마다 fp64 로 올려 계산한다. 로짓 [행][낱말] (numpy)."""
    D = W["wpe.weight"].shape[1]
    NH, NL = D // 64, sum(1 for k in W if k.startswith("h.") and k.endswith(".ln_1.weight"))
    d = lambda k: W[k].double()
    m = len(ids)
    x = d("wte.weight")[ids] + d("wpe.weight")[:m]
    for l in range(NL):
        p = f"h.{l}."
        h = F.layer_norm(x, (D,), d(p + "ln_1.weight"), d(p + "ln_1.bias"), 1e-5)
        q, k, v = torch.addmm(d(p + "attn.c_attn.bias"), h, d(p + "attn.c_attn.weight")).split(D, dim=1)
        q, k, v = (t.view(m, NH, 64).transpose(0, 1) for t in (q, k, v))
        y = F.scaled_dot_product_attention(q[None], k[None], v[None], is_causal=True)[0].transpose(0, 1).reshape(m, D)
        x = x + torch.addmm(d(p + "attn.c_proj.bias"), y, d(p + "attn.c_proj.weight"))
        h = F.layer_norm(x, (D,), d(p + "ln_2.weight"), d(p + "ln_2.bias"), 1e-5)
        x = x + torch.addmm(d(p + "mlp.c_proj.bias"), F.gelu(torch.addmm(d(p + "mlp.c_fc.bias"), h, d(p + "mlp.c_fc.weight")),
                                                              approximate="tanh"), d(p + "mlp.c_proj.weight"))
    x = F.layer_norm(x, (D,), d("ln_f.weight"), d("ln_f.bias"), 1e-5)
    return (x @ d("wte.weight").T).cpu().numpy()


def 걸음상대차(logs, ref):
    return np.linalg.norm(logs.astype(np.float64) - ref, axis=-1) / np.linalg.norm(ref, axis=-1)


class 토치엔진(R.이프로세스):
    이름 = "PyTorch eager"

    def __init__(self, w):
        self.m = TG.토치GPT2(w, 최대문장=1)

    def 프롬프트(self, ids):
        self.m.생성(ids, 1)

    def 생성(self, ids, n):
        return self.m.생성(ids, n)


def HF엔진():
    from transformers import GPT2LMHeadModel
    e = R.HF엔진.__new__(R.HF엔진)
    e.m = GPT2LMHeadModel.from_pretrained(XL, dtype=torch.float32).cuda().eval()
    e.이름 = "HF transformers"
    return e


def main():
    torch.zeros(1, device="cuda")
    res = {"환경": {"torch": torch.__version__, "llama.cpp": "b11496 (000bee54a)", "GPU": torch.cuda.get_device_name(0),
                   "모델": "openai-community/gpt2-xl (층 48, 너비 1600, 머리 25)"},
           "7a 의미 (비트)": {}, "7b 정확도": {}, "7c 생성 속도": {}, "7d 프롬프트 속도": {}}

    def 저장():
        os.makedirs(os.path.dirname(결과), exist_ok=True)
        json.dump(res, open(결과, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    tk = G.토크나이저(XL)
    prompts = [tk.나누기(s) for s in R.문장들]
    평가 = tk.나누기(open(os.path.join(ROOT, "research", "gpu", "5단계", "평가글.txt"), encoding="utf-8").read())[:1024]
    긴 = (tk.나누기(R.문장들[1]) * 40)[:1024]
    로짓모음 = {}
    # ── 7a 의미 (판마다) — 7b 의 글 쪽 로짓도 여기서 모은다 ──────────────────────────────────────────────────────────────
    for fmt in 형식들:
        e = 글엔진(fmt)
        m = e.m
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
        a = {"3b 의 길": b}
        c4 = {}
        긴열 = 긴[:512]
        한번 = e.로짓들([긴열])
        c4["(가) 혼자 대 세 문장 한 묶음: 다른 칸"] = 다른칸(e.로짓들([cut[0]]), e.로짓들(cut))
        c4["(나) 한 번에 대 64토큰씩: 다른 칸"] = 다른칸(한번, e.로짓들([긴열], "조각", 64))
        c4["(나) 한 번에 대 하나씩: 다른 칸"] = 다른칸(한번, e.로짓들([긴열], "하나씩"))
        c4["(다) 한 번에를 다섯 번 더: 첫 번째와 다른 칸"] = [다른칸(한번, e.로짓들([긴열])) for _ in range(5)]
        a["4c 의 (가)(나)(다)"] = c4
        del 한번
        # 되풀이: 세 프롬프트 × 64토큰 × 20번 — 토큰과 걸음마다 로짓이 첫 번째와 같은가
        되 = {}
        for j, ids in enumerate(prompts):
            t0, l0 = e.생성로짓(ids, N)
            틀린 = 0
            for _ in range(되풀이 - 1):
                t1, l1 = e.생성로짓(ids, N)
                틀린 += int(t1 != t0 or 다른칸(l1, l0) != 0)
            되[f"문장{j + 1}"] = 틀린
            로짓모음[(fmt, "생성", j)] = (t0, l0)
        a[f"{되풀이}번 되풀이: 첫 번째와 다른 번"] = 되
        if fmt != "f32":
            로짓모음[(fmt, "평가글")] = e.로짓들([평가])
        a["오류 칸"] = m.오류칸()
        a["통과"] = (all(v["다른 칸"] == 0 and v.get("토큰이 같은가", True) for v in b.values()) and
                    c4["(가) 혼자 대 세 문장 한 묶음: 다른 칸"] == 0 and c4["(나) 한 번에 대 64토큰씩: 다른 칸"] == 0 and
                    c4["(나) 한 번에 대 하나씩: 다른 칸"] == 0 and all(x == 0 for x in c4["(다) 한 번에를 다섯 번 더: 첫 번째와 다른 칸"]) and
                    all(x == 0 for x in 되.values()) and a["오류 칸"] == 0)
        print("7a", fmt, json.dumps({k: (v if not isinstance(v, dict) else {kk: (vv["다른 칸"] if isinstance(vv, dict) else vv)
                                                                         for kk, vv in v.items()}) for k, v in a.items()},
                                     ensure_ascii=False), flush=True)
        res["7a 의미 (비트)"][fmt] = a
        저장()
        m.닫기()
        del e, m
        비우기()
    # ── 7b 정확도 ──────────────────────────────────────────────────────────────────────────────────────────────
    일 = R.일꾼()
    # 짧은실수 판: HF fp32 의 64걸음 로짓, 그다음 원래 모델의 fp64 참값
    hf = HF엔진()
    hf로짓 = [hf.생성로짓(ids, N) for ids in prompts]
    del hf
    비우기()
    w32, _ = 가중치("f32")
    W = {k: torch.from_numpy(v.copy()).cuda() for k, v in w32.items()}
    del w32
    gc.collect()
    정확 = {}
    for 이름, 모음 in (("글 f32", [로짓모음[("f32", "생성", j)] for j in range(3)]), ("HF transformers", hf로짓)):
        rows = []
        for ids, (toks, logs) in zip(prompts, 모음):
            seq = ids + toks
            ref = fp64참값(W, seq[:-1])[len(ids) - 1:]
            r = 걸음상대차(logs, ref)
            rows.append({"중앙값": float(np.median(r)), "최댓값": float(np.max(r))})
        정확[이름] = rows
    배수 = [round(정확["글 f32"][i]["중앙값"] / 정확["HF transformers"][i]["중앙값"], 3) for i in range(3)]
    res["7b 정확도"]["f32"] = {"64걸음 — fp64 참값 대비 상대차 (문장마다)": 정확, "HF fp32 대비 중앙값 배수": 배수,
                            "통과": all(x <= 2 for x in 배수)}
    print("7b f32", json.dumps(res["7b 정확도"]["f32"], ensure_ascii=False), flush=True)
    del W
    비우기()
    저장()
    # 양자 판: llama.cpp 의 64걸음 로짓, 그다음 양자화 모델의 fp64 참값
    for fmt in 형식들[1:]:
        path = os.path.join(ROOT, "build", f"gpt2-xl-{fmt}.gguf")
        라 = R.라마엔진(일, f"llama.cpp {fmt}", path)
        라로짓 = [라.생성로짓(ids, N) for ids in prompts]
        라.닫기()
        _, wq = GR.gpt2가중치(path)
        W = {k: torch.from_numpy(v.copy()).cuda() for k, v in wq.items()}
        del wq
        gc.collect()
        bb = {"글 — 양자화 모델 참값 대비 (평가글)": 견줌(로짓모음[(fmt, "평가글")], fp64참값(W, 평가))}
        생성 = {}
        for 이름, 모음 in ((f"글 {fmt}", [로짓모음[(fmt, "생성", j)] for j in range(3)]), (f"llama.cpp {fmt}", 라로짓)):
            rel = []
            for ids, (toks, logs) in zip(prompts, 모음):
                seq = ids + toks
                ref = fp64참값(W, seq[:-1])[len(ids) - 1:]
                rel.append(float(np.median(걸음상대차(logs, ref))))
            생성[이름] = rel
        bb["생성 64걸음 — 양자화 모델 참값 대비 상대차 중앙값 (세 문장)"] = 생성
        bb["통과"] = (bb["글 — 양자화 모델 참값 대비 (평가글)"]["KL 평균"] < 1e-6 and
                     all(g < l for g, l in zip(생성[f"글 {fmt}"], 생성[f"llama.cpp {fmt}"])))
        print("7b", fmt, json.dumps(bb, ensure_ascii=False), flush=True)
        res["7b 정확도"][fmt] = bb
        del W
        비우기()
        저장()
    del 로짓모음
    gc.collect()
    # ── 7c · 7d 속도 ────────────────────────────────────────────────────────────────────────────────────────────
    c, d = {"실패": {}}, {"실패": {}}
    짧은 = prompts[0]

    def 생성재기(엔진들, 표, 기록):
        for 이름, ids in (("짧은 문맥 (문장 1)", 짧은), ("문맥 960", 긴[:960])):
            R.데우기(엔진들, lambda e: e.생성(ids, N), 기록)
            t1 = R.번갈아(엔진들, lambda e: e.잰_생성(ids, 1), 7, 기록)
            t64 = R.번갈아(엔진들, lambda e: e.잰_생성(ids, N), 7, 기록)
            표.setdefault(이름, {}).update({k: round((t64[k] - t1[k]) / (N - 1), 4) for k in t1 if k in t64})

    def 프롬재기(엔진들, 표, 기록):
        for n in (128, 512, 1024):
            ids = 긴[:n]
            R.데우기(엔진들, lambda e: e.프롬프트(ids), 기록)
            표.setdefault(str(n), {}).update(R.번갈아(엔진들, lambda e: e.잰_프롬프트(ids), 7, 기록))
    # 양자 판 — llama.cpp 와 같은 실행에서 번갈아
    for fmt in 형식들[1:]:
        try:
            e = 글엔진(fmt, 최대문장=1)
        except Exception as ex:
            c["실패"][f"글 {fmt}"] = d["실패"][f"글 {fmt}"] = f"만들지 못함: {ex}"
            traceback.print_exc()
            continue
        라 = R.라마엔진(일, f"llama.cpp {fmt}", os.path.join(ROOT, "build", f"gpt2-xl-{fmt}.gguf"))
        c[fmt], d[fmt] = {}, {}
        생성재기([e, 라], c[fmt], c["실패"])
        프롬재기([e, 라], d[fmt], d["실패"])
        c[fmt]["오류 칸"] = e.m.오류칸()
        print("7c", fmt, c[fmt], flush=True)
        print("7d", fmt, d[fmt], flush=True)
        라.닫기()
        e.m.닫기()
        del e
        비우기()
        저장()
    일.끝()
    # 짧은실수 판 — 글 · PyTorch eager · HF 를 차례로(메모리)
    c["f32"], d["f32"] = {}, {}
    e = 글엔진("f32", 최대문장=1)
    생성재기([e], c["f32"], c["실패"])
    프롬재기([e], d["f32"], d["실패"])
    c["f32"]["오류 칸"] = e.m.오류칸()
    e.m.닫기()
    del e
    비우기()
    w32, _ = 가중치("f32")
    t = 토치엔진(w32)
    del w32
    gc.collect()
    생성재기([t], c["f32"], c["실패"])
    프롬재기([t], d["f32"], d["실패"])
    del t
    비우기()
    hf = HF엔진()
    생성재기([hf], c["f32"], c["실패"])
    for n in (128, 512, 1023):                            # HF 의 위치표는 1024 줄 — 생성(1토큰)은 프롬프트 1023 까지
        ids = 긴[:n]
        R.데우기([hf], lambda e: e.프롬프트(ids), d["실패"])
        d["f32"].setdefault(str(n), {}).update(R.번갈아([hf], lambda e: e.잰_프롬프트(ids), 7, d["실패"]))
    del hf
    비우기()
    print("7c f32", c["f32"], flush=True)
    print("7d f32", d["f32"], flush=True)
    # 판정
    짧은판 = [c["f32"][k] for k in ("짧은 문맥 (문장 1)", "문맥 960")]
    c["통과"] = (not c["실패"] and all(v["글 f32"] < v["PyTorch eager"] and v["글 f32"] < v["HF transformers"] for v in 짧은판) and
                all(v[f"글 {f}"] < v[f"llama.cpp {f}"] for f in 형식들[1:] for k, v in c[f].items() if k != "오류 칸"))
    d["통과"] = (not d["실패"] and all(d["f32"][str(n)]["글 f32"] < d["f32"][str(n)]["PyTorch eager"] for n in (128, 512, 1024)) and
                all(d[f][str(n)][f"글 {f}"] < d[f][str(n)][f"llama.cpp {f}"] for f in ("q8_0", "q4_0") for n in (128, 512, 1024)))
    res["7c 생성 속도"], res["7d 프롬프트 속도"] = c, d
    res["통과"] = {"7a": all(res["7a 의미 (비트)"][f]["통과"] for f in 형식들), "7b": all(res["7b 정확도"][f]["통과"] for f in 형식들),
                  "7c": c["통과"], "7d": d["통과"]}
    저장()
    print(json.dumps(res["통과"], ensure_ascii=False))


if __name__ == "__main__":
    main()
