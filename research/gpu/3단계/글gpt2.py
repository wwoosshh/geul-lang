#!/usr/bin/env python3
"""3단계 — GPT-2 small 을 글 커널로 돌리는 호스트. PyTorch 를 쓰지 않는다.

GPU 계산은 모두 gpt2.gl 의 커널(글ptx.py → PTX → nvcuda.dll)이 한다. 이 파일이 맡는 것은 가중치 파일을 읽어 GPU 에 올리기,
커널을 부르는 순서, 토크나이저뿐이다. numpy 는 파일을 읽고 결과를 받아 오는 데만 쓴다.

행의 배치: 한 번 부를 때 문장 B 개가 m 행씩(행 r 은 문장 r // m, 위치 위치시작 + r % m) — 한 묶음의 문장은 길이가 같다.
"""
import ctypes
import json
import os
import subprocess
import sys
import unicodedata

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from 커널생성 import 어텐션질의수, 정수판들, 정수판들둘, 정수판들KV, 정수판표, 정수판모양, 정수열묶음, 층정규화정수행      # noqa: E402 — 정수 판의 모양(커널과 같은 표 · 규칙)
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
D, NH, NL, V, NCTX = 768, 12, 12, 50257, 1024            # GPT-2 small — 모형마다의 크기는 글GPT2 의 self.D · NH · NL · V (7단계)

c_u64, c_i64, c_uint = ctypes.c_uint64, ctypes.c_int64, ctypes.c_uint


# ── 가중치 파일 (safetensors: 8바이트 머리 길이 + JSON 머리 + 날 데이터) ─────────────────────────────

def 가중치읽기(path):
    """{이름: float32 배열}. 이름의 'transformer.' 앞말은 뗀다. 'attn.bias'(인과 가림 버퍼)는 버린다."""
    with open(path, "rb") as f:
        n = int.from_bytes(f.read(8), "little")
        head = json.loads(f.read(n))
        raw = f.read()
    out = {}
    for name, info in head.items():
        if name == "__metadata__":
            continue
        key = name[len("transformer."):] if name.startswith("transformer.") else name
        if key.endswith(".attn.bias") or key.endswith(".attn.masked_bias"):
            continue
        if info["dtype"] != "F32":
            raise ValueError(f"{name}: {info['dtype']} — F32 만 받는다")
        b, e = info["data_offsets"]
        out[key] = np.frombuffer(raw, dtype=np.float32, count=(e - b) // 4, offset=b).reshape(info["shape"])
    return out


# ── 토크나이저 (GPT-2 바이트 BPE) ──────────────────────────────────────────────────────────────

def _바이트글자():
    bs = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1)) + list(range(ord("®"), ord("ÿ") + 1))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return {b: chr(c) for b, c in zip(bs, cs)}


def _앞자르기(text):
    """GPT-2 의 정규식 's|'t|'re|'ve|'m|'ll|'d| ?\\p{L}+| ?\\p{N}+| ?[^\\s\\p{L}\\p{N}]+|\\s+(?!\\S)|\\s+ 를 손으로 편 것."""
    글자 = lambda ch: unicodedata.category(ch)[0] == "L"
    숫자 = lambda ch: unicodedata.category(ch)[0] == "N"
    기타 = lambda ch: not ch.isspace() and not 글자(ch) and not 숫자(ch)
    out, i, n = [], 0, len(text)
    while i < n:
        for c in ("'s", "'t", "'re", "'ve", "'m", "'ll", "'d"):
            if text.startswith(c, i):
                out.append(c)
                i += len(c)
                break
        else:
            j = i + 1 if text[i] == " " and i + 1 < n else i
            for pred in (글자, 숫자, 기타):
                if pred(text[j]):
                    k = j
                    while k < n and pred(text[k]):
                        k += 1
                    out.append(text[i:k])
                    i = k
                    break
            else:
                k = i
                while k < n and text[k].isspace():
                    k += 1
                if k < n and k - i > 1:
                    k -= 1
                out.append(text[i:k])
                i = k
    return out


class 토크나이저:
    def __init__(self, model_dir):
        self.낱말 = json.load(open(os.path.join(model_dir, "vocab.json"), encoding="utf-8"))
        self.거꾸로 = {v: k for k, v in self.낱말.items()}
        lines = open(os.path.join(model_dir, "merges.txt"), encoding="utf-8").read().split("\n")
        self.순위 = {tuple(l.split()): i for i, l in enumerate(x for x in lines[1:] if x)}
        self.바이트 = _바이트글자()
        self.바이트거꾸로 = {c: b for b, c in self.바이트.items()}

    def _bpe(self, word):
        parts = list(word)
        while len(parts) > 1:
            best = min(((self.순위.get((a, b), 1 << 30), i) for i, (a, b) in enumerate(zip(parts, parts[1:]))))
            if best[0] == 1 << 30:
                break
            i = best[1]
            a, b = parts[i], parts[i + 1]
            merged, k = [], 0
            while k < len(parts):
                if k + 1 < len(parts) and parts[k] == a and parts[k + 1] == b:
                    merged.append(a + b)
                    k += 2
                else:
                    merged.append(parts[k])
                    k += 1
            parts = merged
        return parts

    def 나누기(self, text):
        ids = []
        for piece in _앞자르기(text):
            word = "".join(self.바이트[b] for b in piece.encode("utf-8"))
            ids += [self.낱말[t] for t in self._bpe(word)]
        return ids

    def 잇기(self, ids):
        return bytes(self.바이트거꾸로[c] for i in ids for c in self.거꾸로[i]).decode("utf-8", errors="replace")


# ── 드라이버 (nvcuda.dll) ─────────────────────────────────────────────────────────────────────

class 드라이버:
    def __init__(self):
        cu = ctypes.WinDLL("nvcuda.dll")
        cu.cuMemAlloc_v2.argtypes = [ctypes.POINTER(c_u64), ctypes.c_size_t]
        cu.cuMemcpyHtoD_v2.argtypes = [c_u64, ctypes.c_void_p, ctypes.c_size_t]
        cu.cuMemcpyDtoH_v2.argtypes = [ctypes.c_void_p, c_u64, ctypes.c_size_t]
        cu.cuMemsetD8_v2.argtypes = [c_u64, ctypes.c_ubyte, ctypes.c_size_t]
        cu.cuLaunchKernel.argtypes = [ctypes.c_void_p] + [c_uint] * 7 + [ctypes.c_void_p] * 3
        cu.cuModuleGetGlobal_v2.argtypes = [ctypes.POINTER(c_u64), ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p,
                                            ctypes.c_char_p]
        cu.cuMemFree_v2.argtypes = [c_u64]
        cu.cuModuleUnload.argtypes = [ctypes.c_void_p]
        self.cu = cu
        self.할당들, self.모듈들 = [], []
        ctx = ctypes.c_void_p()
        self.확인(cu.cuInit(0))
        self.확인(cu.cuDevicePrimaryCtxRetain(ctypes.byref(ctx), 0))
        self.확인(cu.cuCtxSetCurrent(ctx))

    @staticmethod
    def 확인(r):
        if r != 0:
            raise RuntimeError(f"CUDA 드라이버 오류 {r}")

    def 모듈(self, ptx):
        mod = ctypes.c_void_p()
        self.확인(self.cu.cuModuleLoadData(ctypes.byref(mod), ptx + b"\0"))
        self.모듈들.append(mod)
        return mod

    def 함수(self, mod, name):
        fn = ctypes.c_void_p()
        self.확인(self.cu.cuModuleGetFunction(ctypes.byref(fn), mod, ("_G" + name.encode("utf-8").hex()).encode()))
        return fn

    def 할당(self, nbytes):
        p = c_u64()
        self.확인(self.cu.cuMemAlloc_v2(ctypes.byref(p), nbytes))
        self.확인(self.cu.cuMemsetD8_v2(p.value, 0, nbytes))
        self.할당들.append(p.value)
        return p.value

    def 놓기(self):
        """이 드라이버로 잡은 메모리와 모듈을 돌려준다(한 실행에서 모델을 여럿 만들 때)."""
        self.맞추기()
        for p in self.할당들:
            self.확인(self.cu.cuMemFree_v2(c_u64(p)))
        for m in self.모듈들:
            self.확인(self.cu.cuModuleUnload(m))
        self.할당들, self.모듈들 = [], []

    def 올리기(self, dptr, arr):
        arr = np.ascontiguousarray(arr)
        self.확인(self.cu.cuMemcpyHtoD_v2(dptr, arr.ctypes.data, arr.nbytes))

    def 내리기(self, dptr, arr):
        self.확인(self.cu.cuMemcpyDtoH_v2(arr.ctypes.data, dptr, arr.nbytes))
        return arr

    def 맞추기(self):
        self.확인(self.cu.cuCtxSynchronize())


