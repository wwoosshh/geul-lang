#!/usr/bin/env python3
"""4단계 — llama.cpp(b11496, CUDA) 를 C API 로 부른다(ctypes). 배포본에는 헤더가 없어서, 구조체는 기본값 함수가 돌려주는 바이트를
읽어 알려진 기본값의 자리로 필드를 짚었다(라마.py 의 시험이 확인한다):

  llama_context_params: n_ctx 0, n_batch 4, n_ubatch 8, n_seq_max 12, n_threads 28, n_threads_batch 32,
                        flash_attn_type 52 (−1 자동, 0 끔, 1 켬), type_k 104, type_v 108 (ggml 형식: 0 F32, 1 F16),
                        offload_kqv 137, kv_unified 141 (b11496 의 llama.h 와 대조함)
  llama_model_params: n_gpu_layers 16 (기본 −1 은 자동 맞춤 — 99 로 모든 층을 GPU 에)
  llama_batch (llama_batch_init 이 돌려줌): n_tokens 0, token 8, embd 16, pos 24, n_seq_id 32, seq_id 40, logits 48

윈도우 x64 호출 규약: 8 바이트보다 큰 구조체를 값으로 넘기면 복사본의 주소가, 돌려받으면 호출하는 쪽이 준 자리의 주소가 넘어간다 —
그래서 구조체는 바이트 판으로 들고 주소를 넘긴다.
"""
import ctypes
import os
import struct

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
DLL = os.path.join(ROOT, "build", "llama-b11496")
V = 50257
c_p = ctypes.c_void_p


