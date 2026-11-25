"""글(geul) 프로그램의 표본 프로파일러 — 어느 함수에서 시간을 쓰는가.

    python -I -X utf8 research/cpu/표본재기.py <소스.gl> [--간격 1] [--깊이 64] [--위 30] [--출력 결과.json] -- <프로그램 인자...>

1. 참조 구현(ref/)으로 소스를 컴파일해 실행 파일과 함수 → 코드 오프셋 표를 얻는다. 두 구현이 같은 바이트를 내므로(D-12) 이 실행
   파일은 자체 컴파일러가 낸 것과 같다 — 적어 둔 sha256 으로 견줄 수 있다.
2. 그 실행 파일을 띄우고, 간격마다 주 스레드를 멈춰 RIP 와 RBP 사슬(글의 함수는 push rbp · mov rbp, rsp 로 시작한다)을 읽는다.
   RIP 가 이미지 밖(kernel32 · ntdll 등)이면 '(외부)'로 세고, 스택에서 이미지 안의 첫 반환 주소를 찾아 부른 쪽으로 잇는다.
3. 자기 시간(맨 위 함수)과 포함 시간(사슬에 든 함수)을 센다. 인라인된 함수는 부른 쪽에 섞인다(D-31).
고정 이미지 베이스(재배치 없음)라 주소가 실행마다 같다.
"""
import argparse, bisect, collections, ctypes, ctypes.wintypes as W, hashlib, io, json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "ref"))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

IMAGE_BASE = 0x140000000
TEXT_RVA = 0x1000


def compile_with_map(src, exe):
    from geul import driver, sema, lower, inline, codegen, pe
    captured = []

    class 잡는Asm(codegen.Asm):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            captured.append(self)

    codegen.Asm = 잡는Asm
    program = driver.load_program(src, os.path.join(ROOT, "표준"))
    unit = sema.analyze(program)
    ir = inline.run(lower.lower_program(unit))
    img = codegen.generate(ir)
    pe.write_pe(img, exe, 3)
    labels = captured[-1].labels
    # 함수 라벨만 남긴다: 함수 이름과 같은 라벨
    fnames = set(f.name for f in ir.functions)
    starts = sorted((off, name) for name, off in labels.items() if name in fnames)
    entry_off = getattr(img, "entry", None)
    if entry_off is not None:
        starts.append((entry_off, "(시작 코드)"))
        starts.sort()
    return starts, len(img.code)


k32 = ctypes.WinDLL("kernel32", use_last_error=True)


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", W.DWORD), ("lpReserved", W.LPWSTR), ("lpDesktop", W.LPWSTR), ("lpTitle", W.LPWSTR),
                ("dwX", W.DWORD), ("dwY", W.DWORD), ("dwXSize", W.DWORD), ("dwYSize", W.DWORD),
                ("dwXCountChars", W.DWORD), ("dwYCountChars", W.DWORD), ("dwFillAttribute", W.DWORD),
                ("dwFlags", W.DWORD), ("wShowWindow", W.WORD), ("cbReserved2", W.WORD), ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", W.HANDLE), ("hStdOutput", W.HANDLE), ("hStdError", W.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", W.HANDLE), ("hThread", W.HANDLE), ("dwProcessId", W.DWORD), ("dwThreadId", W.DWORD)]


k32.CreateProcessW.argtypes = [W.LPCWSTR, W.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, W.BOOL, W.DWORD, ctypes.c_void_p,
                               W.LPCWSTR, ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)]
k32.SuspendThread.argtypes = [W.HANDLE]
k32.SuspendThread.restype = W.DWORD
k32.ResumeThread.argtypes = [W.HANDLE]
k32.ResumeThread.restype = W.DWORD
k32.GetThreadContext.argtypes = [W.HANDLE, ctypes.c_void_p]
k32.ReadProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
k32.WaitForSingleObject.restype = W.DWORD
k32.GetExitCodeProcess.argtypes = [W.HANDLE, ctypes.POINTER(W.DWORD)]
k32.CloseHandle.argtypes = [W.HANDLE]

CONTEXT_AMD64 = 0x00100000
CONTEXT_FLAGS = CONTEXT_AMD64 | 0x1 | 0x2      # CONTROL | INTEGER


