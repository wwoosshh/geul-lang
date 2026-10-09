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


class 양자가중:
    """블록 평면 배치로 다시 깐 양자 가중치 하나(3단계/커널생성.py 의 설명). 형식("F16" · "Q8_0" · "Q4_0"), K(깊이 — 블록이 놓인 축),
    N(열), 값(배치한 값 — 바이트 배열로 본다), 척(척도 반실수 [kb][n] — F16 은 빈 것). nbytes = 값 + 척 (호스트가 [값][척도] 로 잇는다)."""

    def __init__(self, 형식, K, N, 값, 척):
        self.형식, self.K, self.N, self.값, self.척 = 형식, K, N, 값, 척
        self.nbytes = 값.nbytes + 척.nbytes
        self.배치, self.척도폭 = "가닥", N            # 6단계의 깔기정수 는 "정수" 와 64 로 올린 척도폭

    def 바이트(self):
        return np.concatenate([self.값.view(np.uint8).reshape(-1), self.척.view(np.uint8).reshape(-1)])


def 깔기(t, dims, raw):
    """GGUF 텐서(타입 t, 모양 (K, N) — ne0 = K 를 따라 블록, 날 바이트)를 블록 평면 배치로. 값은 그대로 — 자리만 옮긴다:
      칸 (kb, g, n) = 열 n 의 k = 32·kb + g + 4i (i < 8).
      Q4_0: 칸마다 32 비트 낱말 — 바이트 i' 가 블록의 qs[4i' + g] (값 i < 4 는 아래 4 비트, i ≥ 4 는 위 4 비트 — ggml 과 같은 짝).
      Q8_0: 칸마다 평면 둘 — 평면 h 의 바이트 i' 가 qs[g + 4(4h + i')] + 128.   F16: 칸마다 반실수 여덟.   척도: [kb][n]."""
    K, N = dims
    KB = K // 32
    if t == F16:
        h = raw.view(np.uint16).reshape(N, KB, 8, 4)                       # [n][kb][i][g] — k = 32kb + 4i + g
        return 양자가중("F16", K, N, np.ascontiguousarray(h.transpose(1, 3, 0, 2)).reshape(-1), np.zeros(0, np.uint16))
    bl = raw.reshape(N, KB, 블록[t][1])
    d = np.ascontiguousarray(np.ascontiguousarray(bl[:, :, :2]).view(np.uint16).reshape(N, KB).T)   # [kb][n]
    if t == Q4_0:
        qs = bl[:, :, 2:].reshape(N, KB, 4, 4)                              # [n][kb][i'][g] — qs[4i' + g]
        w = np.ascontiguousarray(qs.transpose(0, 1, 3, 2)).view(np.uint32).reshape(N, KB, 4)    # [n][kb][g] (바이트 i' → 비트 8i')
        return 양자가중("Q4_0", K, N, np.ascontiguousarray(w.transpose(1, 2, 0)).reshape(-1), d.reshape(-1))
    if t == Q8_0:
        qs = bl[:, :, 2:].reshape(N, KB, 8, 4) ^ np.uint8(0x80)             # [n][kb][i][g] — int8 + 128 (맨 위 비트 뒤집기와 같다)
        w = np.ascontiguousarray(qs.transpose(0, 1, 3, 2)).reshape(N, KB, 4, 2, 4).view(np.uint32).reshape(N, KB, 4, 2)
        return 양자가중("Q8_0", K, N, np.ascontiguousarray(w.transpose(1, 2, 3, 0)).reshape(-1), d.reshape(-1))
    raise ValueError(f"깔 수 없는 형식 {t}")


def 깔기정수(t, dims, raw):
    """6단계 정수 블록 계약의 배치(3단계/커널생성.py 의 설명): 값 [블록][열][32 바이트](Q8_0 — 부호 있는 q, k 차례) 또는
    [블록][열][16 바이트](Q4_0 — 낱말 j 의 바이트 m: 아래 니블 = q[8j + m] + 8, 위 니블 = q[8j + 4 + m] + 8), 척도 [블록][척도폭]
    (반실수, 척도폭 = N 을 64 로 올림 — 남는 칸은 0). 값은 그대로 — 자리만 옮긴다. 형식은 "Q8_0" · "Q4_0", 배치 = "정수"."""
    K, N = dims
    KB = K // 32
    Np = (N + 63) // 64 * 64
    bl = raw.reshape(N, KB, 블록[t][1])
    d = np.zeros((KB, Np), np.uint16)
    d[:, :N] = np.ascontiguousarray(bl[:, :, :2]).view(np.uint16).reshape(N, KB).T
    if t == Q8_0:
        v = np.ascontiguousarray(bl[:, :, 2:].transpose(1, 0, 2))                    # [KB][N][32]
        q = 양자가중("Q8_0", K, N, v.reshape(-1), d.reshape(-1))
    elif t == Q4_0:
        qs = bl[:, :, 2:]
        u = np.concatenate([qs & 15, qs >> 4], 2)                                  # [N][KB][32] — 니블(q + 8), k 차례
        u = u.transpose(1, 0, 2).reshape(KB, N, 4, 2, 4)                          # [KB][N][j][h][m] — k = 8j + 4h + m
        v = np.ascontiguousarray(u[:, :, :, 0, :] | (u[:, :, :, 1, :] << 4)).astype(np.uint8)
        q = 양자가중("Q4_0", K, N, v.reshape(-1), d.reshape(-1))
    else:
        raise ValueError(f"정수 배치로 깔 수 없는 형식 {t}")
    q.배치, q.척도폭 = "정수", Np
    return q


