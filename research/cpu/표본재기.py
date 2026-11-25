"""글(geul) 프로그램의 표본 프로파일러 — 어느 함수에서 시간을 쓰는가, 운영체제 안의 시간은 무엇인가.

    python -I -X utf8 research/cpu/표본재기.py <소스.gl> [--간격 1] [--깊이 64] [--위 30] [--반복 1] [--출력 결과.json] -- <프로그램 인자...>

1. 참조 구현(ref/)으로 소스를 컴파일해 실행 파일과 함수 → 코드 오프셋 표를 얻는다. 두 구현이 같은 바이트를 내므로(D-12) 이 실행
   파일은 자체 컴파일러가 낸 것과 같다 — 적어 둔 sha256 으로 견줄 수 있다.
2. 그 실행 파일을 띄우고, 간격마다 주 스레드를 멈춰 레지스터와 스택(RSP 에서 스택 꼭대기까지)을 떠 온 뒤 곧 다시 돌린다. 사슬은
   뜬 사본에서 걷는다 — 글의 함수는 push rbp · mov rbp, rsp 로 시작하므로 RBP 사슬을 따라 올라간다.
3. RIP 가 이미지 밖(ntdll · kernelbase 등 — '외부')이면:
   - 그 주소가 든 DLL 과 함수를 찾는다 — 프로세스의 모듈 목록(툴헬프 스냅숏)과 DLL 파일의 .pdata(함수 경계) · 내보내기 표(이름).
     이름이 없는 내부 함수는 '(내부 +RVA)', .pdata 가 없는 잎 함수는 앞선 내보내기 이름에 '≈'.
   - 운영체제 프레임을 그 DLL 의 풀기 정보(UNWIND_INFO — 윈도가 예외 처리에 쓰는 것)로 풀어 글 코드로 돌아가는 반환 주소와 복원된
     RBP 를 얻고, 거기서 글 쪽 사슬을 잇는다. 풀린 반환 주소는 바로 앞이 call 이어야 받는다(아니면 '부른 쪽 모름').
4. 자기 시간(맨 위 함수)과 포함 시간(사슬에 든 함수), 외부 시간의 운영체제 함수별 · 부른 글 함수별 몫을 센다. 인라인된 함수는
   부른 쪽에 섞인다(D-31 · D-55). 시스템 호출 안(커널)의 시간은 그 호출의 ntdll 문(Nt…)으로 잡힌다.
고정 이미지 베이스(재배치 없음)라 글 쪽 주소가 실행마다 같다. 환경 변수 GEUL_REPO 를 주면 그 저장소의 참조 구현 · 표준으로
컴파일한다(다른 판의 컴파일러가 낸 실행 파일을 잴 때). 다른 스크립트가 불러 쓸 수 있다: 잡아컴파일 · profile · 이름사슬 · 외부표.
"""
import argparse, bisect, collections, ctypes, ctypes.wintypes as W, hashlib, io, json, os, struct, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("GEUL_REPO") or os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "ref"))
if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

IMAGE_BASE = 0x140000000
TEXT_RVA = 0x1000


class 지도:
    """실행 파일의 함수 지도: 코드 오프셋 → 함수 이름, 코드 바이트(반환 주소의 앞이 call 인가)."""

    def __init__(self, starts, code):
        self.starts = starts                     # [(오프셋, 이름)] 정렬
        self.offs = [o for o, _ in starts]
        self.code = code
        self.lo = IMAGE_BASE + TEXT_RVA
        self.hi = self.lo + len(code)

    def 안(self, addr):
        return self.lo <= addr < self.hi

    def 이름(self, addr):
        if not self.안(addr):
            return "(외부)"
        i = bisect.bisect_right(self.offs, addr - self.lo) - 1
        return self.starts[i][1] if i >= 0 else "(?)"

    def 부른자리(self, addr):
        """addr 바로 앞이 call 인가 — call rel32(E8), call [rip+disp32](FF 15), call r64(FF D0+r · 41 FF D0+r)."""
        o, c = addr - self.lo, self.code
        return ((o >= 5 and c[o - 5] == 0xE8) or (o >= 6 and c[o - 6] == 0xFF and c[o - 5] == 0x15)
                or (o >= 2 and c[o - 2] == 0xFF and 0xD0 <= c[o - 1] <= 0xD7)
                or (o >= 3 and c[o - 3] == 0x41 and c[o - 2] == 0xFF and 0xD0 <= c[o - 1] <= 0xD7))


