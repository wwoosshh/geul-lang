#!/usr/bin/env python3
"""4단계 재기 — 사람들이 쓰는 환경과 견주기 (docs/17 §7 "4단계"의 판정 그대로).

  build/감사venv/Scripts/python -I research/gpu/4단계/재기4.py

같은 PC(RTX 4070 Ti), 같은 GPT-2 small 가중치. 엔진 셋:
  글            — 3단계의 판(프롬프트는 따로 도는 커널, 생성은 생성 메가커널).
  llama.cpp     — b11496 CUDA, 직접 쓴 F32 GGUF, 기본 설정(플래시 어텐션 자동, KV F16, 마이크로배치 512). C API(라마.py)로 같은
                  탐욕 고리(디코드 → 로짓 → argmax)를 제 프로세스(라마일꾼.py)에서 — PyTorch 와 OpenMP 런타임이 부딪혀 한 프로세스에
                  못 온다. 시간은 일꾼 안에서 잰다. KV F32 판은 기록. llama-bench 의 숫자도 기록.
  HF            — transformers + PyTorch, fp32, SDPA(기본), generate 탐욕.
4a 성능(실제 GPT-2): 프롬프트 128·512·1024(문장 2 의 되풀이) 처리 + 첫 토큰, 생성 토큰당 = (64토큰 − 1토큰) / 63 (짧은 문맥: 문장 1,
   긴 문맥: 960토큰 프롬프트). 엔진을 번갈아 7번, 중앙값.
4b 성능(합성 — 위치표 16384, 시드 0): 프롬프트 4096·16384 처리 + 첫 토큰(번갈아 3번), 생성은 문맥 4096·16320 에서 (33토큰 − 1토큰) / 32
   (번갈아 5번).
4c 의미: (가) 세 문장(프롬프트 + 글이 고른 64토큰, 짧은 길이 68 로 자름) 중 문장 1 의 로짓을 혼자 / 셋을 한 묶음으로, (나) 512토큰 열의
   로짓을 한 번에 / 64토큰씩 / 하나씩(캐시를 이어 가며), (다) 한 번에를 다섯 번 더 — 다른 칸(비트)을 센다. 정확도: 엔진마다 제 탐욕
   64토큰의 걸음마다 로짓을 같은 토큰열의 fp64 참값(PyTorch fp64)과 견준 상대차 ‖x − 참값‖₂ / ‖참값‖₂ 의 중앙값(문장마다), 그리고 fp64
   의 탐욕 토큰과 처음 갈린 자리.
4d 안정성: 세 프롬프트 × 64토큰을 20번 — 토큰과 걸음마다 로짓이 첫 번째와 같은가, 실패 수.
결과는 결과/4단계.json 에(단계마다 덮어 쓴다).
"""
import gc
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

import numpy as np
import torch

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "gpu", "3단계"))
import 글gpt2 as G          # noqa: E402
import 토치gpt2 as T        # noqa: E402

MODEL = os.path.join(ROOT, "build", "gpt2")
GGUF = os.path.join(ROOT, "build", "gpt2-f32.gguf")
합성GGUF = os.path.join(ROOT, "build", "gpt2-synth16k-f32.gguf")
LLAMA = os.path.join(ROOT, "build", "llama-b11496")
결과 = os.path.join(HERE, "결과", "4단계.json")
문장들 = ["The meaning of life is",
        "In a shocking finding, scientists discovered a herd of unicorns living in a remote, previously unexplored valley "
        "in the Andes Mountains. Even more surprising to the researchers was the fact that the unicorns spoke perfect English.",
        "Alan Turing was a"]
V = 50257
합성길이 = 16384
라기본 = "llama.cpp (기본: KV F16)"
라32이름 = "llama.cpp (KV F32, 기록)"
라정이름 = "llama.cpp (KV F32 · 플래시 어텐션 끔, 기록)"      # 플래시 어텐션은 F32 KV 도 F16 으로 바꿔 계산한다 — 가장 정밀한 설정
HF이름 = "HF transformers"


def 잰다(f):
    torch.cuda.synchronize()
    s = time.perf_counter()
    f()
    torch.cuda.synchronize()
    return (time.perf_counter() - s) * 1000