def profile(exe, args, text_size, interval_ms, depth):
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    pi = PROCESS_INFORMATION()
    cmd = ctypes.create_unicode_buffer(subprocess.list2cmdline([exe] + args))
    if not k32.CreateProcessW(None, cmd, None, None, False, 0, None, None, ctypes.byref(si), ctypes.byref(pi)):
        raise OSError(ctypes.get_last_error(), "CreateProcessW")
    winmm = ctypes.WinDLL("winmm")
    winmm.timeBeginPeriod(1)
    raw = ctypes.create_string_buffer(1232 + 16)
    base = (ctypes.addressof(raw) + 15) & ~15
    lo, hi = IMAGE_BASE + TEXT_RVA, IMAGE_BASE + TEXT_RVA + text_size
    stacks = []
    buf = (ctypes.c_uint64 * 2)()
    scan = (ctypes.c_uint64 * 64)()
    got = ctypes.c_size_t()
    t0 = time.perf_counter()
    try:
        while k32.WaitForSingleObject(pi.hProcess, 0) == 0x102:       # WAIT_TIMEOUT
            if k32.SuspendThread(pi.hThread) == 0xFFFFFFFF:
                break
            ctypes.c_uint32.from_address(base + 0x30).value = CONTEXT_FLAGS
            frames = []
            if k32.GetThreadContext(pi.hThread, base):
                rip = ctypes.c_uint64.from_address(base + 0xF8).value
                rsp = ctypes.c_uint64.from_address(base + 0x98).value
                rbp = ctypes.c_uint64.from_address(base + 0xA0).value
                frames.append(rip)
                if not (lo <= rip < hi):
                    # 이미지 밖: 스택에서 이미지 안의 첫 반환 주소(부른 쪽)
                    if k32.ReadProcessMemory(pi.hProcess, rsp, scan, ctypes.sizeof(scan), ctypes.byref(got)):
                        for v in scan:
                            if lo <= v < hi:
                                frames.append(v)
                                break
                bp = rbp
                for _ in range(depth):
                    if not bp or not k32.ReadProcessMemory(pi.hProcess, bp, buf, 16, ctypes.byref(got)):
                        break
                    prev, ret = buf[0], buf[1]
                    if not (lo <= ret < hi):
                        break
                    frames.append(ret)
                    if prev <= bp:
                        break
                    bp = prev
            k32.ResumeThread(pi.hThread)
            if frames:
                stacks.append(frames)
            time.sleep(interval_ms / 1000.0)
    finally:
        winmm.timeEndPeriod(1)
    k32.WaitForSingleObject(pi.hProcess, 0xFFFFFFFF)
    code = W.DWORD()
    k32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
    k32.CloseHandle(pi.hThread)
    k32.CloseHandle(pi.hProcess)
    return stacks, time.perf_counter() - t0, code.value


def main():
    argv = sys.argv[1:]
    prog_args = []
    if "--" in argv:
        k = argv.index("--")
        argv, prog_args = argv[:k], argv[k + 1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("소스")
    ap.add_argument("--간격", type=float, default=1.0)
    ap.add_argument("--깊이", type=int, default=64)
    ap.add_argument("--위", type=int, default=30)
    ap.add_argument("--출력")
    ap.add_argument("--실행파일", help="컴파일한 실행 파일을 둘 곳 (기본: 임시 폴더)")
    a = ap.parse_args(argv)
    exe = a.실행파일 or os.path.join(tempfile.mkdtemp(prefix="geul_prof_"), "prog.exe")
    t0 = time.time()
    starts, text_size = compile_with_map(a.소스, exe)
    sha = hashlib.sha256(open(exe, "rb").read()).hexdigest()
    print(f"컴파일 {time.time() - t0:.1f} 초 · 함수 {len(starts)} · 코드 {text_size} B · sha256 {sha[:16]}…", flush=True)
    offs = [o for o, _ in starts]

    def name_of(addr):
        if not (IMAGE_BASE + TEXT_RVA <= addr < IMAGE_BASE + TEXT_RVA + text_size):
            return "(외부)"
        i = bisect.bisect_right(offs, addr - IMAGE_BASE - TEXT_RVA) - 1
        return starts[i][1] if i >= 0 else "(?)"

    stacks, wall, code = profile(exe, prog_args, text_size, a.간격, a.깊이)
    n = len(stacks)
    self_c = collections.Counter()
    incl_c = collections.Counter()
    for fr in stacks:
        names = [name_of(x) for x in fr]
        self_c[names[0]] += 1
        for nm in set(names):
            incl_c[nm] += 1
    print(f"실행 {wall:.2f} 초 · 종료 코드 {code} · 표본 {n}")
    print(f"\n자기 시간 (위 {a.위})")
    for nm, c in self_c.most_common(a.위):
        print(f"  {100.0 * c / n:6.2f} %  {nm}")
    print(f"\n포함 시간 (위 {a.위})")
    for nm, c in incl_c.most_common(a.위):
        print(f"  {100.0 * c / n:6.2f} %  {nm}")
    if a.출력:
        json.dump({"실행파일_sha256": sha, "실행_초": wall, "표본": n, "자기": self_c.most_common(), "포함": incl_c.most_common()},
                  open(a.출력, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
