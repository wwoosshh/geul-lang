#!/usr/bin/env python3
"""4단계 2 — 4e 반실수의 의미 (컴파일러): 밝힌 좁히기가 IEEE 754 binary16 의 반올림과 비트까지 같은가, 넘침을 잡는가, 넓히기는 정확한가,
밝히지 않은 좁히기는 거부되는가.

  build/감사venv/Scripts/python -I research/gpu/4단계/반실수재기.py

반실수변환.gl(좁히기 · 넓히기)을 글ptx.py 로 만들어 돌린다. 참값은 numpy 의 float32 → float16 (가까운 쪽, 같으면 짝수 — 넘치면 무한)과
float16 → float32 (정확). NaN 은 NaN 이면 같다고 본다(비트의 남은 자리는 보지 않는다). 오류 칸은 모듈의 전역 __geul_err — 실행 전에 0,
실행 뒤에 읽는다(4 는 반실수로의 넘침). 결과는 결과/반실수.json 에.
"""
import ctypes
import importlib.util
import json
import os
import sys
import tempfile
import warnings

import numpy as np
import torch

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
spec = importlib.util.spec_from_file_location("geulptx", os.path.join(ROOT, "research", "gpu", "글ptx.py"))
gp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gp)
dev = torch.device("cuda")
SRC = os.path.join(HERE, "반실수변환.gl")
이름 = lambda s: ("_G" + s.encode("utf-8").hex()).encode()

# 밝히지 않은 좁히기 — 모두 컴파일 오류여야 한다
거부할것 = {
    "대입에서 암시 좁히기": "좁힌칸[i] = 입력[i].",
    "리터럴을 반실수에": "좁힌칸[i] = 0.5.",
    "반실수끼리의 산술(짧은실수가 된다)을 반실수에": "좁힌칸[i] = 좁힌칸[i] + 좁힌칸[i].",
    "정수를 반실수에": "좁힌칸[i] = i.",
}
거부틀 = """외부 [실행번호]는 -> 정수.
[짧은실수 참조 입력에서 반실수 참조 좁힌칸에 정수 개수로 거부시험]는 {{
    정수 i = 실행번호().
    i < 개수이면 {{
        {줄}
    }}
}}
"""