def 다른칸(a, b):
    return int(np.count_nonzero(a.view(np.uint32) != b.view(np.uint32)))


def 상대차(x, ref):
    x, ref = x.astype(np.float64), ref.astype(np.float64)
    return float(np.linalg.norm(x - ref) / np.linalg.norm(ref))


def 합성가중치(w):
    """재기2.py(3j) · gguf쓰기.py --합성 과 같은 만들기 — 같은 모델."""
    rng = np.random.default_rng(0)
    sw = {}
    for k, v in w.items():
        if k == "wpe.weight":
            sw[k] = (rng.standard_normal((합성길이, 768)) * 0.01).astype(np.float32)
        elif k.endswith(".weight") and v.ndim == 2:
            sw[k] = (rng.standard_normal(v.shape) * 0.02).astype(np.float32)
        elif k.endswith(".weight"):
            sw[k] = np.ones_like(v)
        else:
            sw[k] = np.zeros_like(v)
    return sw, [int(x) for x in rng.integers(0, V, 합성길이)]


# ── 엔진 — 모두 같은 일: 프롬프트(첫 토큰까지), 탐욕 생성, 걸음마다의 로짓, 토큰열의 모든 행 로짓 ─────────────────────

class 이프로세스:
    """이 프로세스에서 도는 엔진의 시간 — 앞뒤로 GPU 를 맞춘 벽시계."""

    def 잰_프롬프트(self, ids):
        return 잰다(lambda: self.프롬프트(ids))

    def 잰_생성(self, ids, n):
        return 잰다(lambda: self.생성(ids, n))


class 글엔진(이프로세스):
    이름 = "글"

    def __init__(self, w, **kw):
        self.m = G.글GPT2(w, **kw)

    def 프롬프트(self, ids):
        self.m.생성(ids, 1)

    def 생성(self, ids, n):
        return self.m.생성(ids, n)

    def 생성로짓(self, ids, n):
        """탐욕 n 토큰과 걸음마다의 로짓 [n][어휘] (첫 걸음 = 프롬프트의 마지막 행)."""
        toks = self.m.생성(ids, n, 기록=True)
        첫 = self.m.로짓(1).copy()
        return toks, np.concatenate([첫, self.m.기록된로짓(n)], 0)

    def 로짓들(self, seqs, 방식="한번에", 조각=64):
        """seqs: 같은 길이의 토큰열들 (한 묶음). 첫 열의 모든 행 로짓. 조각·하나씩은 첫 열을 KV 캐시를 이어 가며 나눠 넣는다."""
        m, B, L = self.m, len(seqs), len(seqs[0])
        if 방식 == "한번에":
            m.토큰넣기([t for s in seqs for t in s])
            m.계산(B, L, 0, "전부")
            return m.로짓(B * L)[:L].copy()
        s, out = seqs[0], []
        k = 1 if 방식 == "하나씩" else 조각
        for a in range(0, L, k):
            c = s[a:a + k]
            m.토큰넣기(c)
            m.계산(1, len(c), a, "전부")
            out.append(m.로짓(len(c)).copy())
        return np.concatenate(out, 0)


class 일꾼:
    """라마일꾼.py — llama.cpp 를 제 프로세스에서. JSON 한 줄씩 묻고 답한다, 로짓은 .npy 로."""

    def __init__(self):
        self.p = subprocess.Popen([sys.executable, "-I", os.path.join(HERE, "라마일꾼.py")], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True, encoding="utf-8")
        self.임시 = tempfile.mkdtemp(prefix="geul4_")
        self.번호 = 0

    def 부르기(self, op, **kw):
        self.p.stdin.write(json.dumps({"op": op, **kw}, ensure_ascii=False) + "\n")
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError("llama.cpp 일꾼이 멈췄다")
        r = json.loads(line)
        if not r.pop("ok"):
            raise RuntimeError(r["오류"])
        return r

    def 파일(self):
        self.번호 += 1
        return os.path.join(self.임시, f"{self.번호}.npy")

    def 끝(self):
        self.p.stdin.write(json.dumps({"op": "끝"}) + "\n")
        self.p.stdin.flush()
        self.p.wait(timeout=120)
        shutil.rmtree(self.임시, ignore_errors=True)


