"""IR → x86-64 기계어. 값은 스택 슬롯 또는 피호출자 보존 레지스터에 산다.
Win64 호출 규약: rcx rdx r8 r9 / xmm0-3, 섀도 32B, 5번째부터 스택, rsp 16 정렬.

핍홀 (D-12, 1단계). 결과가 결정적이어야 하므로 규칙을 그대로 self/코드생성.gl 에 옮긴다:
- RAX 전달: 한 번만 쓰이는 임시값이 바로 다음(명령을 내는) 명령의 RAX 피연산자면 슬롯에 저장하지 않는다.
- 상수 즉시값: 한 번만 쓰이는 const 가 add/sub/and/or/xor/mul/시프트/cmp 의 둘째 피연산자, 원소주소의 색인,
  저장의 값, 반환값이면 const 명령을 내지 않고 즉시값으로 쓴다.
- 지역 직접 접근: 한 번만 쓰이는 addr_local 이 바로 적재/저장의 주소면 [rbp+슬롯] 을 직접 쓴다.

레지스터 할당 (D-20, 2단계). 정수·참조 값(실수 제외)을 RBX RSI RDI R12-R15 에 둔다:
- 후보: 즉시값·직접 접근·RAX 전달·접기가 아닌 임시값, 그리고 주소가 새지 않는(모든 지역주소가 같은 타입의 직접
  적재/저장) 스칼라 지역·매개변수 (가변 인자 함수의 매개변수 제외).
- 생존 구간: 기본 블록 단위 역방향 자료 흐름으로 생존 집합을 구하고, 변수마다 [처음 닿는 위치, 마지막 위치].
- 선형 스캔: 시작 위치(같으면 변수 번호) 순서로, 끝 < 시작인 구간만 만료. 빈 레지스터가 없으면 끝이 가장 먼
  활성 구간이 지금 것보다 멀 때만 그 자리를 빼앗는다. 레지스터 없는 값은 슬롯에 산다.
- 프롤로그가 쓰는 레지스터를 push 하고 지역 슬롯은 그 아래에 놓는다.
내보내기 규칙 (결정적):
- 결과 레지스터: 값에 레지스터가 있으면 거기, RAX 전달 값이 레지스터 지역에 바로 저장되면 그 지역의 레지스터,
  아니면 RAX. 계산은 결과 레지스터에서 한다 (나눗셈·호출·가변인자·실수→정수는 RAX).
- 원본 읽기: 별칭(레지스터 지역의 전달되는 직접 적재는 그 레지스터 자체) → 레지스터 → RAX(전달) → 슬롯에서
  스크래치로 적재. 첫 피연산자의 스크래치는 RAX(적재하면 RAX 전달 상태가 된다), 둘째는 RCX.
- 접기: 적재·저장의 주소로만 쓰이는 오프셋·원소주소(크기 1·2·4·8 또는 상수 색인)는 메모리 피연산자에 접는다.
- 비교가 바로 분기의 조건이면 setcc 없이 jcc 로 잇는다.
"""
import struct
from . import types as T
from .x64 import Asm, RAX, RCX, RDX, RBX, RBP, RSP, RSI, RDI, R8, R9, R10, R11, R12, R13, R14, R15, XMM0, XMM1, ARG_REGS
from .ir import Temp
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


def fits32(v):
    return -(1 << 31) <= v < (1 << 31)


IMM_OPS = ("add", "sub", "and", "or", "xor")
SHIFT_OPS = ("shl", "lshr", "ashr")
OPERANDS = {
    "br": ("cond",), "copy": ("src",), "load": ("addr",), "store": ("addr", "src"), "gep": ("base",),
    "index_addr": ("base", "idx"), "bin": ("a", "b"), "cmp": ("a", "b"), "neg": ("a",), "not": ("a",),
    "lnot": ("a",), "cast": ("src",), "ret": ("value",), "vararg": ("idx",), "copy_mem": ("to", "frm"),
}
ALLOC_REGS = [RBX, RSI, RDI, R12, R13, R14, R15]     # 피호출자 보존, 이 순서로 배정
CC_OF = {"eq": "e", "ne": "ne", "lt": "l", "le": "le", "gt": "g", "ge": "ge", "ult": "b", "ule": "be", "ugt": "a", "uge": "ae"}


