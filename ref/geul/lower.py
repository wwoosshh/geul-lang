"""AST → 타입 IR. 의미 분석이 붙인 타입만 사용한다."""
from . import ast as A
from . import types as T
from .ir import IRModule, IRFunction, Temp, dll_for
from .sema import VarSym, FuncSym, ConstSym
from .diagnostics import InternalError

ARG_REGS = 4


class Lowerer:
    def __init__(self, unit):
        self.unit = unit
        self.mod = IRModule()
        self.f = None
        self.loops = []        # (continue_label, break_label)
        self.breaks = []       # break 만 (갈래)

    # ---------- 진입 ----------
    def lower(self):
        for fs in self.unit.externs:
            self.mod.externs[fs.link_name] = (dll_for(fs.link_name), fs.type)
        for g in self.unit.globals:
            self.mod.globals.append(g)
            if isinstance(g.init, tuple) and g.init[0] == "str":
                g.init_index = self.mod.intern_string(g.init[1])    # 문자열 풀 순서를 결정적으로: 전역 초기값이 먼저
        for fs in self.unit.functions:
            self.mod.functions.append(self.lower_function(fs))
        self.mod.entry = self.unit.entry.name
        return self.mod

    def lower_function(self, fs):
        f = IRFunction(fs.name, [(p.sym, p.rtype) for p in fs.params], fs.type.ret, is_entry=(fs is self.unit.entry))
        self.f = f
        for p in fs.params:
            f.locals.append(p.sym)
        for v in fs.locals:
            f.locals.append(v)
        self.loops = []
        self.breaks = []
        self.lower_block(fs.decl.body)
        # 끝에 도달하면 반환 (반환 타입이 있으면 의미 분석이 막았다)
        f.emit("ret", value=None)
        self.f = None
        return f

    # ---------- 문장 ----------
    def lower_block(self, block):
        for s in block.stmts:
            self.lower_stmt(s)

    def lower_stmt(self, s):
        f = self.f
        if isinstance(s, A.VarDecl):
            if s.init is not None:
                v = self.rvalue(s.init)
                addr = self.var_addr(s.sym)
                f.emit("store", addr=addr, src=v, type=s.sym.type)
        elif isinstance(s, A.Block):
            self.lower_block(s)
        elif isinstance(s, A.ExprStmt):
            self.rvalue(s.expr, discard=True)
        elif isinstance(s, A.Assign):
            addr = self.lvalue(s.target)
            t = s.target.type
            if s.op == "=":
                v = self.rvalue(s.value)
            else:
                cur = f.new_temp(t)
                f.emit("load", dst=cur, addr=addr, type=t)
                rhs = self.rvalue(s.value)
                if t.is_ptr():
                    idx = self.to_i64(rhs, s.value.type)
                    if s.op == "-=":
                        nb = f.new_temp(T.INT); f.emit("neg", dst=nb, a=idx); idx = nb
                    v = f.new_temp(t)
                    f.emit("index_addr", dst=v, base=cur, idx=idx, size=t.target.size)
                else:
                    v = self.binop(s.op[:-1], cur, rhs, t, s.target)
            f.emit("store", addr=addr, src=v, type=t)
        elif isinstance(s, A.IncDec):
            addr = self.lvalue(s.target)
            t = s.target.type
            cur = f.new_temp(t)
            f.emit("load", dst=cur, addr=addr, type=t)
            one = f.new_temp(t)
            f.emit("const", dst=one, value=1)
            res = f.new_temp(t)
            f.emit("bin", dst=res, bop="add" if s.delta > 0 else "sub", a=cur, b=one)
            f.emit("store", addr=addr, src=res, type=t)
        elif isinstance(s, A.If):
            end = f.new_label("끝")
            conds = [(s.cond, s.then)] + list(s.elifs)
            for cond, block in conds:
                nxt = f.new_label("아니면")
                c = self.condition(cond)
                then_l = f.new_label("이면")
                f.emit("br", cond=c, ltrue=then_l, lfalse=nxt)
                f.emit("label", name=then_l)
                self.lower_block(block)
                f.emit("jmp", label=end)
                f.emit("label", name=nxt)
            if s.else_:
                self.lower_block(s.else_)
            f.emit("label", name=end)
        elif isinstance(s, A.While):
            top = f.new_label("동안"); body = f.new_label("몸"); end = f.new_label("끝")
            f.emit("label", name=top)
            c = self.condition(s.cond)
            f.emit("br", cond=c, ltrue=body, lfalse=end)
            f.emit("label", name=body)
            self.loops.append((top, end))
            self.lower_block(s.body)
            self.loops.pop()
            f.emit("jmp", label=top)
            f.emit("label", name=end)
        elif isinstance(s, A.DoWhile):
            top = f.new_label("반복"); cont = f.new_label("조건"); end = f.new_label("끝")
            f.emit("label", name=top)
            self.loops.append((cont, end))
            self.lower_block(s.body)
            self.loops.pop()
            f.emit("label", name=cont)
            c = self.condition(s.cond)
            f.emit("br", cond=c, ltrue=top, lfalse=end)
            f.emit("label", name=end)
        elif isinstance(s, A.For):
            if s.init is not None:
                self.lower_stmt(s.init)
            top = f.new_label("반복"); body = f.new_label("몸"); step = f.new_label("증감"); end = f.new_label("끝")
            f.emit("label", name=top)
            c = self.condition(s.cond)
            f.emit("br", cond=c, ltrue=body, lfalse=end)
            f.emit("label", name=body)
            self.loops.append((step, end))
            self.lower_block(s.body)
            self.loops.pop()
            f.emit("label", name=step)
            if s.step is not None:
                self.lower_stmt(s.step)
            f.emit("jmp", label=top)
            f.emit("label", name=end)
        elif isinstance(s, A.Switch):
            subj = self.rvalue(s.subject)
            st = s.subject.type
            end = f.new_label("갈래끝")
            labels = []
            for val, block in s.cases:
                l = f.new_label("경우")
                labels.append(l)
                k = f.new_temp(st)
                f.emit("const", dst=k, value=val)
                c = f.new_temp(T.BOOL)
                f.emit("cmp", dst=c, cond="eq", a=subj, b=k, type=st)
                nxt = f.new_label("다음")
                f.emit("br", cond=c, ltrue=l, lfalse=nxt)
                f.emit("label", name=nxt)
            default_l = f.new_label("기본")
            f.emit("jmp", label=default_l)
            self.breaks.append(end)
            self.loops.append(None)
            for (val, block), l in zip(s.cases, labels):
                f.emit("label", name=l)
                self.lower_block(block)
                f.emit("jmp", label=end)
            f.emit("label", name=default_l)
            if s.default:
                self.lower_block(s.default)
            self.loops.pop()
            self.breaks.pop()
            f.emit("label", name=end)
        elif isinstance(s, A.Return):
            v = self.rvalue(s.value) if s.value is not None else None
            f.emit("ret", value=v)
        elif isinstance(s, A.Break):
            if self.loops and self.loops[-1] is not None:
                f.emit("jmp", label=self.loops[-1][1])
            else:
                f.emit("jmp", label=self.breaks[-1])
        elif isinstance(s, A.Continue):
            for l in reversed(self.loops):
                if l is not None:
                    f.emit("jmp", label=l[0])
                    return
            raise InternalError("계속: 반복문이 없습니다")
        else:
            raise InternalError(f"알 수 없는 문장 {type(s).__name__}")

    # ---------- 주소 ----------
    def var_addr(self, sym):
        t = self.f.new_temp(T.PtrType(sym.type))
        if sym.kind in ("local", "param"):
            self.f.emit("addr_local", dst=t, var=sym)
        else:
            self.f.emit("addr_global", dst=t, var=sym)
        return t

    def lvalue(self, e):
        """식의 주소 (참조 타입 임시값)."""
        f = self.f
        if isinstance(e, A.Cast) and getattr(e, "implicit", False):
            return self.lvalue(e.expr)
        if isinstance(e, A.Name):
            if not isinstance(e.sym, VarSym):
                raise InternalError("주소를 취할 수 없는 이름")
            return self.var_addr(e.sym)
        if isinstance(e, A.Index):
            base = self.rvalue(e.base)          # 배열은 첫 원소 참조로 decay 된다
            idx = self.rvalue(e.index)
            idx64 = self.to_i64(idx, e.index.type)
            elem = e.type
            t = f.new_temp(T.PtrType(elem))
            f.emit("index_addr", dst=t, base=base, idx=idx64, size=elem.size)
            return t
        if isinstance(e, A.Member):
            bt = e.base.type
            if bt.is_ptr():
                base = self.rvalue(e.base)
            else:
                base = self.lvalue(e.base)
            name, ftype, off = e.field
            t = f.new_temp(T.PtrType(ftype))
            f.emit("gep", dst=t, base=base, offset=off)
            return t
        raise InternalError(f"좌변이 아닌 식 {type(e).__name__}")

    def to_i64(self, v, t):
        if t.is_int() and t.bits == 64:
            return v
        d = self.f.new_temp(T.INT)
        self.f.emit("cast", dst=d, kind="sext" if t.signed else "zext", src=v)
        return d

    # ---------- 값 ----------
    def rvalue(self, e, discard=False):
        f = self.f
        t = e.type
        if isinstance(e, A.IntLit):
            d = f.new_temp(t)
            f.emit("const", dst=d, value=e.value)
            return d
        if isinstance(e, A.FloatLit):
            d = f.new_temp(t)
            f.emit("fconst", dst=d, value=e.value)
            return d
        if isinstance(e, A.CharLit):
            d = f.new_temp(t)
            f.emit("const", dst=d, value=e.value)
            return d
        if isinstance(e, A.BoolLit):
            d = f.new_temp(t)
            f.emit("const", dst=d, value=1 if e.value else 0)
            return d
        if isinstance(e, A.NullLit):
            d = f.new_temp(t)
            f.emit("const", dst=d, value=0)
            return d
        if isinstance(e, A.StringLit):
            d = f.new_temp(T.STRING)
            f.emit("str", dst=d, index=self.mod.intern_string(e.value))
            return d
        if isinstance(e, A.Name):
            sym = e.sym
            if isinstance(sym, ConstSym):
                d = f.new_temp(t)
                f.emit("const", dst=d, value=sym.value)
                return d
            if isinstance(sym, FuncSym):
                d = f.new_temp(sym.type)
                f.emit("func_addr", dst=d, name=sym.link_name if sym.is_extern else sym.name, extern=sym.is_extern)
                return d
            addr = self.var_addr(sym)
            if t.is_array() or t.is_struct():
                return addr                      # 배열/묶음 값 = 그 주소
            d = f.new_temp(t)
            f.emit("load", dst=d, addr=addr, type=t)
            return d
        if isinstance(e, (A.Index, A.Member)):
            addr = self.lvalue(e)
            if t.is_array() or t.is_struct():
                return addr
            d = f.new_temp(t)
            f.emit("load", dst=d, addr=addr, type=t)
            return d
        if isinstance(e, A.Call):
            return self.lower_call(e, e.resolved_args, discard)
        if isinstance(e, A.SOVCall):
            return self.lower_call(e, e.resolved_args, discard, surface=[a for a, _ in e.args])
        if isinstance(e, A.Unary):
            if e.op == "&":
                return self.lvalue(e.operand)
            v = self.rvalue(e.operand)
            d = f.new_temp(t)
            if e.op == "-":
                f.emit("neg", dst=d, a=v)
            elif e.op == "~":
                f.emit("not", dst=d, a=v)
            elif e.op == "아닌":
                f.emit("lnot", dst=d, a=v, type=e.operand.type)
            return d
        if isinstance(e, A.Binary):
            return self.lower_binary(e)
        if isinstance(e, A.Ternary):
            c = self.condition(e.cond)
            la = f.new_label("참"); lb = f.new_label("거짓"); end = f.new_label("끝")
            d = f.new_temp(t)
            f.emit("br", cond=c, ltrue=la, lfalse=lb)
            f.emit("label", name=la)
            f.emit("copy", dst=d, src=self.rvalue(e.a))
            f.emit("jmp", label=end)
            f.emit("label", name=lb)
            f.emit("copy", dst=d, src=self.rvalue(e.b))
            f.emit("label", name=end)
            return d
        if isinstance(e, A.Cast):
            return self.lower_cast(e)
        if isinstance(e, A.SizeOf):
            d = f.new_temp(T.INT)
            f.emit("const", dst=d, value=e.rtype.size)
            return d
        raise InternalError(f"알 수 없는 식 {type(e).__name__}")

    def condition(self, e):
        """조건: 참거짓 임시값을 낸다 (정수/참조는 0 비교)."""
        v = self.rvalue(e)
        t = T.decay(e.type)
        if t.is_int() and t.bits == 8 and not t.signed and e.type is T.BOOL:
            return v
        zero = self.f.new_temp(t)
        self.f.emit("const", dst=zero, value=0)
        d = self.f.new_temp(T.BOOL)
        self.f.emit("cmp", dst=d, cond="ne", a=v, b=zero, type=t)
        return d

    def lower_cast(self, e):
        f = self.f
        src_t = T.decay(e.expr.type)
        dst_t = e.type
        v = self.rvalue(e.expr)
        if T.same_type(src_t, dst_t) or (src_t.is_ptr() and dst_t.is_ptr()) or (src_t.is_func() and dst_t.is_ptr()) \
                or (e.expr.type.is_array() and dst_t.is_ptr()):
            d = f.new_temp(dst_t)
            f.emit("copy", dst=d, src=v)
            return d
        d = f.new_temp(dst_t)
        if src_t.is_int() and dst_t.is_int():
            if dst_t.bits > src_t.bits:
                kind = "sext" if src_t.signed else "zext"
            elif dst_t.bits < src_t.bits:
                kind = "trunc"
            else:
                kind = "copy"
        elif src_t.is_int() and dst_t.is_float():
            kind = "sitofp" if src_t.signed else "uitofp"
            if src_t.bits < 64:
                v = self.to_i64(v, src_t)
        elif src_t.is_float() and dst_t.is_int():
            kind = "fptosi"
        elif src_t.is_float() and dst_t.is_float():
            kind = "fpext" if dst_t.bits > src_t.bits else "fptrunc"
        elif src_t.is_ptr() and dst_t.is_int():
            kind = "copy" if dst_t.bits == 64 else "trunc"
        elif src_t.is_int() and dst_t.is_ptr():
            kind = "copy" if src_t.bits == 64 else ("sext" if src_t.signed else "zext")
        else:
            raise InternalError(f"변환 불가 {src_t} -> {dst_t}")
        if kind == "copy":
            f.emit("copy", dst=d, src=v)
        else:
            f.emit("cast", dst=d, kind=kind, src=v)
        return d

    BIN_OPS = {"+": "add", "-": "sub", "*": "mul", "/": "div", "%": "rem", "&": "and", "|": "or", "^": "xor", "<<": "shl", ">>": "shr"}
    CMP_OPS = {"==": "eq", "!=": "ne", "<": "lt", ">": "gt", "<=": "le", ">=": "ge"}

    def binop(self, op, a, b, t, node=None):
        f = self.f
        d = f.new_temp(t)
        if t.is_float():
            f.emit("bin", dst=d, bop="f" + self.BIN_OPS[op], a=a, b=b)
            return d
        name = self.BIN_OPS[op]
        if name == "div":
            name = "sdiv" if t.signed else "udiv"
        elif name == "rem":
            name = "srem" if t.signed else "urem"
        elif name == "shr":
            name = "ashr" if t.signed else "lshr"
        f.emit("bin", dst=d, bop=name, a=a, b=b)
        return d

    def lower_binary(self, e):
        f = self.f
        op = e.op
        t = e.type
        if op in ("그리고", "또는"):
            d = f.new_temp(T.BOOL)
            rhs = f.new_label("우변"); end = f.new_label("끝")
            a = self.condition(e.left)
            f.emit("copy", dst=d, src=a)
            if op == "그리고":
                f.emit("br", cond=a, ltrue=rhs, lfalse=end)
            else:
                f.emit("br", cond=a, ltrue=end, lfalse=rhs)
            f.emit("label", name=rhs)
            b = self.condition(e.right)
            f.emit("copy", dst=d, src=b)
            f.emit("label", name=end)
            return d
        if op in self.CMP_OPS:
            a = self.rvalue(e.left)
            b = self.rvalue(e.right)
            ct = T.decay(e.cmp_type)
            cond = self.CMP_OPS[op]
            if ct.is_float():
                cond = "f" + cond
            elif ct.is_ptr() or ct.is_func() or (ct.is_int() and not ct.signed):
                if cond in ("lt", "gt", "le", "ge"):
                    cond = "u" + cond
            d = f.new_temp(T.BOOL)
            f.emit("cmp", dst=d, cond=cond, a=a, b=b, type=ct)
            return d
        if getattr(e, "ptr_diff", False):
            a = self.rvalue(e.left); b = self.rvalue(e.right)
            diff = f.new_temp(T.INT)
            f.emit("bin", dst=diff, bop="sub", a=a, b=b)
            size = T.decay(e.left.type).target.size
            if size > 1:
                k = f.new_temp(T.INT); f.emit("const", dst=k, value=size)
                d = f.new_temp(T.INT); f.emit("bin", dst=d, bop="sdiv", a=diff, b=k)
                return d
            return diff
        if getattr(e, "ptr_arith", False):
            a = self.rvalue(e.left); b = self.rvalue(e.right)
            b64 = self.to_i64(b, e.right.type)
            if op == "-":
                nb = f.new_temp(T.INT); f.emit("neg", dst=nb, a=b64); b64 = nb
            d = f.new_temp(t)
            f.emit("index_addr", dst=d, base=a, idx=b64, size=T.decay(e.left.type).target.size)
            return d
        a = self.rvalue(e.left)
        b = self.rvalue(e.right)
        if op in ("<<", ">>"):
            b = self.to_i64(b, e.right.type)
        return self.binop(op, a, b, t)

    # ---------- 호출 ----------
    def lower_call(self, e, args, discard, surface=None):
        f = self.f
        fsym = e.callee_sym
        ftype = fsym.type if fsym is not None else e.callee.type
        # 인자는 표면 순서로 평가 (명세 3.5)
        order = list(range(len(args)))
        if surface is not None:
            def key(i):
                a = args[i]
                while isinstance(a, A.Cast) and getattr(a, "implicit", False):
                    a = a.expr
                for j, s in enumerate(surface):
                    if s is a:
                        return j
                return len(surface) + i
            order.sort(key=key)
        vals = [None] * len(args)
        for i in order:
            vals[i] = self.rvalue(args[i])
        if fsym is not None:
            callee = fsym.link_name if fsym.is_extern else fsym.name
            is_extern = fsym.is_extern
        else:
            callee = self.rvalue(e.callee)
            is_extern = False
        f.max_call_args = max(f.max_call_args, len(vals))
        dst = None
        if ftype.ret is not None and not discard:
            dst = f.new_temp(ftype.ret)
        elif ftype.ret is not None:
            dst = f.new_temp(ftype.ret)
        f.emit("call", dst=dst, callee=callee, extern=is_extern, args=vals, sig=ftype, nfixed=len(ftype.params))
        if dst is None:
            return None
        return dst


def lower_program(unit):
    return Lowerer(unit).lower()
