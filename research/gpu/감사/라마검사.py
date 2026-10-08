#!/usr/bin/env python3
"""감사 A3 — llama.cpp(b11496) 의 CUDA 커널을 ggml C API 로 직접 부른다 (README 의 A3 방법 그대로).

  build/감사venv/Scripts/python research/gpu/감사/라마검사.py              # 모든 검사를 검사마다 따로 된 프로세스로
  build/감사venv/Scripts/python research/gpu/감사/라마검사.py <검사이름>    # 검사 하나 — JSON 한 줄을 낸다

ggml 이 단언으로 멈추면(abort) 그 검사의 프로세스만 죽는다 — 그것은 "오류로 멈춤"이지 조용한 손실이 아니다.
"""
import ctypes
import json
import os
import subprocess
import sys
import time

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
LL = os.path.join(ROOT, "build", "llama-b11496")
F32, F16, Q4_0, Q8_0, I32 = 0, 1, 2, 8, 26
N1 = 2 ** 31 + 2 ** 20
P = ctypes.c_void_p
I64, SZ, FL = ctypes.c_int64, ctypes.c_size_t, ctypes.c_float


class InitParams(ctypes.Structure):
    _fields_ = [("mem_size", ctypes.c_size_t), ("mem_buffer", ctypes.c_void_p), ("no_alloc", ctypes.c_bool)]


class GG:
    """ggml 의 C API 중 이 검사에 쓰는 것만."""

    def __init__(self):
        # ggml 이 백엔드 DLL 을 LoadLibrary 로 올릴 때, ggml-cuda.dll 이 기대는 cudart·cublas 는 PATH 로만 찾는다
        os.environ["PATH"] = LL + os.pathsep + os.environ.get("PATH", "")
        os.add_dll_directory(LL)
        self.libs = [ctypes.CDLL(os.path.join(LL, n)) for n in ("ggml-base.dll", "ggml.dll")]
        d = self.fn
        self.init = d("ggml_init", P, InitParams)
        self.free = d("ggml_free", None, P)
        self.new1 = d("ggml_new_tensor_1d", P, P, ctypes.c_int, I64)
        self.new2 = d("ggml_new_tensor_2d", P, P, ctypes.c_int, I64, I64)
        self.new3 = d("ggml_new_tensor_3d", P, P, ctypes.c_int, I64, I64, I64)
        self.add = d("ggml_add", P, P, P, P)
        self.mul = d("ggml_mul", P, P, P, P)
        self.scale = d("ggml_scale", P, P, P, FL)
        self.cont = d("ggml_cont", P, P, P)
        self.view2 = d("ggml_view_2d", P, P, P, I64, I64, SZ, SZ)
        self.transpose = d("ggml_transpose", P, P, P)
        self.soft_max_ext = d("ggml_soft_max_ext", P, P, P, P, FL, FL)
        self.rms_norm = d("ggml_rms_norm", P, P, P, FL)
        self.get_rows = d("ggml_get_rows", P, P, P, P)
        self.mul_mat = d("ggml_mul_mat", P, P, P, P)
        self.flash = d("ggml_flash_attn_ext", P, P, P, P, P, P, FL, FL, FL)
        self.unary = {n: d(n, P, P, P) for n in ("ggml_sqr", "ggml_sqrt", "ggml_gelu", "ggml_silu", "ggml_exp")}
        self.new_graph = d("ggml_new_graph", P, P)
        self.build = d("ggml_build_forward_expand", None, P, P)
        self.tensor_overhead = d("ggml_tensor_overhead", SZ)
        self.graph_overhead = d("ggml_graph_overhead", SZ)
        self.row_size = d("ggml_row_size", SZ, ctypes.c_int, I64)
        self.quantize = d("ggml_quantize_chunk", SZ, ctypes.c_int, P, P, I64, I64, I64, P)
        self.load_all = d("ggml_backend_load_all_from_path", None, ctypes.c_char_p)
        self.init_by_name = d("ggml_backend_init_by_name", P, ctypes.c_char_p, ctypes.c_char_p)
        self.alloc_ctx = d("ggml_backend_alloc_ctx_tensors", P, P, P)
        self.tset = d("ggml_backend_tensor_set", None, P, P, SZ, SZ)
        self.tget = d("ggml_backend_tensor_get", None, P, P, SZ, SZ)
        self.compute = d("ggml_backend_graph_compute", ctypes.c_int, P, P)
        self.buf_free = d("ggml_backend_buffer_free", None, P)
        self.load_all(LL.encode())
        self.cuda = self.init_by_name(b"CUDA0", None)
        assert self.cuda, "CUDA0 백엔드를 열지 못했다"

    def fn(self, name, res, *args):
        for lib in self.libs:
            try:
                f = getattr(lib, name)
            except AttributeError:
                continue
            f.restype, f.argtypes = res, list(args)
            return f
        raise AttributeError(name)


