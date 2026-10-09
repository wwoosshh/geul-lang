#!/usr/bin/env python3
"""5단계 — GGUF(v3) 읽기: 메타데이터와 텐서. 형식은 F32 · F16 · Q8_0 · Q4_0 (ggml 의 블록 그대로).

  Q8_0: 블록 = 값 32 개 — d (f16) + qs[32] (int8).           값 = qs[j] · d
  Q4_0: 블록 = 값 32 개 — d (f16) + qs[16] (바이트).          값[j] = ((qs[j] & 15) − 8) · d,  값[j + 16] = ((qs[j] >> 4) − 8) · d
풀기는 짧은실수로 — d 를 f16 → f32 로(정확) 넓히고 정수와 곱한다(Q8_0 은 가수 19 비트, Q4_0 은 15 비트 이하라 곱이 정확하다).
ggml 의 dequantize_row_* 와 같은 값이다(5단계의 시험이 대조한다). 텐서의 모양은 ggml 의 차례 [ne0, ne1] — 배열은 (ne1, ne0).
"""
import struct

import numpy as np

F32, F16, Q4_0, Q8_0 = 0, 1, 2, 8
이름 = {F32: "F32", F16: "F16", Q4_0: "Q4_0", Q8_0: "Q8_0"}
블록 = {F32: (1, 4), F16: (1, 2), Q4_0: (32, 18), Q8_0: (32, 34)}      # (값 수, 바이트 수)


def _문자열(b, o):
    n = struct.unpack_from("<Q", b, o)[0]
    return b[o + 8:o + 8 + n].decode("utf-8"), o + 8 + n


def _값(b, o, t):
    f = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
    if t in f:
        return struct.unpack_from(f[t], b, o)[0], o + struct.calcsize(f[t])
    if t == 8:
        return _문자열(b, o)
    if t == 9:
        et, n = struct.unpack_from("<IQ", b, o)
        o += 12
        out = []
        for _ in range(n):
            v, o = _값(b, o, et)
            out.append(v)
        return out, o
    raise ValueError(f"GGUF 값 타입 {t}")


class GGUF:
    def __init__(self, path):
        b = self.b = open(path, "rb").read()
        assert b[:4] == b"GGUF", "GGUF 파일이 아니다"
        ver, nt, nkv = struct.unpack_from("<IQQ", b, 4)
        assert ver == 3, f"GGUF 판 {ver}"
        o = 24
        self.meta = {}
        for _ in range(nkv):
            k, o = _문자열(b, o)
            t = struct.unpack_from("<I", b, o)[0]
            self.meta[k], o = _값(b, o + 4, t)
        self.tensors = {}
        for _ in range(nt):
            name, o = _문자열(b, o)
            nd = struct.unpack_from("<I", b, o)[0]
            dims = struct.unpack_from(f"<{nd}Q", b, o + 4)
            t, off = struct.unpack_from("<IQ", b, o + 4 + 8 * nd)
            o += 4 + 8 * nd + 12
            self.tensors[name] = (t, tuple(dims), off)
        al = self.meta.get("general.alignment", 32)
        self.data0 = (o + al - 1) // al * al

    def 원(self, name):
        """(타입, (ne0, ne1, …), 바이트) — 텐서의 날 바이트."""
        t, dims, off = self.tensors[name]
        if t not in 블록:
            raise ValueError(f"{name}: 다루지 않는 형식 {t}")
        n = int(np.prod(dims))
        vb, bb = 블록[t]
        assert n % vb == 0
        nb = n // vb * bb
        s = self.data0 + off
        return t, dims, np.frombuffer(self.b, np.uint8, nb, s)

    def 풀기(self, name):
        """짧은실수로 푼 값 — 배열 모양 (ne1, ne0) (1 차원이면 (ne0,))."""
        t, dims, raw = self.원(name)
        shape = tuple(reversed(dims))
        if t == F32:
            return raw.view(np.float32).reshape(shape).copy()
        if t == F16:
            return raw.view(np.float16).astype(np.float32).reshape(shape)
        bl = raw.reshape(-1, 블록[t][1])
        d = bl[:, :2].copy().view(np.float16).astype(np.float32)          # (블록, 1)
        if t == Q8_0:
            q = bl[:, 2:].view(np.int8).astype(np.float32)                # (블록, 32)
        else:
            qs = bl[:, 2:]
            q = np.concatenate([(qs & 15).astype(np.int8) - 8, (qs >> 4).astype(np.int8) - 8], 1).astype(np.float32)
        return (q * d).astype(np.float32).reshape(shape)


def gpt2가중치(path):
    """GGUF 의 GPT-2 를 HF 이름 · 모양의 짧은실수로 푼다 (선형 가중치는 [입력][출력] — Conv1D 꼴로 되돌린다)."""
    g = GGUF(path)
    w = {"wte.weight": g.풀기("token_embd.weight"), "wpe.weight": g.풀기("position_embd.weight"),
         "ln_f.weight": g.풀기("output_norm.weight"), "ln_f.bias": g.풀기("output_norm.bias")}
    짝 = {"attn_norm": "ln_1", "ffn_norm": "ln_2", "attn_qkv": "attn.c_attn", "attn_output": "attn.c_proj",
         "ffn_up": "mlp.c_fc", "ffn_down": "mlp.c_proj"}
    for l in range(g.meta["gpt2.block_count"]):
        for a, h in 짝.items():
            for s in ("weight", "bias"):
                x = g.풀기(f"blk.{l}.{a}.{s}")
                if s == "weight" and a not in ("attn_norm", "ffn_norm"):
                    x = np.ascontiguousarray(x.T)                           # [출력][입력] → [입력][출력]
                w[f"h.{l}.{h}.{s}"] = x
    return g, w
