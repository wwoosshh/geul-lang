#!/usr/bin/env python3
"""4단계 — llama.cpp 를 제 프로세스에서 돌리는 일꾼 (재기4.py 가 띄운다).

PyTorch(인텔 OpenMP, libiomp5md.dll)와 llama.cpp 의 CPU 백엔드(LLVM OpenMP, libomp.dll)는 한 프로세스에 함께 올 수 없다 — 둘째가
올라오다 "OMP: Error #15" 로 멈춘다. 우회 변수(KMP_DUPLICATE_LIB_OK)는 "틀린 값을 낼 수 있다"고 적혀 있어 견주기에 쓰지 않는다.
사람들도 llama.cpp 는 제 프로세스(llama-server · Ollama · LM Studio)로 돌린다.

표준입력으로 JSON 한 줄 명령을 받아 JSON 한 줄로 답한다(답은 처음의 표준출력으로만 — 네이티브 코드가 표준출력에 쓰는 것은 표준오류로
돌린다). 큰 배열(로짓)은 .npy 파일로 넘긴다. 시간은 일꾼 안에서 잰다 — 프로세스 사이를 오가는 값은 llama.cpp 를 쓰는 사람이 치르지
않으므로 뺀다.

명령: 열기(키, gguf, kv형식, n_ctx, n_batch, n_ubatch, n_seq_max, 모델원, flash) · 프롬프트(키, ids) → ms · 생성(키, ids, n, 파일) → 토큰, ms
      · 로짓들(키, seqs, 방식, 조각, 파일) · 닫기(키) · 끝
"""
import json
import os
import sys
import time
import traceback

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import 라마                 # noqa: E402

V = 50257


class 엔진:
    def __init__(self, gguf, kv형식=1, n_ctx=1024, n_batch=1024, n_ubatch=512, n_seq_max=1, 모델=None, flash=-1):
        self.lm = 라마.라마(gguf, n_ctx=n_ctx, n_batch=n_batch, n_ubatch=n_ubatch, n_seq_max=n_seq_max, kv형식=kv형식, 모델=모델,
                          flash=flash)
        self.n_batch = n_batch
        self.문맥 = [l.strip() for l in self.lm.문맥로그.splitlines()
                   if any(x in l for x in ("flash", "Flash", "K (", "n_ctx ", "n_ubatch", "n_seq_max", "kv_unified"))]

    def _마지막로짓(self):
        return np.ctypeslib.as_array(self.lm.L.llama_get_logits_ith(self.lm.ctx, -1), shape=(V,))

    def _프롬(self, ids):
        """프롬프트를 n_batch 씩 llama_decode — 마지막 토큰의 로짓만 낸다 (llama-cli · llama-server 와 같다)."""
        lm = self.lm
        lm.지우기()
        n = len(ids)
        for a in range(0, n, self.n_batch):
            b = min(n, a + self.n_batch)
            로 = [0] * (b - a)
            if b == n:
                로[-1] = 1
            lm.넣기(ids[a:b], list(range(a, b)), [0] * (b - a), 로)

    def 프롬프트(self, ids):
        self._프롬(ids)
        return int(np.argmax(self._마지막로짓()))

    def 생성(self, ids, n, 로짓도=False):
        """탐욕: 디코드 → 마지막 로짓 → argmax → 다음 디코드."""
        lm = self.lm
        self._프롬(ids)
        toks, logs = [], []
        for s in range(n):
            p = self._마지막로짓()
            if 로짓도:
                logs.append(p.copy())
            t = int(np.argmax(p))
            toks.append(t)
            if s + 1 < n:
                lm.넣기([t], [len(ids) + s], [0], [1])
        return toks, (np.stack(logs) if 로짓도 else None)

    def 대화(self, 덩이들, n, 처음=True):
        """12단계 지속 사용 — 차례마다 덩이(앞 차례의 마지막 생성 토큰 + 새 토큰들)를 앞 캐시에 이어 넣고(n_batch 씩) 마지막 로짓에서 첫
        토큰을 고른 뒤 n − 1 개를 하나씩 탐욕 생성한다(마지막 토큰은 넣지 않는다 — 다음 덩이의 머리). 처음 = 참이면 캐시를 비우고 위치 0
        에서. 차례마다 (넣기 ms, 생성 ms, 끝 위치, 마지막 토큰) — 시간은 로짓을 읽어 GPU 를 맞춘 벽시계."""
        lm = self.lm
        if 처음:
            lm.지우기()
            self.위치 = 0
        out = []
        for 덩이 in 덩이들:
            t0 = time.perf_counter()
            c = len(덩이)
            for a in range(0, c, self.n_batch):
                b = min(c, a + self.n_batch)
                로 = [0] * (b - a)
                if b == c:
                    로[-1] = 1
                lm.넣기(덩이[a:b], list(range(self.위치 + a, self.위치 + b)), [0] * (b - a), 로)
            t = int(np.argmax(self._마지막로짓()))
            t1 = time.perf_counter()
            self.위치 += c
            for s in range(n - 1):
                lm.넣기([t], [self.위치], [0], [1])
                self.위치 += 1
                t = int(np.argmax(self._마지막로짓()))
            t2 = time.perf_counter()
            out.append({"넣기 ms": (t1 - t0) * 1000, "생성 ms": (t2 - t1) * 1000, "위치": self.위치, "끝토큰": t})
        return out

    def 로짓들(self, seqs, 방식="한번에", 조각=64):
        """같은 길이의 토큰열들(시퀀스 0, 1, …)의 모든 행 로짓 중 첫 열의 것. 조각·하나씩은 첫 열을 KV 캐시를 이어 가며 나눠 넣는다."""
        lm = self.lm
        lm.지우기()
        B, L = len(seqs), len(seqs[0])
        if 방식 == "한번에":
            토, 위, 시 = [], [], []
            for b, s in enumerate(seqs):
                토 += s
                위 += list(range(L))
                시 += [b] * L
            lm.넣기(토, 위, 시, [1] * (B * L))
            return lm.모든로짓(B * L)[:L]
        s, out = seqs[0], []
        k = 1 if 방식 == "하나씩" else 조각
        for a in range(0, L, k):
            c = s[a:a + k]
            lm.넣기(c, list(range(a, a + len(c))), [0] * len(c), [1] * len(c))
            out.append(lm.모든로짓(len(c)))
        return np.concatenate(out, 0)