def 잡아컴파일(src, exe, std_dir=None):
    """참조 구현으로 컴파일하며 함수 지도를 잡는다 → (지도, 프로그램 AST)."""
    from geul import driver, sema, lower, inline, codegen, pe
    asms = []

    class 잡는Asm(codegen.Asm):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            asms.append(self)

    옛Asm = codegen.Asm
    codegen.Asm = 잡는Asm
    try:
        program = driver.load_program(src, std_dir or os.path.join(ROOT, "표준"))
        ir = inline.run(lower.lower_program(sema.analyze(program)))
        img = codegen.generate(ir)
        pe.write_pe(img, exe, 3)
    finally:
        codegen.Asm = 옛Asm
    labels = asms[-1].labels
    fnames = set(f.name for f in ir.functions)
    starts = sorted((off, name) for name, off in labels.items() if name in fnames)
    entry_off = getattr(img, "entry", None)
    if entry_off is not None:
        starts.append((entry_off, "(시작 코드)"))
        starts.sort()
    return 지도(starts, bytes(img.code)), program


def compile_with_map(src, exe):
    """옛 꼴 — (함수 시작 표, 코드 크기)."""
    m, _ = 잡아컴파일(src, exe)
    return m.starts, len(m.code)


# ---------------------------------------------------------------- 운영체제 DLL: 이름 붙이기와 스택 풀기

def _연산크기(op, info):
    """풀기 코드 하나가 차지하는 칸 수 (UNWIND_CODE 2 바이트 단위)."""
    if op == 1:
        return 2 if info == 0 else 3                 # ALLOC_LARGE
    if op in (4, 6, 8):
        return 2                                     # SAVE_NONVOL · EPILOG · SAVE_XMM128
    if op in (5, 9):
        return 3                                     # SAVE_NONVOL_FAR · SAVE_XMM128_FAR
    return 1