def 펴보기정수(q):
    """깔기정수의 거꾸로 — 짧은실수 [N][K] (시험용)."""
    K, N, KB, Np = q.K, q.N, q.K // 32, q.척도폭
    d = q.척.view(np.float16).astype(np.float32).reshape(KB, Np)[:, :N]
    if q.형식 == "Q8_0":
        v = q.값.view(np.int8).reshape(KB, N, 32).astype(np.float32)
    else:
        b = q.값.view(np.uint8).reshape(KB, N, 4, 4)
        v = np.stack([b & 15, b >> 4], 3).reshape(KB, N, 32).astype(np.float32) - 8     # [KB][N][j][h][m]
    return np.ascontiguousarray((v * d[:, :, None]).transpose(1, 0, 2)).reshape(N, K)


def gpt2정수(path):
    """GGUF(Q8_0 · Q4_0)의 GPT-2 를 6단계 정수 계약의 배치로 — 선형 가중치와 낱말표는 깔기정수, 나머지(F32)는 짧은실수."""
    g = GGUF(path)

    def 양자(name):
        return 깔기정수(*g.원(name))
    w = {"wte.weight": 양자("token_embd.weight"), "wpe.weight": g.풀기("position_embd.weight"),
         "ln_f.weight": g.풀기("output_norm.weight"), "ln_f.bias": g.풀기("output_norm.bias")}
    짝 = {"attn_norm": "ln_1", "ffn_norm": "ln_2", "attn_qkv": "attn.c_attn", "attn_output": "attn.c_proj",
         "ffn_up": "mlp.c_fc", "ffn_down": "mlp.c_proj"}
    for l in range(g.meta["gpt2.block_count"]):
        for a, h in 짝.items():
            for s in ("weight", "bias"):
                n = f"blk.{l}.{a}.{s}"
                w[f"h.{l}.{h}.{s}"] = 양자(n) if s == "weight" and a not in ("attn_norm", "ffn_norm") else g.풀기(n)
    return w


def 펴보기(q):
    """깔기의 거꾸로 — 짧은실수 [N][K] (시험용: 풀기 와 비트까지 같아야 한다)."""
    K, N, KB = q.K, q.N, q.K // 32
    if q.형식 == "F16":
        h = q.값.view(np.uint16).reshape(KB, 4, N, 8).transpose(2, 0, 3, 1)  # [n][kb][i][g]
        return np.ascontiguousarray(h).view(np.float16).astype(np.float32).reshape(N, K)
    d = q.척.view(np.float16).astype(np.float32).reshape(KB, N)
    if q.형식 == "Q4_0":
        w = q.값.view(np.uint32).reshape(KB, 4, N)
        i = np.arange(8)
        sh = np.where(i < 4, 8 * i, 8 * (i - 4) + 4).astype(np.uint32)
        v = ((w[..., None] >> sh) & 15).astype(np.int32) - 8                 # [kb][g][n][i]
    else:
        w = q.값.view(np.uint32).reshape(KB, 4, 2, N)
        sh = (8 * np.arange(4)).astype(np.uint32)
        v = ((w[..., None] >> sh) & 255).astype(np.int32) - 128               # [kb][g][h][n][i']
        v = v.transpose(0, 1, 3, 2, 4).reshape(KB, 4, N, 8)                   # [kb][g][n][i = 4h + i']
    x = v.astype(np.float32) * d[:, None, :, None]                            # 정확하다
    return np.ascontiguousarray(x.transpose(2, 0, 3, 1)).reshape(N, K)        # [n][kb][i][g]


def gpt2양자(path):
    """GGUF 의 GPT-2 를 글GPT2 가 받는 꼴로 — 선형 가중치와 낱말표는 양자가중(블록 평면 배치), 나머지(F32)는 짧은실수."""
    g = GGUF(path)

    def 양자(name):
        return 깔기(*g.원(name))
    w = {"wte.weight": 양자("token_embd.weight"), "wpe.weight": g.풀기("position_embd.weight"),
         "ln_f.weight": g.풀기("output_norm.weight"), "ln_f.bias": g.풀기("output_norm.bias")}
    짝 = {"attn_norm": "ln_1", "ffn_norm": "ln_2", "attn_qkv": "attn.c_attn", "attn_output": "attn.c_proj",
         "ffn_up": "mlp.c_fc", "ffn_down": "mlp.c_proj"}
    for l in range(g.meta["gpt2.block_count"]):
        for a, h in 짝.items():
            for s in ("weight", "bias"):
                n = f"blk.{l}.{a}.{s}"
                w[f"h.{l}.{h}.{s}"] = 양자(n) if s == "weight" and a not in ("attn_norm", "ffn_norm") else g.풀기(n)
    return w


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
