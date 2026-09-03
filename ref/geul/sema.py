"""의미 분석 (명세 3.3, 3.5, 4절). 이름 해석, 타입 검사, 역할 정규화, 보간.
결과: 각 식 노드에 .type, 이름 노드에 .sym, 호출 노드에 .callee_sym/.resolved_args 를 붙인 Program.
모든 불일치는 오류다 (D-03)."""
from . import ast as A
from . import types as T
from .diagnostics import CompileError, InternalError
from .parser import verb_base

ROLE_PARTICLE = {"대상": "을/를", "목적지": "에", "출처": "에서", "수단": "로", "동반": "와/과", None: "(무표)"}


class Sym:
    pass


class VarSym(Sym):
    def __init__(self, name, type, kind, pos, const=False, init=None):
        self.name = name
        self.type = type
        self.kind = kind          # global | local | param | static
        self.pos = pos
        self.const = const
        self.init = init          # 전역/정적: 상수 초기값 (파이썬 값 또는 ('str', s))
        self.uid = None           # lowering 이 붙이는 고유 번호


class FuncSym(Sym):
    def __init__(self, name, ftype, params, decl, link_name=None):
        self.name = name
        self.type = ftype
        self.params = params      # [A.Param] with .rtype
        self.decl = decl
        self.link_name = link_name
        self.is_extern = decl.body is None


class ConstSym(Sym):
    def __init__(self, name, type, value, pos):
        self.name = name
        self.type = type
        self.value = value
        self.pos = pos


class TypeSym(Sym):
    def __init__(self, name, type):
        self.name = name
        self.type = type


class Scope:
    def __init__(self, parent=None):
        self.parent = parent
        self.names = {}

    def lookup(self, name):
        s = self
        while s is not None:
            if name in s.names:
                return s.names[name]
            s = s.parent
        return None

    def declare(self, name, sym, pos):
        if name in self.names:
            raise CompileError(pos, f"'{name}'은(는) 이미 선언되었습니다")
        self.names[name] = sym


class Unit:
    """의미 분석 결과."""

    def __init__(self):
        self.functions = []      # FuncSym (정의된 것)
        self.externs = []        # FuncSym (외부)
        self.globals = []        # VarSym (global/static)
        self.strings = []        # 문자열 리터럴 풀
        self.entry = None        # 시작하기 FuncSym


