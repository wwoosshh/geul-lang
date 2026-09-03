"""타입 부착 3주소 IR (D-02). 비SSA: 임시값은 슬롯이며 여러 번 대입될 수 있다.
백엔드는 IR 밖의 어떤 정보도 추측하지 않는다."""
from . import types as T


class Temp:
    __slots__ = ("id", "type")

    def __init__(self, id, type):
        self.id = id
        self.type = type

    def __repr__(self):
        return f"%{self.id}"


class Inst:
    """모든 명령은 필드 이름을 가진 단순 레코드다."""
    op = ""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __repr__(self):
        fields = ", ".join(f"{k}={v!r}" for k, v in self.__dict__.items())
        return f"{self.op}({fields})"


def inst(_op, **kw):
    i = Inst(**kw)
    i.op = _op
    return i


class IRFunction:
    def __init__(self, name, params, ret, is_entry=False, variadic=False):
        self.name = name              # 링크 이름 (라벨)
        self.variadic = variadic      # 정의된 가변 인자 함수: 프롤로그가 레지스터 인자 4개를 모두 홈 슬롯에 둔다
        self.params = params          # [(VarSym, Type)]
        self.ret = ret                # Type | None
        self.locals = []              # [VarSym] (local/param 슬롯)
        self.temps = []               # [Temp]
        self.insts = []
        self.is_entry = is_entry
        self.max_call_args = 0
        self._label = 0

    def new_temp(self, type):
        t = Temp(len(self.temps), type)
        self.temps.append(t)
        return t

    def new_label(self, hint="L"):
        self._label += 1
        return f".{self.name}.{hint}{self._label}"

    def emit(self, _op, **kw):
        i = inst(_op, **kw)
        self.insts.append(i)
        return i

    def dump(self):
        """docs/05-덤프-형식.md 의 IR 덤프."""
        ret = str(self.ret) if self.ret is not None else "공허"
        lines = [f"함수 {self.name}({', '.join(f'{s.name}: {t}' for s, t in self.params)}) -> {ret}"]
        params = {s for s, _ in self.params}
        for s in self.locals:
            if s not in params:
                lines.append(f"  지역 {s.name}: {s.type}")
        for i in self.insts:
            lines.append(dump_inst(i))
        return "\n".join(lines)


def _t(x):
    return f"%{x.id}"


def _fbits(value, bits):
    import struct
    if bits == 32:
        return "0x%08X" % struct.unpack("<I", struct.pack("<f", value))[0]
    return "0x%016X" % struct.unpack("<Q", struct.pack("<d", value))[0]


def dump_inst(i):
    op = i.op
    if op == "label":
        return f"  {i.name}:"
    d = f"    {_t(i.dst)}: {i.dst.type} = " if getattr(i, "dst", None) is not None else "    "
    if op == "const":
        return d + f"상수 {i.value}"
    if op == "fconst":
        return d + f"실수상수 {_fbits(i.value, i.dst.type.bits)}"
    if op == "str":
        return d + f"문자열 #{i.index}"
    if op == "addr_local":
        return d + f"지역주소 {i.var.name}"
    if op == "addr_global":
        return d + f"전역주소 {i.var.name}"
    if op == "func_addr":
        return d + ("외부함수주소 " if i.extern else "함수주소 ") + i.name
    if op == "copy":
        return d + f"복사 {_t(i.src)}"
    if op == "load":
        return d + f"적재 {_t(i.addr)}"
    if op == "store":
        return f"    저장 {_t(i.addr)} <- {_t(i.src)} : {i.type}"
    if op == "gep":
        return d + f"오프셋 {_t(i.base)} + {i.offset}"
    if op == "index_addr":
        return d + f"원소주소 {_t(i.base)} + {_t(i.idx)} * {i.size}"
    if op == "bin":
        return d + f"이항 {i.bop} {_t(i.a)} {_t(i.b)}"
    if op == "cmp":
        return d + f"비교 {i.cond} {_t(i.a)} {_t(i.b)} : {i.type}"
    if op == "neg":
        return d + f"부호반전 {_t(i.a)}"
    if op == "not":
        return d + f"비트반전 {_t(i.a)}"
    if op == "lnot":
        return d + f"논리부정 {_t(i.a)} : {i.type}"
    if op == "cast":
        return d + f"변환 {i.kind} {_t(i.src)}"
    if op == "vararg":
        return d + f"가변인자 {_t(i.idx)}"
    if op == "call":
        args = ", ".join(_t(a) for a in i.args)
        callee = i.callee if isinstance(i.callee, str) else _t(i.callee)
        return d + ("외부호출 " if i.extern else "호출 ") + f"{callee}({args})"
    if op == "jmp":
        return f"    점프 {i.label}"
    if op == "br":
        return f"    분기 {_t(i.cond)} ? {i.ltrue} : {i.lfalse}"
    if op == "ret":
        return f"    반환 {_t(i.value)}" if i.value is not None else "    반환"
    return f"    {i!r}"


