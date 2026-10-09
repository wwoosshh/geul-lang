#!/usr/bin/env python3
"""4단계 — GPT-2 를 llama.cpp 의 GGUF 파일로 (llama.cpp 의 변환기 convert_hf_to_gguf.py 는 소스 저장소에 있어 이 PC 에 없다 —
같은 꼴을 직접 쓴다). llama.cpp 의 "gpt2" 구조가 읽는 텐서 이름·모양·메타데이터 그대로:

  token_embd [768, 어휘], position_embd [768, 문맥], output_norm.{weight,bias},
  blk.N.attn_norm.{weight,bias}, blk.N.attn_qkv.{weight [768, 2304], bias}, blk.N.attn_output.{weight [768, 768], bias},
  blk.N.ffn_norm.{weight,bias}, blk.N.ffn_up.{weight [768, 3072], bias}, blk.N.ffn_down.{weight [3072, 768], bias}
  (ggml 의 차원 순서 — 첫 차원이 붙어 있는 쪽. HF 의 Conv1D 가중치 [입력][출력] 은 뒤집어 [출력][입력] 으로 쓴다.)

  python research/gpu/4단계/gguf쓰기.py 출력.gguf [--합성 16384] [--모델 build/gpt2-xl]

--합성 N: 3단계 성능 2 의 합성 모델(위치표 N 줄, 값은 시드 0 의 무작위 — 재기2.py 와 같은 만들기)을 쓴다. 토크나이저는 GPT-2 그대로.
--모델 폴더: 다른 크기의 GPT-2(7단계 — GPT-2 XL). 크기는 그 폴더의 config.json 에서(기본은 build/gpt2 — GPT-2 small).
값은 모두 F32(파일 형식 0). F16·Q8_0 은 llama-quantize 로 만든다.
"""
import json
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "research", "gpu", "3단계"))
import 글gpt2 as G          # noqa: E402

MODEL = os.path.join(ROOT, "build", "gpt2")
정렬 = 32
U32, I32, F32, BOOL, STR, ARR = 4, 5, 6, 7, 8, 9


def 문자열(s):
    b = s.encode("utf-8")
    return struct.pack("<Q", len(b)) + b


def 값(t, v):
    if t == U32:
        return struct.pack("<I", v)
    if t == I32:
        return struct.pack("<i", v)
    if t == F32:
        return struct.pack("<f", v)
    if t == BOOL:
        return struct.pack("<B", 1 if v else 0)
    if t == STR:
        return 문자열(v)
    raise ValueError(t)


def 배열(t, xs):
    out = [struct.pack("<IQ", t, len(xs))]
    if t == STR:
        out += [문자열(x) for x in xs]
    elif t == I32:
        out.append(np.asarray(xs, dtype="<i4").tobytes())
    else:
        raise ValueError(t)
    return b"".join(out)


def 합성가중치(w, 길이):
    rng = np.random.default_rng(0)
    sw = {}
    for k, v in w.items():
        if k == "wpe.weight":
            sw[k] = (rng.standard_normal((길이, 768)) * 0.01).astype(np.float32)
        elif k.endswith(".weight") and v.ndim == 2:
            sw[k] = (rng.standard_normal(v.shape) * 0.02).astype(np.float32)
        elif k.endswith(".weight"):
            sw[k] = np.ones_like(v)
        else:
            sw[k] = np.zeros_like(v)
    return sw


