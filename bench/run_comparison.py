"""Comprehensive benchmark runner: 글 vs C / Rust / Go / Java / JS / Python

Each language runs the SAME logical problem. Each program times the HOT SECTION
internally and prints "RESULT:ms". We launch the process N times, extract the
RESULT value, and report the median.

Run:  python bench/run_comparison.py
"""
import os, re, sys, time, subprocess, shutil, statistics, json

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(ROOT)
RESULT_PAT = re.compile(r'(?:RESULT:|time:)\s*([0-9.]+)')

# ---------- tool paths ----------
CL = r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\cl.exe"
MSVC_INC = r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\include"
UCRT_INC = r"C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\ucrt"
UM_INC = r"C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\um"
SHARED_INC = r"C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\shared"
MSVC_LIB = r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\lib\x64"
UCRT_LIB = r"C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\ucrt\x64"
UM_LIB = r"C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\um\x64"
CLANG = r"C:\Program Files\LLVM\bin\clang.exe"
TCC = os.path.join(REPO, "tools", "tcc-extract", "tcc", "tcc.exe")
GEUL = os.path.abspath(os.path.join(REPO, "dist", "compiler.exe"))

RUNS = 7
BUILD_DIR = os.path.join(ROOT, "build_tmp")
os.makedirs(BUILD_DIR, exist_ok=True)

def compile_msvc(src, out):
    cmd = f'"{CL}" /O2 /nologo /utf-8 /I"{MSVC_INC}" /I"{UCRT_INC}" /I"{UM_INC}" /I"{SHARED_INC}" /Fe:"{out}" /Fo:"{out}.obj" "{src}" /link /LIBPATH:"{MSVC_LIB}" /LIBPATH:"{UCRT_LIB}" /LIBPATH:"{UM_LIB}"'
    r = subprocess.run(cmd, capture_output=True, shell=True)
    return os.path.exists(out)

def compile_clang(src, out):
    r = subprocess.run([CLANG, "-O2", "-o", out, src], capture_output=True)
    return os.path.exists(out)

def compile_tcc(src, out):
    r = subprocess.run([TCC, "-o", out, src], capture_output=True)
    return os.path.exists(out)

def compile_rust(src, out):
    r = subprocess.run(["rustc", "-O", "-o", out, src], capture_output=True)
    return os.path.exists(out)

def compile_go(src, out):
    r = subprocess.run(["go", "build", "-o", out, src], capture_output=True)
    return os.path.exists(out)

def compile_java(src):
    # javac src/X.java -d <outdir>
    outdir = os.path.dirname(src)
    r = subprocess.run(["javac", src, "-d", outdir], capture_output=True)
    return r.returncode == 0

def compile_geul(src, out):
    src = os.path.abspath(src)
    src_dir = os.path.dirname(src)
    src_file = os.path.basename(src)
    exe_default = os.path.splitext(src)[0] + ".exe"
    if os.path.exists(exe_default):
        try: os.remove(exe_default)
        except: pass
    r = subprocess.run([GEUL, "--no-pause", src_file], cwd=src_dir, capture_output=True)
    if os.path.exists(exe_default):
        if exe_default != out:
            shutil.copy2(exe_default, out)
        return True
    print(f'  [geul stderr]: {r.stderr.decode("utf-8", errors="replace")[:200]}')
    return False

