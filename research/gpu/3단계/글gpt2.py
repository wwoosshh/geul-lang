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
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
D, NH, NL, V, NCTX = 768, 12, 12, 50257, 1024

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
        self.cu = cu
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
        return mod

    def 함수(self, mod, name):
        fn = ctypes.c_void_p()
        self.확인(self.cu.cuModuleGetFunction(ctypes.byref(fn), mod, ("_G" + name.encode("utf-8").hex()).encode()))
        return fn

    def 할당(self, nbytes):
        p = c_u64()
        self.확인(self.cu.cuMemAlloc_v2(ctypes.byref(p), nbytes))
        self.확인(self.cu.cuMemsetD8_v2(p.value, 0, nbytes))
        return p.value

    def 올리기(self, dptr, arr):
        arr = np.ascontiguousarray(arr)
        self.확인(self.cu.cuMemcpyHtoD_v2(dptr, arr.ctypes.data, arr.nbytes))

    def 내리기(self, dptr, arr):
        self.확인(self.cu.cuMemcpyDtoH_v2(arr.ctypes.data, dptr, arr.nbytes))
        return arr

    def 맞추기(self):
        self.확인(self.cu.cuCtxSynchronize())


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


class 글GPT2:
    def __init__(self, weights, 최대행=1024, 최대문장=3, 최대길이=NCTX, 로짓행=1024):
        self.dr = dr = 드라이버()

        def build(gl):
            ptx = os.path.join(ROOT, "build", os.path.splitext(gl)[0] + ".ptx")
            subprocess.run([sys.executable, os.path.join(ROOT, "research", "gpu", "글ptx.py"), os.path.join(HERE, gl),
                            "-o", ptx], check=True, capture_output=True)
            return dr.모듈(open(ptx, "rb").read())
        self.mods = [build("gpt2.gl"), build("커널.gl")]
        self.k = {n: dr.함수(self.mods[0], n) for n in ("임베딩", "층정규화", "줄층정규화", "가장큰번호")}
        self.k.update({n: dr.함수(self.mods[1], n) for n in ("흐름어텐션", "조각어텐션", "조각접기")})
        self.선형 = {(판, epi): dr.함수(self.mods[1], f"{판}{epi}")
                    for 판 in ("줄선형1", "깊은줄선형1", "줄선형4", "타일선형", "타일선형넷", "작은타일선형")
                    for epi in ("", "_잔차", "_겔루", "_KV")}
        assert 최대길이 % 64 == 0 and 최대길이 <= 16384, "최대길이는 64 의 배수, 16384 까지 (어텐션의 키 조각 — 접기는 조각 256 개까지)"
        self.최대행, self.최대문장, self.최대길이 = 최대행, 최대문장, 최대길이

        def up(a):
            p = dr.할당(a.nbytes)
            dr.올리기(p, a)
            return p
        w = weights
        self.wte, self.wpe = up(w["wte.weight"]), up(w["wpe.weight"])
        self.wteT = up(np.ascontiguousarray(w["wte.weight"].T))      # 로짓 = x · wteᵀ (가중치 묶음 — 같은 표)
        self.영치우침 = up(np.zeros(V, np.float32))
        # 층마다의 가중치는 종류별로 12 층을 이어 붙여 올린다(생성 메가커널이 층 번호로 자리를 계산한다). 따로 도는 커널은 그 안의
        # 자리를 가리킨다.
        이름들 = ("ln_1.weight", "ln_1.bias", "attn.c_attn.weight", "attn.c_attn.bias", "attn.c_proj.weight", "attn.c_proj.bias",
                 "ln_2.weight", "ln_2.bias", "mlp.c_fc.weight", "mlp.c_fc.bias", "mlp.c_proj.weight", "mlp.c_proj.bias")
        self.묶음 = {}
        self.층 = [{} for _ in range(NL)]
        for 이름 in 이름들:
            한층 = w[f"h.0.{이름}"].nbytes
            바탕 = up(np.concatenate([np.ascontiguousarray(w[f"h.{l}.{이름}"]).reshape(-1) for l in range(NL)]))
            self.묶음[이름] = 바탕
            for l in range(NL):
                self.층[l][이름] = 바탕 + l * 한층
        self.lnf_g, self.lnf_b = up(w["ln_f.weight"]), up(w["ln_f.bias"])
        M = 최대행
        self.h, self.x = dr.할당(M * D * 4), dr.할당(M * D * 4)
        self.q, self.att = dr.할당(M * D * 4), dr.할당(M * D * 4)
        self.fc = dr.할당(M * 4 * D * 4)
        # 모든 행의 로짓("전부")은 로짓행 행까지만 — 긴 문맥에서는 문장마다 마지막 행만 쓴다
        self.로짓행 = max(min(로짓행, M), 최대문장)
        self.logits = dr.할당(self.로짓행 * V * 4)
        self.시험칸 = dr.할당(max(M * 4 * D, self.로짓행 * V) * 4)     # 판 고르기의 출력 (진짜 버퍼를 건드리지 않게)
        # 생성의 어텐션: 키 조각마다의 (m, l, o[64]) — [행][머리][조각][68] (메가커널은 행 하나)
        self.조각칸 = dr.할당(최대문장 * NH * (최대길이 // 64) * 68 * 4)
        kv = 최대문장 * 최대길이 * D * 4
        self.kc바탕, self.vc바탕 = dr.할당(NL * kv), dr.할당(NL * kv)
        # 프롬프트 처리의 어텐션은 키 조각을 통째로 읽고 가린 자리는 쓰지 않는다 — 아직 안 쓴 칸도 유한한 값이게 0 으로
        dr.확인(dr.cu.cuMemsetD8_v2(c_u64(self.kc바탕), 0, ctypes.c_size_t(NL * kv)))
        dr.확인(dr.cu.cuMemsetD8_v2(c_u64(self.vc바탕), 0, ctypes.c_size_t(NL * kv)))
        self.kc = [self.kc바탕 + l * kv for l in range(NL)]
        self.vc = [self.vc바탕 + l * kv for l in range(NL)]
        self.부분값, self.부분번호, self.장벽 = dr.할당(4096), dr.할당(8192), dr.할당(256)
        self.주의셈 = self.장벽 + 64               # 메가커널의 어텐션: 머리마다 도착한 블록 수 (장벽과 함께 0 으로)
        self.메가 = dr.함수(self.mods[1], "생성메가")
        self.메가블록 = 120                      # 커널생성.py 의 생성메가(G) 와 같아야 한다 (SM 60 개 × 2)
        dr.cu.cuLaunchCooperativeKernel.argtypes = [ctypes.c_void_p] + [ctypes.c_uint] * 7 + [ctypes.c_void_p] * 2
        self.로짓기록칸 = None
        self.시각칸, self.시각재기 = dr.할당(8 * 70 * 1100), 0          # 재기용: 0 이 아니면 블록 (값 − 1) 이 장벽마다 GPU 시각을 남긴다
        self.토큰칸 = dr.할당(M * 8)            # 이번에 넣을 토큰
        self.생성칸 = dr.할당(4096 * 8)         # 가장큰번호가 쓰는 자리 (생성할 때)
        self._계획 = {}
        self._고른판 = {}
        self.미리읽기 = True                    # 줄 판이 끝에서 다음 줄 판의 가중치를 L2 로 미리 읽는다(값과는 상관없다)
        cu = dr.cu
        cu.cuEventCreate.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint]
        cu.cuEventRecord.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        cu.cuEventSynchronize.argtypes = [ctypes.c_void_p]
        cu.cuEventElapsedTime.argtypes = [ctypes.POINTER(ctypes.c_float), ctypes.c_void_p, ctypes.c_void_p]

    def 오류칸(self):
        """두 모듈의 오류 칸(2c 범위 검사)을 OR 한 값 — 0 이어야 한다."""
        err = 0
        for mod in self.mods:
            p, n = c_u64(), ctypes.c_size_t()
            self.dr.확인(self.dr.cu.cuModuleGetGlobal_v2(ctypes.byref(p), ctypes.byref(n), mod, b"__geul_err"))
            err |= int(self.dr.내리기(p.value, np.zeros(1, np.uint32))[0])
        return err

    @staticmethod
    def _격자(판, rows, N):
        if 판 in ("줄선형1", "깊은줄선형1", "줄선형4"):
            return ((N + 31) // 32, 1), (128, 1)
        if 판 == "작은타일선형":
            return ((rows + 31) // 32, (N + 31) // 32), (256, 1)
        return ((rows + 63) // 64, (N + 63) // 64), (256, 1)

    def _판(self, src, wt, b, rows, K, N):
        """행 수에 맞는 선형 판. 타일 판은 (행, 깊이, 열) 마다 처음 한 번 재서 가장 빠른 것 — 비트는 어느 판이든 같다.
        재는 동안에는 끝손질 없는 판으로 시험칸에만 쓴다(캐시·잔차를 건드리지 않게)."""
        if rows == 1:                        # 열이 적으면 사슬이 적다 — 사슬마다 48 개씩 미리 읽는 판(재서 정함)
            return "깊은줄선형1" if N <= 1024 else "줄선형1"
        if rows <= 4:
            return "줄선형4"
        key = (rows, K, N)
        if key not in self._고른판:
            후보 = ["타일선형"] + (["타일선형넷"] if N % 64 == 0 else []) + (["작은타일선형"] if N % 32 == 0 else [])
            cu, best = self.dr.cu, None
            for 판 in 후보:
                ps = [c_u64(src), c_u64(wt), c_u64(b), c_u64(self.시험칸), c_i64(rows), c_i64(K), c_i64(N)]
                x = _띄움(self.선형[(판, "")], *self._격자(판, rows, N), ps)
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
        e = (M * D + 255) // 256
        L.append(_띄움(k["임베딩"], (e, 1), (256, 1), [tok, P(self.wte), P(self.wpe), P(self.h), I(M), I(m), pos]))

        줄들 = []                                  # 줄 판(행 넷까지)의 실행 — 끝에서 다음 줄 판의 가중치를 미리 읽게 잇는다

        def lin(epi, src, wt, b, dst, K, N, extra=(), rows=M, kv=None):
            판 = self._판(src, wt, b, rows, K, N)
            ps = [P(src), P(wt), P(b)] + [P(x) for x in extra] + [P(dst), I(rows), I(K), I(N)]
            if kv is not None:
                ps += [I(m), pos, I(self.최대길이)]
            if 판 in ("줄선형1", "깊은줄선형1", "줄선형4"):
                ps += [P(0), I(0)]
                x = _띄움(self.선형[(판, epi)], *self._격자(판, rows, N), ps)
                줄들.append((x, wt, K * N))
                return x
            return _띄움(self.선형[(판, epi)], *self._격자(판, rows, N), ps)

        if M <= 4:                                 # 층정규화 판 — 둘 다 같은 순서 약속(비트가 같다): 행이 적으면 블록 하나가 한 행
            층 = lambda g, b: _띄움(k["줄층정규화"], (M, 1), (256, 1), [P(self.h), P(g), P(b), P(self.x)])
        else:                                      # 많으면 워프 하나가 한 행
            층 = lambda g, b: _띄움(k["층정규화"], ((M + 7) // 8, 1), (256, 1), [P(self.h), P(g), P(b), P(self.x), I(M)])
        # 어텐션 판 — 둘 다 같은 순서 약속(비트가 같다, 커널생성.py): 문장당 행이 둘 이상이면 질의 64 개씩의 흐름어텐션,
        # 하나면(생성) 키 조각을 블록들이 나눠 맡는 조각어텐션 + 차례로 접는 조각접기.
        조각수 = self.최대길이 // 64
        if m >= 2:
            어텐션 = lambda l: [_띄움(k["흐름어텐션"], (NH, B * ((m + 63) // 64)), (256, 1),
                                  [P(self.q), P(self.kc[l]), P(self.vc[l]), P(self.att), I(m), pos, I(self.최대길이)])]
        else:
            어텐션 = lambda l: [_띄움(k["조각어텐션"], ((조각수 + 3) // 4, M * NH), (256, 1),
                                  [P(self.q), P(self.kc[l]), P(self.vc[l]), P(self.조각칸), I(m), pos, I(self.최대길이)]),
                                _띄움(k["조각접기"], (M * NH, 1), (256, 1),
                                  [P(self.조각칸), P(self.att), I(M), I(m), pos, I(self.최대길이)])]
        for l, w in enumerate(self.층):
            L.append(층(w["ln_1.weight"], w["ln_1.bias"]))
            L.append(lin("_KV", self.x, w["attn.c_attn.weight"], w["attn.c_attn.bias"], self.q, D, 3 * D,
                         (self.kc[l], self.vc[l]), kv=True))
            L += 어텐션(l)
            L.append(lin("_잔차", self.att, w["attn.c_proj.weight"], w["attn.c_proj.bias"], self.h, D, D, (self.h,)))
            L.append(층(w["ln_2.weight"], w["ln_2.bias"]))
            L.append(lin("_겔루", self.x, w["mlp.c_fc.weight"], w["mlp.c_fc.bias"], self.fc, D, 4 * D))
            L.append(lin("_잔차", self.fc, w["mlp.c_proj.weight"], w["mlp.c_proj.bias"], self.h, 4 * D, D, (self.h,)))
        L.append(층(self.lnf_g, self.lnf_b))
        if 로짓 == "전부":
            L.append(lin("", self.x, self.wteT, self.영치우침, self.logits, D, V))
        elif isinstance(로짓, int):               # 문장 하나의 마지막 로짓 행만 (긴 문맥의 비트 대조용)
            assert B == 1 and 0 < 로짓 <= min(m, self.로짓행)
            L.append(lin("", self.x + (m - 로짓) * D * 4, self.wteT, self.영치우침, self.logits, D, V, rows=로짓))
        else:
            # 문장마다 마지막 행만: 행 b·m + m − 1 → 로짓의 행 b
            if m == 1:
                L.append(lin("", self.x, self.wteT, self.영치우침, self.logits, D, V))
            else:
                for b in range(B):
                    L.append(lin("", self.x + (b * m + m - 1) * D * 4, self.wteT, self.영치우침, self.logits + b * V * 4,
                                 D, V, rows=1))
            L.append(_띄움(k["가장큰번호"], (B, 1), (256, 1), [P(self.logits), out, I(1), I(V)]))
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
        launch = self.dr.cu.cuLaunchKernel
        for x in L:
            r = launch(x.fn, x.grid[0], x.grid[1], 1, x.block[0], x.block[1], 1, 0, None, x.args, None)
            if r != 0:
                raise RuntimeError(f"커널 실행 오류 {r}")

    # ── 편의 ──

    def 토큰넣기(self, ids):
        self.dr.올리기(self.토큰칸, np.asarray(ids, dtype=np.int64))

    def 로짓(self, rows):
        out = np.empty((rows, V), np.float32)
        self.dr.맞추기()
        return self.dr.내리기(self.logits, out)

    def 생성(self, ids, n, 기록=False):
        """탐욕 생성(문장 하나): 프롬프트는 따로 도는 커널들로 한 번에 처리하고(첫 토큰까지), 나머지 n − 1 개는 생성 메가커널 하나가
        GPU 안에서 차례로 만든다(협력 실행 한 번). 기록 = 참이면 걸음마다의 로짓을 남긴다(로짓기록) — 시험용."""
        p = len(ids)
        assert p + n - 1 <= self.최대길이          # 마지막에 고른 토큰은 다시 넣지 않는다
        self.토큰넣기(ids)
        self.계산(1, p, 0, "끝", 출력자리=self.생성칸)
        if n > 1:
            if 기록 and (self.로짓기록칸 is None or self._기록수 < n):
                self.로짓기록칸, self._기록수 = self.dr.할당(n * V * 4), n
            self.dr.확인(self.dr.cu.cuMemsetD8_v2(self.장벽, 0, 256))
            P, I = c_u64, c_i64
            g = lambda k: P(self.묶음[k])
            ps = [P(self.생성칸), P(self.wte), P(self.wpe), P(self.wteT),
                  g("ln_1.weight"), g("ln_1.bias"), g("attn.c_attn.weight"), g("attn.c_attn.bias"),
                  g("attn.c_proj.weight"), g("attn.c_proj.bias"), g("ln_2.weight"), g("ln_2.bias"),
                  g("mlp.c_fc.weight"), g("mlp.c_fc.bias"), g("mlp.c_proj.weight"), g("mlp.c_proj.bias"),
                  P(self.lnf_g), P(self.lnf_b), P(self.kc바탕), P(self.vc바탕),
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
        out = np.empty((n - 1, V), np.float32)
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
