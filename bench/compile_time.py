"""Compile-time comparison across languages.

For each language, compile fibonacci.<ext> N times, take median.
Interpreted languages (Python, JS) are listed as startup cost only.
"""
import os, sys, subprocess, time, shutil, statistics

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(ROOT)

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

TMP = os.path.join(ROOT, "build_tmp")
os.makedirs(TMP, exist_ok=True)

def time_cmd(cmd, cwd=None, runs=5):
    times = []
    for _ in range(runs):
        t0 = time.time()
        subprocess.run(cmd, cwd=cwd, capture_output=True)
        times.append((time.time() - t0) * 1000)
    times.sort()
    return times[len(times)//2], min(times)

def fmt(label, pair, ref=None):
    median, mn = pair
    if ref is None:
        return f'  {label:15s} median={median:7.1f}ms  (min={mn:.1f})'
    ratio = median / ref
    return f'  {label:15s} median={median:7.1f}ms  (min={mn:.1f})  {ratio:4.1f}x vs C_msvc'

def main():
    print('=== Compile time comparison (fibonacci source) ===\n')

    # C/MSVC
    src = os.path.join(ROOT, 'c', 'fibonacci.c')
    msvc_cmd = f'"{CL}" /O2 /nologo /utf-8 /I"{MSVC_INC}" /I"{UCRT_INC}" /I"{UM_INC}" /I"{SHARED_INC}" /Fe:"{TMP}\\ct_msvc.exe" /Fo:"{TMP}\\ct_msvc.obj" "{src}" /link /LIBPATH:"{MSVC_LIB}" /LIBPATH:"{UCRT_LIB}" /LIBPATH:"{UM_LIB}"'
    r_msvc = time_cmd(msvc_cmd.replace('"', ''), runs=3)  # msvc is slow, fewer runs
    # use shell for msvc
    times = []
    for _ in range(3):
        t0 = time.time()
        subprocess.run(msvc_cmd, capture_output=True, shell=True)
        times.append((time.time() - t0) * 1000)
    times.sort()
    r_msvc = (times[len(times)//2], min(times))

    # Clang
    r_clang = time_cmd([CLANG, "-O2", "-o", f"{TMP}\\ct_clang.exe", src])

    # TCC
    r_tcc = time_cmd([TCC, "-o", f"{TMP}\\ct_tcc.exe", src])

    # Rust
    rs_src = os.path.join(ROOT, 'rust', 'fibonacci.rs')
    r_rust = time_cmd(["rustc", "-O", "-o", f"{TMP}\\ct_rust.exe", rs_src])

    # Go
    go_src = os.path.join(ROOT, 'go', 'fibonacci.go')
    r_go = time_cmd(["go", "build", "-o", f"{TMP}\\ct_go.exe", go_src])

    # Java
    jv_src = os.path.join(ROOT, 'java', 'Fibonacci.java')
    r_java = time_cmd(["javac", jv_src, "-d", TMP])

    # 글
    gl_src_abs = os.path.abspath(os.path.join(ROOT, 'geul', 'native_fib.글'))
    gl_dir = os.path.dirname(gl_src_abs)
    gl_file = os.path.basename(gl_src_abs)
    exe_gl = os.path.splitext(gl_src_abs)[0] + ".exe"
    times = []
    for _ in range(7):
        if os.path.exists(exe_gl):
            try: os.remove(exe_gl)
            except: pass
        t0 = time.time()
        subprocess.run([GEUL, "--no-pause", gl_file], cwd=gl_dir, capture_output=True)
        times.append((time.time() - t0) * 1000)
    times.sort()
    r_geul = (times[len(times)//2], min(times))

    ref = r_msvc[0]
    print(fmt('C (MSVC /O2)', r_msvc, ref))
    print(fmt('C (clang -O2)', r_clang, ref))
    print(fmt('C (TCC)', r_tcc, ref))
    print(fmt('Rust (rustc -O)', r_rust, ref))
    print(fmt('Go (go build)', r_go, ref))
    print(fmt('Java (javac)', r_java, ref))
    print(fmt('글 (optimized)', r_geul, ref))

    # Source size reference
    print('\n=== Source file sizes ===')
    for rel in ['c/fibonacci.c', 'rust/fibonacci.rs', 'go/fibonacci.go',
                'java/Fibonacci.java', 'geul/native_fib.글']:
        p = os.path.join(ROOT, rel)
        sz = os.path.getsize(p)
        with open(p, 'rb') as f: lines = f.read().count(b'\n')
        print(f'  {rel:30s} {sz:6d} bytes  {lines:3d} lines')

if __name__ == '__main__':
    main()
