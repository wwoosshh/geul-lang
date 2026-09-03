"""x86-64 인코더. 필요한 명령만, 항상 명시적 인코딩. 메모리 피연산자는 [base+disp32] 또는 [rip+disp32]."""
import struct

RAX, RCX, RDX, RBX, RSP, RBP, RSI, RDI = range(8)
R8, R9, R10, R11, R12, R13, R14, R15 = range(8, 16)
XMM0, XMM1, XMM2, XMM3 = 0, 1, 2, 3
ARG_REGS = [RCX, RDX, R8, R9]

CC = {"e": 4, "ne": 5, "l": 0xC, "ge": 0xD, "le": 0xE, "g": 0xF, "b": 2, "ae": 3, "be": 6, "a": 7, "p": 0xA, "np": 0xB}


class Asm:
    def __init__(self):
        self.code = bytearray()
        self.labels = {}
        self.label_fixups = []      # (offset, label)  rel32
        self.ext_fixups = []        # (offset, kind, target)  rel32 to iat/str/data

    # ---------- 기본 ----------
    def emit(self, *bs):
        for b in bs:
            self.code.append(b & 0xFF)

    def emit32(self, v):
        self.code += struct.pack("<i", v) if -(1 << 31) <= v < (1 << 31) else struct.pack("<I", v & 0xFFFFFFFF)

    def emit64(self, v):
        self.code += struct.pack("<q", v) if -(1 << 63) <= v < (1 << 63) else struct.pack("<Q", v & 0xFFFFFFFFFFFFFFFF)

    def pos(self):
        return len(self.code)

    def label(self, name):
        if name in self.labels:
            raise KeyError(f"중복 라벨: {name}")       # 힌트 뒤에 번호가 붙으므로 힌트는 숫자로 끝나면 안 된다
        self.labels[name] = self.pos()

    def rex(self, w=0, r=0, x=0, b=0, force=False):
        v = 0x40 | (w << 3) | ((r >> 3) << 2) | ((x >> 3) << 1) | (b >> 3)
        if v != 0x40 or force:
            self.emit(v)

    def modrm(self, mod, reg, rm):
        self.emit((mod << 6) | ((reg & 7) << 3) | (rm & 7))

    def mem(self, reg, base, disp):
        """[base+disp32] 형태 ModRM (+SIB). base 가 None 이면 [rip+disp32] (disp 는 나중에 채움)."""
        if base is None:
            self.modrm(0, reg, 5)
            self.emit32(disp)
            return
        if (base & 7) == 4:
            self.modrm(2, reg, 4)
            self.emit(0x24)
        else:
            self.modrm(2, reg, base)
        self.emit32(disp)

    def rip_fixup(self, kind, target):
        """직전에 낸 disp32 자리를 고정할 fixup. 호출 직전에 disp32 4바이트를 0으로 낸 상태여야 한다."""
        self.ext_fixups.append((self.pos() - 4, kind, target))

    # ---------- 정수 mov ----------
    def mov_imm(self, r, v):
        if 0 <= v < (1 << 32):
            self.rex(0, 0, 0, r)
            self.emit(0xB8 + (r & 7))
            self.emit32(v)
        elif -(1 << 31) <= v < 0:
            self.rex(1, 0, 0, r)
            self.emit(0xC7)
            self.modrm(3, 0, r)
            self.emit32(v)
        else:
            self.rex(1, 0, 0, r)
            self.emit(0xB8 + (r & 7))
            self.emit64(v)

    def mov_rr(self, dst, src):
        self.rex(1, src, 0, dst); self.emit(0x89); self.modrm(3, src, dst)

    def load(self, r, base, disp, bits=64, signed=True):
        """r <- [base+disp], 64비트로 확장."""
        if bits == 64:
            self.rex(1, r, 0, base if base is not None else 0); self.emit(0x8B); self.mem(r, base, disp)
        elif bits == 32:
            if signed:
                self.rex(1, r, 0, base or 0); self.emit(0x63); self.mem(r, base, disp)
            else:
                self.rex(0, r, 0, base or 0); self.emit(0x8B); self.mem(r, base, disp)
        elif bits == 16:
            self.rex(1, r, 0, base or 0); self.emit(0x0F, 0xBF if signed else 0xB7); self.mem(r, base, disp)
        elif bits == 8:
            self.rex(1, r, 0, base or 0); self.emit(0x0F, 0xBE if signed else 0xB6); self.mem(r, base, disp)
        else:
            raise ValueError(bits)

    def store(self, base, disp, r, bits=64):
        if bits == 64:
            self.rex(1, r, 0, base or 0); self.emit(0x89); self.mem(r, base, disp)
        elif bits == 32:
            self.rex(0, r, 0, base or 0); self.emit(0x89); self.mem(r, base, disp)
        elif bits == 16:
            self.emit(0x66); self.rex(0, r, 0, base or 0); self.emit(0x89); self.mem(r, base, disp)
        elif bits == 8:
            self.rex(0, r, 0, base or 0, force=(r >= 4)); self.emit(0x88); self.mem(r, base, disp)
        else:
            raise ValueError(bits)

    def lea(self, r, base, disp):
        self.rex(1, r, 0, base or 0); self.emit(0x8D); self.mem(r, base, disp)

    def movsx_rr(self, dst, src, bits):
        """dst <- 부호 확장(src 의 하위 bits)."""
        if bits == 8:
            self.rex(1, dst, 0, src, force=True); self.emit(0x0F, 0xBE); self.modrm(3, dst, src)
        elif bits == 16:
            self.rex(1, dst, 0, src); self.emit(0x0F, 0xBF); self.modrm(3, dst, src)
        elif bits == 32:
            self.rex(1, dst, 0, src); self.emit(0x63); self.modrm(3, dst, src)

    def movzx_rr(self, dst, src, bits):
        if bits == 8:
            self.rex(1, dst, 0, src, force=True); self.emit(0x0F, 0xB6); self.modrm(3, dst, src)
        elif bits == 16:
            self.rex(1, dst, 0, src); self.emit(0x0F, 0xB7); self.modrm(3, dst, src)
        elif bits == 32:
            self.rex(0, dst, 0, src); self.emit(0x8B); self.modrm(3, dst, src)

    # ---------- 산술 ----------
    def alu(self, op, dst, src):
        """dst op= src (64비트). op: add or and sub xor cmp"""
        code = {"add": 0x01, "or": 0x09, "and": 0x21, "sub": 0x29, "xor": 0x31, "cmp": 0x39}[op]
        self.rex(1, src, 0, dst); self.emit(code); self.modrm(3, src, dst)

    def alu_imm(self, op, dst, imm):
        ext = {"add": 0, "or": 1, "and": 4, "sub": 5, "xor": 6, "cmp": 7}[op]
        self.rex(1, 0, 0, dst); self.emit(0x81); self.modrm(3, ext, dst); self.emit32(imm)

    def imul(self, dst, src):
        self.rex(1, dst, 0, src); self.emit(0x0F, 0xAF); self.modrm(3, dst, src)

    def imul_imm(self, dst, src, imm):
        """dst <- src * imm32"""
        self.rex(1, dst, 0, src); self.emit(0x69); self.modrm(3, dst, src); self.emit32(imm)

    def shift_imm(self, op, r, n):
        ext = {"shl": 4, "shr": 5, "sar": 7}[op]
        self.rex(1, 0, 0, r); self.emit(0xC1); self.modrm(3, ext, r); self.emit(n & 63)

    def store_imm(self, base, disp, v, bits=64):
        """[base+disp] <- imm (bits 크기)"""
        if bits == 64:
            self.rex(1, 0, 0, base or 0); self.emit(0xC7); self.mem(0, base, disp); self.emit32(v)
        elif bits == 32:
            self.rex(0, 0, 0, base or 0); self.emit(0xC7); self.mem(0, base, disp); self.emit32(v)
        elif bits == 16:
            self.emit(0x66); self.rex(0, 0, 0, base or 0); self.emit(0xC7); self.mem(0, base, disp); self.emit(v & 0xFF, (v >> 8) & 0xFF)
        else:
            self.rex(0, 0, 0, base or 0); self.emit(0xC6); self.mem(0, base, disp); self.emit(v & 0xFF)

    def cqo(self):
        self.emit(0x48, 0x99)

    def idiv(self, r):
        self.rex(1, 0, 0, r); self.emit(0xF7); self.modrm(3, 7, r)

    def div(self, r):
        self.rex(1, 0, 0, r); self.emit(0xF7); self.modrm(3, 6, r)

    def shift_cl(self, op, r):
        ext = {"shl": 4, "shr": 5, "sar": 7}[op]
        self.rex(1, 0, 0, r); self.emit(0xD3); self.modrm(3, ext, r)

    def neg(self, r):
        self.rex(1, 0, 0, r); self.emit(0xF7); self.modrm(3, 3, r)

    def not_(self, r):
        self.rex(1, 0, 0, r); self.emit(0xF7); self.modrm(3, 2, r)

    def test(self, a, b):
        self.rex(1, b, 0, a); self.emit(0x85); self.modrm(3, b, a)

    def setcc(self, cc, r):
        self.rex(0, 0, 0, r, force=(r >= 4)); self.emit(0x0F, 0x90 + CC[cc]); self.modrm(3, 0, r)

    # ---------- 분기·호출 ----------
    def jmp(self, label):
        self.emit(0xE9); self.label_fixups.append((self.pos(), label)); self.emit32(0)

    def jcc(self, cc, label):
        self.emit(0x0F, 0x80 + CC[cc]); self.label_fixups.append((self.pos(), label)); self.emit32(0)

    def call_label(self, label):
        self.emit(0xE8); self.label_fixups.append((self.pos(), label)); self.emit32(0)

    def call_iat(self, name):
        self.emit(0xFF, 0x15); self.emit32(0); self.rip_fixup("iat", name)

    def call_reg(self, r):
        self.rex(0, 0, 0, r); self.emit(0xFF); self.modrm(3, 2, r)

    def push(self, r):
        self.rex(0, 0, 0, r); self.emit(0x50 + (r & 7))

    def pop(self, r):
        self.rex(0, 0, 0, r); self.emit(0x58 + (r & 7))

    def ret(self):
        self.emit(0xC3)

    def sub_rsp(self, n):
        self.alu_imm("sub", RSP, n)

    def add_rsp(self, n):
        self.alu_imm("add", RSP, n)

    def lea_rip(self, r, kind, target):
        self.rex(1, r, 0, 0); self.emit(0x8D); self.modrm(0, r, 5); self.emit32(0); self.rip_fixup(kind, target)

    def load_rip(self, r, kind, target):
        self.rex(1, r, 0, 0); self.emit(0x8B); self.modrm(0, r, 5); self.emit32(0); self.rip_fixup(kind, target)

    # ---------- SSE ----------
    def sse(self, prefix, opcode, reg, rm_reg=None, base=None, disp=0, w=0):
        if prefix:
            self.emit(prefix)
        if rm_reg is not None:
            self.rex(w, reg, 0, rm_reg); self.emit(0x0F, opcode); self.modrm(3, reg, rm_reg)
        else:
            self.rex(w, reg, 0, base or 0); self.emit(0x0F, opcode); self.mem(reg, base, disp)

    def movsd_load(self, x, base, disp, bits=64):
        self.sse(0xF2 if bits == 64 else 0xF3, 0x10, x, base=base, disp=disp)

    def movsd_store(self, base, disp, x, bits=64):
        self.sse(0xF2 if bits == 64 else 0xF3, 0x11, x, base=base, disp=disp)

    def fop(self, op, x, y, bits=64):
        code = {"add": 0x58, "sub": 0x5C, "mul": 0x59, "div": 0x5E}[op]
        self.sse(0xF2 if bits == 64 else 0xF3, code, x, rm_reg=y)

    def ucomis(self, x, y, bits=64):
        self.sse(0x66 if bits == 64 else None, 0x2E, x, rm_reg=y)

    def cvtsi2f(self, x, r, bits=64):
        self.sse(0xF2 if bits == 64 else 0xF3, 0x2A, x, rm_reg=r, w=1)

    def cvttf2si(self, r, x, bits=64):
        self.sse(0xF2 if bits == 64 else 0xF3, 0x2C, r, rm_reg=x, w=1)

    def cvtsd2ss(self, x, y):
        self.sse(0xF2, 0x5A, x, rm_reg=y)

    def cvtss2sd(self, x, y):
        self.sse(0xF3, 0x5A, x, rm_reg=y)

    def movq_xr(self, x, r):
        self.emit(0x66); self.rex(1, x, 0, r); self.emit(0x0F, 0x6E); self.modrm(3, x, r)

    def movq_rx(self, r, x):
        self.emit(0x66); self.rex(1, x, 0, r); self.emit(0x0F, 0x7E); self.modrm(3, x, r)

    # ---------- 고정 ----------
    def resolve_labels(self):
        for off, label in self.label_fixups:
            if label not in self.labels:
                raise KeyError(f"라벨 없음: {label}")
            rel = self.labels[label] - (off + 4)
            self.code[off:off + 4] = struct.pack("<i", rel)
