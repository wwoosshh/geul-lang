"""IR → x86-64 기계어. 모든 임시값은 스택 슬롯이다 (성능 목표 없음, 정확성만).
Win64 호출 규약: rcx rdx r8 r9 / xmm0-3, 섀도 32B, 5번째부터 스택, rsp 16 정렬."""
import struct
from . import types as T
from .x64 import Asm, RAX, RCX, RDX, RBP, RSP, R8, R9, R10, R11, XMM0, XMM1, ARG_REGS
from .diagnostics import InternalError
from . import runtime


class Image:
    def __init__(self):
        self.code = b""
        self.code_fixups = []       # (offset, kind, target) rel32
        self.entry = 0              # 코드 안의 오프셋
        self.strings = []           # [bytes]
        self.data = bytearray()
        self.data_abs_fixups = []   # (offset, kind, target) 64비트 절대 주소
        self.data_globals = {}      # name -> offset
        self.imports = {}           # dll -> [name]


def align(n, a):
    return (n + a - 1) // a * a


class FuncGen:
    def __init__(self, asm, f, mod):
        self.a = asm
        self.f = f
        self.mod = mod
        self.slots = {}             # VarSym or Temp -> disp from rbp
        self.frame = 0

    def layout(self):
        cur = 0
        # 매개변수: 홈 슬롯 [rbp+16+8i] 에 저장해 두고 그대로 쓴다
        for i, (sym, t) in enumerate(self.f.params):
            self.slots[sym] = 16 + 8 * i
        for sym in self.f.locals:
            if sym in self.slots:
                continue
            size = align(max(sym.type.size, 8), 8)
            a = 16 if size >= 16 else 8
            cur = align(cur + size, a)
            self.slots[sym] = -cur
        for t in self.f.temps:
            cur += 8
            self.slots[t] = -cur
        locals_size = align(cur, 16)
        out = align(max(4, self.f.max_call_args) * 8, 16)
        self.frame = locals_size + out

    def slot(self, x):
        return self.slots[x]

    # ---------- 도우미 ----------
    def load_temp(self, r, t):
        self.a.load(r, RBP, self.slot(t))

    def store_temp(self, t, r):
        self.a.store(RBP, self.slot(t), r)

    def normalize(self, r, t):
        """64비트 레지스터의 값을 타입 t 의 정규 표현(부호/영 확장)으로."""
        if t.is_int() and t.bits < 64:
            if t.signed:
                self.a.movsx_rr(r, r, t.bits)
            else:
                self.a.movzx_rr(r, r, t.bits)

    def fbits(self, t):
        return 32 if (t.is_float() and t.bits == 32) else 64

    # ---------- 본체 ----------
    def gen(self):
        a = self.a
        f = self.f
        self.layout()
        a.label(f.name)
        a.push(RBP)
        a.mov_rr(RBP, RSP)
        remaining = self.frame
        while remaining > 4096:
            a.sub_rsp(4096)
            a.store(RSP, 0, RAX)
            remaining -= 4096
        if remaining:
            a.sub_rsp(remaining)
        # 레지스터 매개변수를 홈 슬롯에 저장 (가변 인자 함수는 4개 모두 — 가변인자(k) 가 홈 슬롯을 읽는다)
        nspill = 4 if f.variadic else min(4, len(f.params))
        for i in range(nspill):
            t = f.params[i][1] if i < len(f.params) else None
            if t is not None and t.is_float():
                a.movsd_store(RBP, 16 + 8 * i, i, self.fbits(t))
            else:
                a.store(RBP, 16 + 8 * i, ARG_REGS[i])
        for inst in f.insts:
            self.gen_inst(inst)

    def epilogue(self):
        self.a.mov_rr(RSP, RBP)
        self.a.pop(RBP)
        self.a.ret()

    def gen_inst(self, i):
        a = self.a
        op = i.op
        if op == "label":
            a.label(i.name)
        elif op == "jmp":
            a.jmp(i.label)
        elif op == "br":
            self.load_temp(RAX, i.cond)
            a.test(RAX, RAX)
            a.jcc("ne", i.ltrue)
            a.jmp(i.lfalse)
        elif op == "const":
            a.mov_imm(RAX, i.value)
            self.store_temp(i.dst, RAX)
        elif op == "fconst":
            if self.fbits(i.dst.type) == 32:
                a.mov_imm(RAX, struct.unpack("<I", struct.pack("<f", i.value))[0])
            else:
                a.mov_imm(RAX, struct.unpack("<Q", struct.pack("<d", i.value))[0])
            self.store_temp(i.dst, RAX)
        elif op == "str":
            a.lea_rip(RAX, "str", i.index)
            self.store_temp(i.dst, RAX)
        elif op == "addr_local":
            a.lea(RAX, RBP, self.slot(i.var))
            self.store_temp(i.dst, RAX)
        elif op == "addr_global":
            a.lea_rip(RAX, "data", i.var.name)
            self.store_temp(i.dst, RAX)
        elif op == "func_addr":
            if i.extern:
                a.load_rip(RAX, "iat", i.name)
            else:
                a.lea_rip(RAX, "func", i.name)
            self.store_temp(i.dst, RAX)
        elif op == "copy":
            self.load_temp(RAX, i.src)
            self.store_temp(i.dst, RAX)
        elif op == "load":
            t = i.type
            self.load_temp(RCX, i.addr)
            if t.is_float():
                a.load(RAX, RCX, 0, self.fbits(t), False)
            elif t.is_int():
                a.load(RAX, RCX, 0, t.bits, t.signed)
            else:
                a.load(RAX, RCX, 0, 64)
            self.store_temp(i.dst, RAX)
        elif op == "store":
            t = i.type
            self.load_temp(RCX, i.addr)
            self.load_temp(RAX, i.src)
            bits = t.bits if (t.is_int() or t.is_float()) else 64
            a.store(RCX, 0, RAX, bits)
        elif op == "gep":
            self.load_temp(RAX, i.base)
            if i.offset:
                a.alu_imm("add", RAX, i.offset)
            self.store_temp(i.dst, RAX)
        elif op == "index_addr":
            self.load_temp(RAX, i.base)
            self.load_temp(RCX, i.idx)
            if i.size != 1:
                a.mov_imm(RDX, i.size)
                a.imul(RCX, RDX)
            a.alu("add", RAX, RCX)
            self.store_temp(i.dst, RAX)
        elif op == "bin":
            self.gen_bin(i)
        elif op == "cmp":
            self.gen_cmp(i)
        elif op == "neg":
            t = i.dst.type
            if t.is_float():
                self.load_temp(RAX, i.a)
                a.mov_imm(RCX, 1 << (self.fbits(t) - 1))
                a.alu("xor", RAX, RCX)
            else:
                self.load_temp(RAX, i.a)
                a.neg(RAX)
                self.normalize(RAX, t)
            self.store_temp(i.dst, RAX)
        elif op == "not":
            self.load_temp(RAX, i.a)
            a.not_(RAX)
            self.normalize(RAX, i.dst.type)
            self.store_temp(i.dst, RAX)
        elif op == "lnot":
            self.load_temp(RAX, i.a)
            a.test(RAX, RAX)
            a.setcc("e", RAX)
            a.movzx_rr(RAX, RAX, 8)
            self.store_temp(i.dst, RAX)
        elif op == "cast":
            self.gen_cast(i)
        elif op == "vararg":
            # [rbp + 16 + 8*(고정 매개변수 수 + idx)]
            self.load_temp(RCX, i.idx)
            a.mov_imm(RDX, 8)
            a.imul(RCX, RDX)
            a.lea(RAX, RBP, 16 + 8 * len(self.f.params))
            a.alu("add", RAX, RCX)
            a.load(RAX, RAX, 0, 64)
            self.store_temp(i.dst, RAX)
        elif op == "call":
            self.gen_call(i)
        elif op == "ret":
            if i.value is not None:
                t = i.value.type
                if t.is_float():
                    a.movsd_load(XMM0, RBP, self.slot(i.value), self.fbits(t))
                else:
                    self.load_temp(RAX, i.value)
            else:
                a.mov_imm(RAX, 0)
            self.epilogue()
        else:
            raise InternalError(f"코드 생성: 알 수 없는 IR 명령 {op}")

    def gen_bin(self, i):
        a = self.a
        t = i.dst.type
        op = i.bop
        if op.startswith("f"):
            bits = self.fbits(t)
            a.movsd_load(XMM0, RBP, self.slot(i.a), bits)
            a.movsd_load(XMM1, RBP, self.slot(i.b), bits)
            a.fop(op[1:], XMM0, XMM1, bits)
            a.movsd_store(RBP, self.slot(i.dst), XMM0, bits)
            return
        self.load_temp(RAX, i.a)
        self.load_temp(RCX, i.b)
        if op in ("add", "sub", "and", "or", "xor"):
            a.alu(op, RAX, RCX)
        elif op == "mul":
            a.imul(RAX, RCX)
        elif op == "sdiv":
            a.cqo(); a.idiv(RCX)
        elif op == "srem":
            a.cqo(); a.idiv(RCX); a.mov_rr(RAX, RDX)
        elif op == "udiv":
            a.alu("xor", RDX, RDX); a.div(RCX)
        elif op == "urem":
            a.alu("xor", RDX, RDX); a.div(RCX); a.mov_rr(RAX, RDX)
        elif op == "shl":
            a.shift_cl("shl", RAX)
        elif op == "lshr":
            a.shift_cl("shr", RAX)
        elif op == "ashr":
            a.shift_cl("sar", RAX)
        else:
            raise InternalError(f"이항 연산 {op}")
        self.normalize(RAX, t)
        self.store_temp(i.dst, RAX)

    def gen_cmp(self, i):
        a = self.a
        cond = i.cond
        t = i.type
        if cond.startswith("f"):
            bits = self.fbits(t)
            a.movsd_load(XMM0, RBP, self.slot(i.a), bits)
            a.movsd_load(XMM1, RBP, self.slot(i.b), bits)
            c = cond[1:]
            if c == "eq":
                a.ucomis(XMM0, XMM1, bits); a.setcc("e", RAX); a.setcc("np", RCX)
                a.movzx_rr(RAX, RAX, 8); a.movzx_rr(RCX, RCX, 8); a.alu("and", RAX, RCX)
            elif c == "ne":
                a.ucomis(XMM0, XMM1, bits); a.setcc("ne", RAX); a.setcc("p", RCX)
                a.movzx_rr(RAX, RAX, 8); a.movzx_rr(RCX, RCX, 8); a.alu("or", RAX, RCX)
            else:
                if c in ("lt", "le"):
                    a.ucomis(XMM1, XMM0, bits)
                    a.setcc("a" if c == "lt" else "ae", RAX)
                else:
                    a.ucomis(XMM0, XMM1, bits)
                    a.setcc("a" if c == "gt" else "ae", RAX)
                a.movzx_rr(RAX, RAX, 8)
            self.store_temp(i.dst, RAX)
            return
        self.load_temp(RAX, i.a)
        self.load_temp(RCX, i.b)
        a.alu("cmp", RAX, RCX)
        cc = {"eq": "e", "ne": "ne", "lt": "l", "le": "le", "gt": "g", "ge": "ge", "ult": "b", "ule": "be", "ugt": "a", "uge": "ae"}[cond]
        a.setcc(cc, RAX)
        a.movzx_rr(RAX, RAX, 8)
        self.store_temp(i.dst, RAX)

    def gen_cast(self, i):
        a = self.a
        kind = i.kind
        st = i.src.type
        dt = i.dst.type
        if kind in ("sext", "zext", "trunc"):
            self.load_temp(RAX, i.src)
            # 원본은 이미 정규 표현이므로 대상 폭으로 다시 정규화하면 된다
            if kind == "trunc" or dt.bits < 64:
                if dt.signed:
                    a.movsx_rr(RAX, RAX, dt.bits)
                else:
                    a.movzx_rr(RAX, RAX, dt.bits)
            self.store_temp(i.dst, RAX)
        elif kind in ("sitofp", "uitofp"):
            bits = self.fbits(dt)
            self.load_temp(RAX, i.src)
            if kind == "uitofp":
                # 최상위 비트가 켜져 있으면 반으로 나눠 변환 후 두 배
                l_neg = f".{self.f.name}.u2f{i.dst.id}"; l_end = l_neg + "e"
                a.test(RAX, RAX)
                a.jcc("l", l_neg)
                a.cvtsi2f(XMM0, RAX, bits)
                a.jmp(l_end)
                a.label(l_neg)
                a.mov_rr(RCX, RAX)
                a.mov_imm(RDX, 1)
                a.alu("and", RCX, RDX)           # rcx = v & 1
                a.emit(0x48, 0xD1, 0xE8)         # shr rax, 1
                a.alu("or", RAX, RCX)            # rax = (v >> 1) | (v & 1)
                a.cvtsi2f(XMM0, RAX, bits)
                a.fop("add", XMM0, XMM0, bits)
                a.label(l_end)
            else:
                a.cvtsi2f(XMM0, RAX, bits)
            a.movsd_store(RBP, self.slot(i.dst), XMM0, bits)
        elif kind == "fptosi":
            bits = self.fbits(st)
            a.movsd_load(XMM0, RBP, self.slot(i.src), bits)
            a.cvttf2si(RAX, XMM0, bits)
            self.normalize(RAX, dt)
            self.store_temp(i.dst, RAX)
        elif kind == "fpext":
            a.movsd_load(XMM0, RBP, self.slot(i.src), 32)
            a.cvtss2sd(XMM0, XMM0)
            a.movsd_store(RBP, self.slot(i.dst), XMM0, 64)
        elif kind == "fptrunc":
            a.movsd_load(XMM0, RBP, self.slot(i.src), 64)
            a.cvtsd2ss(XMM0, XMM0)
            a.movsd_store(RBP, self.slot(i.dst), XMM0, 32)
        else:
            raise InternalError(f"변환 {kind}")

    def gen_call(self, i):
        a = self.a
        sig = i.sig
        args = i.args
        # 스택 인자 (5번째부터)
        for k in range(4, len(args)):
            self.load_temp(RAX, args[k])
            a.store(RSP, 8 * k, RAX)
        # 레지스터 인자
        for k in range(min(4, len(args))):
            t = args[k].type
            if t.is_float():
                a.movsd_load(k, RBP, self.slot(args[k]), self.fbits(t))
                if sig.variadic:
                    self.load_temp(ARG_REGS[k], args[k])
            else:
                self.load_temp(ARG_REGS[k], args[k])
        callee = i.callee
        if isinstance(callee, str):
            if i.extern:
                a.call_iat(callee)
            else:
                a.call_label(callee)
        else:
            self.load_temp(R11, callee)
            a.call_reg(R11)
        if i.dst is not None:
            t = i.dst.type
            if t.is_float():
                a.movsd_store(RBP, self.slot(i.dst), XMM0, self.fbits(t))
            else:
                self.normalize(RAX, t)
                self.store_temp(i.dst, RAX)


