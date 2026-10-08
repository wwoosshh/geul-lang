#!/usr/bin/env python3
"""글 → PTX 탐침 (연구 docs/17, 탐침 1b).

참조 구현의 앞단(포함·렉서·파서·의미 분석·하강·인라인)을 그대로 쓰고, 타입 IR 을 NVIDIA PTX 텍스트로 옮긴다.
탐침이다 — 컴파일러가 아니다. 받는 범위를 좁게 두고, 범위 밖은 조용히 넘기지 않고 오류로 멈춘다.

  python research/gpu/글ptx.py <커널.gl> [-o <출력.ptx>]

범위
- 표준 라이브러리는 포함하지 않는다. 반환값이 없는 함수가 커널(.entry)이 된다.
- GPU 내장은 외부 선언으로 적는다: `외부 [실행번호]는 -> 정수.`
    실행번호 = 블록번호 × 블록크기 + 블록안번호 (전역 스레드 번호), 실행개수 = 블록수 × 블록크기
- 매개변수와 지역 변수는 스레드의 .local 자리에 두고 범용(generic) 주소로 읽고 쓴다.
  IR 이 값의 주소 공간(전역·공유·지역)을 모르기 때문이다 — 의미 층이 채울 첫 빈칸.
- PTX 는 ASCII 만 받는다(드라이버가 한글 주석도 거부한다). 한글 이름은 "_G" + UTF-8 16진수로 바꾸고
  (쿠다.gl 의 PTX이름 과 같은 규칙), 대응표는 표준출력으로 낸다.
- 의미는 PTX 에 다 적는다 — 드라이버가 고를 여지를 남기지 않는다. 부동소수 연산은 반올림(.rn)을 적어 곱과 덧셈이
  FMA 로 합쳐지지 않게 하고(글의 CPU 의미와 비트까지 같게), .approx·.ftz 는 쓰지 않는다 (docs/17 §7 PTX 계약).
- 2단계(docs/17 §7): 2a 커널의 참조 매개변수는 전역 메모리를 가리키고 거기서 나온 주소도 전역이다(ld.global·st.global).
  주소가 새지 않는 지역 변수는 레지스터에 둔다. 2b 연구용 내장 — 블록안가로·블록안세로·블록가로·블록세로(스레드·블록 번호),
  공유메모리0~3(각 4096 바이트, ld.shared·st.shared), 동기화(bar.sync). 2c 실수 → 정수·짧은실수 변환이 범위를 넘으면 모듈의
  오류 칸 __geul_err 에 비트를 켠다 — 호스트가 실행 뒤에 읽는다.
- 다른 함수 호출, 문자열, 전역 변수, 묶음 값 복사, 가변 인자는 아직 받지 않는다.
"""
import io
import os
import struct
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "ref"))

from geul.driver import load_program          # noqa: E402
from geul import sema, lower, inline          # noqa: E402
from geul.diagnostics import CompileError     # noqa: E402

# GPU 내장. 실행번호·실행개수는 탐침 1 부터, 나머지는 2b 의 연구용 내장이다(언어가 아니다 — 타일을 손으로 써 보기 위한 것).
BLOCK_REGS = {"블록안가로": "%tid.x", "블록안세로": "%tid.y", "블록가로": "%ctaid.x", "블록세로": "%ctaid.y"}
SHARED = {f"공유메모리{k}": f"__geul_sm{k}" for k in range(4)}      # 각 4096 바이트, 공유 메모리 공간의 주소를 돌려준다
SHARED_BYTES = 4096
# 3단계: 여러 행을 한 블록이 맡는 선형 커널의 가닥 합치기 칸 — 16384 바이트 하나. 앞의 넷은 크기를 바꾸지 않는다(2단계의 잰 값 그대로).
SHARED["큰공유메모리"] = "__geul_bsm"
SHARED_SIZE = {name: (16384 if name == "큰공유메모리" else SHARED_BYTES) for name in SHARED}
# 2c: 실수 → 정수, 실수 → 짧은실수 변환의 범위 검사. 넘으면 모듈의 오류 칸 __geul_err 에 비트를 켠다(1 정수, 2 짧은실수) —
# 호스트가 실행 뒤에 읽는다. 조용한 값이 없다. (끄는 것은 재기 도구가 검사의 비용을 잴 때만 한다.)
RANGE_CHECK = True
# 2e: 음이 아니고 32비트 범위임이 증명된 두 값의 나눗셈·나머지를 32비트 명령으로 (결과는 64비트로 되돌린다). GPU 에서 64비트
# 나눗셈은 소프트웨어로 돌아서 비싸다. 곱셈·주소 계산도 좁혀 봤지만, 드라이버 컴파일러가 반복 변수의 곱을 덧셈으로 바꾸는
# 최적화와 겹쳐 이득이 없거나 오히려 느려졌다(타일 행렬곱 2.29 → 2.98 ms) — 그래서 좁히지 않는다. 끄는 것은 재기 도구만.
WIDTH_PROOF = True