def main():
    torch.zeros(1, device=dev)
    cu = ctypes.WinDLL("nvcuda.dll")
    ctx = ctypes.c_void_p()
    assert cu.cuInit(0) == 0 and cu.cuDevicePrimaryCtxRetain(ctypes.byref(ctx), 0) == 0 and cu.cuCtxSetCurrent(ctx) == 0
    text, _ = gp.translate(SRC)
    mod = ctypes.c_void_p()
    assert cu.cuModuleLoadData(ctypes.byref(mod), text.encode("ascii") + b"\0") == 0
    fns = {}
    for n in ("좁히기", "넓히기"):
        fns[n] = ctypes.c_void_p()
        assert cu.cuModuleGetFunction(ctypes.byref(fns[n]), mod, 이름(n)) == 0
    err, size = ctypes.c_uint64(), ctypes.c_size_t()
    assert cu.cuModuleGetGlobal_v2(ctypes.byref(err), ctypes.byref(size), mod, b"__geul_err") == 0

    def run(name, x, out_dtype):
        n = x.numel()
        o = torch.empty(n, dtype=out_dtype, device=dev)
        assert cu.cuMemsetD32_v2(err, 0, 1) == 0
        ps = [ctypes.c_uint64(x.data_ptr()), ctypes.c_uint64(o.data_ptr()), ctypes.c_int64(n)]
        args = (ctypes.c_void_p * 3)(*[ctypes.cast(ctypes.byref(p), ctypes.c_void_p) for p in ps])
        assert cu.cuLaunchKernel(fns[name], (n + 255) // 256, 1, 1, 256, 1, 1, 0, None, args, None) == 0
        assert cu.cuCtxSynchronize() == 0
        e = ctypes.c_uint32()
        assert cu.cuMemcpyDtoH_v2(ctypes.byref(e), err, ctypes.c_size_t(4)) == 0
        return e.value, o.cpu().numpy()

    def 좁히기(xs):
        """xs: float32 numpy → (오류 칸, 커널의 반실수 비트, numpy 의 반실수 비트)."""
        x = torch.from_numpy(np.ascontiguousarray(xs, np.float32)).to(dev)
        e, h = run("좁히기", x, torch.int16)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")                  # numpy 는 넘칠 때 경고를 낸다 — 값(무한)은 그대로 쓴다
            ref = xs.astype(np.float16)
        return e, h.view(np.uint16), ref.view(np.uint16)

    def 다른칸(a, b):
        """반실수 비트 두 판 — NaN 은 둘 다 NaN 이면 같다."""
        nan = lambda u: ((u & 0x7C00) == 0x7C00) & ((u & 0x03FF) != 0)
        same = (a == b) | (nan(a) & nan(b))
        return int((~same).sum())

    res = {}
    # 1. 무작위 100만 개 — 부호 · 크기(2^-30 … 2^15, 반실수의 비정규수에서 최댓값 아래까지) · 가수를 고르게
    rng = np.random.default_rng(48)
    n = 1 << 20
    xs = (rng.choice([-1.0, 1.0], n) * np.exp2(rng.uniform(-30, 15.999, n)) * rng.uniform(1, 2, n)).astype(np.float32)
    xs = xs[np.abs(xs) < 65504]                              # 범위 안만 (넘침은 아래에서 따로)
    e, h, ref = 좁히기(xs)
    res["무작위 (범위 안)"] = {"칸 수": int(len(xs)), "IEEE 와 다른 칸": 다른칸(h, ref), "오류 칸": e}
    # 2. 경계값
    f32 = lambda v: np.float32(v)
    경계 = {
        "0": 0.0, "-0": -0.0, "1 + 2^-11 (한가운데 → 짝수 1)": 1 + 2 ** -11, "1 + 3·2^-11 (한가운데 → 짝수)": 1 + 3 * 2 ** -11,
        "2049 (한가운데 → 2048)": 2049.0, "2051 (한가운데 → 2052)": 2051.0, "1/3": 1 / 3, "-2.5e-5": -2.5e-5,
        "2^-24 (가장 작은 비정규수)": 2.0 ** -24, "2^-25 (한가운데 → 0)": 2.0 ** -25, "3·2^-26 (→ 2^-24)": 3 * 2.0 ** -26,
        "2^-26 (→ 0)": 2.0 ** -26, "2^-14 (가장 작은 정규수)": 2.0 ** -14, "2^-14 − 2^-25 (정규수 바로 아래)": 2.0 ** -14 - 2.0 ** -25,
        "짧은실수의 가장 작은 비정규수": float(np.frombuffer(np.uint32(1).tobytes(), np.float32)[0]),
        "65504 (가장 큰 값)": 65504.0, "65519.99 (→ 65504)": float(np.nextafter(f32(65520), f32(0))),
        "-65519.99": -float(np.nextafter(f32(65520), f32(0))),
    }
    names = list(경계)
    e, h, ref = 좁히기(np.array([경계[k] for k in names], np.float32))
    res["경계값 (범위 안)"] = {"값": {k: f"{h[i]:#06x}" for i, k in enumerate(names)}, "IEEE 와 다른 칸": 다른칸(h, ref), "오류 칸": e}
    # 3. 넘침 — 유한한 값이 무한이 되면 오류 칸에 4. 이미 무한·NaN 은 넘침이 아니다
    넘침 = {"65520 (한가운데 → 무한)": 65520.0, "65536": 65536.0, "1e5": 1e5, "-65520": -65520.0, "3e38": 3e38}
    아님 = {"+무한": float("inf"), "-무한": float("-inf"), "NaN": float("nan")}
    e1, h1, r1 = 좁히기(np.array(list(넘침.values()), np.float32))
    e2, h2, r2 = 좁히기(np.array(list(아님.values()), np.float32))
    e3, h3, r3 = 좁히기(np.array([1.0] * 255 + [65520.0], np.float32))      # 넘치는 칸이 하나뿐이어도
    res["넘침"] = {"넘치는 값들: 오류 칸": e1, "IEEE 와 다른 칸": 다른칸(h1, r1),
                  "무한 · NaN (넘침 아님): 오류 칸": e2, "IEEE 와 다른 칸 (무한 · NaN)": 다른칸(h2, r2),
                  "256 칸 중 하나만 넘침: 오류 칸": e3}
    # 4. 넓히기 — 반실수 65536 가지 모두
    allh = np.arange(65536, dtype=np.uint16)
    e4, w = run("넓히기", torch.from_numpy(allh.view(np.int16).copy()).to(dev), torch.float32)
    refw = allh.view(np.float16).astype(np.float32)
    wb, rb = w.view(np.uint32), refw.view(np.uint32)
    nan32 = lambda u: ((u & 0x7F800000) == 0x7F800000) & ((u & 0x007FFFFF) != 0)
    다른넓힘 = int((~((wb == rb) | (nan32(wb) & nan32(rb)))).sum())
    e5, back, _ = 좁히기(w)
    다른왕복 = 다른칸(back, allh)
    res["넓히기 (65536 가지)"] = {"numpy 와 다른 칸": 다른넓힘, "오류 칸": e4, "다시 좁히면 제자리가 아닌 칸": 다른왕복, "다시 좁힐 때 오류 칸": e5}
    # 5. 밝히지 않은 좁히기는 컴파일 오류
    거부 = {}
    with tempfile.TemporaryDirectory() as d:
        for k, 줄 in 거부할것.items():
            p = os.path.join(d, "거부시험.gl")
            open(p, "w", encoding="utf-8").write(거부틀.format(줄=줄))
            try:
                gp.translate(p)
                거부[k] = "컴파일됨 (거부해야 한다)"
            except gp.CompileError as ex:
                거부[k] = "거부: " + str(ex).splitlines()[-1].split("오류:")[-1].strip()[:160]      # 임시 파일 경로는 빼고
            except gp.PTXError as ex:
                거부[k] = "PTX 탐침 오류 (앞단이 거부해야 한다): " + str(ex)[:160]
    res["밝히지 않은 좁히기"] = 거부
    # 6. 짧은실수 판의 PTX 가 바꾸기 전과 바이트까지 같은가 (build/기준ptx — 바꾸기 전의 코드로 만들어 둔 것)
    기준 = os.path.join(ROOT, "build", "기준ptx")
    같음 = {}
    if os.path.isdir(기준):
        for g in ("gpt2", "커널", "커널프롬"):
            b = os.path.join(기준, g + ".ptx")
            if os.path.exists(b):
                now, _ = gp.translate(os.path.join(ROOT, "research", "gpu", "3단계", g + ".gl"))
                같음[g] = now.encode("ascii") == open(b, "rb").read()
    res["짧은실수 판의 PTX 가 바꾸기 전과 같은가"] = 같음 or "기준 없음 (build/기준ptx)"
    무 = res["무작위 (범위 안)"]
    경 = res["경계값 (범위 안)"]
    넘 = res["넘침"]
    넓 = res["넓히기 (65536 가지)"]
    res["통과 (이 도구가 보는 몫)"] = bool(
        무["IEEE 와 다른 칸"] == 0 and 무["오류 칸"] == 0 and 경["IEEE 와 다른 칸"] == 0 and 경["오류 칸"] == 0 and
        넘["넘치는 값들: 오류 칸"] == 4 and 넘["IEEE 와 다른 칸"] == 0 and 넘["무한 · NaN (넘침 아님): 오류 칸"] == 0 and
        넘["IEEE 와 다른 칸 (무한 · NaN)"] == 0 and 넘["256 칸 중 하나만 넘침: 오류 칸"] == 4 and
        넓["numpy 와 다른 칸"] == 0 and 넓["오류 칸"] == 0 and 넓["다시 좁히면 제자리가 아닌 칸"] == 0 and 넓["다시 좁힐 때 오류 칸"] == 0 and
        all(v.startswith("거부") for v in 거부.values()) and isinstance(같음, dict) and len(같음) == 3 and all(같음.values()))
    os.makedirs(os.path.join(HERE, "결과"), exist_ok=True)
    json.dump(res, open(os.path.join(HERE, "결과", "반실수.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
