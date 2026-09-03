"""드라이버: 포함 처리 → 렉서 → 파서 → (의미 분석 → IR → PE)."""
import os
from .diagnostics import CompileError, InternalError, EXIT_OK, EXIT_USER_ERROR, Pos
from .source import load_source
from .lexer import tokenize
from .parser import parse
from . import ast as A


def resolve_include(name, from_dir, std_dir, pos):
    """명세 3.1: (1) 현재 파일 디렉터리 (2) 표준 라이브러리 디렉터리."""
    for base in (from_dir, os.path.dirname(std_dir.rstrip("/\\"))):
        p = os.path.normpath(os.path.join(base, name))
        if os.path.isfile(p):
            return p
    raise CompileError(pos, f"포함할 파일을 찾을 수 없습니다: {name}")


def load_program(path, std_dir, auto_std=True):
    """포함을 재귀 처리해 선언 목록을 하나로 합친다. 같은 파일은 한 번만."""
    seen = set()
    decls = []

    def visit(p, pos):
        ap = os.path.normcase(os.path.abspath(p))
        if ap in seen:
            return
        seen.add(ap)
        text = load_source(p)
        toks = tokenize(text, p)
        prog = parse(toks, p)
        for ipos, name in prog.includes:
            visit(resolve_include(name, os.path.dirname(os.path.abspath(p)), std_dir, ipos), ipos)
        decls.extend(prog.decls)

    if auto_std:
        std = os.path.join(std_dir, "기본.gl")
        if os.path.isfile(std):
            visit(std, Pos(path, 0, 0))
    visit(path, Pos(path, 0, 0))
    return A.Program(Pos(path, 1, 1), [], decls)


def compile_file(src, out, check=False, dump_ir=False, std_dir=None):
    if not os.path.isfile(src):
        raise CompileError(Pos(src, 0, 0), "파일을 열 수 없습니다")
    program = load_program(src, std_dir)
    from . import sema
    unit = sema.analyze(program)
    if check:
        return EXIT_OK
    from . import lower
    ir = lower.lower_program(unit)
    if dump_ir:
        print(ir.dump())
        return EXIT_OK
    from . import codegen, pe
    if out is None:
        out = os.path.splitext(src)[0] + ".exe"
    if os.path.exists(out):
        os.remove(out)
    image = codegen.generate(ir)
    pe.write_pe(image, out)
    return EXIT_OK