class DLL:
    """시스템 DLL 파일 하나: 내보내기 이름, .pdata 함수 항목, 풀기 정보(UNWIND_INFO)."""
    캐시 = {}

    @classmethod
    def 열기(cls, path):
        if path not in cls.캐시:
            try:
                cls.캐시[path] = cls(path)
            except (OSError, struct.error, ValueError, IndexError):
                cls.캐시[path] = None
        return cls.캐시[path]

    def __init__(self, path):
        d = self.d = open(path, "rb").read()
        self.이름 = os.path.basename(path).lower()
        e = struct.unpack_from("<I", d, 0x3C)[0]
        nsec = struct.unpack_from("<H", d, e + 6)[0]
        optsize = struct.unpack_from("<H", d, e + 20)[0]
        opt = e + 24
        if struct.unpack_from("<H", d, opt)[0] != 0x20B:              # PE32+ 만
            raise ValueError(path)
        exp_rva, exp_size = struct.unpack_from("<II", d, opt + 112)
        pdt_rva, pdt_size = struct.unpack_from("<II", d, opt + 112 + 24)
        self.secs = []
        for k in range(nsec):
            vsize, va, rsize, raw = struct.unpack_from("<IIII", d, opt + optsize + 40 * k + 8)
            self.secs.append((va, max(vsize, rsize), raw))
        self.exports = {}
        o = self.off(exp_rva) if exp_size else None
        if o is not None:
            _, nname, afun, aname, aord = struct.unpack_from("<IIIII", d, o + 20)
            fo, no, oo = self.off(afun), self.off(aname), self.off(aord)
            for i in range(nname):
                nrva = struct.unpack_from("<I", d, no + 4 * i)[0]
                frva = struct.unpack_from("<I", d, fo + 4 * struct.unpack_from("<H", d, oo + 2 * i)[0])[0]
                if exp_rva <= frva < exp_rva + exp_size:
                    continue                                          # 다른 DLL 로 넘기는 이름
                p = self.off(nrva)
                self.exports.setdefault(frva, d[p:d.index(b"\0", p)].decode("ascii", "replace"))
        self.ex = sorted(self.exports)
        o = self.off(pdt_rva) if pdt_size else None
        self.fe = sorted(struct.unpack_from("<III", d, o + 12 * k) for k in range(pdt_size // 12)) if o is not None else []
        self.fb = [f[0] for f in self.fe]

    def off(self, rva):
        for va, size, raw in self.secs:
            if va <= rva < va + size:
                return raw + rva - va
        return None

    def 항목(self, rva):
        k = bisect.bisect_right(self.fb, rva) - 1
        return self.fe[k] if k >= 0 and rva < self.fe[k][1] else None

    def 머리(self, ent):
        """이어진 조각(간접 항목 · UNW_FLAG_CHAININFO)이면 머리 함수의 시작 RVA."""
        d, (head, _, u) = self.d, ent
        for _ in range(16):
            if u & 1:
                q = self.off(u & ~1)
                if q is None:
                    break
                head, _, u = struct.unpack_from("<III", d, q)
                continue
            q = self.off(u)
            if q is None or not (d[q] >> 3) & 4:
                break
            head, _, u = struct.unpack_from("<III", d, q + 4 + 2 * ((d[q + 2] + 1) & ~1))
        return head

    def 이름붙이기(self, rva):
        ent = self.항목(rva)
        if ent:
            head = self.머리(ent)
            nm = self.exports.get(head)
            return f"{self.이름}!{nm}" if nm else f"{self.이름}!(내부 +{head:#x})"
        j = bisect.bisect_right(self.ex, rva) - 1
        return f"{self.이름}!≈{self.exports[self.ex[j]]}" if j >= 0 else f"{self.이름}!(?)"

    def _맺음말(self, rva, regs, read):
        """RIP 가 맺음말(add rsp · lea rsp · pop … · ret) 안이면 그것을 흉내내 부른 쪽 RIP 를, 아니면 False."""
        p, d = self.off(rva), self.d
        if p is None:
            return False
        rsp, seen = regs[4], False
        if d[p:p + 3] == b"\x48\x83\xc4":
            rsp, p, seen = rsp + d[p + 3], p + 4, True
        elif d[p:p + 3] == b"\x48\x81\xc4":
            rsp, p, seen = rsp + struct.unpack_from("<I", d, p + 3)[0], p + 7, True
        elif d[p] in (0x48, 0x49) and d[p + 1] == 0x8D and (d[p + 2] & 0xF8) == 0x60:      # lea rsp, [r+disp8]
            r = (d[p + 2] & 7) + (8 if d[p] == 0x49 else 0)
            rsp, p, seen = regs[r] + struct.unpack_from("<b", d, p + 3)[0], p + 4, True
        pops = []
        while True:
            if 0x58 <= d[p] <= 0x5F:
                pops.append(d[p] - 0x58)
                p += 1
            elif d[p] == 0x41 and 0x58 <= d[p + 1] <= 0x5F:
                pops.append(8 + d[p + 1] - 0x58)
                p += 2
            else:
                break
        끝 = d[p] in (0xC3, 0xC2) or d[p:p + 2] == b"\xf3\xc3"
        if not 끝 and not ((seen or pops) and (d[p] == 0xE9 or d[p:p + 2] == b"\xff\x25" or d[p:p + 3] == b"\x48\xff\x25")):
            return False
        for r in pops:
            v = read(rsp)
            if v is None:
                return None
            regs[r], rsp = v, rsp + 8
        ret = read(rsp)
        if ret is None:
            return None
        regs[4] = rsp + 8
        return ret

    def 풀기(self, rva, regs, read):
        """프레임 하나를 푼다: 이 DLL 안의 RIP(rva)와 정수 레지스터 16 개(RSP 는 4) → 부른 쪽 RIP. 레지스터는 그 자리에서
        부른 쪽의 값으로 바뀐다(비휘발 레지스터 복원). 못 풀면 None. 윈도의 RtlVirtualUnwind 와 같은 규칙(맺음말은 흔한 꼴만)."""
        d = self.d
        ent = self.항목(rva)
        if ent is None:                                              # 잎 함수: 반환 주소가 [rsp]
            ret = read(regs[4])
            if ret is None:
                return None
            regs[4] += 8
            return ret
        begin, _, u = ent
        first = True
        while True:
            if u & 1:                                                # 간접 항목
                q = self.off(u & ~1)
                if q is None:
                    return None
                begin, _, u = struct.unpack_from("<III", d, q)
                continue
            q = self.off(u)
            if q is None:
                return None
            flags, prolog, count, fr = d[q] >> 3, d[q + 1], d[q + 2], d[q + 3]
            freg, foff = fr & 15, fr >> 4
            if first and rva - begin < prolog:
                po = rva - begin                                     # 머리말 안: 그 자리까지 실행된 것만
            else:
                po = 1 << 30
                if first:
                    r = self._맺음말(rva, regs, read)
                    if r is not False:
                        return r
            first = False
            codes = q + 4
            frame = regs[4]
            if freg:
                i = 0
                while i < count:
                    off_, oi = d[codes + 2 * i], d[codes + 2 * i + 1]
                    if oi & 15 == 3 and po >= off_:
                        frame = regs[freg] - foff * 16
                    i += _연산크기(oi & 15, oi >> 4)
            i = 0
            while i < count:
                off_, oi = d[codes + 2 * i], d[codes + 2 * i + 1]
                op, info = oi & 15, oi >> 4
                n = _연산크기(op, info)
                if po >= off_:
                    if op == 0:                                      # PUSH_NONVOL
                        v = read(regs[4])
                        if v is None:
                            return None
                        regs[info] = v
                        regs[4] += 8
                    elif op == 1:                                    # ALLOC_LARGE
                        regs[4] += (struct.unpack_from("<H", d, codes + 2 * i + 2)[0] * 8 if info == 0
                                    else struct.unpack_from("<I", d, codes + 2 * i + 2)[0])
                    elif op == 2:                                    # ALLOC_SMALL
                        regs[4] += info * 8 + 8
                    elif op == 3:                                    # SET_FPREG
                        regs[4] = frame
                    elif op in (4, 5):                               # SAVE_NONVOL(_FAR)
                        disp = (struct.unpack_from("<H", d, codes + 2 * i + 2)[0] * 8 if op == 4
                                else struct.unpack_from("<I", d, codes + 2 * i + 2)[0])
                        v = read(frame + disp)
                        if v is None:
                            return None
                        regs[info] = v
                    elif op == 10:                                   # PUSH_MACHFRAME: 예외 · 인터럽트 틀
                        b = regs[4] + (8 if info else 0)
                        rip, rsp = read(b), read(b + 24)
                        if rip is None or rsp is None:
                            return None
                        regs[4] = rsp
                        return rip
                i += n
            if flags & 4:                                            # UNW_FLAG_CHAININFO: 머리 함수의 풀기 정보로 이어서
                begin, _, u = struct.unpack_from("<III", d, codes + 2 * ((count + 1) & ~1))
                continue
            break
        ret = read(regs[4])
        if ret is None:
            return None
        regs[4] += 8
        return ret


# ---------------------------------------------------------------- 프로세스 띄우기 · 표본

k32 = ctypes.WinDLL("kernel32", use_last_error=True)


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", W.DWORD), ("lpReserved", W.LPWSTR), ("lpDesktop", W.LPWSTR), ("lpTitle", W.LPWSTR),
                ("dwX", W.DWORD), ("dwY", W.DWORD), ("dwXSize", W.DWORD), ("dwYSize", W.DWORD),
                ("dwXCountChars", W.DWORD), ("dwYCountChars", W.DWORD), ("dwFillAttribute", W.DWORD),
                ("dwFlags", W.DWORD), ("wShowWindow", W.WORD), ("cbReserved2", W.WORD), ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", W.HANDLE), ("hStdOutput", W.HANDLE), ("hStdError", W.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", W.HANDLE), ("hThread", W.HANDLE), ("dwProcessId", W.DWORD), ("dwThreadId", W.DWORD)]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", W.DWORD), ("th32ModuleID", W.DWORD), ("th32ProcessID", W.DWORD), ("GlblcntUsage", W.DWORD),
                ("ProccntUsage", W.DWORD), ("modBaseAddr", ctypes.c_void_p), ("modBaseSize", W.DWORD), ("hModule", W.HMODULE),
                ("szModule", ctypes.c_wchar * 256), ("szExePath", ctypes.c_wchar * 260)]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p), ("AllocationProtect", W.DWORD),
                ("PartitionId", W.WORD), ("RegionSize", ctypes.c_size_t), ("State", W.DWORD), ("Protect", W.DWORD),
                ("Type", W.DWORD)]