class _노드인자(ctypes.Structure):
    """CUDA_KERNEL_NODE_PARAMS — 그래프의 커널 마디 하나."""
    _fields_ = [("func", ctypes.c_void_p), ("gx", c_uint), ("gy", c_uint), ("gz", c_uint),
                ("bx", c_uint), ("by", c_uint), ("bz", c_uint), ("smem", c_uint),
                ("params", ctypes.c_void_p), ("extra", ctypes.c_void_p)]


class _띄움:
    """커널 하나의 실행 — 매개변수는 ctypes 칸이라 값만 바꿔 다시 띄울 수 있다. 참조 매개변수(c_uint64)는 16 바이트 정렬이어야
    한다(글ptx.py 의 전역 묶어 읽기가 기대는 약속) — 만들 때 확인한다."""

    def __init__(self, fn, grid, block, params):
        for p in params:
            if isinstance(p, ctypes.c_uint64) and p.value % 16:
                raise ValueError(f"커널의 참조 매개변수가 16 바이트 정렬이 아니다: {p.value:#x}")
        self.fn, self.grid, self.block, self.params = fn, grid, block, params
        self.args = (ctypes.c_void_p * len(params))(*[ctypes.cast(ctypes.byref(p), ctypes.c_void_p) for p in params])


# ── 모델 ─────────────────────────────────────────────────────────────────────────────────────

# 선형 커널의 판 — 판마다 블록이 맡는 칸의 수와 옮기는 방법만 다르고 더하는 순서는 같다(커널생성.py 의 약속). 그래서 행 수에 따라
# 빠른 판을 골라도 칸마다 비트가 같다. 행 하나: 줄선형1, 넷까지: 줄선형4, 그 위: 타일 판 셋 중 처음 한 번 재서 가장 빠른 것.
#   타일선형넷 — 열수가 64 의 배수(가중치를 16 바이트씩 옮긴다), 작은타일선형 — 열수가 32 의 배수, 타일선형 — 어느 열수든.
# 5단계 양자 판(가중치가 5단계/gguf읽기.py 의 양자가중 — GGUF 의 F16 · Q8_0 · Q4_0 을 블록 평면 배치로 깐 것): 모듈 커널반F16.gl ·
# 커널반Q8.gl · 커널반Q4.gl (반실수 KV 만). 타일 판은 둘(타일선형 · 작은타일선형 — 어느 열수든), 로짓은 낱말표의 형식으로 따로 만든
# 판(로짓줄선형1 · 로짓줄선형4 · 로짓타일선형 · 로짓작은타일선형), 임베딩도 그 모듈의 것. 값과 순서는 같은 가중치를 미리 풀어
# 짧은실수로 둔 판(커널반.gl)과 같다 — 그래서 로짓이 비트까지 같다(5a).
양자모듈 = {("F16", "F16"): "커널반F16.gl", ("Q8_0", "Q8_0"): "커널반Q8.gl", ("Q4_0", "Q8_0"): "커널반Q4.gl"}
# 6단계 정수 블록 계약(가중치가 gguf읽기.gpt2정수 — 배치 "정수"): 모듈 커널반Q8정수.gl · 커널반Q4정수.gl. 선형 층마다 활성값을
# 네 자리로 바꾸는 커널(정수로)을 먼저 띄우고, 정수 텐서 코어 행렬곱(정수타일선형 — 행 수와 상관없이 하나)을 띄운다.
정수모듈 = {("Q8_0", "Q8_0"): "커널반Q8정수.gl", ("Q4_0", "Q8_0"): "커널반Q4정수.gl"}
# 8단계 — 자리 둘 계약(활성값 ±2¹⁴): 같은 가중치 배치, 자릿값이 둘. `글GPT2(…, 자리수=2)`
두자리모듈 = {("Q8_0", "Q8_0"): "커널반Q8둘자리.gl", ("Q4_0", "Q8_0"): "커널반Q4둘자리.gl"}
# 9단계 — 정수 KV 계약(자리 둘 + KV 캐시도 자리 둘 블록 정수 + 정수 텐서 코어 어텐션 + 적힌지수). `글GPT2(…, KV형식="정수", 자리수=2)`
정수KV모듈 = {("Q8_0", "Q8_0"): "커널Q8정수KV.gl", ("Q4_0", "Q8_0"): "커널Q4정수KV.gl"}
# 7단계 — GPT-2 XL(너비 1600, 머리 25, 층 48): 커널생성.py 가 크기만 바꿔 만든 모듈(순서 약속은 같다). 짧은실수 판은 짧은실수 KV.
XL모듈 = {("짧은실수", "짧은실수", "짧은실수"): "커널XL.gl", ("F16", "F16", "반실수"): "커널XL반F16.gl",
         ("Q8_0", "Q8_0", "정수"): "커널XL반Q8정수.gl", ("Q4_0", "Q8_0", "정수"): "커널XL반Q4정수.gl",
         ("Q8_0", "Q8_0", "둘자리"): "커널XL반Q8둘자리.gl", ("Q4_0", "Q8_0", "둘자리"): "커널XL반Q4둘자리.gl",
         ("Q8_0", "Q8_0", "정수KV"): "커널XLQ8정수KV.gl", ("Q4_0", "Q8_0", "정수KV"): "커널XLQ4정수KV.gl"}