class 라마엔진:
    _수 = 0

    def __init__(self, 일, 이름, gguf, kv형식=1, n_ctx=1024, n_batch=1024, n_ubatch=512, n_seq_max=1, 모델원=None, flash=-1):
        라마엔진._수 += 1
        self.일, self.이름, self.키 = 일, 이름, f"e{라마엔진._수}"
        self.문맥 = 일.부르기("열기", 키=self.키, gguf=gguf, kv형식=kv형식, n_ctx=n_ctx, n_batch=n_batch, n_ubatch=n_ubatch,
                            n_seq_max=n_seq_max, 모델원=모델원.키 if 모델원 else None, flash=flash)["문맥"]

    def _읽기(self, f):
        x = np.load(f)
        os.remove(f)
        return x

    def 잰_프롬프트(self, ids):
        return self.일.부르기("프롬프트", 키=self.키, ids=ids)["ms"]

    def 프롬프트(self, ids):
        self.잰_프롬프트(ids)

    def 잰_생성(self, ids, n):
        return self.일.부르기("생성", 키=self.키, ids=ids, n=n)["ms"]

    def 생성(self, ids, n):
        return self.일.부르기("생성", 키=self.키, ids=ids, n=n)["토큰"]

    def 생성로짓(self, ids, n):
        f = self.일.파일()
        toks = self.일.부르기("생성", 키=self.키, ids=ids, n=n, 파일=f)["토큰"]
        return toks, self._읽기(f)

    def 로짓들(self, seqs, 방식="한번에", 조각=64):
        f = self.일.파일()
        self.일.부르기("로짓들", 키=self.키, seqs=seqs, 방식=방식, 조각=조각, 파일=f)
        return self._읽기(f)

    def 닫기(self):
        self.일.부르기("닫기", 키=self.키)


class HF엔진(이프로세스):
    이름 = HF이름

    def __init__(self, 상태=None, n_positions=1024):
        from transformers import GPT2Config, GPT2LMHeadModel
        if 상태 is None:
            self.m = GPT2LMHeadModel.from_pretrained(MODEL, dtype=torch.float32).cuda().eval()
        else:
            cfg = GPT2Config.from_pretrained(MODEL)
            cfg.n_positions = n_positions
            m = GPT2LMHeadModel(cfg)
            sd = {("transformer." + k): torch.from_numpy(v) for k, v in 상태.items()}
            sd["lm_head.weight"] = sd["transformer.wte.weight"]
            r = m.load_state_dict(sd, strict=False)
            assert not [k for k in r.missing_keys if not k.endswith("attn.bias")], r.missing_keys
            self.m = m.float().cuda().eval()

    def _gen(self, ids, n, **kw):
        x = torch.tensor([ids], device="cuda")
        return self.m.generate(x, attention_mask=torch.ones_like(x), max_new_tokens=n, do_sample=False, pad_token_id=50256, **kw)

    @torch.no_grad()
    def 프롬프트(self, ids):
        self._gen(ids, 1)[0, -1].item()

    @torch.no_grad()
    def 생성(self, ids, n):
        return self._gen(ids, n)[0, len(ids):].tolist()

    @torch.no_grad()
    def 생성로짓(self, ids, n):
        out = self._gen(ids, n, return_dict_in_generate=True, output_logits=True)
        return out.sequences[0, len(ids):].tolist(), torch.cat(list(out.logits), 0).float().cpu().numpy()

    @torch.no_grad()
    def 로짓들(self, seqs, 방식="한번에", 조각=64):
        L = len(seqs[0])
        if 방식 == "한번에":
            return self.m(torch.tensor(seqs, device="cuda")).logits[0].float().cpu().numpy()
        s, past, out = seqs[0], None, []
        k = 1 if 방식 == "하나씩" else 조각
        for a in range(0, L, k):
            o = self.m(torch.tensor([s[a:a + k]], device="cuda"), past_key_values=past, use_cache=True)
            past = o.past_key_values
            out.append(o.logits[0].float().cpu().numpy())
        return np.concatenate(out, 0)


# ── 재기 ───────────────────────────────────────────────────────────────────────────────────────

