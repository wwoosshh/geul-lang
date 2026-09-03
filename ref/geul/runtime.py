"""프로그램 시작 코드 (D-07). IR 로 작성해 같은 백엔드로 낸다.

- 콘솔 출력 코드페이지를 저장하고 UTF-8 로 설정, 종료 시 복원
- GetCommandLineW → CommandLineToArgvW → UTF-8 argv
- 시작하기 호출, 반환값을 ExitProcess 로
"""
from . import types as T
from .ir import IRFunction, dll_for
from .sema import VarSym

I32 = T.MEDIUM
U32 = T.UMEDIUM

RUNTIME_EXTERNS = {
    "GetConsoleOutputCP": T.FuncType((), U32),
    "SetConsoleOutputCP": T.FuncType((U32,), I32),
    "GetCommandLineW": T.FuncType((), T.VOIDPTR),
    "CommandLineToArgvW": T.FuncType((T.VOIDPTR, T.VOIDPTR), T.VOIDPTR),
    "WideCharToMultiByte": T.FuncType((U32, U32, T.VOIDPTR, I32, T.VOIDPTR, I32, T.VOIDPTR, T.VOIDPTR), I32),
    "LocalFree": T.FuncType((T.VOIDPTR,), T.VOIDPTR),
    "malloc": T.FuncType((T.INT,), T.VOIDPTR),
    "ExitProcess": T.FuncType((U32,), None),
}


def build_startup(mod):
    for name, ft in RUNTIME_EXTERNS.items():
        if name not in mod.externs:
            mod.externs[name] = (dll_for(name), ft)
    entry = None
    for f in mod.functions:
        if f.name == mod.entry:
            entry = f
    f = IRFunction("__글_시작", [], None)
    argc_var = VarSym("argc", I32, "local", None)
    f.locals.append(argc_var)

    def call(name, args, ret):
        dst = f.new_temp(ret) if ret is not None else None
        f.emit("call", dst=dst, callee=name, extern=True, args=args, sig=RUNTIME_EXTERNS[name], nfixed=len(args))
        f.max_call_args = max(f.max_call_args, len(args))
        return dst

    def const(v, t=T.INT):
        d = f.new_temp(t)
        f.emit("const", dst=d, value=v)
        return d

    saved = call("GetConsoleOutputCP", [], U32)
    call("SetConsoleOutputCP", [const(65001, U32)], I32)
    cmd = call("GetCommandLineW", [], T.VOIDPTR)
    argc_addr = f.new_temp(T.PtrType(I32))
    f.emit("addr_local", dst=argc_addr, var=argc_var)
    argvw = call("CommandLineToArgvW", [cmd, argc_addr], T.VOIDPTR)
    argc32 = f.new_temp(I32)
    f.emit("load", dst=argc32, addr=argc_addr, type=I32)
    argc = f.new_temp(T.INT)
    f.emit("cast", dst=argc, kind="sext", src=argc32)
    n1 = f.new_temp(T.INT); f.emit("bin", dst=n1, bop="add", a=argc, b=const(1))
    nbytes = f.new_temp(T.INT); f.emit("bin", dst=nbytes, bop="mul", a=n1, b=const(8))
    argv = call("malloc", [nbytes], T.VOIDPTR)
    i = f.new_temp(T.INT)
    f.emit("const", dst=i, value=0)
    top = f.new_label("루프"); body = f.new_label("몸"); done = f.new_label("끝")
    f.emit("label", name=top)
    c = f.new_temp(T.BOOL); f.emit("cmp", dst=c, cond="lt", a=i, b=argc, type=T.INT)
    f.emit("br", cond=c, ltrue=body, lfalse=done)
    f.emit("label", name=body)
    wslot = f.new_temp(T.PtrType(T.VOIDPTR)); f.emit("index_addr", dst=wslot, base=argvw, idx=i, size=8)
    w = f.new_temp(T.VOIDPTR); f.emit("load", dst=w, addr=wslot, type=T.VOIDPTR)
    zero = const(0, T.VOIDPTR)
    n = call("WideCharToMultiByte", [const(65001, U32), const(0, U32), w, const(-1, I32), zero, const(0, I32), zero, zero], I32)
    n64 = f.new_temp(T.INT); f.emit("cast", dst=n64, kind="sext", src=n)
    buf = call("malloc", [n64], T.VOIDPTR)
    call("WideCharToMultiByte", [const(65001, U32), const(0, U32), w, const(-1, I32), buf, n, zero, zero], I32)
    aslot = f.new_temp(T.PtrType(T.VOIDPTR)); f.emit("index_addr", dst=aslot, base=argv, idx=i, size=8)
    f.emit("store", addr=aslot, src=buf, type=T.VOIDPTR)
    i2 = f.new_temp(T.INT); f.emit("bin", dst=i2, bop="add", a=i, b=const(1))
    f.emit("copy", dst=i, src=i2)
    f.emit("jmp", label=top)
    f.emit("label", name=done)
    last = f.new_temp(T.PtrType(T.VOIDPTR)); f.emit("index_addr", dst=last, base=argv, idx=argc, size=8)
    f.emit("store", addr=last, src=const(0, T.VOIDPTR), type=T.VOIDPTR)
    call("LocalFree", [argvw], T.VOIDPTR)
    # 시작하기
    if entry is None:
        raise RuntimeError("시작하기 없음")
    args = []
    if len(entry.params) == 2:
        argc_t = entry.params[0][1]
        argc_arg = argc if argc_t.bits == 64 else f.new_temp(argc_t)
        if argc_t.bits != 64:
            f.emit("cast", dst=argc_arg, kind="trunc", src=argc)
        args = [argc_arg, argv]
    f.max_call_args = max(f.max_call_args, len(args))
    if entry.ret is not None:
        code = f.new_temp(entry.ret)
        f.emit("call", dst=code, callee=entry.name, extern=False, args=args, sig=T.FuncType(tuple(t for _, t in entry.params), entry.ret), nfixed=len(args))
        code32 = f.new_temp(U32)
        f.emit("cast", dst=code32, kind="trunc" if entry.ret.bits > 32 else "zext", src=code)
    else:
        f.emit("call", dst=None, callee=entry.name, extern=False, args=args, sig=T.FuncType(tuple(t for _, t in entry.params), None), nfixed=len(args))
        code32 = const(0, U32)
    call("SetConsoleOutputCP", [saved], I32)
    call("ExitProcess", [code32], None)
    f.emit("ret", value=None)
    return f