def flit(x, t):
    """실수 상수의 PTX 표기 (t 의 폭)."""
    if t.bits == 32:
        return f"0f{struct.unpack('<I', struct.pack('<f', x))[0]:08X}"
    return f"0d{struct.unpack('<Q', struct.pack('<d', x))[0]:016X}"
# 2g: 곱해더하기(x, y, z) = x × y + z 를 반올림 한 번으로(fma.rn). 소스가 이 낱말로 밝힐 때만 합친다 — `x * y + z` 는 늘 두 번 반올림.
# 3단계: 근사지수(x) ≈ e^x — 근사 명령 ex2.approx 를 쓴다(소스가 이 낱말로 근사를 밝힐 때만, PTX 계약 P2). 제곱근(x) 은 정확한
# 반올림(sqrt.rn). 큰쪽(a, b) 은 max(한쪽이 NaN 이면 다른 쪽).
INTRINSICS = ("실행번호", "실행개수", "동기화", "곱해더하기", "근사지수", "제곱근", "큰쪽") + tuple(BLOCK_REGS) + tuple(SHARED)


class PTXError(Exception):
    pass


def ptx_name(name):
    """PTX 식별자: 라틴 이름은 그대로, 그 밖은 _G + UTF-8 16진수."""
    ok = name and (name[0].isascii() and (name[0].isalpha() or name[0] == "_")) and \
        all(c.isascii() and (c.isalnum() or c == "_") for c in name)
    return name if ok else "_G" + name.encode("utf-8").hex()


def reg_type(t):
    """IR 타입 → PTX 레지스터 타입. 8·16비트 정수도 32비트 레지스터에 둔다."""
    if t.is_float():
        return ".f32" if t.bits == 32 else ".f64"
    if t.is_ptr():
        return ".u64"
    if t.is_int():
        if t.bits == 64:
            return ".s64" if t.signed else ".u64"
        return ".s32" if t.signed else ".u32"
    raise PTXError(f"PTX 탐침이 다루지 않는 값의 타입: {t}")


def mem_type(t):
    """메모리를 읽고 쓸 때의 PTX 타입 (크기 그대로)."""
    if t.is_float():
        return ".f32" if t.bits == 32 else ".f64"
    if t.is_ptr():
        return ".u64"
    if t.is_int():
        return (".s" if t.signed else ".u") + str(t.bits)
    raise PTXError(f"PTX 탐침이 메모리에서 다루지 않는 타입: {t}")


def width(t):
    return 64 if (t.is_ptr() or t.bits == 64) else 32


CMP = {"eq": "eq", "ne": "ne", "lt": "lt", "le": "le", "gt": "gt", "ge": "ge",
       "ult": "lt", "ule": "le", "ugt": "gt", "uge": "ge",
       "feq": "eq", "fne": "neu", "flt": "lt", "fle": "le", "fgt": "gt", "fge": "ge"}

# 부동소수 연산은 반올림을 적는다(.rn). 반올림을 적지 않은 mul/add/sub 는 PTX 명세상 최적화기가 FMA 하나로 합쳐도 되는
# 명령이고, 드라이버가 실제로 합친다 — 반올림이 한 번 빠져 글의 CPU 백엔드(mulss·addss, 연산마다 반올림)와 비트가 달라진다.
# 탐침 곱더하기: 반올림을 빼면 1,048,576개 중 245,734개가 달랐다 (docs/17 §7 PTX 계약).
BIN = {"add": "add", "sub": "sub", "mul": "mul.lo", "sdiv": "div", "udiv": "div", "srem": "rem", "urem": "rem",
       "and": "and", "or": "or", "xor": "xor", "shl": "shl", "lshr": "shr", "ashr": "shr",
       "fadd": "add.rn", "fsub": "sub.rn", "fmul": "mul.rn", "fdiv": "div.rn"}


# 값으로 쓰이는 임시값 자리 (dst 제외)
USE_FIELDS = ("a", "b", "src", "addr", "base", "idx", "cond", "value")

# 2e: 정수 값 범위. 하드웨어가 보장하는 내장의 범위 (블록 한 변 ≤ 1024 스레드, 격자 x ≤ 2^31 − 1 블록, 격자 y ≤ 65535 블록)
I32_MIN, I32_MAX = -2 ** 31, 2 ** 31 - 1
INTRINSIC_RANGE = {"블록안가로": (0, 1023), "블록안세로": (0, 1023), "블록가로": (0, 2 ** 31 - 2), "블록세로": (0, 65534),
                   "실행번호": (0, (2 ** 31 - 1) * 1024 - 1), "실행개수": (1, (2 ** 31 - 1) * 1024)}