class Run:
    """문맥 하나 = 그래프 하나. 텐서 메타데이터만 만들고, 데이터는 CUDA 버퍼에 한꺼번에 잡는다."""

    def __init__(self, g):
        self.g = g
        self.ctx = g.init(InitParams(g.tensor_overhead() * 64 + g.graph_overhead() + (1 << 20), None, True))
        self.buf = None

    def compute(self, outputs, inputs):
        g = self.g
        graph = g.new_graph(self.ctx)
        for o in outputs:
            g.build(graph, o)
        self.buf = g.alloc_ctx(self.ctx, g.cuda)
        if not self.buf:
            raise MemoryError("CUDA 버퍼를 잡지 못했다")
        for t, arr in inputs:
            arr = np.ascontiguousarray(arr)
            g.tset(t, arr.ctypes.data, 0, arr.nbytes)
        st = g.compute(g.cuda, graph)
        if st != 0:
            raise RuntimeError(f"graph_compute 상태 {st}")

    def get(self, t, offset_bytes, count, dtype):
        out = np.empty(count, dtype=dtype)
        self.g.tget(t, out.ctypes.data, offset_bytes, out.nbytes)
        return out

    def close(self):
        if self.buf:
            self.g.buf_free(self.buf)
        self.g.free(self.ctx)


def rel(a, b):
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    return float(np.linalg.norm(a - b) / max(np.linalg.norm(b), 1e-300))


# ---------------- 검사들 ----------------
def row_mm(g, wtype, wname):
    K = N = 4096
    Ms = [1, 2, 3, 4, 8, 16, 32, 64, 128, 256, 512]
    rng = np.random.default_rng(48)
    w = (rng.standard_normal((N, K)) / 64).astype(np.float32)
    x = rng.standard_normal((512, K)).astype(np.float32)
    if wtype in (Q8_0, Q4_0):
        wq = np.empty(g.row_size(wtype, K) * N, dtype=np.uint8)
        g.quantize(wtype, w.ctypes.data, wq.ctypes.data, 0, N, K, None)
    ref, differ, worst = None, [], 0.0
    for M in Ms:
        r = Run(g)
        a = g.new2(r.ctx, wtype, K, N)
        b = g.new2(r.ctx, F32, K, M)
        out = g.mul_mat(r.ctx, a, b)
        wdata = {F32: w, F16: w.astype(np.float16)}.get(wtype, wq if wtype in (Q8_0, Q4_0) else None)
        r.compute([out], [(a, wdata), (b, x[:M])])
        row0 = r.get(out, 0, N, np.float32)
        r.close()
        if ref is None:
            ref = row0
        elif not np.array_equal(row0.view(np.uint32), ref.view(np.uint32)):
            differ.append(M)
            worst = max(worst, float(np.abs(row0.astype(np.float64) - ref).max()))
    return {"성질": "행 불변", "결과": "참고", "세부": f"mul_mat {wname}: 0번 열의 비트가 M=1 과 다른 M {differ or '없음'}, 최대차 {worst:.3g}",
            "다른_M": differ}


