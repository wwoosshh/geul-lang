"""11단계: 판 모양 × 변형을 여러 행렬곱 크기에서 번갈아 잰다. 모든 칸은 기준(정수깊은타일선형, 짝 — 10단계 길)과 비트까지 같아야 한다.
인자: ROOT [형식=Q8_0] [판=이름:WM,WN,MT,NT,한도,S;…(표에 있는 이름이면 값 없이)] [변형=행렬+섞기+Pd접기,…] [모양=M,K,N;…] [크기=XL|small]"""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import os, ctypes, subprocess, time, json
import numpy as np
ROOT = sys.argv[1]
args = dict(a.split("=", 1) for a in sys.argv[2:] if "=" in a)
형식 = args.get("형식", "Q8_0")
T = os.path.join(ROOT, "build", "11단계작업")                # 만든 .gl · .ptx 는 git 밖에
os.makedirs(T, exist_ok=True)
for d in ("8단계", "3단계"):
    sys.path.insert(0, os.path.join(ROOT, "research", "gpu", d))
import 커널생성 as K
import 글gpt2 as G
K.자리수 = 2; K.KV = "정수"; K.지수 = "적힌지수"; K.계약 = "정수"; K.층형식 = 형식
K.너비, K.머리수, K.층수, K.확장폭, K.낱말수 = K.크기들[args.get("크기", "XL")]
판들 = []
for spec in args.get("판", "정수깊은타일선형;정수타일선형").split(";"):
    if ":" in spec:
        이름, v = spec.split(":")
        K.정수판들KV[이름] = tuple(int(x) for x in v.split(","))
    else:
        이름 = spec
    판들.append(이름)
변형들 = args.get("변형", "행렬+섞기+Pd접기").split(",")
모양들 = [tuple(int(x) for x in s.split(",")) for s in args.get("모양", "1024,1600,6400").split(";")]
Q4 = 형식 == "Q4_0"
dr = G.드라이버()
cu = dr.cu


def 모듈(읽기, 판목록):
    조각들 = 읽기.split("+")
    K.타일읽기 = 조각들[0]
    K.둘자리길 = next((x for x in 조각들[1:] if x in ("누적", "마법둘", "cvt")), "cvt")      # 12단계: 끝 계산 길도 변형 이름으로
    K.타일변형 = frozenset(x for x in 조각들[1:] if x not in ("누적", "마법둘", "cvt"))
    body = []
    for 판 in 판목록:
        body += K.정수타일선형("", 판, 형식, 판) + [""]
    src = "\n".join(K.머리줄() + K.정수머리줄() + body)
    gl = os.path.join(T, f"훑기_{형식}_{읽기}.gl"); ptx = gl[:-3] + ".ptx"
    open(gl, "w", encoding="utf-8", newline="\n").write(src)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "research", "gpu", "글ptx.py"), gl, "-o", ptx], capture_output=True)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-1500:]
    return dr.모듈(open(ptx, "rb").read())


mods = {"짝": 모듈("짝", ["정수깊은타일선형"])}
for v in 변형들:
    mods[v] = 모듈(v, 판들)
K.타일읽기, K.타일변형, K.둘자리길 = "행렬", frozenset(), "cvt"
fns = {}
for v, mod in mods.items():
    for 판 in (["정수깊은타일선형"] if v == "짝" else 판들):
        fn = dr.함수(mod, 판)
        regs, loc = ctypes.c_int(), ctypes.c_int()
        cu.cuFuncGetAttribute(ctypes.byref(regs), 4, fn); cu.cuFuncGetAttribute(ctypes.byref(loc), 3, fn)
        fns[(v, 판)] = (fn, regs.value, loc.value)