k32.CreateProcessW.argtypes = [W.LPCWSTR, W.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, W.BOOL, W.DWORD, ctypes.c_void_p,
                               W.LPCWSTR, ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)]
k32.SuspendThread.argtypes = [W.HANDLE]
k32.SuspendThread.restype = W.DWORD
k32.ResumeThread.argtypes = [W.HANDLE]
k32.ResumeThread.restype = W.DWORD
k32.GetThreadContext.argtypes = [W.HANDLE, ctypes.c_void_p]
k32.ReadProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.VirtualQueryEx.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t]
k32.VirtualQueryEx.restype = ctypes.c_size_t
k32.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
k32.WaitForSingleObject.restype = W.DWORD
k32.GetExitCodeProcess.argtypes = [W.HANDLE, ctypes.POINTER(W.DWORD)]
k32.CloseHandle.argtypes = [W.HANDLE]
k32.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
k32.Module32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MODULEENTRY32W)]
k32.Module32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MODULEENTRY32W)]

CONTEXT_AMD64 = 0x00100000
CONTEXT_FLAGS = CONTEXT_AMD64 | 0x1 | 0x2      # CONTROL | INTEGER
INVALID_HANDLE = ctypes.c_void_p(-1).value
STACK_CAP = 1 << 20                            # 한 표본에 떠 오는 스택의 끝 — 1 MB(기본 예약 크기)


