"""글(geul)이 만든 x86-64 를 여러 언어 · 여러 컴파일러와 견준다 — 같은 알고리즘 · 같은 입력(여섯 짝 + 빈 프로그램).

    python -I -X utf8 research/cpu/언어견주기.py [--횟수 11] [--코어 P|E|없음] [--출력 <json>] [--만 fib ...] [--변형 <이름 일부> ...]
        [--zig <exe>] [--gcc <exe>] [--tcc <exe>] [--rustc <exe>] [--go <exe>] [--javac <exe>] [--java <exe>]

변형(빌드):
- 글: build/self_컴파일러.exe(배포 geulc 와 같은 바이트를 낸다) — 기본 x86-64(SSE2), 벡터화 없음.
- C clang(zig cc): -O0 · -O2 · -O2 벡터화 끔. zig cc 는 대상을 주지 않으면 이 CPU 의 명령(native — AVX2 등)을 쓴다. 이 README 의
  앞선 기록과 이어지게 그대로 두고, 글과 같은 명령 집합(기본 x86-64)으로 맞춘 -O2 -mcpu=baseline 을 더한다.
- C gcc: -O0 · -O2(기본 x86-64). tcc: 최적화 없음(한 번 훑는 컴파일러).
- Rust: -C opt-level=0 · 3. Go: 기본 · -gcflags="-N -l"(최적화 · 인라인 끔). 둘 다 기본 x86-64(Go 는 GOAMD64=v1).
- Java: HotSpot — JIT 이 실행 중 이 CPU 의 명령을 쓴다. 시간에 JVM 을 띄우는 값이 든다.
- 실수: 곱과 합을 합치지 않는다(C -ffp-contract=off, 나머지 언어는 스스로 합치지 않는다) — 출력이 비트까지 같다.
- 원본: 글 · C 는 이 폴더의 짝, Rust · Go · Java 는 다른언어/<언어>/ 의 줄마다 옮긴 것, 빈 프로그램은 다른언어/빈/.

재기: 빌드마다 한 번 돌려 출력을 견주고(모든 변형이 같아야 잰다 — sha256 은 파이썬 hashlib 과도), 차례를 돌려 가며 --횟수 번 —
프로세스 전체 벽시계 시간(시작 포함). --코어 P 는 P코어(물리 코어마다 논리 하나, 첫 코어 빼고), E 는 E코어에 이 프로세스를 묶는다
(윈도에서 자식 프로세스는 부모의 친화성을 물려받는다).
"""
import argparse, hashlib, json, math, os, platform, shutil, statistics, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OTHER = os.path.join(HERE, "다른언어")
BENCH = ["empty", "fib", "sieve", "bubble", "matmul", "sha256", "rope"]

# (이름, 언어, 도구, 깃발)
VARIANTS = [
    ("글", "geul", "geulc", []),
    ("C clang -O0", "c", "zig", ["-O0"]),
    ("C clang -O2", "c", "zig", ["-O2", "-ffp-contract=off"]),
    ("C clang -O2 벡터화 끔", "c", "zig", ["-O2", "-ffp-contract=off", "-fno-vectorize", "-fno-slp-vectorize"]),
    ("C clang -O2 기본x86-64", "c", "zig", ["-O2", "-ffp-contract=off", "-mcpu=baseline"]),
    ("C gcc -O0", "c", "gcc", ["-O0"]),
    ("C gcc -O2", "c", "gcc", ["-O2", "-ffp-contract=off"]),
    ("C tcc", "c", "tcc", []),
    ("Rust -O0", "rust", "rustc", ["-C", "opt-level=0"]),
    ("Rust -O3", "rust", "rustc", ["-C", "opt-level=3"]),
    ("Go", "go", "go", []),
    ("Go 최적화 끔", "go", "go", ["-gcflags=-N -l"]),
    ("Java", "java", "javac", []),
]


