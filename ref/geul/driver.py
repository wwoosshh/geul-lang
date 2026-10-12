"""드라이버: 포함 처리 → 렉서 → 파서 → (의미 분석 → IR → PE)."""
import os
from .diagnostics import CompileError, InternalError, EXIT_OK, EXIT_USER_ERROR, Pos
from .source import load_source
from .lexer import tokenize
from .parser import parse
from . import ast as A


def target_overlay(p, std_dir=None):
    """대상별 포함 (D-50): 리눅스 대상이면 포함할 파일 D/X.gl 대신 D/리눅스/X.gl 이 있으면 그것을.
    표준 라이브러리의 리눅스 체계층(표준/리눅스/X.gl)이 이 규칙으로 들어온다. 윈도 대상의 포함은 예전 그대로다(1.x 약속)."""
    from . import ir
    if ir.TARGET == "윈도":
        return p
    alt = os.path.join(os.path.dirname(p), ir.TARGET, os.path.basename(p))
    return alt if os.path.isfile(alt) else p


def resolve_include(name, from_dir, std_dir, pos):
    """명세 3.1: (1) 현재 파일 디렉터리 (2) 표준 라이브러리 디렉터리."""
    for base in (from_dir, os.path.dirname(std_dir.rstrip("/\\"))):
        p = os.path.normpath(os.path.join(base, name))
        if os.path.isfile(p):
            return target_overlay(p, std_dir)
    raise CompileError(pos, f"포함할 파일을 찾을 수 없습니다: {name}")


def scan_includes(toks):
    """토큰열에서 최상위 '포함 "..."' 를 찾는다 (파싱 전에 포함 파일을 먼저 처리하기 위해)."""
    from .lexer import KEYWORD, STRING
    out = []
    for k, t in enumerate(toks[:-1]):
        if t.kind == KEYWORD and t.text == "포함" and toks[k + 1].kind == STRING:
            out.append((t.pos, toks[k + 1].value))
    return out


def load_program(path, std_dir, auto_std=True):
    """포함을 재귀 처리해 선언 목록을 하나로 합친다. 같은 파일은 한 번만.
    포함 파일은 먼저 파싱되므로 그 파일이 선언한 타입 이름을 뒤 파일이 쓸 수 있다."""
    seen = set()
    decls = []
    type_names = set()
    generic_names = set()

    def visit(p, pos):
        ap = os.path.normcase(os.path.abspath(p))
        if ap in seen:
            return
        seen.add(ap)
        text = load_source(p)
        toks = tokenize(text, p)
        for ipos, name in scan_includes(toks):
            visit(resolve_include(name, os.path.dirname(os.path.abspath(p)), std_dir, ipos), ipos)
        prog = parse(toks, p, type_names, generic_names)
        decls.extend(prog.decls)

    if auto_std:
        std = os.path.join(std_dir, "기본.gl")
        if os.path.isfile(std):
            visit(target_overlay(std, std_dir), Pos(path, 0, 0))
    visit(path, Pos(path, 0, 0))
    return A.Program(Pos(path, 1, 1), [], decls)


def dump_file(src, std_dir, what):
    """--dump-tokens / --dump-ast: 주어진 파일 하나만. AST 는 포함 파일의 타입 이름만 빌려 쓴다."""
    from . import dumps
    text = load_source(src)
    toks = tokenize(text, src)
    if what == "tokens":
        print(dumps.dump_tokens(toks))
        return EXIT_OK
    type_names = set()
    generic_names = set()
    seen = set()

    def collect(p, pos):
        ap = os.path.normcase(os.path.abspath(p))
        if ap in seen:
            return
        seen.add(ap)
        t = tokenize(load_source(p), p)
        for ipos, name in scan_includes(t):
            collect(resolve_include(name, os.path.dirname(os.path.abspath(p)), std_dir, ipos), ipos)
        parse(t, p, type_names, generic_names)

    std = os.path.join(std_dir, "기본.gl")
    if os.path.isfile(std):
        collect(target_overlay(std, std_dir), Pos(src, 0, 0))
    for ipos, name in scan_includes(toks):
        collect(resolve_include(name, os.path.dirname(os.path.abspath(src)), std_dir, ipos), ipos)
    prog = parse(toks, src, type_names, generic_names)
    print(dumps.dump_ast(prog))
    return EXIT_OK


def compile_file(src, out, check=False, dump_ir=False, std_dir=None, dump=None, gui=False, hotswap=False, fragment=False, target="윈도"):
    from . import ir as _ir
    _ir.TARGET = target
    if not os.path.isfile(src):
        raise CompileError(Pos(src, 0, 0), "파일을 열 수 없습니다")
    if target == "리눅스" and gui:
        raise CompileError(Pos(src, 0, 0), "--창 은 윈도 대상에만 있습니다 (PE 서브시스템)")
    if dump in ("tokens", "ast"):
        return dump_file(src, std_dir, dump)
    # --조각: 표준 라이브러리를 자동 포함하지 않는다 (순수 잎 함수 하나만).
    program = load_program(src, std_dir, auto_std=not fragment)
    from . import sema
    unit = sema.analyze(program, risky_report_only=(dump == "risky"), hotswap=hotswap, fragment=fragment)
    if dump == "calls":
        print(chr(10).join(unit.index))
        return EXIT_OK
    if dump == "risky":
        print(chr(10).join(unit.risky))
        return EXIT_OK
    if check:
        return EXIT_OK
    from . import lower, inline
    ir = lower.lower_program(unit)
    # 핫스왑에서는 인라인하지 않는다: 인라인된 호출은 함수 테이블을 거치지 않아 교체가 먹지 않는다.
    if not hotswap:
        ir = inline.run(ir)
    if dump_ir:
        print(ir.dump())
        return EXIT_OK
    from . import codegen, pe
    if fragment:
        blob = codegen.generate_fragment(ir, src)
        if out is None:
            out = os.path.splitext(src)[0] + ".bin"
        if os.path.exists(out):
            os.remove(out)
        with open(out, "wb") as fp:
            fp.write(blob)
        return EXIT_OK
    if out is None:
        out = os.path.splitext(src)[0] + (".exe" if target != "리눅스" else "")
    if os.path.exists(out):
        os.remove(out)
    image = codegen.generate(ir, hotswap=hotswap)
    if target == "리눅스":
        from . import elf
        elf.write_elf(image, out)
        os.chmod(out, 0o755)
    else:
        pe.write_pe(image, out, 2 if gui else 3)
    return EXIT_OK