def 모듈목록(pid):
    """프로세스에 올라온 모듈 [(시작, 끝, 경로)] — 툴헬프 스냅숏. 막 뜬 프로세스는 ERROR_BAD_LENGTH(24)로 몇 번 실패할 수 있다."""
    h = None
    for _ in range(50):
        h = k32.CreateToolhelp32Snapshot(0x8 | 0x10, pid)            # TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32
        if h and h != INVALID_HANDLE:
            break
        if ctypes.get_last_error() != 24:
            return []
    else:
        return []
    out = []
    me = MODULEENTRY32W()
    me.dwSize = ctypes.sizeof(me)
    ok = k32.Module32FirstW(h, ctypes.byref(me))
    while ok:
        if me.modBaseAddr:
            out.append((me.modBaseAddr, me.modBaseAddr + me.modBaseSize, me.szExePath))
        ok = k32.Module32NextW(h, ctypes.byref(me))
    k32.CloseHandle(h)
    return sorted(out)


def profile(exe, args, text_size, interval_ms, depth, 함수지도=None, cwd=None):
    """→ (표본들, 벽시계 초, 종료 코드, 모듈 목록). 표본 = [RIP, 글 쪽 반환 주소 …].
    RIP 가 외부면 둘째 칸부터가 운영체제 프레임을 풀어 찾은 글 쪽 사슬이다(못 찾으면 없음). 함수지도(지도)를 주면 풀린 반환 주소의
    바로 앞이 call 인지 확인한다."""
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    pi = PROCESS_INFORMATION()
    cmd = ctypes.create_unicode_buffer(subprocess.list2cmdline([exe] + args))
    if not k32.CreateProcessW(None, cmd, None, None, False, 0, None, cwd, ctypes.byref(si), ctypes.byref(pi)):
        raise OSError(ctypes.get_last_error(), "CreateProcessW")
    winmm = ctypes.WinDLL("winmm")
    winmm.timeBeginPeriod(1)
    raw = ctypes.create_string_buffer(1232 + 16)
    base = (ctypes.addressof(raw) + 15) & ~15
    lo, hi = IMAGE_BASE + TEXT_RVA, IMAGE_BASE + TEXT_RVA + text_size
    stacks = []
    mods, mod_los = [], []
    stackbuf = ctypes.create_string_buffer(STACK_CAP)
    got = ctypes.c_size_t()
    mbi = MEMORY_BASIC_INFORMATION()
    top = 0
    t0 = time.perf_counter()
    try:
        while k32.WaitForSingleObject(pi.hProcess, 0) == 0x102:       # WAIT_TIMEOUT
            if k32.SuspendThread(pi.hThread) == 0xFFFFFFFF:
                break
            ctypes.c_uint32.from_address(base + 0x30).value = CONTEXT_FLAGS
            ok = k32.GetThreadContext(pi.hThread, base)
            n = 0
            if ok:
                regs = [ctypes.c_uint64.from_address(base + 0x78 + 8 * r).value for r in range(16)]
                rip = ctypes.c_uint64.from_address(base + 0xF8).value
                rsp = regs[4]
                if not (top > rsp) and k32.VirtualQueryEx(pi.hProcess, rsp, ctypes.byref(mbi), ctypes.sizeof(mbi)):
                    top = mbi.BaseAddress + mbi.RegionSize                 # 스택 꼭대기(스레드가 끝날 때까지 같다)
                if top > rsp and k32.ReadProcessMemory(pi.hProcess, rsp, stackbuf, min(top - rsp, STACK_CAP), ctypes.byref(got)):
                    n = got.value
            k32.ResumeThread(pi.hThread)
            if ok:
                stack = ctypes.string_at(stackbuf, n)

                def read(a, rsp=rsp, stack=stack):
                    o = a - rsp
                    return struct.unpack_from("<Q", stack, o)[0] if 0 <= o <= len(stack) - 8 else None

                frames = [rip]
                bp = regs[5]
                if not (lo <= rip < hi):
                    pc = rip
                    for _ in range(32):                                # 운영체제 프레임을 푼다
                        i = bisect.bisect_right(mod_los, pc) - 1
                        if i < 0 or pc >= mods[i][1]:
                            mods = 모듈목록(pi.dwProcessId)
                            mod_los = [m[0] for m in mods]
                            i = bisect.bisect_right(mod_los, pc) - 1
                            if i < 0 or pc >= mods[i][1]:
                                pc = None
                                break
                        dll = DLL.열기(mods[i][2])
                        pc = dll.풀기(pc - mods[i][0], regs, read) if dll is not None else None
                        if pc is None or lo <= pc < hi:
                            break
                    if pc is not None and lo <= pc < hi and (함수지도 is None or 함수지도.부른자리(pc)):
                        frames.append(pc)
                        bp = regs[5]                                   # 풀며 복원된 RBP — 부른 글 함수의 틀
                    else:
                        bp = 0
                for _ in range(depth):
                    prev, ret = read(bp) if bp else None, read(bp + 8) if bp else None
                    if prev is None or ret is None or not (lo <= ret < hi):
                        break
                    frames.append(ret)
                    if prev <= bp:
                        break
                    bp = prev
                stacks.append(frames)
            time.sleep(interval_ms / 1000.0)
    finally:
        winmm.timeEndPeriod(1)
    k32.WaitForSingleObject(pi.hProcess, 0xFFFFFFFF)
    code = W.DWORD()
    k32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
    k32.CloseHandle(pi.hThread)
    k32.CloseHandle(pi.hProcess)
    return stacks, time.perf_counter() - t0, code.value, mods


