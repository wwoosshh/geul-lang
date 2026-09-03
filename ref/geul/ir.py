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
    def __init__(self, name, params, ret, is_entry=False):
        self.name = name              # 링크 이름 (라벨)
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
        lines = [f"함수 {self.name}({', '.join(f'{s.name}: {t}' for s, t in self.params)}) -> {self.ret}"]
        for s in self.locals:
            lines.append(f"    지역 {s.name}: {s.type}")
        for i in self.insts:
            if i.op == "label":
                lines.append(f"  {i.name}:")
            else:
                lines.append(f"    {i!r}")
        return "\n".join(lines)


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
            out.append(f"외부 {dll}!{name}: {ft}")
        for g in self.globals:
            out.append(f"전역 {g.name}: {g.type} = {g.init!r}")
        for i, s in enumerate(self.strings):
            out.append(f"문자열 #{i} = {s!r}")
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
}
SHELL32 = {"CommandLineToArgvW"}


def dll_for(link_name):
    if link_name in KERNEL32:
        return "kernel32.dll"
    if link_name in SHELL32:
        return "shell32.dll"
    return "msvcrt.dll"
