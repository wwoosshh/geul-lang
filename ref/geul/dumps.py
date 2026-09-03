"""덤프 형식 (docs/05-덤프-형식.md). 자체호스팅 컴파일러와 참조 구현이 같은 문자열을 내야 한다."""
import dataclasses
from . import ast as A
from .lexer import EOF
from .diagnostics import Pos

NODE_NAMES = {
    "Program": "프로그램", "VarDecl": "변수선언", "FuncDecl": "함수정의", "Param": "매개변수", "StructDecl": "묶음선언",
    "EnumDecl": "나열선언", "AliasDecl": "별칭선언", "Block": "블록", "ExprStmt": "식문", "Assign": "대입", "IncDec": "증감",
    "If": "조건문", "While": "동안", "For": "반복", "DoWhile": "반복하기", "Switch": "갈래", "Return": "반환",
    "Break": "탈출", "Continue": "계속", "IntLit": "정수", "FloatLit": "실수", "CharLit": "문자", "StringLit": "문자열",
    "BoolLit": "참거짓", "NullLit": "없음", "Name": "이름", "Index": "색인", "Member": "멤버", "Call": "호출",
    "SOVCall": "SOV호출", "Unary": "단항", "Binary": "이항", "Ternary": "삼항", "Cast": "변환", "SizeOf": "크기",
    "BaseType": "기본타입", "NamedType": "이름타입", "PtrType": "참조타입", "ArrayType": "배열타입", "FuncType": "함수타입",
}
FIELD_NAMES = {
    "includes": "포함", "decls": "선언", "type": "타입", "name": "이름", "init": "초기값", "static": "정적", "const": "상수",
    "params": "매개변수", "ret": "반환타입", "body": "본문", "link_name": "링크이름", "variadic": "가변", "fields": "필드",
    "is_union": "합침", "values": "값", "stmts": "문장", "expr": "식", "target": "대상", "op": "연산자", "value": "값",
    "delta": "증분", "cond": "조건", "then": "참블록", "elifs": "아니면조건", "else_": "아니면블록", "step": "증감",
    "subject": "대상", "cases": "경우", "default": "기본", "base": "바탕", "index": "색인", "arrow": "화살표",
    "callee": "피호출", "args": "인자", "verb": "동사", "operand": "피연산자", "left": "좌", "right": "우", "a": "참값",
    "b": "거짓값", "unsigned": "부호없는", "elem": "원소", "size": "크기", "role": "역할", "raw": "원문",
}


def dump_tokens(tokens):
    lines = []
    for t in tokens:
        text = "" if t.kind == EOF else t.text
        lines.append(f"{t.pos.line}:{t.pos.col}\t{t.kind}\t{text}")
    return "\n".join(lines)


def _scalar(v):
    if isinstance(v, bool):
        return "참" if v else "거짓"
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return v
    return str(v)


def dump_ast(node):
    out = []
    _dump(node, 0, out, None)
    return "\n".join(out)


def _dump(node, depth, out, label):
    pad = "  " * depth
    head = (label + ": ") if label else ""
    if isinstance(node, A.StringLit):
        out.append(f"{pad}{head}문자열 {node.raw}")
        return
    if isinstance(node, tuple) and len(node) == 2 and isinstance(node[0], Pos):
        out.append(f'{pad}{head}포함 "{node[1]}"')
        return
    if isinstance(node, (list, tuple)):
        out.append(f"{pad}{head}[{len(node)}]")
        for item in node:
            _dump(item, depth + 1, out, None)
        return
    if not dataclasses.is_dataclass(node):
        out.append(f"{pad}{head}{_scalar(node)}")
        return
    kind = NODE_NAMES.get(type(node).__name__, type(node).__name__)
    scalars = []
    children = []
    for f in dataclasses.fields(node):
        if f.name == "pos":
            continue
        v = getattr(node, f.name)
        fname = FIELD_NAMES.get(f.name, f.name)
        if v is None:
            continue
        if isinstance(v, (bool, int, float, str)):
            if f.name == "raw":
                continue
            scalars.append(f"{fname}={_scalar(v)}")
        else:
            children.append((fname, v))
    out.append(f"{pad}{head}{kind}" + (" " + " ".join(scalars) if scalars else ""))
    for fname, v in children:
        if isinstance(v, (list, tuple)) and not v:
            continue
        _dump(v, depth + 1, out, fname)