def main(argv):
    out = argv[1]
    모델 = os.path.join(ROOT, argv[argv.index("--모델") + 1]) if "--모델" in argv else MODEL
    설정 = json.load(open(os.path.join(모델, "config.json"), encoding="utf-8"))
    너비, 층수, 머리수 = 설정["n_embd"], 설정["n_layer"], 설정["n_head"]
    확장 = 설정.get("n_inner") or 4 * 너비
    w = G.가중치읽기(os.path.join(모델, "model.safetensors"))
    문맥 = 설정["n_positions"]
    이름 = ("GPT-2 small (openai-community/gpt2)" if 모델 == MODEL else
            f"GPT-2 ({os.path.basename(모델)} — 층 {층수}, 너비 {너비})")
    if "--합성" in argv:
        문맥 = int(argv[argv.index("--합성") + 1])
        w = 합성가중치(w, 문맥)
        이름 = f"GPT-2 모양의 합성 모델 (위치표 {문맥}, 시드 0)"
    vocab = json.load(open(os.path.join(모델, "vocab.json"), encoding="utf-8"))
    토큰 = [None] * len(vocab)
    for s, i in vocab.items():
        토큰[i] = s
    종류 = [3 if s == "<|endoftext|>" else 1 for s in 토큰]          # 3 = CONTROL, 1 = NORMAL
    합침 = [l.rstrip("\n") for l in open(os.path.join(모델, "merges.txt"), encoding="utf-8")
          if l.strip() and not l.startswith("#version")]

    kv = [("general.architecture", STR, "gpt2"),
          ("general.name", STR, 이름),
          ("general.file_type", U32, 0),
          ("general.alignment", U32, 정렬),
          ("gpt2.context_length", U32, 문맥),
          ("gpt2.embedding_length", U32, 너비),
          ("gpt2.feed_forward_length", U32, 확장),
          ("gpt2.block_count", U32, 층수),
          ("gpt2.attention.head_count", U32, 머리수),
          ("gpt2.attention.layer_norm_epsilon", F32, 1e-5),
          ("tokenizer.ggml.model", STR, "gpt2"),
          ("tokenizer.ggml.pre", STR, "gpt-2"),
          ("tokenizer.ggml.bos_token_id", U32, 50256),
          ("tokenizer.ggml.eos_token_id", U32, 50256),
          ("tokenizer.ggml.add_bos_token", BOOL, False)]
    배열kv = [("tokenizer.ggml.tokens", STR, 토큰), ("tokenizer.ggml.token_type", I32, 종류), ("tokenizer.ggml.merges", STR, 합침)]

    텐서 = [("token_embd.weight", w["wte.weight"]), ("position_embd.weight", w["wpe.weight"]),
          ("output_norm.weight", w["ln_f.weight"]), ("output_norm.bias", w["ln_f.bias"])]
    for l in range(층수):
        h = lambda s: w[f"h.{l}.{s}"]
        텐서 += [(f"blk.{l}.attn_norm.weight", h("ln_1.weight")), (f"blk.{l}.attn_norm.bias", h("ln_1.bias")),
               (f"blk.{l}.attn_qkv.weight", h("attn.c_attn.weight").T), (f"blk.{l}.attn_qkv.bias", h("attn.c_attn.bias")),
               (f"blk.{l}.attn_output.weight", h("attn.c_proj.weight").T), (f"blk.{l}.attn_output.bias", h("attn.c_proj.bias")),
               (f"blk.{l}.ffn_norm.weight", h("ln_2.weight")), (f"blk.{l}.ffn_norm.bias", h("ln_2.bias")),
               (f"blk.{l}.ffn_up.weight", h("mlp.c_fc.weight").T), (f"blk.{l}.ffn_up.bias", h("mlp.c_fc.bias")),
               (f"blk.{l}.ffn_down.weight", h("mlp.c_proj.weight").T), (f"blk.{l}.ffn_down.bias", h("mlp.c_proj.bias"))]

    머리 = [b"GGUF", struct.pack("<IQQ", 3, len(텐서), len(kv) + len(배열kv))]
    for k, t, v in kv:
        머리 += [문자열(k), struct.pack("<I", t), 값(t, v)]
    for k, t, xs in 배열kv:
        머리 += [문자열(k), struct.pack("<I", ARR), 배열(t, xs)]
    자리 = 0
    자리들 = []
    for n, a in 텐서:
        a = np.ascontiguousarray(a, dtype="<f4")
        차원 = list(reversed(a.shape))                    # ggml: 첫 차원이 붙어 있는 쪽
        머리 += [문자열(n), struct.pack("<I", len(차원)), struct.pack(f"<{len(차원)}Q", *차원), struct.pack("<IQ", 0, 자리)]
        자리들.append((자리, a))
        자리 += (a.nbytes + 정렬 - 1) // 정렬 * 정렬
    머리 = b"".join(머리)
    with open(out, "wb") as f:
        f.write(머리)
        f.write(b"\0" * ((-len(머리)) % 정렬))
        바탕 = f.tell()
        for z, a in 자리들:
            f.write(b"\0" * (바탕 + z - f.tell()))
            f.write(a.tobytes())
    print(f"{out}: 텐서 {len(텐서)}개, {os.path.getsize(out) / 1e6:.1f} MB")


if __name__ == "__main__":
    main(sys.argv)
