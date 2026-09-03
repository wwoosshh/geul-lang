"""타입 (명세 3.3). D-02: 모든 값에 타입이 있다."""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


class Type:
    size = 8
    align = 8

    def is_int(self): return isinstance(self, IntType)
    def is_float(self): return isinstance(self, FloatType)
    def is_ptr(self): return isinstance(self, PtrType)
    def is_array(self): return isinstance(self, ArrayType)
    def is_struct(self): return isinstance(self, StructType)
    def is_func(self): return isinstance(self, FuncType)
    def is_void(self): return isinstance(self, VoidType)
    def is_scalar(self): return self.is_int() or self.is_float() or self.is_ptr() or self.is_func()


@dataclass(frozen=True)
class IntType(Type):
    bits: int
    signed: bool
    name: str = ""

    @property
    def size(self): return self.bits // 8
    @property
    def align(self): return self.bits // 8

    def __str__(self):
        return self.name or ("" if self.signed else "부호없는 ") + {8: "작은정수", 16: "짧은정수", 32: "중간정수", 64: "정수"}.get(self.bits, f"i{self.bits}")

    def min_value(self):
        return -(1 << (self.bits - 1)) if self.signed else 0

    def max_value(self):
        return (1 << (self.bits - 1)) - 1 if self.signed else (1 << self.bits) - 1


@dataclass(frozen=True)
class FloatType(Type):
    bits: int

    @property
    def size(self): return self.bits // 8
    @property
    def align(self): return self.bits // 8

    def __str__(self):
        return "실수" if self.bits == 64 else "짧은실수"


@dataclass(frozen=True)
class VoidType(Type):
    size = 0
    align = 1

    def __str__(self):
        return "공허"


@dataclass(frozen=True)
class PtrType(Type):
    target: Type

    def __str__(self):
        if self.target == CHAR:
            return "문자열"
        return f"{self.target} 참조"


@dataclass(frozen=True)
class ArrayType(Type):
    elem: Type
    count: int

    @property
    def size(self): return self.elem.size * self.count
    @property
    def align(self): return self.elem.align

    def __str__(self):
        return f"{self.elem}[{self.count}]"


@dataclass(frozen=True)
class FuncType(Type):
    params: Tuple[Type, ...]
    ret: Optional[Type]
    variadic: bool = False

    def __str__(self):
        ps = ", ".join(str(p) for p in self.params) + (", ..." if self.variadic else "")
        return f"[{ps} -> {self.ret if self.ret else ''}]"


class StructType(Type):
    """이름으로 구분되는 묶음/합침. 필드 배치는 C와 같다."""

    def __init__(self, name, is_union=False):
        self.name = name
        self.is_union = is_union
        self.fields: List[Tuple[str, Type, int]] = []   # (이름, 타입, 오프셋)
        self.size = 0
        self.align = 1
        self.complete = False

    def set_fields(self, fields):
        off = 0
        align = 1
        out = []
        for name, t in fields:
            align = max(align, t.align)
            if self.is_union:
                out.append((name, t, 0))
                off = max(off, t.size)
            else:
                off = (off + t.align - 1) // t.align * t.align
                out.append((name, t, off))
                off += t.size
        self.fields = out
        self.align = align
        self.size = (off + align - 1) // align * align if off else 0
        self.complete = True

    def field(self, name):
        for f in self.fields:
            if f[0] == name:
                return f
        return None

    def __str__(self):
        return self.name

    def __eq__(self, other):
        return self is other

    def __hash__(self):
        return id(self)


INT = IntType(64, True, "정수")
LONG = IntType(64, True, "긴정수")
MEDIUM = IntType(32, True, "중간정수")
SHORT = IntType(16, True, "짧은정수")
BYTE = IntType(8, True, "작은정수")
CHAR = IntType(8, True, "문자")
BOOL = IntType(8, False, "참거짓")
UINT = IntType(64, False, "부호없는 정수")
ULONG = IntType(64, False, "부호없는 긴정수")
UMEDIUM = IntType(32, False, "부호없는 중간정수")
USHORT = IntType(16, False, "부호없는 짧은정수")
UBYTE = IntType(8, False, "부호없는 작은정수")
DOUBLE = FloatType(64)
FLOAT = FloatType(32)
VOID = VoidType()
STRING = PtrType(CHAR)
VOIDPTR = PtrType(VOID)

BASE_BY_NAME = {
    ("정수", False): INT, ("긴정수", False): LONG, ("중간정수", False): MEDIUM, ("짧은정수", False): SHORT, ("작은정수", False): BYTE,
    ("정수", True): UINT, ("긴정수", True): ULONG, ("중간정수", True): UMEDIUM, ("짧은정수", True): USHORT, ("작은정수", True): UBYTE,
    ("실수", False): DOUBLE, ("짧은실수", False): FLOAT, ("문자", False): CHAR, ("문자열", False): STRING,
    ("참거짓", False): BOOL, ("공허", False): VOID,
}


def same_type(a, b):
    """구조적 동일성 (묶음은 이름). 정수는 폭·부호가 같으면 같다 (정수 == 긴정수)."""
    if isinstance(a, IntType) and isinstance(b, IntType):
        return a.bits == b.bits and a.signed == b.signed
    if isinstance(a, StructType) or isinstance(b, StructType):
        return a is b
    if isinstance(a, PtrType) and isinstance(b, PtrType):
        return same_type(a.target, b.target)
    if isinstance(a, ArrayType) and isinstance(b, ArrayType):
        return a.count == b.count and same_type(a.elem, b.elem)
    if isinstance(a, FuncType) and isinstance(b, FuncType):
        if len(a.params) != len(b.params) or a.variadic != b.variadic:
            return False
        if (a.ret is None) != (b.ret is None) or (a.ret is not None and not same_type(a.ret, b.ret)):
            return False
        return all(same_type(x, y) for x, y in zip(a.params, b.params))
    return type(a) is type(b) and a == b


def decay(t):
    """배열 → 첫 원소 참조 (값으로 쓰일 때)."""
    if isinstance(t, ArrayType):
        return PtrType(t.elem)
    return t