def row_rowwise(g, which):
    D = 4096
    rng = np.random.default_rng(48)
    x = rng.standard_normal((512, D)).astype(np.float32)
    ref, differ = None, []
    for M in [1, 2, 3, 4, 8, 16, 32, 64, 128, 256, 512]:
        r = Run(g)
        a = g.new2(r.ctx, F32, D, M)
        out = g.rms_norm(r.ctx, a, 1e-6) if which == "rms_norm" else g.soft_max_ext(r.ctx, a, None, 1.0, 0.0)
        r.compute([out], [(a, x[:M])])
        row0 = r.get(out, 0, D, np.float32)
        r.close()
        if ref is None:
            ref = row0
        elif not np.array_equal(row0.view(np.uint32), ref.view(np.uint32)):
            differ.append(M)
    return {"성질": "행 불변", "결과": "참고", "세부": f"{which}: 0번 행의 비트가 M=1 과 다른 M {differ or '없음'}", "다른_M": differ}


def iw_add(g):
    r = Run(g)
    a = g.new1(r.ctx, F16, N1)
    b = g.new1(r.ctx, F16, 1)
    out = g.add(r.ctx, a, b)
    r.compute([out], [(a, np.zeros(N1, np.float16)), (b, np.ones(1, np.float16))])
    pos = [0, 2 ** 31 - 1, 2 ** 31, 2 ** 31 + 12345, N1 - 1]
    got = [float(r.get(out, p * 2, 1, np.float16)[0]) for p in pos]
    r.close()
    ok = all(v == 1.0 for v in got)
    return {"성질": "정수 폭", "결과": "통과" if ok else "손실", "세부": f"add f16 N1, 먼 자리 {dict(zip(pos, got))}"}