def run(cmd, env=None, cwd=None):
    r = subprocess.run(cmd, capture_output=True, env=env, cwd=cwd, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def which(given, name, extra=()):
    if given:
        return given
    p = shutil.which(name)
    if p:
        return p
    for d in extra:
        q = os.path.join(d, name + ".exe")
        if os.path.isfile(q):
            return q
    return None


# ---- CPU 묶기 (윈도) ----
def cores():
    """[(효율 등급, [논리 CPU ...])] — 물리 코어마다. 윈도가 아니면 None."""
    if os.name != "nt":
        return None
    import ctypes, ctypes.wintypes as wt
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    size = wt.DWORD(0)
    k.GetLogicalProcessorInformationEx(0, None, ctypes.byref(size))
    buf = ctypes.create_string_buffer(size.value)
    if not k.GetLogicalProcessorInformationEx(0, buf, ctypes.byref(size)):
        return None
    off, out = 0, []
    while off < size.value:
        sz = ctypes.c_uint32.from_buffer(buf, off + 4).value
        eff = buf.raw[off + 9]
        mask = ctypes.c_uint64.from_buffer(buf, off + 32).value
        out.append((eff, [i for i in range(64) if mask >> i & 1]))
        off += sz
    return out


def pin(kind):
    cs = cores()
    if not cs or kind == "없음":
        return []
    hi, lo = max(c[0] for c in cs), min(c[0] for c in cs)
    if kind == "P":
        p = [c[1] for c in cs if c[0] == hi]
        cpus = [c[0] for c in (p[1:] if len(p) > 1 else p)]
    else:
        if hi == lo:
            sys.exit("E코어가 없는 CPU 다")
        cpus = [x for c in cs if c[0] == lo for x in c[1]]
    import ctypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.GetCurrentProcess.restype = ctypes.c_void_p
    mask = sum(1 << x for x in cpus)
    if not k.SetProcessAffinityMask(ctypes.c_void_p(k.GetCurrentProcess()), ctypes.c_size_t(mask)):
        sys.exit("SetProcessAffinityMask 실패")
    return cpus


def cpu_name():
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as kk:
                return winreg.QueryValueEx(kk, "ProcessorNameString")[0].strip()
        except OSError:
            pass
    return platform.processor()


def source(b, lang):
    if b == "empty":
        return os.path.join(OTHER, "빈", {"geul": "empty.gl", "c": "empty.c", "rust": "empty.rs", "go": "empty.go", "java": "Empty.java"}[lang])
    return {"geul": os.path.join(HERE, b + ".gl"), "c": os.path.join(HERE, b + ".c"),
            "rust": os.path.join(OTHER, "rust", b + ".rs"), "go": os.path.join(OTHER, "go", b + ".go"),
            "java": os.path.join(OTHER, "java", b[0].upper() + b[1:] + ".java")}[lang]


def sha256_expected():
    import numpy as np
    i = np.arange(67108864, dtype=np.int64)
    return hashlib.sha256((((i * 2654435761) >> 13) & 255).astype(np.uint8).tobytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    for t in ("zig", "gcc", "tcc", "rustc", "go", "javac", "java"):
        ap.add_argument("--" + t)
    ap.add_argument("--횟수", type=int, default=11)
    ap.add_argument("--코어", default="P", choices=["P", "E", "없음"])
    ap.add_argument("--출력", default=os.path.join(HERE, "언어결과.json"))
    ap.add_argument("--만", nargs="*", default=BENCH)
    ap.add_argument("--변형", nargs="*", default=None, help="이름에 이 글자가 든 변형만")
    a = ap.parse_args()

    tools = {"geulc": os.path.join(ROOT, "build", "self_컴파일러.exe")}
    for t in ("zig", "gcc", "tcc", "rustc", "go", "javac", "java"):
        tools[t] = which(getattr(a, t), t)
    variants = [v for v in VARIANTS if (a.변형 is None or any(s in v[0] for s in a.변형))]
    missing = sorted({v[2] for v in variants if not tools.get(v[2])} | ({"java"} if any(v[1] == "java" for v in variants) and not tools["java"] else set()))
    if missing:
        sys.exit(f"도구를 찾지 못했다: {missing} — --<도구> 로 준다")
    cpus = pin(a.코어)

    tmp = tempfile.mkdtemp(prefix="geul_lang_")
    genv = dict(os.environ, GEUL_ROOT=ROOT)
    goenv = dict(os.environ, GOTOOLCHAIN="local", GOFLAGS="", GOCACHE=os.path.join(tmp, "gocache"), GOPATH=os.path.join(tmp, "gopath"))
    if tools.get("go"):
        goenv["GOROOT"] = os.path.dirname(os.path.dirname(tools["go"]))

    def ver(cmd):
        rc, o, e = run(cmd)
        return (o or e).strip().splitlines()[0] if (o or e).strip() else "?"
    info = {"시각": time.strftime("%Y-%m-%d %H:%M"), "cpu": cpu_name(), "묶은 논리 CPU": cpus, "코어": a.코어, "횟수": a.횟수,
            "python": sys.version.split()[0], "geulc_sha256": hashlib.sha256(open(tools["geulc"], "rb").read()).hexdigest()}
    for t, cmd in (("zig", ["version"]), ("gcc", ["--version"]), ("tcc", ["-v"]), ("rustc", ["-V"]), ("go", ["version"]), ("java", ["-version"])):
        if tools.get(t):
            info[t] = ver([tools[t]] + cmd) if t != "go" else ver([tools[t], "version"])
    print(json.dumps(info, ensure_ascii=False))

    # ---- 빌드 ----
    builds = {}
    for b in a.만:
        builds[b] = []
        for k, (name, lang, tool, flags) in enumerate(variants):
            src = source(b, lang)
            if not os.path.isfile(src):
                sys.exit(f"원본이 없다: {src}")
            d = os.path.join(tmp, f"{b}_{k}")
            os.makedirs(d)
            local = os.path.join(d, os.path.basename(src))
            shutil.copy(src, local)
            exe = os.path.join(d, b + ".exe")
            if lang == "geul":
                cmd, env = [tools["geulc"], local, "-o", exe], genv
            elif lang == "c":
                cmd, env = ([tools["zig"], "cc"] if tool == "zig" else [tools[tool]]) + flags + ["-o", exe, local], None
            elif lang == "rust":
                cmd, env = [tools["rustc"], *flags, local, "-o", exe], None
            elif lang == "go":
                cmd, env = [tools["go"], "build", *flags, "-o", exe, local], goenv
            else:
                cmd, env = [tools["javac"], "-encoding", "UTF-8", "-d", d, local], None
            rc, o, e = run(cmd, env=env, cwd=d)
            if rc != 0:
                sys.exit(f"빌드 실패 {b} {name}: {' '.join(cmd)}\n{o}{e}")
            runcmd = [tools["java"], "-cp", d, os.path.splitext(os.path.basename(src))[0]] if lang == "java" else [exe]
            builds[b].append((name, runcmd))
        print(f"빌드 {b}: {len(builds[b])} 가지", flush=True)

    # ---- 재기 ----
    result = {"정보": info, "변형": [v[0] for v in variants], "재기": {}}
    for b in a.만:
        outs = {}
        for name, cmd in builds[b]:
            rc, o, e = run(cmd)
            if rc != 0:
                sys.exit(f"실행 실패 {b} {name}: {rc} {o}{e}")
            outs[name] = o.replace("\r\n", "\n").strip()
        if len(set(outs.values())) != 1:
            sys.exit(f"{b}: 출력이 다르다 {json.dumps(outs, ensure_ascii=False)}")
        if b == "sha256" and outs["글"] != sha256_expected():
            sys.exit("sha256 이 hashlib 과 다르다")
        times = {name: [] for name, _ in builds[b]}
        n = len(builds[b])
        for r in range(a.횟수):
            order = builds[b][r % n:] + builds[b][:r % n]
            for name, cmd in order:
                t0 = time.perf_counter_ns()
                subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL)
                times[name].append((time.perf_counter_ns() - t0) / 1e9)
        stat = {}
        for name, v in times.items():
            q = statistics.quantiles(v, n=4) if len(v) >= 4 else [min(v), statistics.median(v), max(v)]
            stat[name] = {"중앙값": statistics.median(v), "최소": min(v), "최대": max(v), "사분위": [q[0], q[2]], "모두": v}
        result["재기"][b] = {"출력": outs["글"], "변형": stat}
        g = stat["글"]["중앙값"]
        print(f"{b:7s} " + " | ".join(f"{name} {stat[name]['중앙값'] * 1000:8.1f}ms" for name, _ in builds[b]), flush=True)
        json.dump(result, open(a.출력, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # ---- 요약: 글 / 변형 (빈 프로그램 빼고 기하평균) ----
    bs = [b for b in a.만 if b != "empty"]
    print("\n글 ÷ 변형 (1 보다 크면 글이 느리다)")
    for name, *_ in variants:
        rs = [result["재기"][b]["변형"]["글"]["중앙값"] / result["재기"][b]["변형"][name]["중앙값"] for b in bs]
        gm = math.exp(sum(math.log(x) for x in rs) / len(rs)) if rs else float("nan")
        print(f"  {name:22s} " + " ".join(f"{b} {x:5.2f}" for b, x in zip(bs, rs)) + f" | 기하평균 {gm:5.2f}")
    json.dump(result, open(a.출력, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