def escape_bytes(b):
    """문자열 풀 덤프용 정규 이스케이프."""
    out = []
    for ch in b[:-1]:   # 끝의 NUL 제외
        if ch == 10: out.append("\\n")
        elif ch == 9: out.append("\\t")
        elif ch == 13: out.append("\\r")
        elif ch == 0: out.append("\\0")
        elif ch == 92: out.append("\\\\")
        elif ch == 34: out.append('\\"')
        else: out.append(chr(ch) if ch < 128 else None)
    # 비ASCII 바이트는 UTF-8 로 그대로 (None 자리를 원본 바이트로 채운다)
    res = bytearray()
    k = 0
    for ch in b[:-1]:
        piece = out[k]; k += 1
        if piece is None:
            res.append(ch)
        else:
            res += piece.encode("utf-8")
    return res.decode("utf-8", "replace")


class IRModule:
    def __init__(self):
        self.functions = []           # [IRFunction]
        self.externs = {}             # link_name -> (dll, FuncType)
        self.globals = []             # [VarSym] (global/static, .init 상수)
        self.strings = []             # [bytes] (NUL 포함)
        self._string_index = {}
        self.entry = None             # 시작하기 IRFunction 이름

    def intern_string(self, s):
        b = s.encode("utf-8") + b"\0"
        if b in self._string_index:
            return self._string_index[b]
        self._string_index[b] = len(self.strings)
        self.strings.append(b)
        return self._string_index[b]

    def dump(self):
        out = []
        for name, (dll, ft) in self.externs.items():
            out.append(f"외부 {dll} {name}: {ft}")
        for g in self.globals:
            init = g.init
            if init is None:
                s = "없음"
            elif isinstance(init, tuple):
                s = f"문자열 #{g.init_index}"
            elif g.type.is_float():
                s = "실수상수 " + _fbits(float(init), g.type.bits)
            else:
                s = str(int(init))
            out.append(f"전역 {g.name}: {g.type} = {s}")
        for i, s in enumerate(self.strings):
            out.append(f'문자열 #{i} "{escape_bytes(s)}"')
        out.append(f"진입 {self.entry}")
        for f in self.functions:
            out.append(f.dump())
        return "\n".join(out)


KERNEL32 = {
    "ExitProcess", "GetStdHandle", "WriteFile", "ReadFile", "GetCommandLineW", "GetConsoleOutputCP",
    "SetConsoleOutputCP", "WideCharToMultiByte", "MultiByteToWideChar", "LocalFree", "QueryPerformanceCounter",
    "QueryPerformanceFrequency", "Sleep", "GetTickCount", "GetTickCount64", "CreateFileW", "CloseHandle",
    "GetLastError", "VirtualAlloc", "VirtualFree", "HeapAlloc", "HeapFree", "GetProcessHeap", "SetConsoleCP",
    "GetConsoleCP", "GetFileSizeEx", "SetFilePointerEx", "DeleteFileW", "GetEnvironmentVariableW",
    "GetCurrentDirectoryW", "CreateDirectoryW", "FindFirstFileW", "FindNextFileW", "FindClose",
    "HeapReAlloc", "GetFileType", "ReadConsoleW", "WriteConsoleW", "CreateProcessW", "WaitForSingleObject",
    "GetExitCodeProcess", "GetSystemTimeAsFileTime", "FlushFileBuffers", "SetEndOfFile", "GetFileAttributesW",
    "GetModuleFileNameW",
}
SHELL32 = {"CommandLineToArgvW"}


def dll_for(link_name):
    if link_name in KERNEL32:
        return "kernel32.dll"
    if link_name in SHELL32:
        return "shell32.dll"
    return "msvcrt.dll"