def 번갈아(엔진들, 잰일, 번, 기록):
    """엔진을 번갈아 번 번 — 중앙값 ms (잰일(e) 가 ms 를 돌려준다). 실패한 엔진은 기록에 적고 빼낸다."""
    t = {e.이름: [] for e in 엔진들}
    for _ in range(번):
        for e in list(엔진들):
            try:
                t[e.이름].append(잰일(e))
            except Exception as ex:
                기록[e.이름] = f"실패: {type(ex).__name__}: {str(ex)[:300]}"
                traceback.print_exc()
                엔진들.remove(e)
                t.pop(e.이름, None)
    return {k: round(float(np.median(v)), 4) for k, v in t.items() if v}


def 데우기(엔진들, 일, 기록):
    for e in list(엔진들):
        try:
            일(e)
        except Exception as ex:
            기록[e.이름] = f"실패: {type(ex).__name__}: {str(ex)[:300]}"
            traceback.print_exc()
            엔진들.remove(e)


def 라마벤치(gguf, 인자):
    env = dict(os.environ)
    env["PATH"] = LLAMA + os.pathsep + env.get("PATH", "")
    # llama-bench 는 ASCII 가 아닌 경로(…\프로젝트\…)를 열지 못한다 — 저장소 뿌리에서 상대 경로로 넘긴다
    r = subprocess.run([os.path.join(LLAMA, "llama-bench.exe"), "-m", os.path.relpath(gguf, ROOT), "-ngl", "99", "-o", "json"] + 인자,
                       capture_output=True, text=True, env=env, encoding="utf-8", errors="replace", cwd=ROOT)
    try:
        return [{"n_prompt": x["n_prompt"], "n_gen": x["n_gen"], "n_depth": x.get("n_depth", 0), "t/s": round(x["avg_ts"], 1),
                 "flash_attn": x.get("flash_attn"), "type_k": x.get("type_k")} for x in json.loads(r.stdout)]
    except Exception:
        return [{"오류": r.stdout[-500:] + r.stderr[-500:]}]