바이트수 = {"짧은실수": lambda K, N: 4 * K * N, "F16": lambda K, N: 2 * K * N,
          "Q8_0": lambda K, N: K * N + K * N // 16, "Q4_0": lambda K, N: K * N // 2 + K * N // 16}


def 형식(x):
    """가중치의 형식 — 양자가중이면 그 형식, 아니면(numpy 배열) "짧은실수"."""
    return getattr(x, "형식", "짧은실수")


def _가중인자(x):
    """가중치 자리의 커널 매개변수 — 짧은실수: 정수 주소 하나, 양자: (값, 척도) 또는 (값,)(F16)."""
    return [c_u64(v) for v in x] if isinstance(x, tuple) else [c_u64(x)]


def _바탕(x):
    return x[0] if isinstance(x, tuple) else x


class 글GPT2:
    def __init__(self, weights, 최대행=1024, 최대문장=3, 최대길이=NCTX, 로짓행=1024, 프롬메가=False, KV형식="짧은실수", 자리수=4):
        """KV형식: KV 캐시의 원소 — "짧은실수"(커널.gl) 또는 "반실수"(커널반.gl, 4단계 2 — 밝힌 정밀도: 쓸 때 `으로 반실수` 로
        반올림 한 번, 읽을 때 정확히 넓힌다). 다른 커널과 순서 약속은 같다. 자리수: 정수 블록 계약의 활성값 자리(4 — 6단계, 2 — 8단계).
        KV형식 "정수"(9단계): KV 캐시를 자리 둘 블록 정수로 두고 어텐션을 정수 텐서 코어 · dp4a 로(정수 KV 계약, 적힌지수) — 자리수 2 의 정수 판만."""
        assert 자리수 in (2, 4)
        self.자리수 = 자리수
        assert KV형식 in ("짧은실수", "반실수", "정수")
        assert not (프롬메가 and KV형식 == "정수")
        assert not (프롬메가 and KV형식 == "반실수"), "프롬프트 메가커널(3l)은 짧은실수 KV 판만 있다"
        # 모형의 크기 — 가중치에서(7단계: GPT-2 small · XL). 머리 하나는 64 칸.
        self.D, self.NCTX = weights["wpe.weight"].shape[1], weights["wpe.weight"].shape[0]
        self.NL = sum(1 for k in weights if k.startswith("h.") and k.endswith(".ln_1.weight"))
        self.NH = self.D // 64
        wte0 = weights["wte.weight"]
        self.V = wte0.shape[0] if isinstance(wte0, np.ndarray) else wte0.N
        D, NH, NL, V = self.D, self.NH, self.NL, self.V
        assert (D, NH, NL) in ((768, 12, 12), (1600, 25, 48)), f"모듈이 없는 크기: 너비 {D}, 층 {NL}"
        self.크기 = "small" if D == 768 else "XL"
        assert not (프롬메가 and self.크기 != "small"), "프롬프트 메가커널은 GPT-2 small 만"
        self.KV형식 = KV형식
        self.층형식, self.낱말형식 = 형식(weights["h.0.attn.c_attn.weight"]), 형식(weights["wte.weight"])
        self.양자 = (self.층형식, self.낱말형식) != ("짧은실수", "짧은실수")
        self.정수 = self.양자 and getattr(weights["h.0.attn.c_attn.weight"], "배치", "가닥") == "정수"
        if self.양자:
            assert KV형식 in ("반실수", "정수"), "양자 판(5단계 · 6단계)은 반실수 KV 판(또는 9단계의 정수 KV 판)만 있다"
            assert (self.층형식, self.낱말형식) in (정수모듈 if self.정수 else 양자모듈), f"모듈이 없는 형식: {(self.층형식, self.낱말형식)}"
        assert 자리수 == 4 or self.정수, "자리 둘은 정수 계약 판(gguf읽기.gpt2정수)에서만"
        self.정수KV = KV형식 == "정수"
        assert not self.정수KV or (self.정수 and 자리수 == 2), "정수 KV 판은 자리 둘의 정수 계약 판에서만"
        self.dr = dr = 드라이버()

        def build(gl):
            ptx = os.path.join(ROOT, "build", os.path.splitext(gl)[0] + ".ptx")
            subprocess.run([sys.executable, os.path.join(ROOT, "research", "gpu", "글ptx.py"), os.path.join(HERE, gl),
                            "-o", ptx], check=True, capture_output=True)
            return dr.모듈(open(ptx, "rb").read())
        if self.크기 == "small":
            모듈 = (정수KV모듈[(self.층형식, self.낱말형식)] if self.정수KV else
                   ((두자리모듈 if 자리수 == 2 else 정수모듈) if self.정수 else 양자모듈)[(self.층형식, self.낱말형식)] if self.양자 else
                   ("커널.gl" if KV형식 == "짧은실수" else "커널반.gl"))
        else:
            열쇠 = (self.층형식, self.낱말형식, "정수KV" if self.정수KV else ("둘자리" if 자리수 == 2 else "정수") if self.정수 else KV형식)
            assert 열쇠 in XL모듈, f"XL 모듈이 없는 판: {열쇠}"
            모듈 = XL모듈[열쇠]
        self.mods = [build("gpt2.gl" if self.크기 == "small" else "gpt2XL.gl"), build(모듈)]
        self.k = {n: dr.함수(self.mods[0], n) for n in ("임베딩", "층정규화", "줄층정규화", "가장큰번호")}
        self.k.update({n: dr.함수(self.mods[1], n) for n in (("KV정수로", "정수어텐션", "정수어텐션둘", "정수조각어텐션", "정수조각접기") if self.정수KV else
                                                           ("흐름어텐션", "조각어텐션", "조각접기"))})
        if self.양자:
            self.k["임베딩"] = dr.함수(self.mods[1], "임베딩")
        if self.정수:
            self.k["정수로"] = dr.함수(self.mods[1], "정수로")
            self.k["층정규화정수"] = dr.함수(self.mods[1], "층정규화정수")
            if self.정수KV:                      # 11단계: 블록 판(블록 하나가 한 행 — 같은 비트), 행 수마다 재서 고른다
                self.k["층정규화정수줄"] = dr.함수(self.mods[1], "층정규화정수줄")
            if not self.정수KV:
                self.k["흐름어텐션정수"] = dr.함수(self.mods[1], "흐름어텐션정수")
            판표 = 정수판표(자리수, self.정수KV)
            self.선형 = {(판, epi): dr.함수(self.mods[1], f"{판}{epi}") for 판 in (*판표, "정수줄선형")
                       for epi in (("", "_잔차", "_겔루") if self.정수KV else ("", "_잔차", "_겔루", "_KV"))}
            self.선형.update({(판, epi): dr.함수(self.mods[1], f"{판}{epi}") for 판 in 판표 if 판표[판][3] >= 4
                            for epi in (("_겔루정수", "_KV정수") if self.정수KV else ("_겔루정수",))})
            self.로짓선형 = {판: dr.함수(self.mods[1], f"로짓{판}") for 판 in (*판표, "정수줄선형")}
        else:
            판들 = ("줄선형1", "깊은줄선형1", "줄선형4", "타일선형", "작은타일선형") + (() if self.양자 else ("타일선형넷",))
            self.선형 = {(판, epi): dr.함수(self.mods[1], f"{판}{epi}") for 판 in 판들 for epi in ("", "_잔차", "_겔루", "_KV")}
            self.로짓선형 = ({판: dr.함수(self.mods[1], f"로짓{판}") for 판 in ("줄선형1", "줄선형4", "타일선형", "작은타일선형")}
                         if self.양자 else {판: self.선형[(판, "")] for 판 in 판들})
        assert 최대길이 % 64 == 0 and 최대길이 <= (131072 if self.정수KV else 16384), \
            "최대길이는 64 의 배수, 16384 까지 (어텐션의 키 조각 — 접기는 조각 256 개까지; 정수 KV 판은 131072 까지)"
        self.최대행, self.최대문장, self.최대길이 = 최대행, 최대문장, 최대길이

        def up(a):
            p = dr.할당(a.nbytes)
            dr.올리기(p, a)
            return p

        def 양자올림(q):
            """양자가중 하나를 [값][척도] 로 올린다 — (값 주소, 척도 주소) 또는 (값 주소,)(F16)."""
            p = up(q.바이트())
            return (p, p + q.값.nbytes) if q.척.nbytes else (p,)
        w = weights
        self.wpe = up(w["wpe.weight"])
        if self.낱말형식 == "짧은실수":
            self.wte = up(w["wte.weight"])
            self.wteT = up(np.ascontiguousarray(w["wte.weight"].T))      # 로짓 = x · wteᵀ (가중치 묶음 — 같은 표)
        else:                                      # 양자 판: 임베딩과 로짓이 같은 표(블록 평면 배치 — 열 = 토큰, k = 768)를 읽는다
            self.wte = self.wteT = 양자올림(w["wte.weight"])
        self.영치우침 = up(np.zeros(V, np.float32))
        # 층마다의 가중치는 종류별로 12 층을 이어 붙여 올린다(생성 메가커널이 층 번호로 자리를 계산한다). 따로 도는 커널은 그 안의
        # 자리를 가리킨다. 양자 가중치는 층마다 [값][척도] 를 잇는다(메가커널의 층 걸음 = 그 바이트 수).
        이름들 = ("ln_1.weight", "ln_1.bias", "attn.c_attn.weight", "attn.c_attn.bias", "attn.c_proj.weight", "attn.c_proj.bias",
                 "ln_2.weight", "ln_2.bias", "mlp.c_fc.weight", "mlp.c_fc.bias", "mlp.c_proj.weight", "mlp.c_proj.bias")
        self.묶음 = {}
        self.층 = [{} for _ in range(NL)]
        for 이름 in 이름들:
            x0 = w[f"h.0.{이름}"]
            한층 = x0.nbytes
            if 형식(x0) == "짧은실수":
                바탕 = up(np.concatenate([np.ascontiguousarray(w[f"h.{l}.{이름}"]).reshape(-1) for l in range(NL)]))
                self.묶음[이름] = 바탕
                for l in range(NL):
                    self.층[l][이름] = 바탕 + l * 한층
            else:
                assert all(w[f"h.{l}.{이름}"].nbytes == 한층 and 형식(w[f"h.{l}.{이름}"]) == self.층형식 for l in range(NL))
                바탕 = up(np.concatenate([w[f"h.{l}.{이름}"].바이트() for l in range(NL)]))
                vb = x0.값.nbytes
                둘 = (lambda a: (a, a + vb)) if x0.척.nbytes else (lambda a: (a,))
                self.묶음[이름] = 둘(바탕)
                for l in range(NL):
                    self.층[l][이름] = 둘(바탕 + l * 한층)
        self.lnf_g, self.lnf_b = up(w["ln_f.weight"]), up(w["ln_f.bias"])
        M = 최대행
        if self.정수:                                # 활성값의 네 자리 [4][행][깊이] 바이트와 블록 마법수 [행][블록][4] — 깊이는 4D 까지
            self.자릿값, self.정보 = dr.할당(자리수 * M * 4 * D), dr.할당(M * (4 * D // 32) * 16)
            # c_fc 의 끝손질(_겔루정수)이 mlp c_proj 의 자리를 바로 쓰는 칸 — c_fc 가 읽는 칸과 따로
            self.자릿값2, self.정보2 = dr.할당(자리수 * M * 4 * D), dr.할당(M * (4 * D // 32) * 16)
        self.h, self.x = dr.할당(M * D * 4), dr.할당(M * D * 4)
        self.q, self.att = dr.할당(max(M, 12) * D * 4), dr.할당(M * D * 4)     # 정수 KV 판의 줄 길은 q 에 행 넷의 q · k · v(짧은실수)
        self.fc = dr.할당(M * 4 * D * 4)
        # 모든 행의 로짓("전부")은 로짓행 행까지만 — 긴 문맥에서는 문장마다 마지막 행만 쓴다
        self.로짓행 = max(min(로짓행, M), 최대문장)
        self.logits = dr.할당(self.로짓행 * V * 4)
        self.시험칸 = dr.할당(max(M * 4 * D, self.로짓행 * V) * 4)     # 판 고르기의 출력 (진짜 버퍼를 건드리지 않게)
        # 생성의 어텐션: 키 조각마다의 (m, l, o[64]) — [행][머리][조각][68] (메가커널은 행 하나)
        self.조각칸 = dr.할당(최대문장 * NH * (최대길이 // 64) * 68 * 4)
        kv = 최대문장 * 최대길이 * D * (4 if KV형식 == "짧은실수" else 2)      # 층 하나의 키(또는 값) 칸 — 바이트
        self.kc바탕, self.vc바탕 = dr.할당(NL * kv), dr.할당(NL * kv)
        # 프롬프트 처리의 어텐션은 키 조각을 통째로 읽고 가린 자리는 쓰지 않는다 — 아직 안 쓴 칸도 유한한 값이게 0 으로
        dr.확인(dr.cu.cuMemsetD8_v2(c_u64(self.kc바탕), 0, ctypes.c_size_t(NL * kv)))
        dr.확인(dr.cu.cuMemsetD8_v2(c_u64(self.vc바탕), 0, ctypes.c_size_t(NL * kv)))
        self.kc = [self.kc바탕 + l * kv for l in range(NL)]
        self.vc = [self.vc바탕 + l * kv for l in range(NL)]
        if self.정수KV:                              # 9단계: 키 · 값의 블록 지수(E + 114, 바이트) [문장·머리][위치][2], q 의 자리 둘 · 정보(활성값 배치)
            ek = 최대문장 * NH * 최대길이 * 2
            self.ke바탕, self.ve바탕 = dr.할당(NL * ek), dr.할당(NL * ek)
            dr.확인(dr.cu.cuMemsetD8_v2(c_u64(self.ke바탕), 0, ctypes.c_size_t(NL * ek)))
            dr.확인(dr.cu.cuMemsetD8_v2(c_u64(self.ve바탕), 0, ctypes.c_size_t(NL * ek)))
            self.ke = [self.ke바탕 + l * ek for l in range(NL)]
            self.ve = [self.ve바탕 + l * ek for l in range(NL)]
            정보폭 = (M + 63) // 64 * 64
            self.자릿값q, self.정보q = dr.할당(2 * M * D), dr.할당(D // 32 * 정보폭 * 4)
            # 판 고르기의 시험용 캐시(문장 하나 몫 — 진짜 캐시를 건드리지 않게)
            self.시험KV = [dr.할당(n) for n in (2 * M * D, D // 32 * 정보폭 * 4, 최대길이 * D * 2, 최대길이 * D * 2, NH * 최대길이 * 2, NH * 최대길이 * 2)]
        self.부분값, self.부분번호, self.장벽 = dr.할당(4096), dr.할당(8192), dr.할당(256)
        self.주의셈 = self.장벽 + 64               # 메가커널의 어텐션: 머리마다 도착한 블록 수 (장벽과 함께 0 으로)
        self.메가 = dr.함수(self.mods[1], "생성메가")
        # 프롬프트 메가커널: 장벽 [16] · 일셈 [16] · 끝셈 [층 12][단계 8][행 묶음] (정수) — 띄우기 전에 0 으로(참조는 16 바이트 정렬)
        self.프롬 = dr.함수(build("커널프롬.gl"), "프롬메가") if 프롬메가 else None     # 3l 의 시도 — 따로 도는 커널보다 느려 기본은 끔
        self.묶음최대 = (최대행 + 63) // 64
        self.프롬셈크기 = 32 + 12 * 8 * self.묶음최대 * 8
        self.프롬셈 = dr.할당(self.프롬셈크기)
        self.블록일 = dr.할당(8 * 256)
        self.프롬메가쓰기 = 프롬메가              # 문장 하나의 프롬프트를 메가커널로(값은 따로 도는 커널들과 같다)
        self.프롬시각칸, self.프롬시각재기 = dr.할당(8 * 4 * (8 + 12 * 600) * self.묶음최대), 0     # 재기용: 일마다 [가져옴, 기다림 끝, 끝남, 블록]
        self.메가블록 = 120                      # 커널생성.py 의 생성메가(G) 와 같아야 한다 (SM 60 개 × 2)
        dr.cu.cuLaunchCooperativeKernel.argtypes = [ctypes.c_void_p] + [ctypes.c_uint] * 7 + [ctypes.c_void_p] * 2
        self.로짓기록칸 = None
        self.시각칸, self.시각재기 = dr.할당(8 * 70 * 1100), 0          # 재기용: 0 이 아니면 블록 (값 − 1) 이 장벽마다 GPU 시각을 남긴다
        self.토큰칸 = dr.할당(M * 8)            # 이번에 넣을 토큰
        self.생성칸 = dr.할당(4096 * 8)         # 가장큰번호가 쓰는 자리 (생성할 때)
        self._계획 = {}
        # 6단계: 행이 다섯 이상인 계산(프롬프트)은 커널들을 CUDA 그래프 하나로 띄운다 — 같은 커널을 같은 차례로(값은 그대로),
        # 커널 사이의 빈틈만 준다. 그래프는 매개변수의 값을 만들 때 베껴 두므로 (계획, 위치시작, 토큰자리, 출력자리)마다 하나
        # — (그 계획의 띄움 목록, 실행본).
        self._그래프 = {}
        self.그래프쓰기 = True
        self._고른판 = {}
        self.미리읽기 = True                    # 줄 판이 끝에서 다음 줄 판의 가중치를 L2 로 미리 읽는다(값과는 상관없다)
        self.묶어바꾸기 = True                  # 6단계: 네 자리 바꾸기를 앞 커널에 묶는다(값과는 상관없다 — 끄는 것은 대조 시험만)
        cu = dr.cu
        cu.cuEventCreate.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint]
        cu.cuEventRecord.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        cu.cuEventSynchronize.argtypes = [ctypes.c_void_p]
        cu.cuEventElapsedTime.argtypes = [ctypes.POINTER(ctypes.c_float), ctypes.c_void_p, ctypes.c_void_p]

    def 닫기(self):
        """GPU 메모리와 모듈을 돌려준다 — 그 뒤로는 쓰지 않는다."""
        self.dr.맞추기()
        for _, ex in self._그래프.values():
            self.dr.확인(self.dr.cu.cuGraphExecDestroy(ex))
        self._그래프 = {}
        self.dr.놓기()

    def _그래프만들기(self, L):
        """띄움들을 차례로 잇는 CUDA 그래프(마디마다 앞 마디 하나에 기댄다) — 실행본을 돌려준다."""
        cu = self.dr.cu
        g = ctypes.c_void_p()
        self.dr.확인(cu.cuGraphCreate(ctypes.byref(g), 0))
        앞 = None
        for x in L:
            p = _노드인자(x.fn, x.grid[0], x.grid[1], 1, x.block[0], x.block[1], 1, 0, ctypes.cast(x.args, ctypes.c_void_p), None)
            마디 = ctypes.c_void_p()
            기댐 = (ctypes.c_void_p * 1)(앞) if 앞 is not None else None
            self.dr.확인(cu.cuGraphAddKernelNode(ctypes.byref(마디), g, 기댐, 1 if 앞 is not None else 0, ctypes.byref(p)))
            앞 = 마디
        ex = ctypes.c_void_p()
        self.dr.확인(cu.cuGraphInstantiateWithFlags(ctypes.byref(ex), g, ctypes.c_ulonglong(0)))
        self.dr.확인(cu.cuGraphDestroy(g))
        return ex

    def 오류칸(self):
        """두 모듈의 오류 칸(2c 범위 검사)을 OR 한 값 — 0 이어야 한다."""
        err = 0
        for mod in self.mods:
            p, n = c_u64(), ctypes.c_size_t()
            self.dr.확인(self.dr.cu.cuModuleGetGlobal_v2(ctypes.byref(p), ctypes.byref(n), mod, b"__geul_err"))
            err |= int(self.dr.내리기(p.value, np.zeros(1, np.uint32))[0])
        return err

    @staticmethod
    def _격자(판, rows, N, K=None, 작음=True):
        if 판 in 정수판들KV:
            BM, BN, T = 정수판모양(판)
            return ((rows + BM - 1) // BM, (N + BN - 1) // BN), (T, 1)
        if 판 == "정수줄선형":                 # 열 묶음 w (커널과 같은 규칙 — 커널생성.정수열묶음; XL 은 깊이 K 로)
            w = 정수열묶음(K, N, 작음)
            return ((N + w - 1) // w, 1), (256, 1)
        if 판 in ("줄선형1", "깊은줄선형1", "줄선형4"):
            return ((N + 31) // 32, 1), (128, 1)
        if 판 == "작은타일선형":
            return ((rows + 31) // 32, (N + 31) // 32), (256, 1)
        return ((rows + 63) // 64, (N + 63) // 64), (256, 1)

    def _판(self, src, wt, b, rows, K, N, 로짓=False, epi=""):
        """행 수에 맞는 선형 판. 타일 판은 (행, 깊이, 열) 마다 처음 한 번 재서 가장 빠른 것 — 비트는 어느 판이든 같다.
        재는 동안에는 끝손질 없는 판으로 시험칸에만 쓴다(캐시·잔차를 건드리지 않게). 로짓 = 참: 낱말표의 판(양자 판은 따로 만든 것)."""
        if self.정수:                        # 6단계: 행 넷까지는 dp4a 줄 판, 그 위는 정수 텐서 코어 판 둘 중 재서 빠른 것 — 같은 계약(비트가 같다)
            if rows <= 4:
                return "정수줄선형"
            key = (rows, K, N, 로짓, epi)
            if key not in self._고른판:
                self._고른판[key] = self._정수판재기(rows, K, N, 로짓, epi)
            return self._고른판[key]
        if rows == 1:                        # 열이 적으면 사슬이 적다 — 사슬마다 48 개씩 미리 읽는 판(재서 정함)
            return "깊은줄선형1" if N <= 1024 and not 로짓 else "줄선형1"
        if rows <= 4:
            return "줄선형4"
        key = (rows, K, N, 로짓)
        if key not in self._고른판:
            if self.양자:                    # 양자 판의 타일 판은 둘 다 어느 열수든 받는다
                후보 = ["타일선형", "작은타일선형"]
            else:
                후보 = ["타일선형"] + (["타일선형넷"] if N % 64 == 0 else []) + (["작은타일선형"] if N % 32 == 0 else [])
            cu, best = self.dr.cu, None
            for 판 in 후보:
                ps = [c_u64(src)] + _가중인자(wt) + [c_u64(b), c_u64(self.시험칸), c_i64(rows), c_i64(K), c_i64(N)]
                x = _띄움(self.로짓선형[판] if 로짓 else self.선형[(판, "")], *self._격자(판, rows, N), ps)
                run = lambda: cu.cuLaunchKernel(x.fn, x.grid[0], x.grid[1], 1, x.block[0], x.block[1], 1, 0, None, x.args, None)
                run()
                ts = []
                for _ in range(5):
                    e0, e1 = ctypes.c_void_p(), ctypes.c_void_p()
                    cu.cuEventCreate(ctypes.byref(e0), 0)
                    cu.cuEventCreate(ctypes.byref(e1), 0)
                    cu.cuEventRecord(e0, None)
                    run()
                    cu.cuEventRecord(e1, None)
                    cu.cuEventSynchronize(e1)
                    ms = ctypes.c_float()
                    cu.cuEventElapsedTime(ctypes.byref(ms), e0, e1)
                    ts.append(ms.value)
                    cu.cuEventDestroy_v2(e0)
                    cu.cuEventDestroy_v2(e1)
                t = sorted(ts)[2]
                if best is None or t < best[0]:
                    best = (t, 판)
            self._고른판[key] = best[1]
        return self._고른판[key]

    def _정수판재기(self, rows, K, N, 로짓, epi=""):
        """정수 텐서 코어 판들(커널생성.정수판들 — 칸을 나누는 모양만 다르다)을 재서 빠른 것 — 비트는 같다(계약). 끝손질까지 같은
        판(epi)을 재되 출력 · 잔차 · KV 칸은 모두 시험칸에 쓴다(진짜 버퍼를 건드리지 않는다). 활성값은 x(또는 fc)를 바꾼 것.
        클럭이 오르도록 후보를 번갈아 20 ms 넘게 띄운 뒤, 후보마다 세 번씩 번갈아 재서 중앙값이 가장 작은 것."""
        import time
        cu, 시 = self.dr.cu, self.시험칸
        x = _띄움(self.k["정수로"], ((K // 32 + 31) // 32, rows), (256, 1),
                  [c_u64(self.x if K == self.D else self.fc), c_u64(self.자릿값), c_u64(self.정보), c_i64(rows), c_i64(K)])
        cu.cuLaunchKernel(x.fn, x.grid[0], x.grid[1], 1, x.block[0], x.block[1], 1, 0, None, x.args, None)
        wt = self.wteT if 로짓 else self.층[0][{(self.D, 3 * self.D): "attn.c_attn.weight", (self.D, self.D): "attn.c_proj.weight",
                                            (self.D, 4 * self.D): "mlp.c_fc.weight", (4 * self.D, self.D): "mlp.c_proj.weight"}[(K, N)]]
        kv = 시 + 4 * self.D * self.최대행                         # 시험칸의 q 출력 뒤에 키 · 값 (층 하나, 문장 하나 몫씩)
        extra = {"_잔차": [시], "_KV": [kv, kv + 2 * self.D * self.최대길이], "_겔루정수": [kv],
                 "_KV정수": getattr(self, "시험KV", [])}.get(epi, [])
        def 띄움(판, 격자, 행시작=0, 열시작=0):
            fn = self.로짓선형[판] if 로짓 else self.선형[(판, epi)]
            ps = [c_u64(self.자릿값), c_u64(self.정보)] + _가중인자(wt) + [c_u64(self.영치우침)] + [c_u64(v) for v in extra] + \
                 ([] if epi == "_KV정수" else [c_u64(시)]) + [c_i64(rows), c_i64(K), c_i64(N), c_i64((N + 63) // 64 * 64)] + \
                 ([c_i64(rows), c_i64(0), c_i64(self.최대길이)] if epi in ("_KV", "_KV정수") else []) + \
                 ([c_i64(행시작), c_i64(열시작)] if self.정수KV else [])
            y = _띄움(fn, 격자, (정수판모양(판)[2], 1), ps)
            return lambda y=y: cu.cuLaunchKernel(y.fn, y.grid[0], y.grid[1], 1, y.block[0], y.block[1], 1, 0, None, y.args, None)

        def 재기(runs):
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < 0.02:
                for run in runs.values():
                    run()
                self.dr.맞추기()
            ts = {판: [] for 판 in runs}
            e0, e1 = ctypes.c_void_p(), ctypes.c_void_p()
            cu.cuEventCreate(ctypes.byref(e0), 0)
            cu.cuEventCreate(ctypes.byref(e1), 0)
            for _ in range(3):
                for 판, run in runs.items():
                    cu.cuEventRecord(e0, None)
                    for _ in range(3):
                        run()
                    cu.cuEventRecord(e1, None)
                    cu.cuEventSynchronize(e1)
                    ms = ctypes.c_float()
                    cu.cuEventElapsedTime(ctypes.byref(ms), e0, e1)
                    ts[판].append(ms.value)
            cu.cuEventDestroy_v2(e0)
            cu.cuEventDestroy_v2(e1)
            return {판: sorted(v)[1] for 판, v in ts.items()}

        판들 = [판 for 판 in 정수판표(self.자리수, self.정수KV) if 로짓 or (판, epi) in self.선형]   # _겔루정수 는 열 조각 넷 이상인 판만
        runs = {판: 띄움(판, self._격자(판, rows, N)[0]) for 판 in 판들}
        ts = 재기(runs)
        best = min(ts, key=ts.get)
        if not self.정수KV:
            return best
        # 11단계(정수 KV 판): 꼬리 자르기 — 큰 판이 꽉 찬 바퀴만큼 열의 앞쪽을 맡고 남은 열을 작은 판이 따로(실행 둘, 차례대로). 칸마다의
        # 계산(k 의 차례)은 그대로라 비트가 같다. 빠른 큰 판 둘 × 칸이 반 이하인 작은 판을 재서, 나누지 않은 가장 빠른 판과 견준다.
        nsm = ctypes.c_int()
        self.dr.확인(cu.cuDeviceGetAttribute(ctypes.byref(nsm), 16, 0))
        후보 = {}
        for 큰 in sorted(ts, key=ts.get)[:2]:
            BM, BN, T = 정수판모양(큰)
            gx, gy = (rows + BM - 1) // BM, (N + BN - 1) // BN
            점유 = ctypes.c_int()
            fn = self.로짓선형[큰] if 로짓 else self.선형[(큰, epi)]
            self.dr.확인(cu.cuOccupancyMaxActiveBlocksPerMultiprocessor(ctypes.byref(점유), fn, T, ctypes.c_size_t(0)))
            자리 = nsm.value * 점유.value
            if 자리 <= 0 or gx * gy <= 자리 or (gx * gy) % 자리 == 0:
                continue
            ny = ((gx * gy) // 자리 * 자리) // gx              # 큰 판이 맡는 열 조각 수(꽉 찬 바퀴 안)
            if ny < 1 or ny >= gy:
                continue
            Nb = ny * BN
            for 작 in 판들:
                BMs, BNs, Ts = 정수판모양(작)
                if 2 * BMs * BNs > BM * BN:
                    continue
                a = 띄움(큰, (gx, ny))
                b = 띄움(작, ((rows + BMs - 1) // BMs, (N - Nb + BNs - 1) // BNs), 0, Nb)
                후보[("분할", 큰, 작, Nb)] = lambda a=a, b=b: (a(), b())
        if not 후보:
            return best
        후보[best] = runs[best]
        ts2 = 재기(후보)
        return min(ts2, key=ts2.get)

    def _층판(self, M):
        """11단계(정수 KV 판): 층정규화정수의 워프 판과 블록 판(층정규화정수줄 — 같은 비트)을 행 수마다 한 번 재서 빠른 것. 출력은 시험칸에."""
        key = ("층", M)
        if key not in self._고른판:
            import time
            cu, 시 = self.dr.cu, self.시험칸
            RB = 층정규화정수행(self.D)
            ps = [c_u64(self.h), c_u64(self.층[0]["ln_1.weight"]), c_u64(self.층[0]["ln_1.bias"]), c_u64(시),
                  c_u64(시 + 4 * self.D * self.최대행), c_i64(M)]
            xs = {"워프": _띄움(self.k["층정규화정수"], ((M + RB - 1) // RB, 1), (32 * RB, 1), ps),
                  "줄": _띄움(self.k["층정규화정수줄"], (M, 1), (256, 1), ps)}
            run = lambda x: cu.cuLaunchKernel(x.fn, x.grid[0], x.grid[1], 1, x.block[0], x.block[1], 1, 0, None, x.args, None)
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < 0.02:
                for x in xs.values():
                    run(x)
                self.dr.맞추기()
            e0, e1 = ctypes.c_void_p(), ctypes.c_void_p()
            cu.cuEventCreate(ctypes.byref(e0), 0)
            cu.cuEventCreate(ctypes.byref(e1), 0)
            ts = {n: [] for n in xs}
            for _ in range(3):
                for n, x in xs.items():
                    cu.cuEventRecord(e0, None)
                    for _ in range(5):
                        run(x)
                    cu.cuEventRecord(e1, None)
                    cu.cuEventSynchronize(e1)
                    ms = ctypes.c_float()
                    cu.cuEventElapsedTime(ctypes.byref(ms), e0, e1)
                    ts[n].append(ms.value)
            cu.cuEventDestroy_v2(e0)
            cu.cuEventDestroy_v2(e1)
            self._고른판[key] = min(ts, key=lambda n: sorted(ts[n])[1])
        return self._고른판[key]

    def _만들기(self, B, m, 로짓):
        """문장 B 개 × m 행의 한 번 계산. 로짓: "전부"(모든 행), "끝"(문장마다 마지막 행 + 가장큰번호), 정수 k(문장 하나의 마지막 k 행)."""
        M = B * m
        assert M <= self.최대행 and B <= self.최대문장
        assert 로짓 != "전부" or M <= self.로짓행, "모든 행의 로짓은 로짓행 행까지"
        k = self.k
        pos, tok, out = c_i64(0), c_u64(self.토큰칸), c_u64(self.생성칸)
        P = lambda v: c_u64(v)
        I = lambda v: c_i64(v)
        L = []
        e = (M * self.D + 255) // 256
        L.append(_띄움(k["임베딩"], (e, 1), (256, 1), [tok] + _가중인자(self.wte) + [P(self.wpe), P(self.h), I(M), I(m), pos]))

        줄들 = []                                  # 줄 판(행 넷까지)의 실행 — 끝에서 다음 줄 판의 가중치를 미리 읽게 잇는다

        def lin(epi, src, wt, b, dst, K, N, extra=(), rows=M, kv=None, 로짓=False, 바뀐=False, 자리=None):
            if self.정수 and rows <= 4:      # dp4a 줄 판 — 판 안에서 행마다 네 자리로 바꾼다
                fn = self.로짓선형["정수줄선형"] if 로짓 else self.선형[("정수줄선형", epi)]
                ps = [P(src)] + _가중인자(wt) + [P(b)] + [P(x) for x in extra] + [P(dst), I(rows), I(K), I(N)]
                if kv is not None:
                    ps += [I(m), pos, I(self.최대길이)]
                return _띄움(fn, *self._격자("정수줄선형", rows, N, K, self.크기 == "small"), ps)
            if self.정수:                   # 활성값을 네 자리로 바꾸고(정수로) 정수 텐서 코어 행렬곱 — 척도폭은 N 을 64 로 올림
                판 = self._판(src, wt, b, rows, K, N, 로짓, epi)
                자리 = 자리 or (self.자릿값, self.정보)
                if not 바뀐:                 # 바뀐 = 참: 앞 커널(층정규화정수 · _겔루정수)이 이미 네 자리로 바꿔 두었다
                    L.append(_띄움(k["정수로"], ((K // 32 + 31) // 32, rows), (256, 1),
                                   [P(src), P(자리[0]), P(자리[1]), I(rows), I(K)]))
                ps0 = [P(자리[0]), P(자리[1])] + _가중인자(wt) + [P(b)] + [P(x) for x in extra] + \
                      ([] if epi == "_KV정수" else [P(dst)]) + [I(rows), I(K), I(N), I((N + 63) // 64 * 64)]
                if kv is not None:
                    ps0 += [I(m), pos, I(self.최대길이)]
                if isinstance(판, tuple):        # 11단계 꼬리 자르기: 큰 판(열 [0, Nb)) 다음에 작은 판(열 [Nb, N)) — 같은 비트
                    _, 큰, 작, Nb = 판
                    BM, BN, T = 정수판모양(큰)
                    L.append(_띄움(self.로짓선형[큰] if 로짓 else self.선형[(큰, epi)], ((rows + BM - 1) // BM, Nb // BN), (T, 1),
                                   ps0 + [I(0), I(0)]))
                    BMs, BNs, Ts = 정수판모양(작)
                    return _띄움(self.로짓선형[작] if 로짓 else self.선형[(작, epi)],
                                 ((rows + BMs - 1) // BMs, (N - Nb + BNs - 1) // BNs), (Ts, 1), ps0 + [I(0), I(Nb)])
                fn = self.로짓선형[판] if 로짓 else self.선형[(판, epi)]
                return _띄움(fn, *self._격자(판, rows, N), ps0 + ([I(0), I(0)] if self.정수KV else []))
            판 = self._판(src, wt, b, rows, K, N, 로짓)
            fn = self.로짓선형[판] if 로짓 else self.선형[(판, epi)]
            ps = [P(src)] + _가중인자(wt) + [P(b)] + [P(x) for x in extra] + [P(dst), I(rows), I(K), I(N)]
            if kv is not None:
                ps += [I(m), pos, I(self.최대길이)]
            if 판 in ("줄선형1", "깊은줄선형1", "줄선형4"):
                ps += [P(0), I(0)]
                x = _띄움(fn, *self._격자(판, rows, N), ps)
                # 미리읽기의 수는 4 바이트 단위(짧은실수 판은 K · N 개 그대로)
                줄들.append((x, _바탕(wt), 바이트수[self.낱말형식 if 로짓 else self.층형식](K, N) // 4))
                return x
            return _띄움(fn, *self._격자(판, rows, N), ps)

        if M <= 4:                                 # 층정규화 판 — 둘 다 같은 순서 약속(비트가 같다): 행이 적으면 블록 하나가 한 행
            층 = lambda g, b: _띄움(k["줄층정규화"], (M, 1), (256, 1), [P(self.h), P(g), P(b), P(self.x)])
        else:                                      # 많으면 워프 하나가 한 행
            층 = lambda g, b: _띄움(k["층정규화"], ((M + 7) // 8, 1), (256, 1), [P(self.h), P(g), P(b), P(self.x), I(M)])
        # 어텐션 판 — 둘 다 같은 순서 약속(비트가 같다, 커널생성.py): 문장당 행이 둘 이상이면 질의 64 개씩의 흐름어텐션,
        # 하나면(생성) 키 조각을 블록들이 나눠 맡는 조각어텐션 + 차례로 접는 조각접기.
        조각수 = self.최대길이 // 64
        if m >= 2:
            어텐션 = lambda l: [_띄움(k["흐름어텐션"], (self.NH, B * ((m + 63) // 64)), (256, 1),
                                  [P(self.q), P(self.kc[l]), P(self.vc[l]), P(self.att), I(m), pos, I(self.최대길이)])]
        else:
            어텐션 = lambda l: [_띄움(k["조각어텐션"], ((조각수 + 3) // 4, M * self.NH), (256, 1),
                                  [P(self.q), P(self.kc[l]), P(self.vc[l]), P(self.조각칸), I(m), pos, I(self.최대길이)]),
                                _띄움(k["조각접기"], (M * self.NH, 1), (256, 1),
                                  [P(self.조각칸), P(self.att), I(M), I(m), pos, I(self.최대길이)])]
        # 6단계: 정수 판의 타일 길(행 다섯 이상 — 문장은 셋까지라 문장마다 행이 둘 이상)은 네 자리 바꾸기를 앞 커널에 묶는다 —
        # 층정규화 1 · 2 (층정규화정수), 어텐션(흐름어텐션정수 → c_proj), c_fc 의 끝손질(_겔루정수 → mlp c_proj). 같은 값.
        묶음 = self.정수 and M > 4 and self.묶어바꾸기
        if 묶음:
            assert m >= 2
            RB = 층정규화정수행(self.D)
            if self.정수KV and self._층판(M) == "줄":
                정층 = lambda g, b: _띄움(k["층정규화정수줄"], (M, 1), (256, 1), [P(self.h), P(g), P(b), P(self.자릿값), P(self.정보), I(M)])
            else:
                정층 = lambda g, b: _띄움(k["층정규화정수"], ((M + RB - 1) // RB, 1), (32 * RB, 1),
                                        [P(self.h), P(g), P(b), P(self.자릿값), P(self.정보), I(M)])
            어텐션 = lambda l: [_띄움(k["흐름어텐션정수"], (self.NH, B * ((m + 63) // 64)), (256, 1),
                                  [P(self.q), P(self.kc[l]), P(self.vc[l]), P(self.정보), P(self.자릿값), I(M), I(m), pos,
                                   I(self.최대길이)])]
        c_attn = lambda l, w: [lin("_KV", self.x, w["attn.c_attn.weight"], w["attn.c_attn.bias"], self.q, self.D, 3 * self.D,
                                   (self.kc[l], self.vc[l]), kv=True, 바뀐=묶음)]
        if self.정수KV:
            # 9단계 — 정수 KV 계약: 행 다섯 이상은 타일 c_attn 의 끝손질(_KV정수)이 q 자리 · 키 · 값 캐시를 바로 쓰고 정수어텐션(텐서 코어)이
            # c_proj 의 자리 둘을 바로 쓴다(바꾸기를 묶는 길만). 행 넷까지는 줄 판 c_attn → q 칸(짧은실수) → KV정수로 → 행마다
            # 정수조각어텐션 + 정수조각접기(생성 판 — 같은 비트). 두 길의 캐시 바이트는 같다.
            assert 묶음 or M <= 4, "정수 KV 판의 프롬프트(행 다섯 이상)는 바꾸기를 묶는 길(묶어바꾸기)만 있다"
            KV인자 = lambda l: [P(self.kc[l]), P(self.vc[l]), P(self.ke[l]), P(self.ve[l])]
            조각수 = self.최대길이 // 64
            if M > 4:
                c_attn = lambda l, w: [lin("_KV정수", self.x, w["attn.c_attn.weight"], w["attn.c_attn.bias"], None, self.D, 3 * self.D,
                                           [self.자릿값q, self.정보q, self.kc[l], self.vc[l], self.ke[l], self.ve[l]], kv=True, 바뀐=True)]
                어텐션 = lambda l: [_띄움(k["정수어텐션"], (self.NH, B * ((m + 어텐션질의수 - 1) // 어텐션질의수)), (2 * 어텐션질의수, 1),
                                      [P(self.자릿값q), P(self.정보q)] + KV인자(l) + [P(self.정보), P(self.자릿값), I(M), I(m), pos, I(self.최대길이)])]
            else:
                c_attn = lambda l, w: [lin("", self.x, w["attn.c_attn.weight"], w["attn.c_attn.bias"], self.q, self.D, 3 * self.D),
                                       _띄움(k["KV정수로"], ((3 * self.D // 32 + 31) // 32, M), (256, 1),
                                            [P(self.q), P(self.자릿값q), P(self.정보q)] + KV인자(l) + [I(M), I(m), pos, I(self.최대길이)])]
                어텐션 = lambda l: [_띄움(k["정수조각어텐션"], ((조각수 + 7) // 8, M * self.NH), (256, 1),
                                      [P(self.자릿값q), P(self.정보q)] + KV인자(l) + [P(self.조각칸), I(M), I(m), pos, I(self.최대길이)]),
                                    _띄움(k["정수조각접기"], (M * self.NH, 1), (256, 1), [P(self.조각칸), P(self.att), I(M), I(m), pos, I(self.최대길이)])]
        for l, w in enumerate(self.층):
            L.append(정층(w["ln_1.weight"], w["ln_1.bias"]) if 묶음 else 층(w["ln_1.weight"], w["ln_1.bias"]))
            L += c_attn(l, w)
            L += 어텐션(l)
            L.append(lin("_잔차", self.att, w["attn.c_proj.weight"], w["attn.c_proj.bias"], self.h, self.D, self.D, (self.h,), 바뀐=묶음))
            L.append(정층(w["ln_2.weight"], w["ln_2.bias"]) if 묶음 else 층(w["ln_2.weight"], w["ln_2.bias"]))
            if 묶음:                                # c_fc 의 끝손질이 mlp c_proj 의 네 자리(자릿값2 · 정보2)를 바로 쓴다
                L.append(lin("_겔루정수", self.x, w["mlp.c_fc.weight"], w["mlp.c_fc.bias"], self.자릿값2, self.D, 4 * self.D,
                             (self.정보2,), 바뀐=True))
                L.append(lin("_잔차", self.fc, w["mlp.c_proj.weight"], w["mlp.c_proj.bias"], self.h, 4 * self.D, self.D, (self.h,),
                             바뀐=True, 자리=(self.자릿값2, self.정보2)))
            else:
                L.append(lin("_겔루", self.x, w["mlp.c_fc.weight"], w["mlp.c_fc.bias"], self.fc, self.D, 4 * self.D))
                L.append(lin("_잔차", self.fc, w["mlp.c_proj.weight"], w["mlp.c_proj.bias"], self.h, 4 * self.D, self.D, (self.h,)))
        L.append(층(self.lnf_g, self.lnf_b))
        if 로짓 == "전부":
            L.append(lin("", self.x, self.wteT, self.영치우침, self.logits, self.D, self.V, 로짓=True))
        elif isinstance(로짓, int):               # 문장 하나의 마지막 로짓 행만 (긴 문맥의 비트 대조용)
            assert B == 1 and 0 < 로짓 <= min(m, self.로짓행)
            L.append(lin("", self.x + (m - 로짓) * self.D * 4, self.wteT, self.영치우침, self.logits, self.D, self.V, rows=로짓, 로짓=True))
        else:
            # 문장마다 마지막 행만: 행 b·m + m − 1 → 로짓의 행 b
            if m == 1:
                L.append(lin("", self.x, self.wteT, self.영치우침, self.logits, self.D, self.V, 로짓=True))
            else:
                for b in range(B):
                    L.append(lin("", self.x + (b * m + m - 1) * self.D * 4, self.wteT, self.영치우침, self.logits + b * self.V * 4,
                                 self.D, self.V, rows=1, 로짓=True))
            L.append(_띄움(k["가장큰번호"], (B, 1), (256, 1), [P(self.logits), out, I(1), I(self.V)]))
        if self.미리읽기:
            for (x, _, _), (_, wt, n) in zip(줄들, 줄들[1:]):
                x.params[-2].value, x.params[-1].value = wt, n
        return pos, tok, out, L

    def 계산(self, B, m, 위치시작, 로짓="전부", 토큰자리=None, 출력자리=None):
        """토큰은 토큰자리(기본 self.토큰칸)에 [B·m] int64 로 있어야 한다. 기다리지 않는다."""
        key = (B, m, 로짓)
        if key not in self._계획:
            self._계획[key] = self._만들기(B, m, 로짓)
        pos, tok, out, L = self._계획[key]
        assert 위치시작 + m <= self.최대길이
        pos.value = 위치시작
        tok.value = self.토큰칸 if 토큰자리 is None else 토큰자리
        out.value = self.생성칸 if 출력자리 is None else 출력자리
        if self.그래프쓰기 and B * m > 4:
            gk = (key, pos.value, tok.value, out.value)
            있던 = self._그래프.get(gk)
            if 있던 is None or 있던[0] is not L:        # 계획을 다시 만들었으면 그래프도 다시
                if 있던 is not None:
                    self.dr.확인(self.dr.cu.cuGraphExecDestroy(있던[1]))
                self._그래프[gk] = (L, self._그래프만들기(L))
            r = self.dr.cu.cuGraphLaunch(self._그래프[gk][1], None)
            if r != 0:
                raise RuntimeError(f"그래프 실행 오류 {r}")
            return
        launch = self.dr.cu.cuLaunchKernel
        for x in L:
            r = launch(x.fn, x.grid[0], x.grid[1], 1, x.block[0], x.block[1], 1, 0, None, x.args, None)
            if r != 0:
                raise RuntimeError(f"커널 실행 오류 {r}")

    # ── 편의 ──

    def 토큰넣기(self, ids):
        self.dr.올리기(self.토큰칸, np.asarray(ids, dtype=np.int64))

    def 로짓(self, rows):
        out = np.empty((rows, self.V), np.float32)
        self.dr.맞추기()
        return self.dr.내리기(self.logits, out)

    def 프롬메가로(self, ids):
        """문장 하나의 프롬프트를 프롬프트 메가커널로(협력 실행 한 번): KV 캐시를 채우고, 마지막 행의 로짓을 logits 에, 고른 토큰을
        생성칸[0] 에 둔다 — 계산("끝") 과 같은 값."""
        p = len(ids)
        assert 2 <= p <= self.최대행 and p <= self.최대길이
        self.토큰넣기(ids)
        self.dr.확인(self.dr.cu.cuMemsetD8_v2(self.프롬셈, 0, self.프롬셈크기))
        P, I = c_u64, c_i64
        g = lambda k: P(self.묶음[k])
        ps = [P(self.토큰칸), P(self.wte), P(self.wpe), P(self.wteT),
              g("ln_1.weight"), g("ln_1.bias"), g("attn.c_attn.weight"), g("attn.c_attn.bias"),
              g("attn.c_proj.weight"), g("attn.c_proj.bias"), g("ln_2.weight"), g("ln_2.bias"),
              g("mlp.c_fc.weight"), g("mlp.c_fc.bias"), g("mlp.c_proj.weight"), g("mlp.c_proj.bias"),
              P(self.lnf_g), P(self.lnf_b), P(self.kc바탕), P(self.vc바탕),
              P(self.h), P(self.x), P(self.q), P(self.att), P(self.fc), P(self.logits),
              P(self.부분값), P(self.부분번호), P(self.프롬셈), P(self.프롬셈 + 16), P(self.프롬셈 + 32), P(self.블록일), P(self.생성칸), P(self.프롬시각칸),
              I(p), I(self.최대길이), I(self.최대문장), I(self.묶음최대), I(self.프롬시각재기)]
        assert all(x.value % 16 == 0 for x in ps if isinstance(x, c_u64)), "프롬프트 메가커널의 참조 매개변수가 16 바이트 정렬이 아니다"
        args = (ctypes.c_void_p * len(ps))(*[ctypes.cast(ctypes.byref(x), ctypes.c_void_p) for x in ps])
        self._프롬인자 = (ps, args)
        r = self.dr.cu.cuLaunchCooperativeKernel(self.프롬, self.메가블록, 1, 1, 256, 1, 1, 0, None, args)
        if r != 0:
            raise RuntimeError(f"프롬프트 메가커널 실행 오류 {r}")

    def 생성(self, ids, n, 기록=False):
        """탐욕 생성(문장 하나): 프롬프트는 따로 도는 커널들로 한 번에 처리하고(첫 토큰까지), 나머지 n − 1 개는 생성 메가커널 하나가
        GPU 안에서 차례로 만든다(협력 실행 한 번). 기록 = 참이면 걸음마다의 로짓을 남긴다(로짓기록) — 시험용."""
        p = len(ids)
        assert p + n - 1 <= self.최대길이          # 마지막에 고른 토큰은 다시 넣지 않는다
        if self.프롬메가쓰기 and p >= 2:
            self.프롬메가로(ids)
        else:
            self.토큰넣기(ids)
            self.계산(1, p, 0, "끝", 출력자리=self.생성칸)
        if n > 1:
            if 기록 and (self.로짓기록칸 is None or self._기록수 < n):
                self.로짓기록칸, self._기록수 = self.dr.할당(n * self.V * 4), n
            self.dr.확인(self.dr.cu.cuMemsetD8_v2(self.장벽, 0, 256))
            P, I = c_u64, c_i64
            g = lambda k: _가중인자(self.묶음[k])
            낱말 = _가중인자(self.wte) + [P(self.wpe)] if self.낱말형식 != "짧은실수" else [P(self.wte), P(self.wpe), P(self.wteT)]
            ps = [P(self.생성칸)] + 낱말 + [
                  *g("ln_1.weight"), *g("ln_1.bias"), *g("attn.c_attn.weight"), *g("attn.c_attn.bias"),
                  *g("attn.c_proj.weight"), *g("attn.c_proj.bias"), *g("ln_2.weight"), *g("ln_2.bias"),
                  *g("mlp.c_fc.weight"), *g("mlp.c_fc.bias"), *g("mlp.c_proj.weight"), *g("mlp.c_proj.bias"),
                  P(self.lnf_g), P(self.lnf_b), P(self.kc바탕), P(self.vc바탕)] + ([P(self.ke바탕), P(self.ve바탕)] if self.정수KV else []) + [
                  P(self.h), P(self.q), P(self.att), P(self.fc), P(self.로짓기록칸 or self.logits),
                  P(self.부분값), P(self.부분번호), P(self.장벽), P(self.시각칸), P(self.조각칸), P(self.주의셈),
                  I(p), I(n), I(self.최대길이), I(self.최대문장), I(1 if 기록 else 0), I(int(self.시각재기))]
            assert all(x.value % 16 == 0 for x in ps if isinstance(x, c_u64)), "메가커널의 참조 매개변수가 16 바이트 정렬이 아니다"
            args = (ctypes.c_void_p * len(ps))(*[ctypes.cast(ctypes.byref(x), ctypes.c_void_p) for x in ps])
            self._메가인자 = (ps, args)
            r = self.dr.cu.cuLaunchCooperativeKernel(self.메가, self.메가블록, 1, 1, 256, 1, 1, 0, None, args)
            if r != 0:
                raise RuntimeError(f"생성 메가커널 실행 오류 {r}")
        out = np.zeros(n, np.int64)
        self.dr.맞추기()
        return [int(t) for t in self.dr.내리기(self.생성칸, out)]

    def 기록된로짓(self, n):
        out = np.empty((n - 1, self.V), np.float32)
        self.dr.맞추기()
        return self.dr.내리기(self.로짓기록칸, out)

    def 생성_여러커널(self, ids, n):
        """탐욕 생성(문장 하나)을 따로 도는 커널들로: 프롬프트를 한 번에 처리하고 n 개를 하나씩 — 다음 토큰은 GPU 의 가장큰번호가
        고른다. 호스트는 토큰을 기다리지 않는다(마지막에 한 번 받는다)."""
        p = len(ids)
        self.토큰넣기(ids)
        self.계산(1, p, 0, "끝", 출력자리=self.생성칸)
        for s in range(n - 1):
            self.계산(1, 1, p + s, "끝", 토큰자리=self.생성칸 + s * 8, 출력자리=self.생성칸 + (s + 1) * 8)
        out = np.zeros(n, np.int64)
        self.dr.맞추기()
        return [int(t) for t in self.dr.내리기(self.생성칸, out)]