SWAP = {"lt": "gt", "le": "ge", "gt": "lt", "ge": "le", "eq": "eq", "ne": "ne",
        "ult": "ugt", "ule": "uge", "ugt": "ult", "uge": "ule"}


def type_range(t):
    if t.is_int():
        b = t.bits
        return (-(2 ** (b - 1)), 2 ** (b - 1) - 1) if t.signed else (0, 2 ** b - 1)
    return None


def clamp_to(t, lo, hi):
    """정확한 구간이 타입의 범위를 넘으면(순환할 수 있으면) 타입의 전 범위."""
    tr = type_range(t)
    return (lo, hi) if tr[0] <= lo and hi <= tr[1] else tr


def refine(r, cond, b):
    """v cond b 가 참일 때 v 의 구간 r 을 좁힌다. 빈 구간이면 None."""
    lo, hi = r
    if cond.startswith("u"):
        if r[0] < 0 or b[0] < 0:
            return r
        cond = cond[1:]
    if cond == "lt":
        hi = min(hi, b[1] - 1)
    elif cond == "le":
        hi = min(hi, b[1])
    elif cond == "gt":
        lo = max(lo, b[0] + 1)
    elif cond == "ge":
        lo = max(lo, b[0])
    elif cond == "eq":
        lo, hi = max(lo, b[0]), min(hi, b[1])
    return (lo, hi) if lo <= hi else None


NEGATE = {"lt": "ge", "le": "gt", "gt": "le", "ge": "lt", "eq": "ne", "ne": "eq",
          "ult": "uge", "ule": "ugt", "ugt": "ule", "uge": "ult"}


def is_scalar(t):
    return t.is_float() or t.is_int() or t.is_ptr()