def main():
    torch.zeros(1, device="cuda")
    import transformers
    res = {"환경": {"torch": torch.__version__, "transformers": transformers.__version__, "llama.cpp": "b11496 (000bee54a)",
                   "torch allow_tf32(matmul)": torch.backends.cuda.matmul.allow_tf32,
                   "GPU": torch.cuda.get_device_name(0)}}

    def 저장():
        os.makedirs(os.path.dirname(결과), exist_ok=True)
        json.dump(res, open(결과, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    w = G.가중치읽기(os.path.join(MODEL, "model.safetensors"))
    tk = G.토크나이저(MODEL)
    긴 = (tk.나누기(문장들[1]) * 40)[:1024]
    짧은 = tk.나누기(문장들[0])

    일 = 일꾼()
    글 = 글엔진(w)
    라 = 라마엔진(일, 라기본, GGUF)
    라32 = 라마엔진(일, 라32이름, GGUF, kv형식=0, 모델원=라)
    라정 = 라마엔진(일, 라정이름, GGUF, kv형식=0, 모델원=라, flash=0)
    hf = HF엔진()
    엔진들 = [글, 라, 라32, 라정, hf]
    res["llama.cpp 문맥 (로그)"] = {e.이름: e.문맥 for e in (라, 라32, 라정)}
    res["데우기: 문장 1 의 16토큰"] = {e.이름: tk.잇기(e.생성(짧은, 16)) for e in 엔진들}
    print(res["llama.cpp 문맥 (로그)"], flush=True)

    # 4a ── 실제 GPT-2 의 성능 ─────────────────────────────────────────────────────────────────────
    a = {"프롬프트 처리 + 첫 토큰 ms": {}, "생성 ms/토큰": {}, "실패": {}}
    for n in (128, 512, 1024):
        ids = 긴[:n]
        데우기(엔진들, lambda e: e.프롬프트(ids), a["실패"])
        a["프롬프트 처리 + 첫 토큰 ms"][n] = 번갈아(엔진들, lambda e: e.잰_프롬프트(ids), 7, a["실패"])
        print("4a 프롬프트", n, a["프롬프트 처리 + 첫 토큰 ms"][n], flush=True)
    for 이름, ids in (("짧은 문맥 (문장 1, 5토큰)", 짧은), ("문맥 960", 긴[:960])):
        데우기(엔진들, lambda e: e.생성(ids, 64), a["실패"])
        t1 = 번갈아(엔진들, lambda e: e.잰_생성(ids, 1), 7, a["실패"])
        t64 = 번갈아(엔진들, lambda e: e.잰_생성(ids, 64), 7, a["실패"])
        a["생성 ms/토큰"][이름] = {k: round((t64[k] - t1[k]) / 63, 4) for k in t1 if k in t64}
        print("4a 생성", 이름, a["생성 ms/토큰"][이름], flush=True)
    a["llama-bench (기본 설정, t/s)"] = 라마벤치(GGUF, ["-p", "128,512,1024", "-n", "64", "-r", "5"]) + \
        라마벤치(GGUF, ["-p", "0", "-n", "64", "-d", "960", "-r", "5"])
    판 = list(a["프롬프트 처리 + 첫 토큰 ms"].values()) + list(a["생성 ms/토큰"].values())
    a["통과"] = all(라기본 in v and HF이름 in v and v["글"] < v[라기본] and v["글"] < v[HF이름] for v in 판)
    res["4a 성능 (실제 GPT-2)"] = a
    저장()

    # 4c ── 의미 ─────────────────────────────────────────────────────────────────────────────────
    c = {}
    seqs = [tk.나누기(s) for s in 문장들]
    seqs = [s + 글.생성(s, 64) for s in seqs]
    L = min(len(s) for s in seqs)
    seqs = [s[:L] for s in seqs]
    긴열 = 긴[:512]
    라묶음 = 라마엔진(일, 라기본, GGUF, n_seq_max=4, 모델원=라)            # (가) 의 묶음은 시퀀스 넷까지 받는 문맥에서 (혼자도 같은 문맥)
    라묶음32 = 라마엔진(일, 라32이름, GGUF, kv형식=0, n_seq_max=4, 모델원=라)
    라묶음정 = 라마엔진(일, 라정이름, GGUF, kv형식=0, n_seq_max=4, 모델원=라, flash=0)
    한번들 = {}
    for e, eb in ((글, 글), (라, 라묶음), (라32, 라묶음32), (라정, 라묶음정), (hf, hf)):
        r = {}
        혼자 = eb.로짓들([seqs[0]])
        묶음 = eb.로짓들(seqs)
        r["(가) 혼자 대 세 문장 한 묶음: 다른 칸"] = 다른칸(혼자, 묶음)
        r["(가) 최대 절대차"] = float(np.abs(혼자 - 묶음).max())
        r["(가) 고른 토큰이 다른 행"] = int((혼자.argmax(-1) != 묶음.argmax(-1)).sum())
        한번 = e.로짓들([긴열])
        조각 = e.로짓들([긴열], "조각", 64)
        하나 = e.로짓들([긴열], "하나씩")
        r["(나) 한 번에 대 64토큰씩: 다른 칸"] = 다른칸(한번, 조각)
        r["(나) 한 번에 대 하나씩: 다른 칸"] = 다른칸(한번, 하나)
        r["(나) 최대 절대차 (64토큰씩 / 하나씩)"] = [float(np.abs(한번 - 조각).max()), float(np.abs(한번 - 하나).max())]
        r["(나) 고른 토큰이 다른 행 (64토큰씩 / 하나씩)"] = [int((한번.argmax(-1) != 조각.argmax(-1)).sum()),
                                                  int((한번.argmax(-1) != 하나.argmax(-1)).sum())]
        r["(다) 한 번에를 다섯 번 더: 첫 번째와 다른 칸"] = [다른칸(한번, e.로짓들([긴열])) for _ in range(5)]
        r["칸 수 (가 / 나)"] = [int(혼자.size), int(한번.size)]
        한번들[e.이름] = 한번
        c[e.이름] = r
        print("4c", e.이름, r, flush=True)
    c["llama.cpp 묶음 문맥 (로그)"] = {e.이름: e.문맥 for e in (라묶음, 라묶음32, 라묶음정)}
    c["llama.cpp 의 512토큰 한 번에: 기본(KV F16) 대 다른 설정 — 다른 칸"] = {
        k: 다른칸(한번들[라기본], 한번들[k]) for k in (라32이름, 라정이름)}
    for e in (라묶음, 라묶음32, 라묶음정):
        e.닫기()
    # 정확도: 엔진마다 제 탐욕 64토큰 + 걸음마다 로짓 → 같은 토큰열의 fp64 참값
    tm64 = T.토치GPT2(w, dtype=torch.float64, 최대문장=1)
    fp64토큰 = []
    for s in 문장들:
        x = torch.tensor([tk.나누기(s)], device="cuda")
        toks = []
        for _ in range(64):
            nxt = int(tm64.계산(x, 0, 끝만=True)[0].argmax())
            toks.append(nxt)
            x = torch.cat([x, torch.tensor([[nxt]], device="cuda")], 1)
        fp64토큰.append(toks)
    # 프롬프트 처리의 정확도(기록): 512토큰 열을 한 번에 넣은 모든 행의 로짓 대 fp64 참값 — 행마다 상대차의 중앙값·최댓값
    ref512 = tm64.계산(torch.tensor([긴열], device="cuda"), 0)[0].cpu().numpy()
    c["프롬프트 512행 상대차 (기록)"] = {}
    for k, x in 한번들.items():
        e512 = [상대차(x[i], ref512[i]) for i in range(len(긴열))]
        c["프롬프트 512행 상대차 (기록)"][k] = {"중앙값": float(np.median(e512)), "최댓값": float(np.max(e512)),
                                         "fp64 와 고른 토큰이 다른 행": int((x.argmax(-1) != ref512.argmax(-1)).sum())}
    print("4c 프롬프트 512행", c["프롬프트 512행 상대차 (기록)"], flush=True)
    del ref512, 한번들
    정확 = {}
    for e in 엔진들:
        rows = []
        for s, ref토큰 in zip(문장들, fp64토큰):
            ids = tk.나누기(s)
            toks, logs = e.생성로짓(ids, 64)
            seq = ids + toks
            ref = tm64.계산(torch.tensor([seq[:-1]], device="cuda"), 0)[0, len(ids) - 1:].cpu().numpy()
            errs = [상대차(logs[i], ref[i]) for i in range(64)]
            갈림 = next((i for i in range(64) if toks[i] != ref토큰[i]), None)
            rows.append({"중앙값": float(np.median(errs)), "최댓값": float(np.max(errs)), "fp64 탐욕과 처음 갈린 자리": 갈림})
        정확[e.이름] = rows
        print("4c 정확도", e.이름, [f"{r['중앙값']:.3e}" for r in rows], [r["fp64 탐욕과 처음 갈린 자리"] for r in rows], flush=True)
    del tm64
    gc.collect()
    torch.cuda.empty_cache()
    c["정확도 (fp64 참값 대비 상대차, 문장마다)"] = 정확
    배수 = {e.이름: [round(정확[e.이름][i]["중앙값"] / 정확[HF이름][i]["중앙값"], 3) for i in range(3)] for e in 엔진들}
    c["HF fp32 대비 중앙값 배수"] = 배수
    g = c["글"]
    c["통과"] = (g["(가) 혼자 대 세 문장 한 묶음: 다른 칸"] == 0 and g["(나) 한 번에 대 64토큰씩: 다른 칸"] == 0 and
                g["(나) 한 번에 대 하나씩: 다른 칸"] == 0 and all(x == 0 for x in g["(다) 한 번에를 다섯 번 더: 첫 번째와 다른 칸"]) and
                all(x <= 2 for x in 배수["글"]))
    res["4c 의미"] = c
    저장()

    # 4d ── 안정성 ───────────────────────────────────────────────────────────────────────────────
    d = {}
    for e in 엔진들:
        첫 = {}
        다름토큰 = 다름로짓 = 실패 = 0
        for _ in range(20):
            for s in 문장들:
                try:
                    toks, logs = e.생성로짓(tk.나누기(s), 64)
                except Exception:
                    실패 += 1
                    traceback.print_exc()
                    continue
                if s not in 첫:
                    첫[s] = (toks, logs)
                else:
                    다름토큰 += int(toks != 첫[s][0])
                    다름로짓 += int(다른칸(logs, 첫[s][1]) > 0)
        d[e.이름] = {"생성 수": 20 * 3, "첫 번째와 토큰이 다른 생성": 다름토큰, "첫 번째와 로짓 비트가 다른 생성": 다름로짓, "실패": 실패}
        print("4d", e.이름, d[e.이름], flush=True)
    d["오류 칸 (글)"] = 글.m.오류칸()
    g = d["글"]
    d["통과"] = g["첫 번째와 토큰이 다른 생성"] == 0 and g["첫 번째와 로짓 비트가 다른 생성"] == 0 and g["실패"] == 0 and d["오류 칸 (글)"] == 0
    res["4d 안정성"] = d
    저장()
    글오류 = d["오류 칸 (글)"]
    for e in (라32, 라정, 라):
        e.닫기()
    del hf, 글, 엔진들
    gc.collect()
    torch.cuda.empty_cache()

    # 4b ── 합성 긴 문맥 ─────────────────────────────────────────────────────────────────────────
    sw, 합성ids = 합성가중치(w)
    글합 = 글엔진(sw, 최대행=합성길이, 최대문장=1, 최대길이=합성길이, 로짓행=128)
    라합 = 라마엔진(일, 라기본, 합성GGUF, n_ctx=합성길이, n_batch=2048)        # llama.cpp 의 기본 n_batch 2048 · n_ubatch 512
    라합32 = 라마엔진(일, 라32이름, 합성GGUF, kv형식=0, n_ctx=합성길이, n_batch=2048, 모델원=라합)
    라합정 = 라마엔진(일, 라정이름, 합성GGUF, kv형식=0, n_ctx=합성길이, n_batch=2048, 모델원=라합, flash=0)
    합엔진 = [글합, 라합, 라합32, 라합정]
    b = {"프롬프트 처리 + 첫 토큰 ms": {}, "생성 ms/토큰": {}, "실패": {},
         "llama.cpp 문맥 (로그)": {e.이름: e.문맥 for e in (라합, 라합32, 라합정)}}
    try:
        hf합 = HF엔진(sw, n_positions=합성길이)
        hf합.이름 = HF이름 + " (기록)"
        합엔진.append(hf합)
    except Exception as ex:
        b["실패"][HF이름] = f"만들지 못함: {type(ex).__name__}: {str(ex)[:300]}"
    for n in (4096, 16384):
        ids = 합성ids[:n]
        데우기(합엔진, lambda e: e.프롬프트(ids), b["실패"])
        b["프롬프트 처리 + 첫 토큰 ms"][n] = 번갈아(합엔진, lambda e: e.잰_프롬프트(ids), 3, b["실패"])
        print("4b 프롬프트", n, b["프롬프트 처리 + 첫 토큰 ms"][n], flush=True)
    for P in (4096, 16320):
        ids = 합성ids[:P]
        데우기(합엔진, lambda e: e.생성(ids, 33), b["실패"])
        t1 = 번갈아(합엔진, lambda e: e.잰_생성(ids, 1), 5, b["실패"])
        t33 = 번갈아(합엔진, lambda e: e.잰_생성(ids, 33), 5, b["실패"])
        b["생성 ms/토큰"][P] = {k: round((t33[k] - t1[k]) / 32, 4) for k in t1 if k in t33}
        print("4b 생성", P, b["생성 ms/토큰"][P], flush=True)
    b["llama-bench (기본 설정, t/s)"] = 라마벤치(합성GGUF, ["-p", "4096,16384", "-n", "0", "-r", "3"]) + \
        라마벤치(합성GGUF, ["-p", "0", "-n", "32", "-d", "4096,16320", "-r", "3"])
    판 = list(b["프롬프트 처리 + 첫 토큰 ms"].values()) + list(b["생성 ms/토큰"].values())
    b["통과"] = all(라기본 in v and v["글"] < v[라기본] for v in 판)
    res["4b 성능 (합성 긴 문맥)"] = b
    res["오류 칸 (__geul_err)"] = max(글오류, 글합.m.오류칸())
    저장()
    일.끝()
    print(json.dumps({"4a": a["통과"], "4b": b["통과"], "4c": c["통과"], "4d": d["통과"], "오류 칸": res["오류 칸 (__geul_err)"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