def 외부이름(mods, addr):
    """운영체제 쪽 주소 → 'dll!함수'."""
    los = [m[0] for m in mods]
    i = bisect.bisect_right(los, addr) - 1
    if i < 0 or addr >= mods[i][1]:
        return "(모르는 곳)"
    dll = DLL.열기(mods[i][2])
    return dll.이름붙이기(addr - mods[i][0]) if dll is not None else os.path.basename(mods[i][2]).lower() + "!(?)"


def 이름사슬(stacks, mods, 함수지도):
    """표본들 → [(맨 위 이름, 글 함수 이름 사슬)]. 맨 위가 외부면 'dll!함수'이고, 사슬의 첫 칸이 그것을 부른 글 함수다."""
    out = []
    for fr in stacks:
        top = 함수지도.이름(fr[0]) if 함수지도.안(fr[0]) else 외부이름(mods, fr[0])
        out.append((top, [함수지도.이름(x) for x in fr if 함수지도.안(x)]))
    return out


def 외부인가(이름):
    return "!" in 이름 or 이름.startswith("(모르는")


def 외부표(named, top=20, 단계=3):
    """외부 표본의 몫 → 줄들: 운영체제 함수별, 부른 글 함수별, 부른 글 함수의 사슬(단계 만큼), 부른 글 함수 → 운영체제 함수."""
    n = len(named)
    ext = [(t, ch) for t, ch in named if 외부인가(t)]
    m = len(ext)
    lines = [f"\n외부 — 운영체제 안 {100.0 * m / max(n, 1):.1f} % (표본 {m}). 앞은 전체 대비, 괄호는 외부 안의 몫"]
    if not m:
        return lines
    모름 = "(부른 쪽 모름)"
    tables = (("운영체제 함수별", collections.Counter(t for t, _ in ext)),
              ("부른 글 함수별", collections.Counter(ch[0] if ch else 모름 for _, ch in ext)),
              (f"부른 글 함수의 사슬 {단계} 단계 (바로 부른 함수 < 그것을 부른 함수 < …)",
               collections.Counter(" < ".join(ch[:단계]) if ch else 모름 for _, ch in ext)),
              ("부른 글 함수 → 운영체제 함수", collections.Counter(f"{ch[0] if ch else 모름} → {t}" for t, ch in ext)))
    for 제목, c in tables:
        lines.append(f"\n  {제목} (위 {top})")
        for nm, k in c.most_common(top):
            lines.append(f"    {100.0 * k / n:6.2f} % ({100.0 * k / m:5.1f} %)  {nm}")
    return lines


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
    ap.add_argument("--반복", type=int, default=1, help="프로그램을 이만큼 돌려 표본을 모은다")
    ap.add_argument("--출력")
    ap.add_argument("--실행파일", help="컴파일한 실행 파일을 둘 곳 (기본: 임시 폴더)")
    a = ap.parse_args(argv)
    exe = a.실행파일 or os.path.join(tempfile.mkdtemp(prefix="geul_prof_"), "prog.exe")
    t0 = time.time()
    m, _ = 잡아컴파일(a.소스, exe)
    sha = hashlib.sha256(open(exe, "rb").read()).hexdigest()
    print(f"컴파일 {time.time() - t0:.1f} 초 · 함수 {len(m.starts)} · 코드 {len(m.code)} B · sha256 {sha[:16]}…", flush=True)
    named, walls = [], []
    for _ in range(a.반복):
        stacks, wall, code, mods = profile(exe, prog_args, len(m.code), a.간격, a.깊이, m)
        if code != 0:
            print(f"종료 코드 {code}")
        named += 이름사슬(stacks, mods, m)
        walls.append(wall)
    n = len(named)
    self_c = collections.Counter("(외부)" if 외부인가(t) else t for t, _ in named)
    incl_c = collections.Counter()
    for t, ch in named:
        incl_c.update(set(ch) | ({"(외부)"} if 외부인가(t) else set()))
    print(f"실행 {a.반복} 번 · 가운데 {sorted(walls)[len(walls) // 2]:.2f} 초 · 표본 {n}")
    print(f"\n자기 시간 (위 {a.위})")
    for nm, c in self_c.most_common(a.위):
        print(f"  {100.0 * c / n:6.2f} %  {nm}")
    print(f"\n포함 시간 (위 {a.위})")
    for nm, c in incl_c.most_common(a.위):
        print(f"  {100.0 * c / n:6.2f} %  {nm}")
    for line in 외부표(named):
        print(line)
    if a.출력:
        ext = [(t, ch) for t, ch in named if 외부인가(t)]
        json.dump({"실행파일_sha256": sha, "실행_초": walls, "표본": n, "자기": self_c.most_common(), "포함": incl_c.most_common(),
                   "외부_운영체제": collections.Counter(t for t, _ in ext).most_common(),
                   "외부_부른쪽": collections.Counter(ch[0] if ch else "(부른 쪽 모름)" for _, ch in ext).most_common()},
                  open(a.출력, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