class Sema:
    def __init__(self, program):
        self.program = program
        self.globals = Scope()
        self.unit = Unit()
        self.func = None          # 현재 함수 FuncSym
        self.scope = self.globals
        self.loop_depth = 0
        self.switch_depth = 0
        self.static_counter = 0

    def error(self, pos, msg):
        raise CompileError(pos, msg)

    # ---------- 타입 해석 ----------
    def resolve_type(self, node):
        if isinstance(node, A.BaseType):
            return T.BASE_BY_NAME[(node.name, node.unsigned)]
        if isinstance(node, A.NamedType):
            sym = self.globals.lookup(node.name)
            if not isinstance(sym, TypeSym):
                self.error(node.pos, f"타입이 아닙니다: '{node.name}'")
            return sym.type
        if isinstance(node, A.PtrType):
            return T.PtrType(self.resolve_type(node.target))
        if isinstance(node, A.ArrayType):
            elem = self.resolve_type(node.elem)
            if node.size <= 0:
                self.error(node.pos, "배열 크기는 1 이상이어야 합니다")
            return T.ArrayType(elem, node.size)
        if isinstance(node, A.ResultType):
            base = self.resolve_type(node.base)
            if base.is_array():
                self.error(node.pos, "배열의 결과 타입은 없습니다")
            return T.ResultType(None if base.is_void() else base)
        if isinstance(node, A.SliceType):
            elem = self.resolve_type(node.elem)
            if elem.is_void():
                self.error(node.pos, "조각의 원소 타입은 '공허'일 수 없습니다")
            return T.SliceType(elem)
        if isinstance(node, A.FuncType):
            params = tuple(T.decay(self.resolve_type(p)) for p in node.params)
            ret = self.resolve_type(node.ret) if node.ret is not None else None
            if ret is not None and ret.is_void():
                ret = None
            return T.FuncType(params, ret)
        raise InternalError(f"알 수 없는 타입 노드 {type(node).__name__}")

    # ---------- 프로그램 ----------
    def analyze(self):
        func_decls = []
        for d in self.program.decls:
            if isinstance(d, A.StructDecl):
                st = T.StructType(d.name, d.is_union)
                self.globals.declare(d.name, TypeSym(d.name, st), d.pos)
                fields = []
                seen = set()
                for ft, fname in d.fields:
                    if fname in seen:
                        self.error(d.pos, f"필드 이름이 중복됩니다: '{fname}'")
                    seen.add(fname)
                    t = self.resolve_type(ft)
                    if t.is_void() or (t.is_struct() and not t.complete):
                        self.error(d.pos, f"필드 '{fname}'의 타입이 올바르지 않습니다")
                    fields.append((fname, t))
                st.set_fields(fields)
            elif isinstance(d, A.EnumDecl):
                self.globals.declare(d.name, TypeSym(d.name, T.INT), d.pos)
                for i, v in enumerate(d.values):
                    self.globals.declare(v, ConstSym(v, T.INT, i, d.pos), d.pos)
            elif isinstance(d, A.AliasDecl):
                self.globals.declare(d.name, TypeSym(d.name, self.resolve_type(d.type)), d.pos)
            elif isinstance(d, A.VarDecl):
                self.declare_global(d)
            elif isinstance(d, A.FuncDecl):
                fs = self.declare_function(d)
                if d.body is not None:
                    func_decls.append((d, fs))
            else:
                raise InternalError(f"알 수 없는 선언 {type(d).__name__}")
        for d, fs in func_decls:
            self.check_function(d, fs)
        entry = self.globals.lookup("시작하기")
        if not isinstance(entry, FuncSym) or entry.is_extern:
            self.error(self.program.pos, "'시작하기' 함수가 없습니다")
        self.unit.entry = entry
        return self.unit

    def declare_global(self, d):
        t = self.resolve_type(d.type)
        if t.is_void():
            self.error(d.pos, "변수의 타입은 '공허'일 수 없습니다")
        init = None
        if d.init is not None:
            if t.is_array() or t.is_struct():
                self.error(d.pos, "배열·묶음 변수는 초기화식을 가질 수 없습니다")
            init = self.const_value(d.init, t)
        sym = VarSym(d.name, t, "global", d.pos, const=d.const, init=init)
        self.check_name(d.name, d.pos)
        self.globals.declare(d.name, sym, d.pos)
        self.unit.globals.append(sym)
        return sym

    def check_name(self, name, pos):
        if name in ("증가", "감소", "증가하다", "감소하다"):
            self.error(pos, f"'{name}'은(는) 예약된 동사 이름입니다")

    def declare_function(self, d):
        params = []
        ptypes = []
        seen = set()
        for p in d.params:
            t = T.decay(self.resolve_type(p.type))
            if t.is_void():
                self.error(p.pos, "매개변수의 타입은 '공허'일 수 없습니다")
            if p.name in seen:
                self.error(p.pos, f"매개변수 이름이 중복됩니다: '{p.name}'")
            seen.add(p.name)
            p.rtype = t
            params.append(p)
            ptypes.append(t)
        ret = self.resolve_type(d.ret) if d.ret is not None else None
        if ret is not None and ret.is_void():
            ret = None
        if ret is not None and ret.is_array():
            self.error(d.pos, "함수는 배열을 값으로 반환할 수 없습니다")
        if d.body is None and ((ret is not None and ret.is_agg()) or any(t.is_agg() for t in ptypes)):
            self.error(d.pos, "외부 함수는 묶음·조각을 값으로 주고받을 수 없습니다 (참조로)")
        ftype = T.FuncType(tuple(ptypes), ret, d.variadic)
        self.check_name(d.name, d.pos)
        if d.name == "시작하기":
            if d.body is None:
                self.error(d.pos, "'시작하기'는 외부 함수일 수 없습니다")
            if not (len(ptypes) == 0 or (len(ptypes) == 2 and ptypes[0].is_int() and ptypes[1].is_ptr())):
                self.error(d.pos, "'시작하기'는 매개변수가 없거나 (정수 argc, 문자열 참조 argv)여야 합니다")
            if ret is not None and not ret.is_int():
                self.error(d.pos, "'시작하기'의 반환 타입은 정수여야 합니다")
        fs = FuncSym(d.name, ftype, params, d, d.link_name)
        self.globals.declare(d.name, fs, d.pos)
        (self.unit.externs if fs.is_extern else self.unit.functions).append(fs)
        return fs

    # ---------- 상수 초기값 ----------
    def const_value(self, e, target):
        """전역·정적 초기화식: 상수식만."""
        if isinstance(e, A.IntLit):
            self.check_int_range(e.value, target, e.pos)
            return float(e.value) if target.is_float() else e.value
        if isinstance(e, A.FloatLit):
            if not target.is_float():
                self.error(e.pos, f"실수 리터럴을 '{target}' 변수에 넣을 수 없습니다")
            return e.value
        if isinstance(e, A.CharLit):
            return e.value
        if isinstance(e, A.BoolLit):
            return 1 if e.value else 0
        if isinstance(e, A.NullLit):
            if not target.is_ptr():
                self.error(e.pos, "'없음'은 참조 타입에만 넣을 수 있습니다")
            return 0
        if isinstance(e, A.StringLit):
            if not (target.is_ptr() and T.same_type(target.target, T.CHAR)):
                self.error(e.pos, f"문자열을 '{target}' 변수에 넣을 수 없습니다")
            if "{" in e.raw.replace("\\{", ""):
                self.error(e.pos, "보간 문자열은 초기화식에 쓸 수 없습니다")
            return ("str", e.value)
        if isinstance(e, A.Name):
            s = self.globals.lookup(e.name)
            if isinstance(s, ConstSym):
                return s.value
            self.error(e.pos, "전역 변수의 초기화식은 상수여야 합니다")
        if isinstance(e, A.Unary) and e.op == "-":
            v = self.const_value(e.operand, target)
            if isinstance(v, tuple):
                self.error(e.pos, "전역 변수의 초기화식은 상수여야 합니다")
            return -v
        if isinstance(e, A.Binary) and e.op in ("+", "-", "*", "/", "%"):
            a = self.const_value(e.left, target)
            b = self.const_value(e.right, target)
            if isinstance(a, tuple) or isinstance(b, tuple):
                self.error(e.pos, "전역 변수의 초기화식은 상수여야 합니다")
            if e.op == "+": return a + b
            if e.op == "-": return a - b
            if e.op == "*": return a * b
            if b == 0:
                self.error(e.pos, "0으로 나눌 수 없습니다")
            if e.op == "/": return a // b if target.is_int() else a / b
            return a % b
        self.error(e.pos, "전역 변수의 초기화식은 상수여야 합니다")

    def check_int_range(self, value, target, pos):
        if target.is_int():
            if not (target.min_value() <= value <= target.max_value()):
                self.error(pos, f"리터럴 {value}이(가) '{target}' 범위를 넘습니다")
        elif target.is_float():
            return
        elif target.is_ptr():
            if value != 0:
                self.error(pos, "참조에는 0(없음)만 넣을 수 있습니다")
        else:
            self.error(pos, f"정수를 '{target}'에 넣을 수 없습니다")

    # ---------- 함수 본문 ----------
    def check_function(self, d, fs):
        self.func = fs
        self.scope = Scope(self.globals)
        fs.locals = []
        for p in fs.params:
            sym = VarSym(p.name, p.rtype, "param", p.pos)
            self.scope.declare(p.name, sym, p.pos)
            p.sym = sym
        self.loop_depth = 0
        self.switch_depth = 0
        self.check_block(d.body, new_scope=False)
        if fs.type.ret is not None and not self.always_returns(d.body):
            self.error(d.pos, f"'{d.name}': 값을 반환하지 않는 경로가 있습니다")
        self.func = None
        self.scope = self.globals

    def always_returns(self, block):
        for s in block.stmts:
            if self.stmt_returns(s):
                return True
        return False

    def stmt_returns(self, s):
        if isinstance(s, A.Return):
            return True
        if isinstance(s, A.Block):
            return self.always_returns(s)
        if isinstance(s, A.If):
            if s.else_ is None:
                return False
            return self.always_returns(s.then) and all(self.always_returns(b) for _, b in s.elifs) and self.always_returns(s.else_)
        if isinstance(s, A.While):
            return isinstance(s.cond, A.BoolLit) and s.cond.value and not self.has_break(s.body)
        if isinstance(s, A.Switch):
            return s.default is not None and all(self.always_returns(b) for _, b in s.cases) and self.always_returns(s.default) \
                and not any(self.has_break(b) for _, b in s.cases) and not self.has_break(s.default)
        if isinstance(s, A.ExprStmt) and isinstance(s.expr, A.Call) and isinstance(s.expr.callee, A.Name) and s.expr.callee.name == "종료":
            return True
        if isinstance(s, A.ExprStmt) and isinstance(s.expr, A.SOVCall) and getattr(s.expr, "callee_sym", None) is not None and s.expr.callee_sym.name == "종료":
            return True
        return False

    def has_break(self, block):
        for s in block.stmts:
            if isinstance(s, A.Break):
                return True
            if isinstance(s, A.Block) and self.has_break(s):
                return True
            if isinstance(s, A.If):
                if self.has_break(s.then) or any(self.has_break(b) for _, b in s.elifs) or (s.else_ and self.has_break(s.else_)):
                    return True
        return False

    def check_block(self, block, new_scope=True):
        if new_scope:
            self.scope = Scope(self.scope)
        for s in block.stmts:
            self.check_stmt(s)
        if new_scope:
            self.scope = self.scope.parent

    def declare_local(self, d):
        t = self.resolve_type(d.type)
        if t.is_void():
            self.error(d.pos, "변수의 타입은 '공허'일 수 없습니다")
        self.check_name(d.name, d.pos)
        if d.static:
            init = self.const_value(d.init, t) if d.init is not None else None
            if d.init is not None and (t.is_array() or t.is_struct()):
                self.error(d.pos, "배열·묶음 변수는 초기화식을 가질 수 없습니다")
            self.static_counter += 1
            sym = VarSym(f"{self.func.name}.{d.name}.{self.static_counter}", t, "static", d.pos, const=d.const, init=init)
            sym.display = d.name
            self.unit.globals.append(sym)
            d.init = None
        else:
            sym = VarSym(d.name, t, "local", d.pos, const=d.const)
            if d.init is not None:
                if t.is_array():
                    self.error(d.pos, "배열 변수는 초기화식을 가질 수 없습니다")
                self.check_expr(d.init, t)
                d.init = self.coerce(d.init, t, d.init.pos, "초기화")
            self.func.locals.append(sym)
        if d.const and d.init is None and not d.static:
            self.error(d.pos, "상수는 선언과 함께 초기화해야 합니다")
        self.scope.declare(d.name, sym, d.pos)
        d.sym = sym

    def check_stmt(self, s):
        if isinstance(s, A.VarDecl):
            self.declare_local(s)
        elif isinstance(s, A.Block):
            self.check_block(s)
        elif isinstance(s, A.ExprStmt):
            e = self.check_expr(s.expr, None)
            if not isinstance(s.expr, (A.Call, A.SOVCall, A.Try)):
                self.error(s.pos, "호출이 아닌 식은 문장이 될 수 없습니다")
        elif isinstance(s, A.Assign):
            self.check_assign(s)
        elif isinstance(s, A.IncDec):
            t = self.check_lvalue(s.target)
            if not t.is_int():
                self.error(s.pos, f"증감문의 대상은 정수여야 합니다 (현재 '{t}')")
        elif isinstance(s, A.If):
            s.cond = self.check_cond(s.cond)
            self.check_block(s.then)
            s.elifs = [(self.check_cond(c), b) for c, b in s.elifs]
            for _, b in s.elifs:
                self.check_block(b)
            if s.else_:
                self.check_block(s.else_)
        elif isinstance(s, A.While):
            s.cond = self.check_cond(s.cond)
            self.loop_depth += 1
            self.check_block(s.body)
            self.loop_depth -= 1
        elif isinstance(s, A.DoWhile):
            self.loop_depth += 1
            self.check_block(s.body)
            self.loop_depth -= 1
            s.cond = self.check_cond(s.cond)
        elif isinstance(s, A.For):
            self.scope = Scope(self.scope)
            if s.init is not None:
                self.check_stmt(s.init)
            s.cond = self.check_cond(s.cond)
            if s.step is not None:
                self.check_stmt(s.step)
            self.loop_depth += 1
            self.check_block(s.body)
            self.loop_depth -= 1
            self.scope = self.scope.parent
        elif isinstance(s, A.Switch):
            st = self.check_expr(s.subject, None)
            if not st.is_int():
                self.error(s.pos, f"갈래문의 대상은 정수여야 합니다 (현재 '{st}')")
            seen = set()
            for i, (v, b) in enumerate(s.cases):
                val = self.const_value(v, st)
                if val in seen:
                    self.error(v.pos, f"'경우 {val}'이(가) 중복됩니다")
                seen.add(val)
                s.cases[i] = (val, b)
            self.switch_depth += 1
            for _, b in s.cases:
                self.check_block(b)
            if s.default:
                self.check_block(s.default)
            self.switch_depth -= 1
        elif isinstance(s, A.Return):
            ret = self.func.type.ret
            if s.value is None:
                if ret is not None and not (ret.is_result() and ret.value is None):
                    self.error(s.pos, f"'{self.func.name}'은(는) '{ret}' 값을 반환해야 합니다")
            else:
                if ret is None:
                    self.error(s.pos, f"'{self.func.name}'은(는) 반환값이 없는 함수입니다")
                self.check_expr(s.value, ret)
                s.value = self.coerce(s.value, ret, s.value.pos, "반환")
        elif isinstance(s, A.Break):
            if self.loop_depth == 0 and self.switch_depth == 0:
                self.error(s.pos, "'탈출'은 반복문·갈래문 안에서만 쓸 수 있습니다")
        elif isinstance(s, A.Continue):
            if self.loop_depth == 0:
                self.error(s.pos, "'계속'은 반복문 안에서만 쓸 수 있습니다")
        else:
            raise InternalError(f"알 수 없는 문장 {type(s).__name__}")

    def check_cond(self, e):
        t = self.check_expr(e, None)
        if not (t.is_int() or t.is_ptr()):
            self.error(e.pos, f"조건은 정수·참거짓·참조여야 합니다 (현재 '{t}')")
        return e

    def check_assign(self, s):
        t = self.check_lvalue(s.target)
        if s.op == "=":
            self.check_expr(s.value, t)
            s.value = self.coerce(s.value, t, s.value.pos, "대입")
            return
        # 복합 대입: target = target op value
        op = s.op[:-1]
        vt = self.check_expr(s.value, t if t.is_int() else None)
        if op in ("&", "|", "^", "<<", ">>", "%") and not (t.is_int() and vt.is_int()):
            self.error(s.pos, f"'{s.op}'는 정수에만 쓸 수 있습니다")
        if t.is_ptr():
            if op not in ("+", "-") or not vt.is_int():
                self.error(s.pos, "참조에는 정수를 더하거나 뺄 수만 있습니다")
        elif not ((t.is_int() or t.is_float()) and (vt.is_int() or vt.is_float())):
            self.error(s.pos, f"'{s.op}'를 '{t}'와 '{vt}'에 쓸 수 없습니다")
        s.value = self.coerce(s.value, t, s.value.pos, "대입")

    def check_lvalue(self, e):
        t = self.check_expr(e, None)
        if isinstance(e, A.Name):
            sym = e.sym
            if isinstance(sym, VarSym):
                if sym.const:
                    self.error(e.pos, f"상수 '{sym.name}'에는 대입할 수 없습니다")
                if sym.type.is_array():
                    self.error(e.pos, "배열 자체에는 대입할 수 없습니다")
                return t
            self.error(e.pos, f"'{e.name}'에는 대입할 수 없습니다")
        if isinstance(e, (A.Index, A.Member)):
            if t.is_array():
                self.error(e.pos, "배열 자체에는 대입할 수 없습니다")
            return t
        self.error(e.pos, "대입할 수 있는 대상이 아닙니다")

    # ---------- 변환 ----------
    def coerce(self, e, target, pos, what):
        """식 e (타입 e.type) 를 target 으로 암시 변환. 불가하면 오류. 변환 노드를 끼워 반환."""
        src = e.type
        if T.same_type(src, target):
            return e
        if src.is_array() and target.is_ptr() and (T.same_type(src.elem, target.target) or target.target.is_void()):
            return self.wrap_cast(e, target)
        if src.is_array() and target.is_slice() and T.same_type(src.elem, target.elem):
            return self.wrap_cast(e, target)                # 배열 → 조각 (D-17)
        if target.is_result() and target.value is not None and not src.is_result():
            inner = self.coerce(e, target.value, pos, what)  # 값 → T 결과 (성공, D-18)
            return self.wrap_cast(inner, target)
        if src.is_int() and target.is_int():
            if isinstance(e, A.IntLit):
                self.check_int_range(e.value, target, e.pos)
            return self.wrap_cast(e, target)
        if src.is_int() and target.is_float():
            if isinstance(e, A.IntLit):
                return self.wrap_cast(e, target)
            self.error(pos, f"{what}: 정수를 실수로 넣으려면 '으로 {target}' 명시 변환이 필요합니다")
        if src.is_float() and target.is_float():
            return self.wrap_cast(e, target)
        if src.is_ptr() and target.is_ptr():
            if src.target.is_void() or target.target.is_void():
                return self.wrap_cast(e, target)
            if isinstance(e, A.NullLit):
                return self.wrap_cast(e, target)
            self.error(pos, f"{what}: '{src}'를 '{target}'에 넣을 수 없습니다 (공허 참조를 거치거나 명시 변환)")
        if isinstance(e, A.IntLit) and e.value == 0 and target.is_ptr():
            return self.wrap_cast(e, target)
        if src.is_func() and target.is_func() and T.same_type(src, target):
            return e
        self.error(pos, f"{what}: '{src}' 타입을 '{target}'에 넣을 수 없습니다 — 호환되지 않는 타입")

    def wrap_cast(self, e, target):
        c = A.Cast(e.pos, e, None)
        c.type = target
        c.implicit = True
        return c

    def arith_common(self, a, b, pos, op):
        """이항 산술의 공통 타입."""
        ta, tb = a.type, b.type
        if ta.is_float() or tb.is_float():
            if not ((ta.is_float() or ta.is_int()) and (tb.is_float() or tb.is_int())):
                self.error(pos, f"'{op}'를 '{ta}'와 '{tb}'에 쓸 수 없습니다")
            return T.DOUBLE if 64 in (getattr(ta, "bits", 0), getattr(tb, "bits", 0)) and (ta.is_float() and ta.bits == 64 or tb.is_float() and tb.bits == 64) else (ta if ta.is_float() else tb)
        if ta.is_int() and tb.is_int():
            bits = max(ta.bits, tb.bits)
            signed = ta.signed and tb.signed
            if bits == 64 and signed:
                return T.INT
            return T.IntType(bits, signed)
        self.error(pos, f"'{op}'를 '{ta}'와 '{tb}'에 쓸 수 없습니다")

    # ---------- 식 ----------
    def check_expr(self, e, expected):
        t = self._check_expr(e, expected)
        e.type = t
        return t

    def _check_expr(self, e, expected):
        if isinstance(e, A.Call) and isinstance(e.callee, A.Name) and e.callee.name == "오류" and self.scope.lookup("오류") is None:
            return self.check_error_ctor(e, expected)
        if expected is not None and expected.is_result():
            expected = expected.value            # 리터럴은 결과의 값 타입을 따른다
        if isinstance(e, A.IntLit):
            if expected is not None and (expected.is_int() or expected.is_float()):
                if expected.is_int():
                    self.check_int_range(e.value, expected, e.pos)
                return expected
            if not (-(1 << 63) <= e.value < (1 << 64)):
                self.error(e.pos, f"리터럴 {e.value}이(가) 64비트 범위를 넘습니다")
            return T.UINT if e.value >= (1 << 63) else T.INT
        if isinstance(e, A.FloatLit):
            return expected if expected is not None and expected.is_float() else T.DOUBLE
        if isinstance(e, A.CharLit):
            return T.CHAR
        if isinstance(e, A.BoolLit):
            return T.BOOL
        if isinstance(e, A.NullLit):
            return expected if expected is not None and expected.is_ptr() else T.VOIDPTR
        if isinstance(e, A.StringLit):
            if self.has_interpolation(e.raw):
                self.error(e.pos, "보간 문자열은 '쓰기' 계열 호출의 첫 인자에서만 쓸 수 있습니다")
            self.unit.strings.append(e.value)
            return T.STRING
        if isinstance(e, A.Name):
            sym = self.scope.lookup(e.name)
            if sym is None:
                self.error(e.pos, f"선언되지 않은 이름입니다: '{e.name}'")
            e.sym = sym
            if isinstance(sym, VarSym):
                return sym.type
            if isinstance(sym, ConstSym):
                return sym.type
            if isinstance(sym, FuncSym):
                return sym.type
            self.error(e.pos, f"'{e.name}'은(는) 타입 이름이라 값으로 쓸 수 없습니다")
        if isinstance(e, A.Index):
            bt = self.check_expr(e.base, None)
            it = self.check_expr(e.index, T.INT)
            if not it.is_int():
                self.error(e.index.pos, f"색인은 정수여야 합니다 (현재 '{it}')")
            if bt.is_array():
                return bt.elem
            if bt.is_slice():
                return bt.elem
            if bt.is_ptr() and not bt.target.is_void():
                return bt.target
            self.error(e.pos, f"색인할 수 없는 타입입니다: '{bt}'")
        if isinstance(e, A.SliceExpr):
            bt = self.check_expr(e.base, None)
            if bt.is_array() or bt.is_slice():
                elem = bt.elem
            elif bt.is_ptr() and not bt.target.is_void():
                elem = bt.target
                if e.hi is None:
                    self.error(e.pos, "참조에서 조각을 만들 때는 끝이 필요합니다 (길이를 알 수 없습니다)")
            else:
                self.error(e.pos, f"조각을 만들 수 없는 타입입니다: '{bt}'")
            for which in ("lo", "hi"):
                x = getattr(e, which)
                if x is not None:
                    t = self.check_expr(x, T.INT)
                    if not t.is_int():
                        self.error(x.pos, f"조각의 경계는 정수여야 합니다 (현재 '{t}')")
                    setattr(e, which, self.coerce(x, T.INT, x.pos, "조각"))
            return T.SliceType(elem)
        if isinstance(e, A.Member):
            bt = self.check_expr(e.base, None)
            st = bt
            if bt.is_ptr():
                st = bt.target
            if not st.is_agg():
                self.error(e.pos, f"'{bt}'에는 멤버가 없습니다")
            f = st.field(e.name)
            if f is None:
                self.error(e.pos, f"'{st}'에 '{e.name}' 필드가 없습니다")
            e.field = f
            return f[1]
        if isinstance(e, A.Call):
            if isinstance(e.callee, A.Name) and e.callee.name == "가변인자" and self.scope.lookup("가변인자") is None:
                return self.check_vararg(e)
            return self.check_call(e)
        if isinstance(e, A.Try):
            t = self.check_expr(e.expr, None)
            if not t.is_result():
                self.error(e.pos, f"'시도'의 대상은 결과 타입이어야 합니다 (현재 '{t}')")
            if self.func is None or self.func.type.ret is None or not self.func.type.ret.is_result():
                self.error(e.pos, "'시도'는 결과를 돌려주는 함수 안에서만 쓸 수 있습니다")
            return t.value if t.value is not None else T.VOID
        if isinstance(e, A.SOVCall):
            return self.check_sov_call(e)
        if isinstance(e, A.Unary):
            if e.op == "&":
                t = self.check_expr(e.operand, None)
                if not isinstance(e.operand, (A.Name, A.Index, A.Member)) or (isinstance(e.operand, A.Name) and not isinstance(e.operand.sym, VarSym)):
                    self.error(e.pos, "'&'는 변수·원소·필드에만 쓸 수 있습니다")
                return T.PtrType(T.decay(t) if t.is_array() else t) if not t.is_array() else T.PtrType(t.elem)
            t = self.check_expr(e.operand, expected)
            if e.op == "-":
                if not (t.is_int() or t.is_float()):
                    self.error(e.pos, f"'-'를 '{t}'에 쓸 수 없습니다")
                if t.is_int() and not t.signed:
                    return T.IntType(t.bits, True) if t.bits < 64 else T.INT
                return t
            if e.op == "~":
                if not t.is_int():
                    self.error(e.pos, f"'~'를 '{t}'에 쓸 수 없습니다")
                return t
            if e.op == "아닌":
                if not (t.is_int() or t.is_ptr()):
                    self.error(e.pos, f"'아닌'을 '{t}'에 쓸 수 없습니다")
                return T.BOOL
        if isinstance(e, A.Binary):
            return self.check_binary(e, expected)
        if isinstance(e, A.Ternary):
            self.check_cond(e.cond)
            ta = self.check_expr(e.a, expected)
            tb = self.check_expr(e.b, expected)
            if T.same_type(ta, tb):
                return ta
            if (ta.is_int() or ta.is_float()) and (tb.is_int() or tb.is_float()):
                ct = self.arith_common(e.a, e.b, e.pos, "?:")
                e.a = self.coerce(e.a, ct, e.a.pos, "삼항")
                e.b = self.coerce(e.b, ct, e.b.pos, "삼항")
                return ct
            if ta.is_ptr() and tb.is_ptr():
                return ta
            self.error(e.pos, f"삼항 연산의 두 값 타입이 다릅니다: '{ta}', '{tb}'")
        if isinstance(e, A.Cast):
            if e.type is not None and getattr(e, "implicit", False):
                return e.type
            target = self.resolve_type(e.type)
            src = self.check_expr(e.expr, None)
            src = T.decay(src)
            ok = ((src.is_int() or src.is_float()) and (target.is_int() or target.is_float())) \
                or (src.is_ptr() and (target.is_ptr() or target.is_int())) \
                or (src.is_int() and target.is_ptr()) \
                or (src.is_func() and target.is_ptr())
            if not ok:
                self.error(e.pos, f"'{src}'를 '{target}'(으)로 변환할 수 없습니다")
            e.type = target
            return target
        if isinstance(e, A.SizeOf):
            e.rtype = self.resolve_type(e.type)
            return T.INT
        raise InternalError(f"알 수 없는 식 {type(e).__name__}")

    def check_binary(self, e, expected):
        op = e.op
        if op == "혹은":
            tl = self.check_expr(e.left, None)
            if not tl.is_result() or tl.value is None:
                self.error(e.pos, f"'혹은'의 왼쪽은 값이 있는 결과여야 합니다 (현재 '{tl}')")
            self.check_expr(e.right, tl.value)
            e.right = self.coerce(e.right, tl.value, e.right.pos, "혹은")
            return tl.value
        if op in ("그리고", "또는"):
            self.check_cond(e.left)
            self.check_cond(e.right)
            return T.BOOL
        hint = expected if (expected is not None and (expected.is_int() or expected.is_float())) else None
        # 리터럴은 다른 쪽 피연산자의 타입을 따른다. 들어가지 않는 정수 리터럴은 정수(64비트)로 (명세 3.8)
        if isinstance(e.left, (A.IntLit, A.FloatLit)) and not isinstance(e.right, (A.IntLit, A.FloatLit)):
            tr = self.check_expr(e.right, hint)
            tl = self.check_expr(e.left, self.operand_hint(e.left, tr))
        else:
            tl = self.check_expr(e.left, hint)
            tr = self.check_expr(e.right, self.operand_hint(e.right, tl))
        tl, tr = T.decay(tl), T.decay(tr)
        if op in ("==", "!=", "<", ">", "<=", ">="):
            if tl.is_ptr() and (tr.is_ptr() or isinstance(e.right, (A.IntLit, A.NullLit))):
                e.right = self.coerce(e.right, tl, e.right.pos, "비교") if not tr.is_ptr() else e.right
                e.cmp_type = tl
                return T.BOOL
            if tr.is_ptr() and isinstance(e.left, (A.IntLit, A.NullLit)):
                e.left = self.coerce(e.left, tr, e.left.pos, "비교")
                e.cmp_type = tr
                return T.BOOL
            if tl.is_func() and tr.is_func():
                e.cmp_type = tl
                return T.BOOL
            ct = self.arith_common(e.left, e.right, e.pos, op)
            e.left = self.coerce(e.left, ct, e.left.pos, "비교")
            e.right = self.coerce(e.right, ct, e.right.pos, "비교")
            e.cmp_type = ct
            return T.BOOL
        if op in ("+", "-") and tl.is_ptr():
            if op == "-" and tr.is_ptr():
                if not T.same_type(tl, tr):
                    self.error(e.pos, "서로 다른 참조 타입끼리는 뺄 수 없습니다")
                e.ptr_diff = True
                return T.INT
            if not tr.is_int():
                self.error(e.pos, "참조에는 정수만 더하거나 뺄 수 있습니다")
            e.right = self.coerce(e.right, T.INT, e.right.pos, "참조 산술")
            e.ptr_arith = True
            return tl
        if op == "+" and tr.is_ptr() and tl.is_int():
            e.left, e.right = e.right, e.left
            e.right = self.coerce(e.right, T.INT, e.right.pos, "참조 산술")
            e.ptr_arith = True
            return tr
        if op in ("&", "|", "^", "<<", ">>", "%"):
            if not (tl.is_int() and tr.is_int()):
                self.error(e.pos, f"'{op}'는 정수에만 쓸 수 있습니다 ('{tl}', '{tr}')")
        ct = self.arith_common(e.left, e.right, e.pos, op)
        if op in ("<<", ">>"):
            ct = tl if tl.is_int() else ct
            e.right = self.coerce(e.right, T.INT, e.right.pos, "시프트")
            e.left = self.coerce(e.left, ct, e.left.pos, "시프트")
            return ct
        e.left = self.coerce(e.left, ct, e.left.pos, "산술")
        e.right = self.coerce(e.right, ct, e.right.pos, "산술")
        return ct

    @staticmethod
    def operand_hint(lit, t):
        """상대 피연산자 타입 t 를 리터럴의 힌트로. 정수 리터럴이 t 에 들어가지 않으면 힌트 없음(정수)."""
        if not (t.is_int() or t.is_float()):
            return None
        if isinstance(lit, A.IntLit) and t.is_int() and not (t.min_value() <= lit.value <= t.max_value()):
            return None
        return t

    # ---------- 호출 ----------
    def callee_of(self, e):
        if isinstance(e.callee, A.Name):
            sym = self.scope.lookup(e.callee.name)
            if sym is None:
                self.error(e.callee.pos, f"선언되지 않은 함수입니다: '{e.callee.name}'")
            e.callee.sym = sym
            if isinstance(sym, FuncSym):
                e.callee.type = sym.type
                return sym, sym.type
            if isinstance(sym, VarSym) and sym.type.is_func():
                e.callee.type = sym.type
                return None, sym.type
            self.error(e.callee.pos, f"'{e.callee.name}'은(는) 함수가 아닙니다")
        t = self.check_expr(e.callee, None)
        if not t.is_func():
            self.error(e.callee.pos, f"호출할 수 없는 타입입니다: '{t}'")
        return None, t

    def check_error_ctor(self, e, expected):
        """오류(코드): 문맥의 결과 타입으로 실패 값을 만든다 (명세 3.8)."""
        if expected is None or not expected.is_result():
            self.error(e.pos, "'오류(...)'의 결과 타입을 알 수 없습니다 — 반환·대입·인자 자리에서 쓰세요")
        if len(e.args) != 1:
            self.error(e.pos, "'오류'에는 코드 하나가 필요합니다")
        t = self.check_expr(e.args[0], T.INT)
        if not t.is_int():
            self.error(e.args[0].pos, f"오류 코드는 정수여야 합니다 (현재 '{t}')")
        e.args[0] = self.coerce(e.args[0], T.INT, e.args[0].pos, "오류")
        e.err_ctor = True
        e.callee_sym = None
        e.resolved_args = list(e.args)
        return expected

    def check_vararg(self, e):
        """명세 3.5: 가변 인자 함수 안에서 k 번째 추가 인자를 64비트 원시 값으로 읽는다."""
        if self.func is None or not self.func.type.variadic:
            self.error(e.pos, "'가변인자'는 가변 인자 함수(...) 안에서만 쓸 수 있습니다")
        if len(e.args) != 1:
            self.error(e.pos, "'가변인자'에는 색인 하나가 필요합니다")
        t = self.check_expr(e.args[0], T.INT)
        if not t.is_int():
            self.error(e.args[0].pos, f"'가변인자'의 색인은 정수여야 합니다 (현재 '{t}')")
        e.args[0] = self.coerce(e.args[0], T.INT, e.args[0].pos, "가변인자")
        e.vararg = True
        e.callee_sym = None
        e.resolved_args = list(e.args)
        return T.INT

    def check_call(self, e):
        fsym, ftype = self.callee_of(e)
        e.callee_sym = fsym
        args = list(e.args)
        e.resolved_args = self.bind_args(e, ftype, args, fsym)
        return ftype.ret if ftype.ret is not None else T.VOID

    def bind_args(self, e, ftype, args, fsym):
        n = len(ftype.params)
        if len(args) < n or (len(args) > n and not ftype.variadic):
            name = fsym.name if fsym else "함수"
            self.error(e.pos, f"'{name}' 호출의 인자 개수가 다릅니다: {n}개 필요, {len(args)}개 있음")
        out = []
        for i, a in enumerate(args):
            if i < n:
                pt = ftype.params[i]
                if i == 0 and ftype.variadic and isinstance(a, A.StringLit) and self.has_interpolation(a.raw):
                    if len(args) > 1:
                        self.error(a.pos, "보간 문자열에는 추가 서식 인자를 섞을 수 없습니다")
                    fmt, names = self.expand_interpolation(a)
                    a.value = fmt
                    a.raw = ""
                    self.check_expr(a, pt)
                    out.append(self.coerce(a, pt, a.pos, "인자"))
                    for nm in names:
                        self.check_expr(nm, None)
                        out.append(self.promote_vararg(nm))
                    return out
                at = self.check_expr(a, pt)
                out.append(self.coerce(a, pt, a.pos, f"인자 {i + 1}"))
            else:
                self.check_expr(a, None)
                out.append(self.promote_vararg(a))
        return out

    def promote_vararg(self, a):
        t = T.decay(a.type)
        if t.is_int():
            return self.wrap_cast(a, T.IntType(64, t.signed)) if t.bits < 64 else a
        if t.is_float():
            return self.wrap_cast(a, T.DOUBLE) if t.bits < 64 else a
        if t.is_array():
            return self.wrap_cast(a, T.PtrType(t.elem))
        if t.is_ptr() or t.is_func():
            return a
        self.error(a.pos, f"'{t}' 타입은 가변 인자로 넘길 수 없습니다")

    def check_sov_call(self, e):
        fsym = self.resolve_verb(e.verb, e.pos)
        e.callee_sym = fsym
        ftype = fsym.type
        params = fsym.params
        # 역할 정규화 (명세 3.5)
        by_role = {}
        for a, role in e.args:
            by_role.setdefault(role, []).append(a)
        ordered = [None] * len(params)
        for i, p in enumerate(params):
            if p.role is not None and by_role.get(p.role):
                ordered[i] = by_role[p.role].pop(0)
        unmarked = by_role.get(None, [])
        for i, p in enumerate(params):
            if ordered[i] is None and (p.role is None or True) and unmarked:
                ordered[i] = unmarked.pop(0)
        missing = [params[i] for i in range(len(params)) if ordered[i] is None]
        leftover = [(r, a) for r, lst in by_role.items() for a in lst if r is not None or True]
        leftover = [(r, a) for r, lst in by_role.items() for a in lst]
        if missing:
            p = missing[0]
            self.error(e.pos, f"'{fsym.name}' 호출에 '{p.name}'({ROLE_PARTICLE.get(p.role)}) 인자가 없습니다")
        if leftover and not ftype.variadic:
            r, a = leftover[0]
            self.error(a.pos, f"'{fsym.name}' 호출에 남는 인자가 있습니다 ({ROLE_PARTICLE.get(r)})")
        args = ordered + [a for r, a in leftover]
        e.resolved_args = self.bind_args(e, ftype, args, fsym)
        return ftype.ret if ftype.ret is not None else T.VOID

    def resolve_verb(self, root, pos):
        """명세 2.6: X기 → X → (X가 Y하이면) Y."""
        cands = [root + "기", root]
        base = verb_base(root)
        if base != root:
            cands.append(base)
            cands.append(base + "기")
        for c in cands:
            s = self.scope.lookup(c)
            if isinstance(s, FuncSym):
                return s
        self.error(pos, f"동사 '{root}다'에 해당하는 함수가 없습니다 (찾은 이름: {', '.join(cands)})")

    # ---------- 보간 ----------
    @staticmethod
    def has_interpolation(raw):
        if not raw:
            return False
        i = 1
        while i < len(raw) - 1:
            c = raw[i]
            if c == "\\":
                i += 2
                continue
            if c == "{":
                return True
            i += 1
        return False

    def expand_interpolation(self, lit):
        """원문 raw 를 서식 문자열과 이름 목록으로."""
        raw = lit.raw
        out = []
        names = []
        i = 1
        ESC = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\", '"': '"', "{": "{", "}": "}", "'": "'"}
        while i < len(raw) - 1:
            c = raw[i]
            if c == "\\":
                out.append(ESC[raw[i + 1]])
                i += 2
                continue
            if c == "%":
                out.append("%%")
                i += 1
                continue
            if c == "{":
                j = raw.find("}", i)
                if j < 0:
                    self.error(lit.pos, "보간 '{'가 닫히지 않았습니다")
                name = raw[i + 1:j].strip()
                sym = self.scope.lookup(name)
                if not isinstance(sym, (VarSym, ConstSym)):
                    self.error(lit.pos, f"보간에 쓸 수 없는 이름입니다: '{name}'")
                t = T.decay(sym.type)
                if t.is_int():
                    if t is T.CHAR or (t.bits == 8 and t.signed and sym.type.name == "문자"):
                        fmt = "%c"
                    else:
                        fmt = "%llu" if not t.signed and t.bits == 64 else "%lld"
                elif t.is_float():
                    fmt = "%f"
                elif t.is_ptr() and T.same_type(t.target, T.CHAR):
                    fmt = "%s"
                else:
                    self.error(lit.pos, f"'{name}'의 타입 '{t}'은(는) 보간할 수 없습니다")
                out.append(fmt)
                n = A.Name(lit.pos, name)
                names.append(n)
                i = j + 1
                continue
            out.append(c)
            i += 1
        return "".join(out), names


def analyze(program):
    return Sema(program).analyze()