def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    답 = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)                       # 네이티브 코드의 표준출력은 표준오류로
    sys.stdout = sys.stderr
    엔진들 = {}
    for line in sys.stdin:
        c = json.loads(line)
        op = c["op"]
        try:
            if op == "끝":
                break
            if op == "열기":
                원 = 엔진들[c["모델원"]].lm.model if c.get("모델원") else None
                e = 엔진(c["gguf"], c["kv형식"], c["n_ctx"], c["n_batch"], c["n_ubatch"], c["n_seq_max"], 원, c.get("flash", -1))
                엔진들[c["키"]] = e
                r = {"문맥": e.문맥}
            elif op == "프롬프트":
                e = 엔진들[c["키"]]
                t0 = time.perf_counter()
                tok = e.프롬프트(c["ids"])
                r = {"ms": (time.perf_counter() - t0) * 1000, "토큰": tok}
            elif op == "생성":
                e = 엔진들[c["키"]]
                t0 = time.perf_counter()
                toks, logs = e.생성(c["ids"], c["n"], 로짓도=bool(c.get("파일")))
                ms = (time.perf_counter() - t0) * 1000
                if logs is not None:
                    np.save(c["파일"], logs)
                r = {"ms": ms, "토큰": toks}
            elif op == "대화":
                r = {"차례": 엔진들[c["키"]].대화(c["덩이들"], c["n"], c.get("처음", True))}
            elif op == "로짓들":
                x = 엔진들[c["키"]].로짓들(c["seqs"], c["방식"], c["조각"])
                np.save(c["파일"], x)
                r = {"모양": list(x.shape)}
            elif op == "닫기":
                엔진들.pop(c["키"]).lm.닫기()
                r = {}
            else:
                raise ValueError(op)
            답.write(json.dumps({"ok": True, **r}, ensure_ascii=False) + "\n")
        except Exception:
            답.write(json.dumps({"ok": False, "오류": traceback.format_exc()}, ensure_ascii=False) + "\n")
        답.flush()
    # 모델을 가진 엔진은 나중에 닫는다 (빌린 문맥이 먼저)
    for k in sorted(엔진들, key=lambda k: 엔진들[k].lm.내모델):
        엔진들[k].lm.닫기()


if __name__ == "__main__":
    main()
