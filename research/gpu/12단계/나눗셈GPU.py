"""글 커널에서 상수 나누기 · 나머지(주석 (* 상수나눗셈 *) 켬 · 끔)가 GPU 에서 0 쪽 자름과 같은가 — 부호 있는 64 비트 값(끝값 · 무작위)과
음이 아님이 증명된 값(& 2^30 − 1) 둘 다. 인자: ROOT"""
import sys, os, subprocess, ctypes
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np
ROOT = sys.argv[1]
T = os.path.join(ROOT, "build", "12단계작업")            # 만든 .gl · .ptx 는 git 밖에
os.makedirs(T, exist_ok=True)
sys.path.insert(0, os.path.join(ROOT, "research", "gpu", "3단계"))
import 글gpt2 as G
CS = [2, 3, 7, 10, 24, 32, 64, 768, 1600, 2304, 4800, 102400, 131072, 50257]
def 소스(켬):
    L = (["(* 상수나눗셈 *)"] if 켬 else []) + ["외부 [실행번호]는 -> 정수.", "",
         f"[정수 참조 입력에서 정수 참조 출력에 정수 n으로 나눗셈시험]는 {{",
         "    정수 i = 실행번호().",
         "    i < n이면 {",
         "        정수 x = 입력[i].",
         "        정수 y = x & 1073741823."]
    k = 0
    for c in CS:
        for v in ("x", "y"):
            L.append(f"        출력[i * {4 * len(CS)} + {k}] = {v} / {c}."); k += 1
            L.append(f"        출력[i * {4 * len(CS)} + {k}] = {v} % {c}."); k += 1
    L += ["    }", "}"]
    return "\n".join(L) + "\n"
rng = np.random.default_rng(3)
xs = [0, 1, -1, 2, -2, (1 << 63) - 1, -(1 << 63), -(1 << 63) + 1, 1 << 31, -(1 << 31), (1 << 32) - 1, -(1 << 32) + 1]
for c in CS:
    for b in (c, 7 * c, 1000003 * c):
        for d in (-1, 0, 1):
            xs += [b + d, -(b + d)]
xs += [int(v) for v in rng.integers(-(1 << 63), (1 << 63) - 1, 20000, dtype=np.int64)]
xs += [int(v) for v in rng.integers(-(1 << 40), 1 << 40, 20000, dtype=np.int64)]
n = len(xs)
X = np.array(xs, np.int64)
def 참(a, c, div):
    q = abs(a) // c
    q = -q if a < 0 else q
    return q if div else a - q * c
기대 = np.zeros((n, 4 * len(CS)), np.int64)
for r, a in enumerate(xs):
    y = a & 1073741823
    k = 0
    for c in CS:
        for v in (a, y):
            기대[r, k] = 참(v, c, True); 기대[r, k + 1] = 참(v, c, False); k += 2
dr = G.드라이버(); cu = dr.cu
입 = dr.할당(X.nbytes); dr.올리기(입, X)
출 = dr.할당(기대.nbytes)
for 켬 in (False, True):
    gl = os.path.join(T, f"나눗셈GPU_{int(켬)}.gl"); ptx = gl[:-3] + ".ptx"
    open(gl, "w", encoding="utf-8", newline="\n").write(소스(켬))
    r = subprocess.run([sys.executable, os.path.join(ROOT, "research", "gpu", "글ptx.py"), gl, "-o", ptx], capture_output=True)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-800:]
    txt = open(ptx, encoding="utf-8").read()
    fn = dr.함수(dr.모듈(txt.encode()), "나눗셈시험")
    x = G._띄움(fn, ((n + 127) // 128, 1), (128, 1), [ctypes.c_uint64(입), ctypes.c_uint64(출), ctypes.c_int64(n)])
    dr.확인(cu.cuLaunchKernel(x.fn, *x.grid, 1, *x.block, 1, 0, None, x.args, None)); dr.맞추기()
    got = dr.내리기(출, np.empty_like(기대))
    틀림 = int((got != 기대).sum())
    print(f"상수나눗셈 {'켬' if 켬 else '끔'}: 값 {기대.size} 개 중 틀림 {틀림}; PTX 의 div/rem.s64 {txt.count('div.s64') + txt.count('rem.s64')} 개, mul.hi {txt.count('mul.hi.s64')} 개;",
          [l for l in txt.splitlines() if l.startswith("// 12:") or l.startswith("// 2e")])