def iw_cont(g):
    R, C = 32768, 65568
    r = Run(g)
    a = g.new2(r.ctx, F16, C, R)                                 # a[r][c], 행 R 개 × 열 C 개
    y = g.cont(r.ctx, g.transpose(r.ctx, a))                       # y[c][r]
    pat = np.tile(np.arange(127, dtype=np.float16), (N1 + 126) // 127)[:N1]
    r.compute([y], [(a, pat)])
    samples = [(R - 1, C - 1), (R - 1, 0), (0, C - 1), (R // 2, C - 3), (R - 2, C // 2), (32767, 65535)]
    bad = []
    for rr, cc in samples:
        v = float(r.get(y, (cc * R + rr) * 2, 1, np.float16)[0])
        if v != (rr * C + cc) % 127:
            bad.append((rr, cc, v))
    r.close()
    return {"성질": "정수 폭", "결과": "통과" if not bad else "손실", "세부": f"transpose+cont f16 [65568, 32768], 틀린 표본 {bad}"}


def iw_rowwise(g, which):
    D, R = 1024, 2 ** 19 + 1
    rng = np.random.default_rng(48)
    x = rng.standard_normal((R, D), dtype=np.float32)
    r = Run(g)
    a = g.new2(r.ctx, F32, D, R)
    out = g.rms_norm(r.ctx, a, 1e-6) if which == "rms_norm" else g.soft_max_ext(r.ctx, a, None, 1.0, 0.0)
    r.compute([out], [(a, x)])
    last = r.get(out, (R - 1) * D * 4, D, np.float32)
    r.close()
    r = Run(g)
    a1 = g.new2(r.ctx, F32, D, 1)
    o1 = g.rms_norm(r.ctx, a1, 1e-6) if which == "rms_norm" else g.soft_max_ext(r.ctx, a1, None, 1.0, 0.0)
    r.compute([o1], [(a1, x[-1:])])
    alone = r.get(o1, 0, D, np.float32)
    r.close()
    d = rel(last, alone)
    same = np.array_equal(last.view(np.uint32), alone.view(np.uint32))
    ok = np.isfinite(last).all() and d <= 1e-2
    return {"성질": "정수 폭", "결과": "통과" if ok else "손실",
            "세부": f"{which} f32 [1024, 2^19+1] 마지막 행: 그 행만 계산한 것과 상대차 {d:.3g}, 비트 같음 {same}"}


def iw_get_rows(g):
    D, R = 1024, 2 ** 21 + 1
    rng = np.random.default_rng(48)
    block = rng.standard_normal((1024, D)).astype(np.float16)     # 4.3 GB 표를 블록 반복으로 만들고
    table = np.tile(block, (R // 1024 + 1, 1))[:R]
    table[-1] = rng.standard_normal(D).astype(np.float16)          # 마지막 행만 다르게 — 엉뚱한 행을 읽으면 드러난다
    r = Run(g)
    t = g.new2(r.ctx, F16, D, R)
    idx = g.new1(r.ctx, I32, 1)
    out = g.get_rows(r.ctx, t, idx)
    r.compute([out], [(t, table), (idx, np.array([R - 1], np.int32))])
    got = r.get(out, 0, D, np.float32)
    r.close()
    ok = np.array_equal(got, table[-1].astype(np.float32))
    return {"성질": "정수 폭", "결과": "통과" if ok else "손실", "세부": f"get_rows f16 [1024, 2^21+1] 마지막 행 정확 {ok}"}


def iw_mul_mat(g):
    K, N, M = 16, 32784, 65536                                    # 출력 N × M = N1 원소 (f32 8.6 GB)
    rng = np.random.default_rng(48)
    A = rng.integers(0, 3, (N, K)).astype(np.float16)
    B = rng.integers(0, 3, (M, K)).astype(np.float32)
    r = Run(g)
    a = g.new2(r.ctx, F16, K, N)
    b = g.new2(r.ctx, F32, K, M)
    out = g.mul_mat(r.ctx, a, b)                                   # out[m][n] = Σ_k A[n,k] B[m,k]
    r.compute([out], [(a, A), (b, B)])
    probe = [(M - 1, N - 1), (M - 1, 0), (M - 2, N // 2), (40000, N - 5), (65535, 32783)]
    bad = []
    for m, n in probe:
        v = float(r.get(out, (m * N + n) * 4, 1, np.float32)[0])
        e = float(A[n].astype(np.float64) @ B[m].astype(np.float64))
        if v != e:
            bad.append((m, n, v, e))
    r.close()
    return {"성질": "정수 폭", "결과": "통과" if not bad else "손실", "세부": f"mul_mat 출력 N1 원소, 틀린 표본 {bad}"}


def iw_flash(g):
    D, NKV, NQ = 128, 262144, 8256                                # 가리개 원소 NKV × NQ > 2^31
    rng = np.random.default_rng(48)
    q = rng.standard_normal((NQ, D), dtype=np.float32)
    k = rng.standard_normal((NKV, D), dtype=np.float32).astype(np.float16)
    v = rng.standard_normal((NKV, D), dtype=np.float32).astype(np.float16)
    lim = np.minimum(32 * (np.arange(NQ, dtype=np.int64) + 1), NKV)
    mask = np.where(np.arange(NKV, dtype=np.int64)[None, :] < lim[:, None], np.float16(0), np.float16(-np.inf)).astype(np.float16)
    scale = 1.0 / np.sqrt(D)
    r = Run(g)
    tq = g.new3(r.ctx, F32, D, NQ, 1)
    tk = g.new3(r.ctx, F16, D, NKV, 1)
    tv = g.new3(r.ctx, F16, D, NKV, 1)
    tm = g.new2(r.ctx, F16, NKV, NQ)
    out = g.flash(r.ctx, tq, tk, tv, tm, scale, 0.0, 0.0)          # [D, 1, NQ]
    r.compute([out], [(tq, q), (tk, k), (tv, v), (tm, mask)])
    res = {}
    for j in (100, 8192, NQ - 1):
        got = r.get(out, j * D * 4, D, np.float32)
        L = int(lim[j])
        s = (k[:L].astype(np.float64) @ q[j].astype(np.float64)) * scale
        p = np.exp(s - s.max())
        ref = (p / p.sum()) @ v[:L].astype(np.float64)
        res[j] = (bool(np.isfinite(got).all()), rel(got, ref))
    r.close()
    ok = all(f and d <= 1e-2 for f, d in res.values())
    return {"성질": "정수 폭", "결과": "통과" if ok else "손실",
            "세부": "flash_attn_ext 가리개 [262144, 8256]: " + ", ".join(f"질의 {j}: 유한 {f}, 상대차 {d:.3g}" for j, (f, d) in res.items())}


def layout(g, opname, vname):
    rng = np.random.default_rng(48)
    base = rng.standard_normal((1024, 1024)).astype(np.float32)
    if opname == "sqrt":
        base = np.abs(base) + 0.1
    r = Run(g)
    a = g.new2(r.ctx, F32, 1024, 1024)
    if vname == "전치":
        v = g.transpose(r.ctx, a); shape = (1024, 1024)
    elif vname == "넓은 행 간격":
        v = g.view2(r.ctx, a, 512, 1024, 4096, 0); shape = (512, 1024)
    else:
        v = g.view2(r.ctx, a, 1000, 1000, 4096, (1 * 1024 + 3) * 4); shape = (1000, 1000)
    other = g.new2(r.ctx, F32, *shape)
    c = g.cont(r.ctx, v)

    def op(t):
        if opname == "add":
            return g.add(r.ctx, t, other)
        if opname == "mul":
            return g.mul(r.ctx, t, other)
        if opname == "scale":
            return g.scale(r.ctx, t, 1.7)
        return g.unary["ggml_" + opname](r.ctx, t)

    o1, o2 = op(v), op(c)
    r.compute([o1, o2], [(a, base), (other, rng.standard_normal(shape[::-1]).astype(np.float32))])
    n = shape[0] * shape[1]
    x1, x2 = r.get(o1, 0, n, np.float32), r.get(o2, 0, n, np.float32)
    r.close()
    same = np.array_equal(x1.view(np.uint32), x2.view(np.uint32))
    return {"성질": "배치 무관", "결과": "통과" if same else "손실",
            "세부": f"{opname}@{vname}: " + ("비트까지 같음" if same else f"다른 칸 {int((x1.view(np.uint32) != x2.view(np.uint32)).sum())}, 최대차 {float(np.abs(x1 - x2).max()):.3g}")}


def range_mm_partial(g):
    K, N = 8192, 64
    w = np.concatenate([np.full(K // 2, 300.0), np.full(K // 2, -300.0)]).astype(np.float16)
    W = np.tile(w, (N, 1))
    out = []
    for M in (1, 64):
        r = Run(g)
        a = g.new2(r.ctx, F16, K, N)
        b = g.new2(r.ctx, F32, K, M)
        o = g.mul_mat(r.ctx, a, b)
        r.compute([o], [(a, W), (b, np.ones((M, K), np.float32))])
        got = r.get(o, 0, N * M, np.float32)
        r.close()
        out.append((M, bool(np.isfinite(got).all()), float(np.abs(np.nan_to_num(got, nan=np.inf)).max())))
    ok = all(f and m == 0.0 for _, f, m in out)
    return {"성질": "범위", "결과": "통과" if ok else "손실",
            "세부": "mul_mat f16 ±300 (K=8192, 참값 0): " + ", ".join(f"M={M}: 유한 {f}, 최대 |값| {m}" for M, f, m in out)}


def range_mm_act(g):
    K, N = 4096, 64
    W = np.full((N, K), 1e-3, np.float16)
    out = []
    for M in (1, 64):
        X = np.full((M, K), 1e5, np.float32)
        r = Run(g)
        a = g.new2(r.ctx, F16, K, N)
        b = g.new2(r.ctx, F32, K, M)
        o = g.mul_mat(r.ctx, a, b)
        r.compute([o], [(a, W), (b, X)])
        got = r.get(o, 0, N * M, np.float32)
        r.close()
        exp_v = float(K * np.float64(np.float16(1e-3)) * 1e5)
        out.append((M, bool(np.isfinite(got).all()), rel(got, np.full_like(got, exp_v, dtype=np.float64))))
    ok = all(f and d <= 1e-2 for _, f, d in out)
    return {"성질": "범위", "결과": "통과" if ok else "손실",
            "세부": "mul_mat f16 가중치 × 활성 1e5 (참값 4.1e5): " + ", ".join(f"M={M}: 유한 {f}, 상대차 {d:.3g}" for M, f, d in out)}


def range_flash(g):
    D, NKV = 64, 256
    rng = np.random.default_rng(48)
    v = rng.standard_normal((NKV, D), dtype=np.float32).astype(np.float16)
    out = []
    for NQ in (1, 64):
        r = Run(g)
        tq = g.new3(r.ctx, F32, D, NQ, 1)
        tk = g.new3(r.ctx, F16, D, NKV, 1)
        tv = g.new3(r.ctx, F16, D, NKV, 1)
        tm = g.new2(r.ctx, F16, NKV, NQ)
        o = g.flash(r.ctx, tq, tk, tv, tm, 1.0 / 8.0, 0.0, 0.0)
        r.compute([o], [(tq, np.full((NQ, D), 100.0, np.float32)), (tk, np.full((NKV, D), 100.0, np.float16)),
                        (tv, v), (tm, np.zeros((NQ, NKV), np.float16))])
        got = r.get(o, 0, D * NQ, np.float32).reshape(NQ, D)
        r.close()
        ref = v.astype(np.float64).mean(0)
        out.append((NQ, bool(np.isfinite(got).all()), rel(got[0], ref)))
    ok = all(f and d <= 1e-2 for _, f, d in out)
    return {"성질": "범위", "결과": "통과" if ok else "손실",
            "세부": "flash_attn_ext f16 점수 8e4: " + ", ".join(f"질의 {n}개: 유한 {f}, 상대차 {d:.3g}" for n, f, d in out)}


CHECKS = {
    "행불변-mm-f32": lambda g: row_mm(g, F32, "f32"), "행불변-mm-f16": lambda g: row_mm(g, F16, "f16"),
    "행불변-mm-q8_0": lambda g: row_mm(g, Q8_0, "q8_0"), "행불변-mm-q4_0": lambda g: row_mm(g, Q4_0, "q4_0"),
    "행불변-rms_norm": lambda g: row_rowwise(g, "rms_norm"), "행불변-soft_max": lambda g: row_rowwise(g, "soft_max"),
    "정수폭-a-add": iw_add, "정수폭-b-cont": iw_cont, "정수폭-c-soft_max": lambda g: iw_rowwise(g, "soft_max"),
    "정수폭-d-rms_norm": lambda g: iw_rowwise(g, "rms_norm"), "정수폭-e-get_rows": iw_get_rows,
    "정수폭-f-mul_mat": iw_mul_mat, "정수폭-g-flash": iw_flash,
    "범위-a-mm부분합": range_mm_partial, "범위-b-mm활성": range_mm_act, "범위-c-flash": range_flash,
}
for _op in ("add", "mul", "sqr", "sqrt", "gelu", "silu", "exp", "scale"):
    for _v in ("전치", "넓은 행 간격", "어긋난 시작"):
        CHECKS[f"배치무관-{_op}-{_v}"] = (lambda o, vv: (lambda g: layout(g, o, vv)))(_op, _v)


def main(argv):
    if argv:
        name = argv[0]
        t0 = time.time()
        res = CHECKS[name](GG())
        res.update({"검사": name, "초": round(time.time() - t0, 1)})
        print("RESULT " + json.dumps(res, ensure_ascii=False))
        return 0
    results = []
    for name in CHECKS:
        try:
            p = subprocess.run([sys.executable, os.path.abspath(__file__), name], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=1200)
            line = [l for l in p.stdout.splitlines() if l.startswith("RESULT ")]
            if line:
                res = json.loads(line[-1][7:])
            else:
                err = (p.stderr or p.stdout).strip().splitlines()[-3:]
                kind = "메모리 부족" if any("memory" in e.lower() or "MemoryError" in e for e in err) else "오류로 멈춤"
                res = {"검사": name, "결과": kind, "세부": " | ".join(err)[:400], "종료코드": p.returncode}
        except subprocess.TimeoutExpired:
            res = {"검사": name, "결과": "시간 초과", "세부": "1200초"}
        results.append(res)
        print(f"{res['검사']:<24} {res['결과']:<5} {res.get('세부', '')}", flush=True)
    os.makedirs(os.path.join(HERE, "결과"), exist_ok=True)
    json.dump({"대상": "llama.cpp b11496 (win-cuda-13.4-x64)", "결과": results},
              open(os.path.join(HERE, "결과", "라마검사.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