class FuncPTX:
    def __init__(self, f):
        self.f = f
        self.lines = []
        self.labels = {}
        # 2a: 주소가 새지 않는 지역 변수는 레지스터에 둔다 — 그 주소가 load/store 의 자리로만 쓰이는 변수
        self.addr_of = {i.dst: i.var for i in f.insts if i.op == "addr_local"}
        escaped = set()
        for i in f.insts:
            for fld in USE_FIELDS + ("args",):
                v = getattr(i, fld, None)
                for t in (v if isinstance(v, (list, tuple)) else [v]):
                    if t in self.addr_of and not (fld == "addr" and i.op in ("load", "store")):
                        escaped.add(self.addr_of[t])
        self.regvar = {}         # VarSym -> PTX 레지스터
        for v in f.locals:
            if v not in escaped and is_scalar(v.type):
                self.regvar[v] = f"%v{len(self.regvar)}"
        self.slots = {}          # VarSym -> 지역 자리 오프셋 (레지스터로 못 간 변수만)
        off = 0
        for v in f.locals:
            if v in self.regvar:
                continue
            size = max(getattr(v.type, "size", 8), 1)
            off = (off + 7) // 8 * 8
            self.slots[v] = off
            off += size
        self.depot = (off + 7) // 8 * 8
        self.space = self.address_spaces()
        self.rng = self.ranges() if WIDTH_PROOF else {}
        self.narrowed = {"나눗셈·나머지": 0}

    def address_spaces(self):
        """2a: 임시값의 주소 공간. 규칙 — 커널의 참조 매개변수는 전역 메모리를 가리키고, 거기서 나온 주소(색인·필드·복사)도
        전역이다. 공유 메모리 내장이 준 주소는 공유. 타입처럼 전해질 뿐 추측하지 않는다. 한 변수에 서로 다른 공간이 섞이면
        이 커널은 모두 범용 주소로 돌아간다(예전과 같은 코드)."""
        f = self.f
        params = {sym for sym, _ in f.params}
        var_src = {v: ({"global"} if v in params else set()) for v in self.regvar if v.type.is_ptr()}
        temp = {}
        changed = True
        while changed:
            changed = False
            for i in f.insts:
                s = None
                if i.op == "load" and i.addr in self.addr_of and self.addr_of[i.addr] in var_src:
                    srcs = var_src[self.addr_of[i.addr]]
                    s = next(iter(srcs)) if len(srcs) == 1 else ("generic" if srcs else None)
                elif i.op in ("index_addr", "gep"):
                    s = temp.get(i.base)
                elif i.op == "copy":
                    s = temp.get(i.src)
                elif i.op == "call" and i.extern and i.callee in SHARED:
                    s = "shared"
                elif getattr(i, "dst", None) is not None and i.dst.type.is_ptr():
                    s = "generic"
                if s is not None and temp.get(i.dst) != s:
                    temp[i.dst] = s
                    changed = True
                if i.op == "store" and i.addr in self.addr_of and self.addr_of[i.addr] in var_src:
                    s2 = temp.get(i.src, "generic")
                    srcs = var_src[self.addr_of[i.addr]]
                    if s2 not in srcs:
                        srcs.add(s2)
                        changed = True
        if any(len(s) > 1 for s in var_src.values()):
            self.global_params = set()
            return {}
        self.global_params = {v for v, s in var_src.items() if v in params and s == {"global"}}
        return {t: s for t, s in temp.items() if s in ("global", "shared")}

    def mem(self, addr):
        """메모리 명령의 공간 접미사."""
        return {"global": ".global", "shared": ".shared"}.get(self.space.get(addr), "")

    # ---------- 2e: 정수 값 범위의 증명 ----------
    def ranges(self):
        """정수 임시값마다 값이 들 수 있는 구간을 구한다 — 흐름을 따르는 구간 해석. 근거는 상수, 내장(스레드·블록 번호)의
        범위, 분기 조건으로 좁힌 변수의 구간뿐이고, 반복의 머리로 돌아오는 간선에서는 넓힌다(끝이 있게). 레지스터로 간 정수
        변수만 추적하고, 매개변수·메모리에서 읽은 값은 타입의 전 범위다. 그래서 실행할 때 받는 크기에서 나온 값은 좁혀지지 않는다."""
        insts = self.f.insts
        self.defs = {i.dst: i for i in insts if getattr(i, "dst", None) is not None}
        starts = {0}
        for k, i in enumerate(insts):
            if i.op == "label":
                starts.add(k)
            if i.op in ("jmp", "br", "ret") and k + 1 < len(insts):
                starts.add(k + 1)
        starts = sorted(starts)
        blocks = list(zip(starts, starts[1:] + [len(insts)]))
        at_label = {insts[s].name: bi for bi, (s, _) in enumerate(blocks) if insts[s].op == "label"}
        ivars = [v for v in self.regvar if v.type.is_int()]
        rng = {}
        state_in = {0: {v: type_range(v.type) for v in ivars}}
        work = [0]
        hull = lambda a, b: (min(a[0], b[0]), max(a[1], b[1]))
        while work:
            bi = work.pop(0)
            st = dict(state_in[bi])
            s, e = blocks[bi]
            src = {}                                       # 임시값 -> 이 블록에서 그 값을 읽어 온 변수(그 뒤로 안 바뀜)
            for k in range(s, e):
                i = insts[k]
                if i.op == "store" and self.addr_of.get(i.addr) in st:
                    v = self.addr_of[i.addr]
                    st[v] = self.range_of(rng, i.src) if i.src.type.is_int() else type_range(v.type)
                    src = {t: w for t, w in src.items() if w is not v}
                    continue
                d = getattr(i, "dst", None)
                if d is None or not d.type.is_int():
                    continue
                r = self.eval_range(i, st, rng)
                rng[d] = hull(rng[d], r) if d in rng else r
                if i.op == "load" and self.addr_of.get(i.addr) in st:
                    src[d] = self.addr_of[i.addr]
            last = insts[e - 1] if e > s else None
            if last is not None and last.op == "jmp":
                succ = [(at_label[last.label], st)]
            elif last is not None and last.op == "br":
                succ = [(at_label[last.ltrue], self.branch_state(last.cond, st, rng, src, True)),
                        (at_label[last.lfalse], self.branch_state(last.cond, st, rng, src, False))]
            elif last is not None and last.op == "ret":
                succ = []
            else:
                succ = [(bi + 1, st)] if bi + 1 < len(blocks) else []
            for nb, ns in succ:
                if ns is None:                             # 조건이 늘 거짓인 간선
                    continue
                if nb not in state_in:
                    state_in[nb] = ns
                    work.append(nb)
                    continue
                old = state_in[nb]
                new = {v: hull(old[v], ns[v]) for v in ivars}
                if new == old:
                    continue
                if nb <= bi:                               # 반복의 머리로 돌아오는 간선 — 커지는 쪽 끝을 타입의 끝까지 넓힌다
                    new = {v: (old[v][0] if new[v][0] >= old[v][0] else type_range(v.type)[0],
                               old[v][1] if new[v][1] <= old[v][1] else type_range(v.type)[1]) for v in ivars}
                state_in[nb] = new
                if nb not in work:
                    work.append(nb)
        return rng

    def range_of(self, rng, t):
        return rng.get(t) or type_range(t.type)

    def eval_range(self, i, st, rng):
        t = i.dst.type
        R = lambda x: self.range_of(rng, x)
        op = i.op
        if op == "const":
            return clamp_to(t, int(i.value), int(i.value))
        if op == "load":
            v = self.addr_of.get(i.addr)
            return st[v] if v in st else type_range(t)
        if op == "copy":
            return R(i.src) if i.src.type.is_int() else type_range(t)
        if op == "call":
            return INTRINSIC_RANGE.get(i.callee, type_range(t)) if i.extern else type_range(t)
        if op in ("cmp", "lnot"):
            return (0, 1)
        if op == "neg":
            a = R(i.a)
            return clamp_to(t, -a[1], -a[0])
        if op == "cast":
            if i.kind in ("sext", "zext", "trunc") and i.src.type.is_int():
                a = R(i.src)
                if i.kind == "zext" and a[0] < 0:
                    return type_range(t)
                return clamp_to(t, a[0], a[1])
            return type_range(t)
        if op != "bin":
            return type_range(t)
        a, b = R(i.a), R(i.b)
        bop = i.bop
        if bop == "add":
            return clamp_to(t, a[0] + b[0], a[1] + b[1])
        if bop == "sub":
            return clamp_to(t, a[0] - b[1], a[1] - b[0])
        if bop == "mul":
            c = [a[0] * b[0], a[0] * b[1], a[1] * b[0], a[1] * b[1]]
            return clamp_to(t, min(c), max(c))
        if bop in ("sdiv", "udiv") and a[0] >= 0 and b[0] >= 1:
            return clamp_to(t, a[0] // b[1], a[1] // b[0])
        if bop in ("srem", "urem") and a[0] >= 0 and b[0] >= 1:
            return (0, min(a[1], b[1] - 1))
        if bop == "and" and (a[0] >= 0 or b[0] >= 0):
            return (0, min(x[1] for x in (a, b) if x[0] >= 0))
        if bop in ("or", "xor") and a[0] >= 0 and b[0] >= 0:
            return clamp_to(t, 0, (1 << max(a[1], b[1]).bit_length()) - 1)
        if bop == "shl" and a[0] >= 0 and b[0] == b[1] and 0 <= b[0] < 64:
            return clamp_to(t, a[0] << b[0], a[1] << b[0])
        if bop in ("lshr", "ashr") and a[0] >= 0 and b[0] == b[1] and 0 <= b[0] < 64:
            return (a[0] >> b[0], a[1] >> b[0])
        return type_range(t)

    def branch_state(self, cond, st, rng, src, taken):
        """분기의 한쪽 간선에서의 변수 구간: 조건이 비교이고 그 피연산자가 이 블록에서 읽은 변수면 그 변수를 좁힌다."""
        c = self.defs.get(cond)
        if c is None or c.op != "cmp" or not c.type.is_int():
            return st
        rel = c.cond if taken else NEGATE[c.cond]
        out = dict(st)
        for x, y, rr in ((c.a, c.b, rel), (c.b, c.a, SWAP[rel])):
            v = src.get(x)
            if v is not None and rr != "ne":
                n = refine(out[v], rr, self.range_of(rng, y))
                if n is None:
                    return None
                out[v] = n
        return out

    def fits32(self, t):
        r = self.rng.get(t)
        return r is not None and I32_MIN <= r[0] and r[1] <= I32_MAX

    def r(self, t):
        return f"%t{t.id}"

    def label(self, name):
        if name not in self.labels:
            self.labels[name] = f"$L{len(self.labels) + 1}"
        return self.labels[name]

    def emit(self, s):
        self.lines.append("    " + s)

    def int_type(self, t, signed=None):
        """정수 명령의 타입 접미사. 레지스터 폭을 따른다."""
        s = t.signed if signed is None else signed
        return (".s" if s else ".u") + str(width(t))

    def normalize(self, d, t):
        """8·16비트 값을 32비트 레지스터 안에서 그 타입의 범위로 맞춘다."""
        if t.is_int() and t.bits < 32:
            sh = 32 - t.bits
            if t.signed:
                self.emit(f"shl.b32 {d}, {d}, {sh};")
                self.emit(f"shr.s32 {d}, {d}, {sh};")
            else:
                self.emit(f"and.b32 {d}, {d}, {(1 << t.bits) - 1};")

    def gen(self):
        f = self.f
        if f.ret is not None:
            raise PTXError(f"'{f.name}': 반환값이 있는 함수는 아직 받지 않는다 (커널은 반환값이 없다)")
        params = [f"    .param {mem_type(t) if not (t.is_int() and t.bits < 32) else ('.s32' if t.signed else '.u32')} p{k}"
                  for k, (_, t) in enumerate(f.params)]
        out = [f"// kernel: {ptx_name(f.name)}", f".visible .entry {ptx_name(f.name)}(", ",\n".join(params), ")", "{"]
        if self.depot:
            out.append(f"    .local .align 8 .b8 __depot[{self.depot}];")
        out.append("    .reg .u64 %SPL, %SP;")
        out.append("    .reg .pred %p, %q;")
        out.append("    .reg .u32 %x<4>;")
        out.append("    .reg .u64 %X<3>;")
        out.append("    .reg .b32 %w<3>;")
        out.append("    .reg .f32 %fw<2>;")
        for name in sorted({i.callee for i in f.insts if i.op == "call" and i.extern and i.callee in SHARED}):
            out.append(f"    .shared .align 16 .b8 {SHARED[name]}[{SHARED_SIZE[name]}];")
        for t in f.temps:
            out.append(f"    .reg {reg_type(t.type)} {self.r(t)};")
        for v, reg in self.regvar.items():
            out.append(f"    .reg {reg_type(v.type)} {reg};")
        for k, (sym, t) in enumerate(f.params):
            if sym not in self.regvar:
                out.append(f"    .reg {reg_type(t)} %a{k};")
        if self.depot:
            self.emit("mov.u64 %SPL, __depot;")
            self.emit("cvta.local.u64 %SP, %SPL;")
        for k, (sym, t) in enumerate(f.params):
            ld = mem_type(t) if not (t.is_int() and t.bits < 32) else ("." + ("s" if t.signed else "u") + "32")
            if sym in self.regvar:                 # 2a: 매개변수를 레지스터로 바로 — 참조 매개변수는 전역 주소로 바꿔 둔다
                self.emit(f"ld.param{ld} {self.regvar[sym]}, [p{k}];")
                if sym in self.global_params:
                    self.emit(f"cvta.to.global.u64 {self.regvar[sym]}, {self.regvar[sym]};")
            else:
                self.emit(f"ld.param{ld} %a{k}, [p{k}];")
                self.emit(f"st{mem_type(t)} [%SP+{self.slots[sym]}], %a{k};")
        for i in f.insts:
            self.inst(i)
        n = self.narrowed
        out.insert(0, f"// 2e width proof: {n['나눗셈·나머지']} div/rem computed with 32-bit operands")
        return "\n".join(out + self.lines + ["}"])

    def inst(self, i):
        op = i.op
        e = self.emit
        if op == "label":
            self.lines.append(f"{self.label(i.name)}:")
        elif op == "const":
            t = i.dst.type
            bits = width(t)
            e(f"mov.b{bits} {self.r(i.dst)}, {int(i.value) & ((1 << bits) - 1):#x};")
        elif op == "fconst":
            if i.dst.type.bits == 32:
                e(f"mov.f32 {self.r(i.dst)}, 0f{struct.unpack('<I', struct.pack('<f', i.value))[0]:08X};")
            else:
                e(f"mov.f64 {self.r(i.dst)}, 0d{struct.unpack('<Q', struct.pack('<d', i.value))[0]:016X};")
        elif op == "addr_local":
            if i.var not in self.regvar:           # 레지스터로 간 변수는 주소가 없다
                e(f"add.u64 {self.r(i.dst)}, %SP, {self.slots[i.var]};")
        elif op == "copy":
            e(f"mov{reg_type(i.dst.type)} {self.r(i.dst)}, {self.r(i.src)};")
        elif op == "load":
            var = self.addr_of.get(i.addr)
            if var in self.regvar:
                e(f"mov{reg_type(i.dst.type)} {self.r(i.dst)}, {self.regvar[var]};")
            else:
                e(f"ld{self.mem(i.addr)}{mem_type(i.dst.type)} {self.r(i.dst)}, [{self.r(i.addr)}];")
        elif op == "store":
            var = self.addr_of.get(i.addr)
            if var in self.regvar:
                e(f"mov{reg_type(var.type)} {self.regvar[var]}, {self.r(i.src)};")
            else:
                e(f"st{self.mem(i.addr)}{mem_type(i.type)} [{self.r(i.addr)}], {self.r(i.src)};")
        elif op == "gep":
            e(f"add.s64 {self.r(i.dst)}, {self.r(i.base)}, {i.offset};")
        elif op == "index_addr":
            idx = self.r(i.idx)
            if width(i.idx.type) == 32:
                e(f"cvt{'.s64.s32' if i.idx.type.signed else '.u64.u32'} %X0, {idx};")
                idx = "%X0"
            e(f"mad.lo.s64 {self.r(i.dst)}, {idx}, {i.size}, {self.r(i.base)};")
        elif op == "bin":
            self.binop(i)
        elif op == "cmp":
            t = i.type
            cond = CMP[i.cond]
            if t.is_float():
                ty = reg_type(t)
            elif t.is_ptr():
                ty = ".u64"
            else:
                ty = self.int_type(t, signed=not i.cond.startswith("u") and t.signed)
            e(f"setp.{cond}{ty} %p, {self.r(i.a)}, {self.r(i.b)};")
            e(f"selp.u32 {self.r(i.dst)}, 1, 0, %p;")
        elif op == "neg":
            t = i.dst.type
            e(f"neg{reg_type(t) if t.is_float() else self.int_type(t, signed=True)} {self.r(i.dst)}, {self.r(i.a)};")
            self.normalize(self.r(i.dst), t)
        elif op == "not":
            e(f"not.b{width(i.dst.type)} {self.r(i.dst)}, {self.r(i.a)};")
            self.normalize(self.r(i.dst), i.dst.type)
        elif op == "lnot":
            t = i.type
            zero = ("0f00000000" if t.bits == 32 else "0d0000000000000000") if t.is_float() else "0"
            ty = reg_type(t) if t.is_float() else (".u64" if width(t) == 64 else ".u32")
            e(f"setp.eq{ty} %p, {self.r(i.a)}, {zero};")
            e(f"selp.u32 {self.r(i.dst)}, 1, 0, %p;")
        elif op == "cast":
            self.cast(i)
        elif op == "call":
            self.call(i)
        elif op == "jmp":
            e(f"bra.uni {self.label(i.label)};")
        elif op == "br":
            e(f"setp.ne.u32 %p, {self.r(i.cond)}, 0;")
            e(f"@%p bra {self.label(i.ltrue)};")
            e(f"bra.uni {self.label(i.lfalse)};")
        elif op == "ret":
            if i.value is not None:
                raise PTXError("커널은 값을 돌려줄 수 없다")
            e("ret;")
        else:
            raise PTXError(f"'{self.f.name}': PTX 탐침이 아직 받지 않는 IR 명령 '{op}' (문자열·전역·함수 값·묶음 복사·가변 인자 등)")

    def binop(self, i):
        t = i.dst.type
        d, a, b = self.r(i.dst), self.r(i.a), self.r(i.b)
        base = BIN[i.bop]
        if t.is_float():
            self.emit(f"{base}{reg_type(t)} {d}, {a}, {b};")
            return
        if i.bop in ("and", "or", "xor"):
            self.emit(f"{base}.b{width(t)} {d}, {a}, {b};")
        elif i.bop in ("shl", "lshr", "ashr"):
            amt = b
            if width(i.b.type) == 64:
                self.emit(f"cvt.u32.u64 %x0, {b};")
                amt = "%x0"
            ty = ".b" + str(width(t)) if i.bop == "shl" else self.int_type(t, signed=(i.bop == "ashr"))
            self.emit(f"{base}{ty} {d}, {a}, {amt};")
        elif (width(t) == 64 and i.bop in ("sdiv", "srem", "udiv", "urem") and self.fits32(i.a) and self.fits32(i.b)
              and self.rng[i.a][0] >= 0 and self.rng[i.b][0] >= 1):
            # 2e: 음이 아닌 두 값이 32비트 범위임이 증명됐다 — 32비트 나눗셈(부호 있는 것과 없는 것의 답이 같다)
            self.emit(f"cvt.u32.u64 %w0, {a};")
            self.emit(f"cvt.u32.u64 %w1, {b};")
            self.emit(f"{'div' if i.bop.endswith('div') else 'rem'}.u32 %w2, %w0, %w1;")
            self.emit(f"cvt.u64.u32 {d}, %w2;")
            self.narrowed["나눗셈·나머지"] += 1
        else:
            signed = t.signed if i.bop in ("add", "sub", "mul") else i.bop in ("sdiv", "srem")
            self.emit(f"{base}{self.int_type(t, signed=signed)} {d}, {a}, {b};")
        self.normalize(d, t)

    def cast(self, i):
        d, s = self.r(i.dst), self.r(i.src)
        dt, st = i.dst.type, i.src.type
        k = i.kind
        e = self.emit
        if k in ("sext", "zext", "trunc"):
            if width(dt) == width(st):
                e(f"mov.b{width(dt)} {d}, {s};")
            elif width(dt) == 64:      # 32 → 64
                e(f"cvt{'.s64.s32' if k == 'sext' else '.u64.u32'} {d}, {s};")
            else:                      # 64 → 32
                e(f"cvt.u32.u64 {d}, {s};")
            self.normalize(d, dt)
        elif k in ("sitofp", "uitofp"):
            e(f"cvt.rn{reg_type(dt)}{self.int_type(st, signed=(k == 'sitofp'))} {d}, {s};")
        elif k in ("fptosi", "fptoui"):
            if RANGE_CHECK:            # 2c: 값이 대상 정수의 범위 [lo, hi) 밖이면(NaN 포함) 오류 칸에 1
                bits = dt.bits
                lo, hi = (-(2.0 ** (bits - 1)), 2.0 ** (bits - 1)) if k == "fptosi" else (-1.0, 2.0 ** bits)
                ft = reg_type(st)
                cmp_lo = "ge" if k == "fptosi" else "gt"
                e(f"setp.{cmp_lo}{ft} %q, {s}, {flit(lo, st)};")
                e(f"setp.lt.and{ft} %q, {s}, {flit(hi, st)}, %q;")
                e("@!%q red.global.or.b32 [__geul_err], 1;")
            e(f"cvt.rzi{self.int_type(dt, signed=(k == 'fptosi'))}{reg_type(st)} {d}, {s};")
            self.normalize(d, dt)
        elif k == "fpext":
            e(f"cvt.f64.f32 {d}, {s};")
        elif k == "fptrunc":
            e(f"cvt.rn.f32.f64 {d}, {s};")
            if RANGE_CHECK:            # 2c: 유한한 실수가 짧은실수로 오며 무한이 되면 오류 칸에 2
                e(f"testp.infinite.f32 %q, {d};")
                e(f"testp.finite.f64 %p, {s};")
                e("and.pred %q, %q, %p;")
                e("@%q red.global.or.b32 [__geul_err], 2;")
        else:
            raise PTXError(f"PTX 탐침이 아직 받지 않는 변환 '{k}'")

    def call(self, i):
        name = i.callee if isinstance(i.callee, str) else None
        if not (i.extern and name in INTRINSICS):
            raise PTXError(f"'{self.f.name}': 함수 호출은 아직 받지 않는다 (GPU 내장 {', '.join(INTRINSICS)} 만): {name}")
        e = self.emit
        if name == "동기화":          # 블록 안의 모든 스레드가 여기까지 오고, 그 앞의 공유 메모리 쓰기가 보인다
            e("bar.sync 0;")
            return
        if i.dst is None:
            raise PTXError(f"GPU 내장 '{name}' 의 값을 쓰지 않았다")
        d = self.r(i.dst)
        if name == "곱해더하기":
            x, y, z = (self.r(a) for a in i.args)
            e(f"fma.rn{reg_type(i.dst.type)} {d}, {x}, {y}, {z};")
        elif name == "근사지수":
            if i.dst.type.bits != 32:
                raise PTXError("근사지수는 짧은실수만 받는다")
            e(f"mul.rn.f32 %fw0, {self.r(i.args[0])}, 0f3FB8AA3B;")      # x · log2(e)
            e(f"ex2.approx.f32 {d}, %fw0;")
        elif name == "제곱근":
            e(f"sqrt.rn{reg_type(i.dst.type)} {d}, {self.r(i.args[0])};")
        elif name == "큰쪽":
            e(f"max{reg_type(i.dst.type)} {d}, {self.r(i.args[0])}, {self.r(i.args[1])};")
        elif name in BLOCK_REGS:
            e(f"mov.u32 %x1, {BLOCK_REGS[name]};")
            e(f"cvt.u64.u32 {d}, %x1;")
        elif name in SHARED:          # 공유 메모리 공간의 주소 — 이 주소로의 읽기·쓰기는 ld.shared·st.shared 가 된다
            e(f"mov.u64 {d}, {SHARED[name]};")
        elif name == "실행번호":       # %ctaid.x * %ntid.x + %tid.x
            e("mov.u32 %x1, %ctaid.x;")
            e("mov.u32 %x2, %ntid.x;")
            e("mov.u32 %x3, %tid.x;")
            e("mul.wide.u32 %X1, %x1, %x2;")
            e("cvt.u64.u32 %X2, %x3;")
            e(f"add.s64 {d}, %X1, %X2;")
        else:                         # 실행개수 = %nctaid.x * %ntid.x
            e("mov.u32 %x1, %nctaid.x;")
            e("mov.u32 %x2, %ntid.x;")
            e(f"mul.wide.u32 {d}, %x1, %x2;")


def translate(src):
    program = load_program(src, os.path.join(ROOT, "표준"), auto_std=False)
    unit = sema.analyze(program, fragment=True)
    ir = inline.run(lower.lower_program(unit))
    kernels = [f for f in ir.functions if f.ret is None]
    if not kernels:
        raise PTXError("커널이 없다 — 반환값이 없는 함수가 커널이 된다")
    head = ["//", "// geul -> PTX probe (research/gpu/geulptx). ASCII only: Korean names are mangled as _G + UTF-8 hex.", "//",
            ".version 7.0", ".target sm_52", ".address_size 64", "",
            "// 2c: range-check error cell (bit 1: float->int out of range, bit 2: float64->float32 overflow)",
            ".visible .global .align 4 .u32 __geul_err;", ""]
    body = [FuncPTX(f).gen() for f in kernels]
    return "\n".join(head) + "\n\n".join(body) + "\n", [(f.name, ptx_name(f.name)) for f in kernels]


def main(argv):
    if not argv or argv[0].startswith("-"):
        print(__doc__)
        return 3
    src = argv[0]
    out = argv[argv.index("-o") + 1] if "-o" in argv else os.path.splitext(src)[0] + ".ptx"
    try:
        text, names = translate(src)
    except CompileError as e:
        print(str(e), file=sys.stderr)
        return 1
    except PTXError as e:
        print(f"{src}: PTX 탐침 오류: {e}", file=sys.stderr)
        return 1
    text.encode("ascii")      # PTX 는 ASCII 만 — 어기면 여기서 멈춘다
    open(out, "w", encoding="ascii", newline="\n").write(text)
    for g, p in names:
        print(f"커널 {g} → {p}")
    print(f"PTX: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