P, I = ctypes.c_uint64, ctypes.c_int64
rng = np.random.default_rng(1)
Mx = max(m for m, k, n in 모양들); Kx = max(k for m, k, n in 모양들); Nx = max(n for m, k, n in 모양들)
wmax = max(k * n for m, k, n in 모양들) // (2 if Q4 else 1)
big = dr.할당(wmax + 4096); dr.올리기(big, rng.integers(0, 256, wmax + 4096).astype(np.uint8))
dig = dr.할당(2 * Mx * Kx + 4096)
inf = dr.할당((Kx // 32) * ((Mx + 63) // 64 * 64) * 4 + 4096)
out, bias = dr.할당(Mx * Nx * 4), dr.할당(Nx * 4)
dr.올리기(bias, (rng.standard_normal(Nx) * 0.1).astype(np.float32))
scale = dr.할당((Kx // 32) * (Nx + 64) * 2 + 4096)
run = lambda x: cu.cuLaunchKernel(x.fn, x.grid[0], x.grid[1], 1, x.block[0], x.block[1], 1, 0, None, x.args, None)
e0, e1 = ctypes.c_void_p(), ctypes.c_void_p()
cu.cuEventCreate(ctypes.byref(e0), 0); cu.cuEventCreate(ctypes.byref(e1), 0)
결과 = {}
for (M, Kd, N_) in 모양들:
    d0 = rng.integers(-128, 128, (M, Kd)).astype(np.int8)
    d1 = rng.integers(-64, 65, (M, Kd)).astype(np.int8)
    dr.올리기(dig, np.concatenate([d0.ravel(), d1.ravel()]).view(np.uint8))
    E = rng.integers(-3, 3, (Kd // 32) * ((M + 63) // 64 * 64))
    dr.올리기(inf, (((137 + E) << 23) + 4194304).astype(np.int32))
    dr.올리기(scale, (rng.standard_normal((Kd // 32) * ((N_ + 63) // 64 * 64)) * 0.01).astype(np.float16))
    runs = {}
    for (v, 판), (fn, regs, loc) in fns.items():
        행, 열, 스 = K.정수판모양(판)
        runs[(v, 판)] = G._띄움(fn, ((M + 행 - 1) // 행, (N_ + 열 - 1) // 열), (스, 1),
                               [P(dig), P(inf), P(big), P(scale), P(bias), P(out), I(M), I(Kd), I(N_), I((N_ + 63) // 64 * 64)] + ([] if v == "짝" else [I(0), I(0)]))
    기준 = None
    for k, x in runs.items():
        dr.올리기(out, np.zeros(M * N_, np.float32))
        dr.확인(run(x)); dr.맞추기()
        y = np.empty(M * N_, np.float32); dr.내리기(out, y)
        if 기준 is None:
            기준 = y
        else:
            다른 = int(np.count_nonzero(y.view(np.uint32) != 기준.view(np.uint32)))
            if args.get("검사", "1") == "1":
                assert 다른 == 0, (k, 다른)
            elif 다른:
                print(f"   (값 다름 — 시간만) {k} 다른 칸 {다른}")
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 0.4:
        for x in runs.values():
            run(x)
        dr.맞추기()
    ts = {k: [] for k in runs}
    for _ in range(7):
        for k, x in runs.items():
            cu.cuEventRecord(e0, None)
            for _ in range(10):
                run(x)
            cu.cuEventRecord(e1, None); cu.cuEventSynchronize(e1)
            ms = ctypes.c_float(); cu.cuEventElapsedTime(ctypes.byref(ms), e0, e1)
            ts[k].append(ms.value / 10 * 1000)
    print(f"--- {형식} M {M} K {Kd} N {N_}" + (": 모두 기준과 비트까지 같다" if args.get("검사", "1") == "1" else ": (시간 나누기 — 값 검사 끔)"))
    for (v, 판), x in sorted(runs.items(), key=lambda kv: sorted(ts[kv[0]])[3]):
        t = sorted(ts[(v, 판)])[3]
        fn, regs, loc = fns[(v, 판)]
        print(f"   {v:22s} {판:14s} {t:8.1f} µs {2 * M * Kd * N_ * 2 / (t * 1e-6) / 3.2e14 * 100:5.1f}%  regs {regs} local {loc} 격자 {x.grid}")
        결과[f"{M},{Kd},{N_}|{v}|{판}"] = t
    sys.stdout.flush()
json.dump(결과, open(os.path.join(T, f"훑기_{형식}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