class 라마:
    def __init__(self, gguf, n_ctx=1024, n_batch=1024, n_ubatch=512, n_seq_max=4, flash=-1, kv형식=1, 통합KV=False, 조용히=True):
        os.add_dll_directory(DLL)
        # ggml 이 백엔드 DLL(ggml-cuda.dll)을 LoadLibraryW 로 부르면 그 의존 DLL(cuBLAS·cudart)은 PATH 에서 찾는다 — 없으면 조용히
        # CPU 만 남는다(모델이 CPU 에 올라도 "offloaded 13/13 layers to GPU" 라고 적힌다). 그래서 PATH 앞에 둔다.
        if DLL not in os.environ.get("PATH", ""):
            os.environ["PATH"] = DLL + os.pathsep + os.environ.get("PATH", "")
        L = self.L = ctypes.CDLL(os.path.join(DLL, "llama.dll"))
        if 조용히:
            self._로그 = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_char_p, c_p)(lambda lv, s, u: None)
            L.llama_log_set(self._로그, None)
        G = self.G = ctypes.CDLL(os.path.join(DLL, "ggml.dll"))
        G.ggml_backend_load_all_from_path.argtypes = [ctypes.c_char_p]
        G.ggml_backend_load_all_from_path(DLL.encode("utf-8"))      # CUDA·CPU 백엔드 DLL 을 불러온다
        L.llama_backend_init()
        for n in ("llama_model_default_params", "llama_context_default_params", "llama_batch_init"):
            getattr(L, n).restype = c_p
        L.llama_model_default_params.argtypes = [c_p]
        L.llama_context_default_params.argtypes = [c_p]
        L.llama_model_load_from_file.restype = c_p
        L.llama_model_load_from_file.argtypes = [ctypes.c_char_p, c_p]
        L.llama_init_from_model.restype = c_p
        L.llama_init_from_model.argtypes = [c_p, c_p]
        L.llama_batch_init.argtypes = [c_p, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32]
        L.llama_decode.restype = ctypes.c_int32
        L.llama_decode.argtypes = [c_p, c_p]
        L.llama_get_logits_ith.restype = ctypes.POINTER(ctypes.c_float)
        L.llama_get_logits_ith.argtypes = [c_p, ctypes.c_int32]
        L.llama_get_memory.restype = c_p
        L.llama_get_memory.argtypes = [c_p]
        L.llama_memory_clear.argtypes = [c_p, ctypes.c_bool]
        L.llama_synchronize.argtypes = [c_p]
        for n in ("llama_n_ctx", "llama_n_batch", "llama_n_ubatch", "llama_n_seq_max"):
            getattr(L, n).restype = ctypes.c_uint32
            getattr(L, n).argtypes = [c_p]
        mp = ctypes.create_string_buffer(256)
        L.llama_model_default_params(mp)
        assert struct.unpack_from("<ii", mp.raw, 16) == (-1, 1), "모델 구조체 기본값이 예상과 다르다"
        struct.pack_into("<i", mp, 16, 99)                       # n_gpu_layers: 모든 층을 GPU 에 (−1 은 "자동 맞춤")
        self.model = L.llama_model_load_from_file(gguf.encode("utf-8"), mp)
        assert self.model, "llama.cpp 가 모델을 읽지 못했다"
        cp = ctypes.create_string_buffer(512)
        L.llama_context_default_params(cp)
        기본 = struct.unpack_from("<IIII", cp.raw, 0) + struct.unpack_from("<ii", cp.raw, 104)
        assert 기본 == (512, 2048, 512, 1, 1, 1), f"구조체 기본값이 예상과 다르다: {기본}"
        struct.pack_into("<IIII", cp, 0, n_ctx, n_batch, n_ubatch, n_seq_max)
        struct.pack_into("<i", cp, 52, flash)
        struct.pack_into("<ii", cp, 104, kv형식, kv형식)
        struct.pack_into("<B", cp, 141, 1 if 통합KV else 0)            # kv_unified
        if not 조용히:
            print("문맥 구조체 136..143:", cp.raw[136:144].hex())
        self.ctx = L.llama_init_from_model(self.model, cp)
        assert self.ctx, "llama.cpp 가 문맥을 만들지 못했다"
        got = (L.llama_n_ctx(self.ctx), L.llama_n_batch(self.ctx), L.llama_n_ubatch(self.ctx), L.llama_n_seq_max(self.ctx))
        assert got[0] >= n_ctx and got[1] == n_batch and got[2] == n_ubatch and got[3] == n_seq_max, f"설정이 안 먹었다: {got}"
        self.batch = ctypes.create_string_buffer(56)
        L.llama_batch_init(self.batch, n_batch, 0, n_seq_max)
        self.n_batch = n_batch
        b = self.batch.raw
        self.p_tok, self.p_pos, self.p_nseq, self.p_seq, self.p_log = (struct.unpack_from("<Q", b, o)[0] for o in (8, 24, 32, 40, 48))

    def 지우기(self):
        self.L.llama_memory_clear(self.L.llama_get_memory(self.ctx), True)

    def 넣기(self, 토큰들, 위치들, 시퀀스들, 로짓):
        """한 번의 llama_decode — 줄 i: 토큰, 위치, 시퀀스 번호, 로짓을 낼지."""
        n = len(토큰들)
        assert n <= self.n_batch
        ctypes.memmove(self.p_tok, np.asarray(토큰들, np.int32).ctypes.data, 4 * n)
        ctypes.memmove(self.p_pos, np.asarray(위치들, np.int32).ctypes.data, 4 * n)
        ctypes.memmove(self.p_nseq, np.ones(n, np.int32).ctypes.data, 4 * n)
        ctypes.memmove(self.p_log, np.asarray(로짓, np.int8).ctypes.data, n)
        seqp = ctypes.cast(self.p_seq, ctypes.POINTER(ctypes.c_void_p))
        for i, s in enumerate(시퀀스들):
            ctypes.cast(seqp[i], ctypes.POINTER(ctypes.c_int32))[0] = s
        struct.pack_into("<i", self.batch, 0, n)
        r = self.L.llama_decode(self.ctx, self.batch)
        assert r == 0, f"llama_decode 실패 {r}"

    def 로짓(self, i):
        p = self.L.llama_get_logits_ith(self.ctx, i)
        return np.ctypeslib.as_array(p, shape=(V,)).copy()

    def 맞추기(self):
        self.L.llama_synchronize(self.ctx)