def generate(mod):
    asm = Asm()
    img = Image()
    # 런타임 시작 함수 + 사용자 함수
    start = runtime.build_startup(mod)
    funcs = [start] + mod.functions
    for f in funcs:
        FuncGen(asm, f, mod).gen()
    asm.resolve_labels()
    img.code = bytes(asm.code)
    img.entry = asm.labels[start.name]
    # 코드 fixup: func 라벨은 코드 내부 상대 주소로 바로 해결
    for off, kind, target in asm.ext_fixups:
        if kind == "func":
            rel = asm.labels[target] - (off + 4)
            img.code = img.code[:off] + struct.pack("<i", rel) + img.code[off + 4:]
        else:
            img.code_fixups.append((off, kind, target))
    img.strings = list(mod.strings)
    # 임포트
    for name, (dll, ft) in mod.externs.items():
        img.imports.setdefault(dll, [])
        if name not in img.imports[dll]:
            img.imports[dll].append(name)
    # 전역 데이터
    for g in mod.globals:
        size = max(g.type.size, 1)
        al = min(max(g.type.align, 1), 16)
        off = align(len(img.data), al)
        img.data += b"\0" * (off - len(img.data))
        img.data_globals[g.name] = off
        init = g.init
        if init is None:
            img.data += b"\0" * size
        elif isinstance(init, tuple) and init[0] == "str":
            idx = mod.intern_string(init[1])
            img.data_abs_fixups.append((off, "str", idx))
            img.data += b"\0" * 8
        elif g.type.is_float():
            img.data += struct.pack("<d", float(init)) if g.type.bits == 64 else struct.pack("<f", float(init))
        else:
            bits = g.type.bits if g.type.is_int() else 64
            v = int(init) & ((1 << bits) - 1)
            img.data += v.to_bytes(bits // 8, "little")
    img.strings = list(mod.strings)
    return img
