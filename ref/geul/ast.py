"""AST. 파서가 만들고 의미 분석이 타입을 붙인다."""
from dataclasses import dataclass, field
from typing import Optional, List, Tuple
from .diagnostics import Pos


@dataclass
class Node:
    pos: Pos


# ---------- 타입 표기 (구문) ----------
@dataclass
class BaseType(Node):
    name: str            # 정수 긴정수 짧은정수 작은정수 실수 짧은실수 문자 문자열 참거짓 공허
    unsigned: bool = False


@dataclass
class NamedType(Node):
    name: str


@dataclass
class PtrType(Node):
    target: Node


@dataclass
class ArrayType(Node):
    elem: Node
    size: int


@dataclass
class SliceType(Node):
    elem: Node


@dataclass
class ResultType(Node):
    base: Node


@dataclass
class GenericType(Node):
    name: str
    args: List[Node]


@dataclass
class TypeApply(Node):
    """식 자리의 제네릭 함수 인스턴스: 이름(타입, ...)"""
    name: str
    args: List[Node]


@dataclass
class GenericType(Node):
    name: str
    args: List[Node]


@dataclass
class TypeApply(Node):
    """식 자리의 제네릭 함수 인스턴스: 이름(타입, ...)"""
    name: str
    args: List[Node]


@dataclass
class ResultType(Node):
    base: Node


@dataclass
class GenericType(Node):
    name: str
    args: List[Node]


@dataclass
class TypeApply(Node):
    """식 자리의 제네릭 함수 인스턴스: 이름(타입, ...)"""
    name: str
    args: List[Node]


@dataclass
class GenericType(Node):
    name: str
    args: List[Node]


@dataclass
class TypeApply(Node):
    """식 자리의 제네릭 함수 인스턴스: 이름(타입, ...)"""
    name: str
    args: List[Node]


@dataclass
class FuncType(Node):
    params: List[Node]
    ret: Optional[Node]


# ---------- 선언 ----------
@dataclass
class Param(Node):
    type: Node
    name: str
    role: Optional[str]      # 대상 목적지 출처 수단 동반 또는 None(무표)


@dataclass
class VarDecl(Node):
    type: Node
    name: str
    init: Optional[Node]
    static: bool = False
    const: bool = False


@dataclass
class FuncDecl(Node):
    name: str
    params: List[Param]
    ret: Optional[Node]
    body: Optional["Block"]          # None 이면 외부 선언
    link_name: Optional[str] = None  # 외부 선언의 링크 이름
    variadic: bool = False
    type_params: List[str] = field(default_factory=list)   # 제네릭 (D-19)
    type_params: List[str] = field(default_factory=list)   # 제네릭 (D-19)


@dataclass
class StructDecl(Node):
    name: str
    fields: List[Tuple[Node, str]]
    is_union: bool = False
    type_params: List[str] = field(default_factory=list)   # 제네릭 (D-19)
    type_params: List[str] = field(default_factory=list)   # 제네릭 (D-19)


@dataclass
class EnumDecl(Node):
    name: str
    values: List[str]


@dataclass
class AliasDecl(Node):
    name: str
    type: Node


@dataclass
class Program(Node):
    includes: List[Tuple[Pos, str]]
    decls: List[Node]


# ---------- 문장 ----------
@dataclass
class Block(Node):
    stmts: List[Node]


@dataclass
class ExprStmt(Node):
    expr: Node


@dataclass
class Assign(Node):
    target: Node
    op: str            # = += -= ...
    value: Node


@dataclass
class IncDec(Node):
    target: Node
    delta: int


@dataclass
class If(Node):
    cond: Node
    then: Block
    elifs: List[Tuple[Node, Block]]
    else_: Optional[Block]


@dataclass
class While(Node):
    cond: Node
    body: Block


@dataclass
class For(Node):
    init: Optional[Node]
    cond: Node
    step: Optional[Node]
    body: Block


@dataclass
class DoWhile(Node):
    body: Block
    cond: Node


@dataclass
class Switch(Node):
    subject: Node
    cases: List[Tuple[Node, Block]]
    default: Optional[Block]


@dataclass
class Return(Node):
    value: Optional[Node]


@dataclass
class Break(Node):
    pass


@dataclass
class Continue(Node):
    pass


# ---------- 식 ----------
@dataclass
class IntLit(Node):
    value: int


@dataclass
class FloatLit(Node):
    value: float
    raw: str = ""       # 원문 (덤프용; 음수 접기는 '-' 를 앞에 붙인다)


@dataclass
class CharLit(Node):
    value: int


@dataclass
class StringLit(Node):
    value: str
    raw: str = ""       # 따옴표 포함 원문 (보간 분석용)


@dataclass
class BoolLit(Node):
    value: bool


@dataclass
class NullLit(Node):
    pass


@dataclass
class Name(Node):
    name: str


@dataclass
class Index(Node):
    base: Node
    index: Node


@dataclass
class Try(Node):
    expr: Node


@dataclass
class Try(Node):
    expr: Node


@dataclass
class SliceExpr(Node):
    base: Node
    lo: Optional[Node]
    hi: Optional[Node]


@dataclass
class Member(Node):
    base: Node
    name: str
    arrow: bool


@dataclass
class Call(Node):
    callee: Node
    args: List[Node]


@dataclass
class SOVCall(Node):
    args: List[Tuple[Node, Optional[str]]]   # (식, 역할)
    verb: str                                # 어미를 뗀 어근 (예: 더하기, 쓰, 할인계산, 계산하기하)


@dataclass
class Unary(Node):
    op: str            # - 아닌 ~ &
    operand: Node


@dataclass
class Binary(Node):
    op: str
    left: Node
    right: Node


@dataclass
class Ternary(Node):
    cond: Node
    a: Node
    b: Node


@dataclass
class Cast(Node):
    expr: Node
    type: Node


@dataclass
class SizeOf(Node):
    type: Node