def run_measure(cmd_list, runs=RUNS, cwd=None):
    times = []
    for _ in range(runs):
        r = subprocess.run(cmd_list, capture_output=True, text=True, cwd=cwd, encoding='utf-8', errors='replace')
        out = (r.stdout or '') + (r.stderr or '')
        m = RESULT_PAT.search(out)
        if m:
            times.append(float(m.group(1)))
    if not times:
        return None
    times.sort()
    return times[len(times)//2]

def bench_title(name):
    print(f'\n=== {name} ===')

def fmt_row(label, ms, baseline):
    if ms is None:
        return f'  {label:20s} FAILED'
    ratio = ms / baseline if baseline else float('inf')
    return f'  {label:20s} {ms:10.1f}ms  ({ratio:.2f}x)'

BENCHES = [
    # (name, hot description, per-language file mapping)
    ('fibonacci(40) 재귀', {
        'geul':   ('geul/native_fib.글', 'compile_geul'),
        'c_msvc': ('c/fibonacci.c', 'compile_msvc'),
        'c_clang':('c/fibonacci.c', 'compile_clang'),
        'c_tcc':  ('c/fibonacci.c', 'compile_tcc'),
        'rust':   ('rust/fibonacci.rs', 'compile_rust'),
        'go':     ('go/fibonacci.go', 'compile_go'),
        'java':   ('java/Fibonacci.java', 'compile_java_Fibonacci'),
        'js':     ('js/fibonacci.js', 'node'),
        'python': ('python/fibonacci.py', 'python'),
    }),
    ('primes sieve(1M)', {
        'geul':   ('geul/native_primes.글', 'compile_geul'),
        'c_msvc': ('c/primes.c', 'compile_msvc'),
        'c_clang':('c/primes.c', 'compile_clang'),
        'c_tcc':  ('c/primes.c', 'compile_tcc'),
        'rust':   ('rust/primes.rs', 'compile_rust'),
        'go':     ('go/primes.go', 'compile_go'),
        'java':   ('java/Primes.java', 'compile_java_Primes'),
        'js':     ('js/primes.js', 'node'),
        'python': ('python/primes.py', 'python'),
    }),
    ('bubblesort(30K)', {
        'geul':   ('geul/native_sort.글', 'compile_geul'),
        'c_msvc': ('c/bubblesort.c', 'compile_msvc'),
        'c_clang':('c/bubblesort.c', 'compile_clang'),
        'c_tcc':  ('c/bubblesort.c', 'compile_tcc'),
        'rust':   ('rust/bubblesort.rs', 'compile_rust'),
        'go':     ('go/bubblesort.go', 'compile_go'),
        'java':   ('java/Bubblesort.java', 'compile_java_Bubblesort'),
        'js':     ('js/bubblesort.js', 'node'),
        'python': ('python/bubblesort.py', 'python'),
    }),
]

def main():
    # First, copy std.gl so 글 can find it next to the source
    # (our compiler looks for std.gl in dist/)
    results = {}
    for bench_name, langs in BENCHES:
        bench_title(bench_name)
        results[bench_name] = {}
        # C baseline first
        c_baseline = None
        for label, (relpath, how) in langs.items():
            src = os.path.join(ROOT, relpath)
            tmp_base = os.path.join(BUILD_DIR, f"{label}_{os.path.splitext(os.path.basename(src))[0]}")
            tmp_exe = tmp_base + ".exe"
            compile_ok = False
            run_cmd = None
            # skip bubblesort on 글 if not present? (handled by ok check below)
            if how == 'compile_msvc':
                compile_ok = compile_msvc(src, tmp_exe); run_cmd = [tmp_exe]
            elif how == 'compile_clang':
                compile_ok = compile_clang(src, tmp_exe); run_cmd = [tmp_exe]
            elif how == 'compile_tcc':
                compile_ok = compile_tcc(src, tmp_exe); run_cmd = [tmp_exe]
            elif how == 'compile_rust':
                compile_ok = compile_rust(src, tmp_exe); run_cmd = [tmp_exe]
            elif how == 'compile_go':
                compile_ok = compile_go(src, tmp_exe); run_cmd = [tmp_exe]
            elif how.startswith('compile_java_'):
                classname = how.split('_')[-1]
                compile_ok = compile_java(src); run_cmd = ["java", "-cp", os.path.dirname(src), classname]
            elif how == 'compile_geul':
                compile_ok = compile_geul(src, tmp_exe); run_cmd = [tmp_exe]
            elif how == 'node':
                compile_ok = True; run_cmd = ["node", src]
            elif how == 'python':
                compile_ok = True; run_cmd = [sys.executable, src]

            if not compile_ok or not run_cmd:
                print(f'  {label:20s} COMPILE FAIL')
                results[bench_name][label] = None
                continue
            ms = run_measure(run_cmd)
            results[bench_name][label] = ms

        # print sorted by speed
        baseline = results[bench_name].get('c_msvc') or results[bench_name].get('c_clang')
        for label in ['c_msvc','c_clang','geul','rust','go','java','c_tcc','js','python']:
            if label in results[bench_name]:
                print(fmt_row(label, results[bench_name][label], baseline))

    # summary table
    print('\n=========================================================')
    print('SUMMARY (ms; ratio to C_MSVC /O2)')
    print('=========================================================')
    cols = ['c_msvc','c_clang','rust','go','geul','java','c_tcc','js','python']
    header = f'{"benchmark":25s}' + ''.join(f'{c:>12s}' for c in cols)
    print(header)
    for bench_name, _ in BENCHES:
        row = f'{bench_name:25s}'
        base = results[bench_name].get('c_msvc')
        for c in cols:
            v = results[bench_name].get(c)
            if v is None:
                row += f'{"-":>12s}'
            else:
                ratio = v/base if base else None
                row += f'{v:>8.1f} ' + (f'({ratio:.1f}x)' if ratio else '')[:4]
                row = row[:len(row)] # keep format stable
        print(row)

    with open(os.path.join(ROOT, 'results', 'comparison_latest.json'), 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

if __name__ == '__main__':
    main()