class FuncGen:
    def __init__(self, asm, f, mod):
        self.a = asm
        self.f = f
        self.mod = mod
        self.slots = {}             # VarSym or Temp -> disp from rbp
        self.frame = 0
        self.uses = {}
        self.defs = {}
        self.user = {}
        self.imm_only = {}          # Temp -> 상수값 (const 명령을 내지 않는다)
        self.direct = {}            # Temp -> VarSym (addr_local 명령을 내지 않는다)
        self.rax_temp = None        # 지금 RAX 에 든 임시값
        self.copy_labels = 0
        self.forwarded = set()      # RAX 로만 흐르는 임시값 (레지스터 후보 아님)
        self.fold = {}              # Temp -> 명령 (적재·저장의 주소로 접히는 오프셋·원소주소)
        self.local_ok = set()       # 레지스터 후보 지역
        self.reg = {}               # VarSym or Temp -> 레지스터
        self.nsaved = 0             # 프롤로그가 저장하는 레지스터 수 (ALLOC_REGS 의 앞부분)
        self.alias = {}             # Temp -> VarSym (레지스터 지역의 전달되는 직접 적재)
        self.pre_stored = None      # 결과를 저장 대상 레지스터에 바로 계산한 임시값
        self.pending_cc = None      # 분기로 이어질 비교의 조건 코드
        self.pending_cond = None

    def layout(self):
        cur = 8 * self.nsaved       # 저장된 레지스터들 아래부터
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

    # ---------- 분석 (핍홀) ----------
    def analyze(self):
        insts = self.f.insts
        for k, i in enumerate(insts):
            d = getattr(i, "dst", None)
            if d is not None:
                self.defs[d] = self.defs.get(d, 0) + 1
            for name in OPERANDS.get(i.op, ()):
                v = getattr(i, name)
                if isinstance(v, Temp):
                    self.uses[v] = self.uses.get(v, 0) + 1
                    self.user[v] = k
            if i.op == "call":
                for v in i.args:
                    self.uses[v] = self.uses.get(v, 0) + 1
                    self.user[v] = k
                if not isinstance(i.callee, str):
                    self.uses[i.callee] = self.uses.get(i.callee, 0) + 1
                    self.user[i.callee] = k
        for i in insts:
            if i.op == "const" and self.defs.get(i.dst) == 1 and self.uses.get(i.dst) == 1:
                u = insts[self.user[i.dst]]
                v = i.value
                d = i.dst
                ok = False
                if u.op == "bin" and u.b is d and u.a is not d:
                    if u.bop in IMM_OPS or u.bop == "mul":
                        ok = fits32(v)
                    elif u.bop in SHIFT_OPS:
                        ok = 0 <= v < 64
                elif u.op == "cmp" and u.b is d and u.a is not d and not u.cond.startswith("f"):
                    ok = fits32(v)
                elif u.op == "index_addr" and u.idx is d and u.base is not d:
                    ok = fits32(v * u.size)
                elif u.op == "store" and u.src is d and u.addr is not d:
                    ok = fits32(v) and not u.type.is_float()
                elif u.op == "ret" and u.value is d:
                    ok = True
                if ok:
                    self.imm_only[d] = v
        for i in insts:
            if i.op == "addr_local" and self.defs.get(i.dst) == 1 and self.uses.get(i.dst) == 1:
                u = insts[self.user[i.dst]]
                if (u.op == "load" and u.addr is i.dst) or (u.op == "store" and u.addr is i.dst and u.src is not i.dst):
                    self.direct[i.dst] = i.var

    def elided(self, i):
        return (i.op == "const" and i.dst in self.imm_only) or (i.op == "addr_local" and i.dst in self.direct)

    def rax_operand(self, i):
        """명령이 RAX 로 먼저 읽는 피연산자 (없으면 None)."""
        op = i.op
        if op == "br":
            return i.cond
        if op == "copy":
            return i.src
        if op == "load":
            return None if i.addr in self.direct else i.addr
        if op == "store":
            return None if i.src in self.imm_only else i.src
        if op in ("gep", "index_addr"):
            return i.base
        if op == "bin":
            return None if i.bop.startswith("f") else i.a
        if op == "cmp":
            return None if i.cond.startswith("f") else i.a
        if op in ("neg", "not", "lnot"):
            return i.a
        if op == "cast":
            return i.src if i.kind in ("sext", "zext", "trunc", "sitofp", "uitofp") else None
        if op == "ret":
            return i.value if (i.value is not None and not i.value.type.is_float() and i.value not in self.imm_only) else None
        if op == "vararg":
            return i.idx
        return None

    def next_emitting(self, k):
        insts = self.f.insts
        j = k + 1
        while j < len(insts) and self.elided(insts[j]):
            j += 1
        return j if j < len(insts) else None

    # ---------- 레지스터 할당 (D-20) ----------
    def scalar_ok(self, t):
        return t.is_int() or t.is_ptr() or t.is_func()

    def analyze_alloc(self):
        insts = self.f.insts
        # RAX 로만 흐르는 임시값은 후보가 아니다 (마무리가 슬롯에 저장하지 않는 것)
        for k, i in enumerate(insts):
            d = getattr(i, "dst", None)
            if d is None:
                continue
            if self.uses.get(d) == 1 and self.defs.get(d) == 1:
                j = self.next_emitting(k)
                if j is not None and self.user.get(d) == j and self.rax_operand(insts[j]) is d:
                    self.forwarded.add(d)
        # 접기: 바로 다음 적재·저장의 주소로만 쓰이는 오프셋·원소주소
        for k, i in enumerate(insts):
            if i.op in ("gep", "index_addr") and self.defs.get(i.dst) == 1 and self.uses.get(i.dst) == 1:
                j = self.next_emitting(k)
                if j is not None and self.user[i.dst] == j:
                    u = insts[j]
                    if (u.op == "load" and u.addr is i.dst) or (u.op == "store" and u.addr is i.dst and u.src is not i.dst):
                        if i.op == "gep" or i.idx in self.imm_only or i.size in (1, 2, 4, 8):
                            self.fold[i.dst] = i
        # 후보 지역: 스칼라, 주소가 새지 않음(모든 지역주소가 같은 타입의 직접 적재/저장), 가변 인자 함수의 매개변수 제외
        params = {s for s, _ in self.f.params}
        ok = set()
        for sym in self.f.locals:
            if self.scalar_ok(sym.type) and not (self.f.variadic and sym in params):
                ok.add(sym)
        for i in insts:
            if i.op == "addr_local" and i.var in ok:
                if i.dst not in self.direct:
                    ok.discard(i.var)
                else:
                    u = insts[self.user[i.dst]]
                    if not T.same_type(u.type, i.var.type):
                        ok.discard(i.var)
        self.local_ok = ok

    def cand_temp(self, t):
        return (isinstance(t, Temp) and not t.type.is_float() and t not in self.imm_only
                and t not in self.direct and t not in self.forwarded and t not in self.fold)

    def inst_def(self, i):
        d = getattr(i, "dst", None)
        if d is not None and self.cand_temp(d):
            return d
        if i.op == "store" and i.addr in self.direct and self.direct[i.addr] in self.local_ok:
            return self.direct[i.addr]
        return None

    def inst_uses(self, i):
        out = []
        for name in OPERANDS.get(i.op, ()):
            v = getattr(i, name)
            if self.cand_temp(v):
                out.append(v)
        if i.op == "call":
            for v in i.args:
                if self.cand_temp(v):
                    out.append(v)
            if not isinstance(i.callee, str) and self.cand_temp(i.callee):
                out.append(i.callee)
        if i.op == "load" and i.addr in self.direct and self.direct[i.addr] in self.local_ok:
            out.append(self.direct[i.addr])
        return out

    def allocate(self):
        insts = self.f.insts
        n = len(insts)
        # 변수 번호: 후보 지역(지역 순서) 다음 후보 임시(번호 순서)
        vars_ = [s for s in self.f.locals if s in self.local_ok] + [t for t in self.f.temps if self.cand_temp(t)]
        if not vars_ or n == 0:
            return
        vid = {v: k for k, v in enumerate(vars_)}
        # 기본 블록: 라벨에서, 그리고 점프·분기·반환 다음에서 시작
        starts = [0]
        for k in range(1, n):
            if insts[k].op == "label" or insts[k - 1].op in ("jmp", "br", "ret"):
                starts.append(k)
        blocks = []
        for j, s in enumerate(starts):
            e = starts[j + 1] - 1 if j + 1 < len(starts) else n - 1
            blocks.append((s, e))
        nb = len(blocks)
        label_block = {}
        for j, (s, e) in enumerate(blocks):
            if insts[s].op == "label":
                label_block[insts[s].name] = j
        succ = []
        for j, (s, e) in enumerate(blocks):
            last = insts[e]
            if last.op == "jmp":
                succ.append([label_block[last.label]])
            elif last.op == "br":
                succ.append([label_block[last.ltrue], label_block[last.lfalse]])
            elif last.op == "ret":
                succ.append([])
            else:
                succ.append([j + 1] if j + 1 < nb else [])
        # 블록의 use(정의 전에 쓰임)·def
        use_b = []
        def_b = []
        for (s, e) in blocks:
            u = set()
            d = set()
            for k in range(s, e + 1):
                for v in self.inst_uses(insts[k]):
                    if vid[v] not in d:
                        u.add(vid[v])
                dd = self.inst_def(insts[k])
                if dd is not None:
                    d.add(vid[dd])
            use_b.append(u)
            def_b.append(d)
        live_in = [set() for _ in range(nb)]
        live_out = [set() for _ in range(nb)]
        changed = True
        while changed:
            changed = False
            for j in range(nb - 1, -1, -1):
                out = set()
                for sj in succ[j]:
                    out |= live_in[sj]
                inn = use_b[j] | (out - def_b[j])
                if out != live_out[j] or inn != live_in[j]:
                    live_out[j] = out
                    live_in[j] = inn
                    changed = True
        # 생존 구간 [start, end]: 블록 경계·정의·사용 위치를 모두 포함
        nv = len(vars_)
        start = [-1] * nv
        end = [-1] * nv

        def touch(v, k):
            if start[v] < 0 or k < start[v]:
                start[v] = k
            if k > end[v]:
                end[v] = k

        for j, (s, e) in enumerate(blocks):
            for v in live_out[j]:
                touch(v, e)
            for v in live_in[j]:
                touch(v, s)
            for k in range(s, e + 1):
                i = insts[k]
                dd = self.inst_def(i)
                if dd is not None:
                    touch(vid[dd], k)
                for v in self.inst_uses(i):
                    touch(vid[v], k)
        # 선형 스캔
        order = sorted([v for v in range(nv) if start[v] >= 0], key=lambda v: (start[v], v))
        active = []                 # (end, vid, reg) 오름차순
        free = list(range(len(ALLOC_REGS)))
        assign = {}
        for v in order:
            s = start[v]
            keep = []
            for a in active:
                if a[0] < s:
                    free.append(a[2])
                else:
                    keep.append(a)
            active = keep
            if free:
                free.sort()
                r = free.pop(0)
                assign[v] = r
                active.append((end[v], v, r))
                active.sort()
            else:
                spill = active[-1]
                if spill[0] > end[v]:
                    active.pop()
                    del assign[spill[1]]
                    assign[v] = spill[2]
                    active.append((end[v], v, spill[2]))
                    active.sort()
        for v, r in assign.items():
            self.reg[vars_[v]] = ALLOC_REGS[r]
        self.nsaved = (max(assign.values()) + 1) if assign else 0
        # 별칭: 레지스터 지역의 전달되는 직접 적재는 그 레지스터 자체다
        for i in insts:
            if i.op == "load" and i.dst in self.forwarded and i.addr in self.direct and self.direct[i.addr] in self.reg:
                self.alias[i.dst] = self.direct[i.addr]

    # ---------- 도우미: 값의 위치 ----------
    def holder(self, t):
        """t 가 지금 들어 있는 레지스터 (없으면 None: 슬롯에 있다)."""
        x = self.alias.get(t)
        if x is not None:
            return self.reg[x]
        r = self.reg.get(t)
        if r is not None:
            return r
        if self.rax_temp is t:
            return RAX
        return None

    def in_rax_only(self, t):
        return self.rax_temp is t and t not in self.alias and t not in self.reg

    def src_reg(self, t, scratch):
        """t 를 담은 레지스터. 슬롯에 있으면 scratch 로 적재한다 (scratch 가 RAX 면 RAX 전달 상태가 된다)."""
        r = self.holder(t)
        if r is not None:
            return r
        self.a.load(scratch, RBP, self.slot(t))
        if scratch == RAX:
            self.rax_temp = t
        return scratch

    def load_into(self, r, t):
        """r <- t"""
        s = self.holder(t)
        if s is None:
            self.a.load(r, RBP, self.slot(t))
            if r == RAX:
                self.rax_temp = t
        elif s != r:
            self.a.mov_rr(r, s)

    def two_srcs(self, a, b, sa, sb):
        """a, b 를 담은 레지스터 둘. a 의 적재가 RAX 에 든 b 를 덮지 않게 b 를 먼저 옮긴다."""
        if sa == RAX and a is not b and self.holder(a) is None and self.in_rax_only(b):
            self.a.mov_rr(sb, RAX)
            rb = sb
            ra = self.src_reg(a, RAX)
            return ra, rb
        ra = self.src_reg(a, sa)
        rb = self.src_reg(b, sb)
        return ra, rb

    def dst_reg(self, d):
        """d 를 계산할 레지스터: 자기 레지스터, 아니면 바로 저장될 레지스터 지역의 것, 아니면 RAX."""
        r = self.reg.get(d)
        if r is not None:
            return r
        if d in self.forwarded:
            u = self.f.insts[self.user[d]]
            if u.op == "store" and u.src is d and u.addr in self.direct:
                x = self.direct[u.addr]
                if x in self.reg:
                    return self.reg[x]
        return RAX

    def finish_in(self, k, d, r):
        """d 의 값이 레지스터 r 에 있다."""
        if r == RAX:
            if d in self.reg:
                self.a.mov_rr(self.reg[d], RAX)
            elif d not in self.forwarded:
                self.a.store(RBP, self.slot(d), RAX)
            self.rax_temp = d
        elif r != self.reg.get(d):
            self.pre_stored = d

    def addr_parts(self, t, base_scratch, idx_scratch):
        """주소 임시값 t 의 메모리 피연산자 (base, index, scale, disp). 접힌 오프셋·원소주소를 편다."""
        f = self.fold.get(t)
        if f is None:
            return self.src_reg(t, base_scratch), None, 1, 0
        if f.op == "gep":
            return self.src_reg(f.base, base_scratch), None, 1, f.offset
        if f.idx in self.imm_only:
            return self.src_reg(f.base, base_scratch), None, 1, self.imm_only[f.idx] * f.size
        rb, ri = self.two_srcs(f.base, f.idx, base_scratch, idx_scratch)
        return rb, ri, f.size, 0

    def normalize(self, r, t):
        """64비트 레지스터의 값을 타입 t 의 정규 표현(부호/영 확장)으로."""
        if t.is_int() and t.bits < 64:
            if t.signed:
                self.a.movsx_rr(r, r, t.bits)
            else:
                self.a.movzx_rr(r, r, t.bits)

    def norm_imm(self, v, t):
        """즉시값을 타입 t 의 정규 표현으로 (좁은 정수는 부호/영 확장)."""
        if t.is_int() and t.bits < 64:
            v &= (1 << t.bits) - 1
            if t.signed and v & (1 << (t.bits - 1)):
                v -= 1 << t.bits
        return v

    def fbits(self, t):
        return 32 if (t.is_float() and t.bits == 32) else 64

    # ---------- 본체 ----------
    def gen(self):
        a = self.a
        f = self.f
        self.analyze()
        self.analyze_alloc()
        self.allocate()
        self.layout()
        a.label(f.name)
        a.push(RBP)
        a.mov_rr(RBP, RSP)
        for r in ALLOC_REGS[:self.nsaved]:
            a.push(r)
        remaining = self.frame - 8 * self.nsaved
        while remaining > 4096:
            a.sub_rsp(4096)
            a.store(RSP, 0, RAX)
            remaining -= 4096
        if remaining:
            a.sub_rsp(remaining)
        # 레지스터 매개변수: 홈 슬롯에 저장 (가변 인자 함수는 4개 모두 — 가변인자(k) 가 홈 슬롯을 읽는다),
        # 레지스터에 사는 매개변수는 바로 옮긴다
        nspill = 4 if f.variadic else min(4, len(f.params))
        for i in range(nspill):
            sym = f.params[i][0] if i < len(f.params) else None
            t = f.params[i][1] if i < len(f.params) else None
            if sym is not None and sym in self.reg:
                a.mov_rr(self.reg[sym], ARG_REGS[i])
            elif t is not None and t.is_float():
                a.movsd_store(RBP, 16 + 8 * i, i, self.fbits(t))
            else:
                a.store(RBP, 16 + 8 * i, ARG_REGS[i])
        for i in range(4, len(f.params)):
            sym = f.params[i][0]
            if sym in self.reg:
                a.load(self.reg[sym], RBP, 16 + 8 * i)
        self.rax_temp = None
        self.pre_stored = None
        self.pending_cc = None
        self.pending_cond = None
        for k, inst in enumerate(f.insts):
            self.gen_inst(k, inst)

    def epilogue(self):
        a = self.a
        if self.nsaved:
            a.lea(RSP, RBP, -8 * self.nsaved)
            for r in reversed(ALLOC_REGS[:self.nsaved]):
                a.pop(r)
        else:
            a.mov_rr(RSP, RBP)
        a.pop(RBP)
        a.ret()

    def gen_inst(self, k, i):
        a = self.a
        op = i.op
        if self.elided(i):
            return
        if op in ("gep", "index_addr") and i.dst in self.fold:
            return
        if op == "label":
            a.label(i.name)
            self.rax_temp = None
        elif op == "jmp":
            a.jmp(i.label)
            self.rax_temp = None
        elif op == "br":
            if i.cond is self.pending_cond:
                a.jcc(self.pending_cc, i.ltrue)
                self.pending_cond = None
                self.pending_cc = None
            else:
                rc = self.src_reg(i.cond, RAX)
                a.test(rc, rc)
                a.jcc("ne", i.ltrue)
            a.jmp(i.lfalse)
            self.rax_temp = None
        elif op == "const":
            rd = self.dst_reg(i.dst)
            a.mov_imm(rd, i.value)
            self.finish_in(k, i.dst, rd)
        elif op == "fconst":
            if self.fbits(i.dst.type) == 32:
                a.mov_imm(RAX, struct.unpack("<I", struct.pack("<f", i.value))[0])
            else:
                a.mov_imm(RAX, struct.unpack("<Q", struct.pack("<d", i.value))[0])
            a.store(RBP, self.slot(i.dst), RAX)
            self.rax_temp = i.dst
        elif op == "str":
            rd = self.dst_reg(i.dst)
            a.lea_rip(rd, "str", i.index)
            self.finish_in(k, i.dst, rd)
        elif op == "addr_local":
            rd = self.dst_reg(i.dst)
            a.lea(rd, RBP, self.slot(i.var))
            self.finish_in(k, i.dst, rd)
        elif op == "addr_global":
            rd = self.dst_reg(i.dst)
            a.lea_rip(rd, "data", i.var.name)
            self.finish_in(k, i.dst, rd)
        elif op == "func_addr":
            rd = self.dst_reg(i.dst)
            if i.extern:
                a.load_rip(rd, "iat", i.name)
            else:
                a.lea_rip(rd, "func", i.name)
            self.finish_in(k, i.dst, rd)
        elif op == "copy":
            rd = self.dst_reg(i.dst)
            self.load_into(rd, i.src)
            self.finish_in(k, i.dst, rd)
        elif op == "load":
            self.gen_load(k, i)
        elif op == "store":
            self.gen_store(k, i)
        elif op == "gep":
            rd = self.dst_reg(i.dst)
            if i.offset:
                a.lea(rd, self.src_reg(i.base, RAX), i.offset)
            else:
                self.load_into(rd, i.base)
            self.finish_in(k, i.dst, rd)
        elif op == "index_addr":
            rd = self.dst_reg(i.dst)
            if i.idx in self.imm_only:
                off = self.imm_only[i.idx] * i.size
                if off:
                    a.lea(rd, self.src_reg(i.base, RAX), off)
                else:
                    self.load_into(rd, i.base)
            else:
                rb, ri = self.two_srcs(i.base, i.idx, RAX, RCX)
                if i.size in (1, 2, 4, 8):
                    a.lea(rd, rb, 0, ri, i.size)
                else:
                    a.imul_imm(RCX, ri, i.size)
                    a.lea(rd, rb, 0, RCX, 1)
            self.finish_in(k, i.dst, rd)
        elif op == "bin":
            self.gen_bin(k, i)
        elif op == "cmp":
            self.gen_cmp(k, i)
        elif op == "neg":
            t = i.dst.type
            if t.is_float():
                self.load_into(RAX, i.a)
                a.mov_imm(RCX, 1 << (self.fbits(t) - 1))
                a.alu("xor", RAX, RCX)
                self.finish_in(k, i.dst, RAX)
            else:
                rd = self.dst_reg(i.dst)
                self.load_into(rd, i.a)
                a.neg(rd)
                self.normalize(rd, t)
                self.finish_in(k, i.dst, rd)
        elif op == "not":
            rd = self.dst_reg(i.dst)
            self.load_into(rd, i.a)
            a.not_(rd)
            self.normalize(rd, i.dst.type)
            self.finish_in(k, i.dst, rd)
        elif op == "lnot":
            ra = self.src_reg(i.a, RAX)
            a.test(ra, ra)
            rd = self.dst_reg(i.dst)
            a.setcc("e", rd)
            a.movzx_rr(rd, rd, 8)
            self.finish_in(k, i.dst, rd)
        elif op == "cast":
            self.gen_cast(k, i)
        elif op == "vararg":
            # [rbp + 16 + 8*(고정 매개변수 수 + idx)]
            self.load_into(RAX, i.idx)
            a.mov_imm(RDX, 8)
            a.imul(RAX, RDX)
            a.lea(RCX, RBP, 16 + 8 * len(self.f.params))
            a.alu("add", RAX, RCX)
            a.load(RAX, RAX, 0, 64)
            self.finish_in(k, i.dst, RAX)
        elif op == "call":
            self.gen_call(k, i)
        elif op == "copy_mem":
            self.gen_copy_mem(i)
        elif op == "ret":
            if i.value is not None:
                t = i.value.type
                if t.is_float():
                    a.movsd_load(XMM0, RBP, self.slot(i.value), self.fbits(t))
                elif i.value in self.imm_only:
                    a.mov_imm(RAX, self.imm_only[i.value])
                else:
                    self.load_into(RAX, i.value)
            else:
                a.mov_imm(RAX, 0)
            self.epilogue()
            self.rax_temp = None
        else:
            raise InternalError(f"코드 생성: 알 수 없는 IR 명령 {op}")

    def gen_load(self, k, i):
        a = self.a
        d = i.dst
        t = i.type
        if d in self.alias:
            return
        if i.addr in self.direct:
            var = self.direct[i.addr]
            if var in self.reg:
                rd = self.dst_reg(d)
                if rd != self.reg[var]:
                    a.mov_rr(rd, self.reg[var])
                self.finish_in(k, d, rd)
                return
            base, index, scale, disp = RBP, None, 1, self.slot(var)
        else:
            base, index, scale, disp = self.addr_parts(i.addr, RAX, RCX)
        rd = self.dst_reg(d)
        if t.is_float():
            a.load(rd, base, disp, self.fbits(t), False, index, scale)
        elif t.is_int():
            a.load(rd, base, disp, t.bits, t.signed, index, scale)
        else:
            a.load(rd, base, disp, 64, True, index, scale)
        self.finish_in(k, d, rd)

    def gen_store(self, k, i):
        a = self.a
        if i.src is self.pre_stored:
            self.pre_stored = None
            return
        t = i.type
        bits = t.bits if (t.is_int() or t.is_float()) else 64
        if i.addr in self.direct:
            var = self.direct[i.addr]
            if var in self.reg:
                rv = self.reg[var]
                if i.src in self.imm_only:
                    a.mov_imm(rv, self.norm_imm(self.imm_only[i.src], t))
                else:
                    rs = self.src_reg(i.src, RDX)
                    if rs != rv:
                        a.mov_rr(rv, rs)
                return
            base, index, scale, disp = RBP, None, 1, self.slot(var)
        else:
            base, index, scale, disp = self.addr_parts(i.addr, RCX, R8)
        if i.src in self.imm_only:
            a.store_imm(base, disp, self.imm_only[i.src], bits, index, scale)
        else:
            rs = self.src_reg(i.src, RDX)
            a.store(base, disp, rs, bits, index, scale)

    def gen_bin(self, k, i):
        a = self.a
        d = i.dst
        t = d.type
        op = i.bop
        if op.startswith("f"):
            bits = self.fbits(t)
            a.movsd_load(XMM0, RBP, self.slot(i.a), bits)
            a.movsd_load(XMM1, RBP, self.slot(i.b), bits)
            a.fop(op[1:], XMM0, XMM1, bits)
            a.movsd_store(RBP, self.slot(d), XMM0, bits)
            return
        rd = self.dst_reg(d)
        if i.b in self.imm_only:
            v = self.imm_only[i.b]
            self.load_into(rd, i.a)
            if op in IMM_OPS:
                a.alu_imm(op, rd, v)
            elif op == "mul":
                a.imul_imm(rd, rd, v)
            elif op == "shl":
                a.shift_imm("shl", rd, v)
            elif op == "lshr":
                a.shift_imm("shr", rd, v)
            elif op == "ashr":
                a.shift_imm("sar", rd, v)
            else:
                raise InternalError(f"즉시값 이항 연산 {op}")
        elif op in IMM_OPS or op == "mul":
            rb = self.src_reg(i.b, RCX)
            if rd != RAX and rb == rd:
                rd = RAX                            # b 가 결과 레지스터에 산다: RAX 에서 계산
            if rd == RAX and rb == RAX and self.holder(i.a) != RAX:
                a.mov_rr(RCX, RAX)                  # a 를 RAX 로 가져오면 b 가 덮이므로 먼저 옮긴다
                rb = RCX
            self.load_into(rd, i.a)
            if op == "mul":
                a.imul(rd, rb)
            else:
                a.alu(op, rd, rb)
        elif op in SHIFT_OPS:
            rb = self.src_reg(i.b, RCX)
            if rb != RCX:
                a.mov_rr(RCX, rb)
            self.load_into(rd, i.a)
            a.shift_cl({"shl": "shl", "lshr": "shr", "ashr": "sar"}[op], rd)
        else:
            rb = self.src_reg(i.b, RCX)
            if rb == RAX:
                a.mov_rr(RCX, RAX)
                rb = RCX
            self.load_into(RAX, i.a)
            if op == "sdiv":
                a.cqo(); a.idiv(rb)
            elif op == "srem":
                a.cqo(); a.idiv(rb); a.mov_rr(RAX, RDX)
            elif op == "udiv":
                a.alu("xor", RDX, RDX); a.div(rb)
            elif op == "urem":
                a.alu("xor", RDX, RDX); a.div(rb); a.mov_rr(RAX, RDX)
            else:
                raise InternalError(f"이항 연산 {op}")
            rd = RAX
        self.normalize(rd, t)
        self.finish_in(k, d, rd)

    def gen_cmp(self, k, i):
        a = self.a
        cond = i.cond
        t = i.type
        d = i.dst
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
            self.finish_in(k, d, RAX)
            return
        if i.b in self.imm_only:
            ra = self.src_reg(i.a, RAX)
            a.alu_imm("cmp", ra, self.imm_only[i.b])
        else:
            ra, rb = self.two_srcs(i.a, i.b, RAX, RCX)
            a.alu("cmp", ra, rb)
        cc = CC_OF[cond]
        if d in self.forwarded and self.f.insts[self.user[d]].op == "br":
            self.pending_cc = cc
            self.pending_cond = d
            return
        rd = self.dst_reg(d)
        a.setcc(cc, rd)
        a.movzx_rr(rd, rd, 8)
        self.finish_in(k, d, rd)

    def gen_cast(self, k, i):
        a = self.a
        kind = i.kind
        st = i.src.type
        dt = i.dst.type
        if kind in ("sext", "zext", "trunc"):
            rd = self.dst_reg(i.dst)
            # 원본은 이미 정규 표현이므로 대상 폭으로 다시 정규화하면 된다
            if kind == "trunc" or dt.bits < 64:
                rs = self.src_reg(i.src, RAX)
                if dt.signed:
                    a.movsx_rr(rd, rs, dt.bits)
                else:
                    a.movzx_rr(rd, rs, dt.bits)
            else:
                self.load_into(rd, i.src)
            self.finish_in(k, i.dst, rd)
        elif kind in ("sitofp", "uitofp"):
            bits = self.fbits(dt)
            self.load_into(RAX, i.src)
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
            self.rax_temp = None
        elif kind == "fptosi":
            bits = self.fbits(st)
            a.movsd_load(XMM0, RBP, self.slot(i.src), bits)
            a.cvttf2si(RAX, XMM0, bits)
            self.normalize(RAX, dt)
            self.finish_in(k, i.dst, RAX)
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

    def gen_copy_mem(self, i):
        """[to] <- [frm], size 바이트. 128 바이트까지는 펼치고, 그 위는 8바이트 루프 (RSI/RDI 를 쓰지 않는다)."""
        a = self.a
        n = i.size
        self.load_into(RCX, i.frm)
        self.load_into(RDX, i.to)
        off = 0
        if n > 128:
            self.copy_labels += 1
            lbl = f".{self.f.name}.cp{self.copy_labels}"
            a.mov_imm(R8, n // 8)
            a.label(lbl)
            a.load(RAX, RCX, 0)
            a.store(RDX, 0, RAX)
            a.alu_imm("add", RCX, 8)
            a.alu_imm("add", RDX, 8)
            a.alu_imm("sub", R8, 1)
            a.jcc("ne", lbl)
            n = n % 8
        while off + 8 <= n:
            a.load(RAX, RCX, off)
            a.store(RDX, off, RAX)
            off += 8
        while off < n:
            a.load(RAX, RCX, off, 8, False)
            a.store(RDX, off, RAX, 8)
            off += 1
        self.rax_temp = None

    def gen_call(self, k, i):
        a = self.a
        sig = i.sig
        args = i.args
        # 스택 인자 (5번째부터)
        for j in range(4, len(args)):
            rs = self.src_reg(args[j], RAX)
            a.store(RSP, 8 * j, rs)
        # 레지스터 인자
        for j in range(min(4, len(args))):
            t = args[j].type
            if t.is_float():
                a.movsd_load(j, RBP, self.slot(args[j]), self.fbits(t))
                if sig.variadic:
                    self.load_into(ARG_REGS[j], args[j])
            else:
                self.load_into(ARG_REGS[j], args[j])
        callee = i.callee
        if isinstance(callee, str):
            if i.extern:
                a.call_iat(callee)
            else:
                a.call_label(callee)
        else:
            a.call_reg(self.src_reg(callee, R11))
        self.rax_temp = None
        if i.dst is not None:
            t = i.dst.type
            if t.is_float():
                a.movsd_store(RBP, self.slot(i.dst), XMM0, self.fbits(t))
            else:
                self.normalize(RAX, t)
                self.finish_in(k, i.dst, RAX)


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
