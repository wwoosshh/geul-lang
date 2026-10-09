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
- 4단계 2(docs/17): 연구 옵션의 `반실수`(IEEE 754 binary16, ref/geul/research.py) — 저장 형식(.b16 레지스터, ld/st .b16).
  좁히기 `으로 반실수` 는 cvt.rn.f16.f32(가까운 쪽 반올림, 비정규수 그대로), 넘쳐 무한이 되면 오류 칸에 4. 넓히기는 cvt.f32.f16
  (정확). 반실수 산술은 앞단이 짧은실수로 올려서 낸다.
- 다른 함수 호출, 문자열, 전역 변수, 묶음 값 복사, 가변 인자는 아직 받지 않는다.
"""
import io
import os
import re
import struct
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "ref"))

from geul.driver import load_program          # noqa: E402
from geul import sema, lower, inline, research  # noqa: E402
from geul.diagnostics import CompileError     # noqa: E402

# GPU 내장. 실행번호·실행개수는 탐침 1 부터, 나머지는 2b 의 연구용 내장이다(언어가 아니다 — 타일을 손으로 써 보기 위한 것).
BLOCK_REGS = {"블록안가로": "%tid.x", "블록안세로": "%tid.y", "블록가로": "%ctaid.x", "블록세로": "%ctaid.y"}
SHARED = {f"공유메모리{k}": f"__geul_sm{k}" for k in range(4)}      # 각 4096 바이트, 공유 메모리 공간의 주소를 돌려준다
SHARED_BYTES = 4096
# 3단계: 여러 행을 한 블록이 맡는 선형 커널의 가닥 합치기 칸 — 16384 바이트 하나. 앞의 넷은 크기를 바꾸지 않는다(2단계의 잰 값 그대로).
SHARED["큰공유메모리"] = "__geul_bsm"
SHARED_SIZE = {name: (16384 if name == "큰공유메모리" else SHARED_BYTES) for name in SHARED}
# 3단계 성능: 공유판N — N KB 짜리 판 하나(N = 4, 8, …, 48). 커널이 필요한 만큼만 잡는다(블록당 정적 공유 메모리는 48 KB 까지).
for _kb in list(range(4, 49, 4)) + [33]:                 # 33: 9단계 정수어텐션의 실험(SM 에 블록 셋 — 3 × 33 KB ≤ 100 KB)
    SHARED[f"공유판{_kb}"] = f"__geul_pan{_kb}"
    SHARED_SIZE[f"공유판{_kb}"] = _kb * 1024
# 2c: 실수 → 정수, 실수 → 짧은실수 변환의 범위 검사. 넘으면 모듈의 오류 칸 __geul_err 에 비트를 켠다(1 정수, 2 짧은실수) —
# 호스트가 실행 뒤에 읽는다. 조용한 값이 없다. (끄는 것은 재기 도구가 검사의 비용을 잴 때만 한다.)
RANGE_CHECK = True
# 2e: 음이 아니고 32비트 범위임이 증명된 두 값의 나눗셈·나머지를 32비트 명령으로 (결과는 64비트로 되돌린다). GPU 에서 64비트
# 나눗셈은 소프트웨어로 돌아서 비싸다. 곱셈·주소 계산도 좁혀 봤지만, 드라이버 컴파일러가 반복 변수의 곱을 덧셈으로 바꾸는
# 최적화와 겹쳐 이득이 없거나 오히려 느려졌다(타일 행렬곱 2.29 → 2.98 ms) — 그래서 좁히지 않는다. 끄는 것은 재기 도구만.
WIDTH_PROOF = True
# 3단계 성능: a[x + 상수] 의 상수를 메모리 명령의 즉시 오프셋으로 접는다(주소 계산만 줄고 값은 그대로). 끄는 것은 재기 도구만.
FOLD_OFFSETS = True
# 3단계 성능: 공유 메모리 판에서 4 의 배수 자리부터 네 칸을 차례로 읽으면 ld.shared.v4 하나로(값은 그대로). 끄는 것은 재기 도구만.
VECTOR_LOADS = True
# 같은 묶어 읽기를 전역 메모리에서도(ld.global.v4) — 커널의 참조 매개변수가 16 바이트 정렬이라는 약속 아래에서만(호스트가 확인).
VECTOR_GLOBAL = True
LAUNCH_BOUNDS = {}                               # 커널 이름 -> (블록당 스레드 수, SM 당 블록 수) — 소스의 실행한도 주석에서


def flit(x, t):
    """실수 상수의 PTX 표기 (t 의 폭)."""
    if t.bits == 32:
        return f"0f{struct.unpack('<I', struct.pack('<f', x))[0]:08X}"
    return f"0d{struct.unpack('<Q', struct.pack('<d', x))[0]:016X}"
# 2g: 곱해더하기(x, y, z) = x × y + z 를 반올림 한 번으로(fma.rn). 소스가 이 낱말로 밝힐 때만 합친다 — `x * y + z` 는 늘 두 번 반올림.
# 3단계: 근사지수(x) ≈ e^x — 근사 명령 ex2.approx 를 쓴다(소스가 이 낱말로 근사를 밝힐 때만, PTX 계약 P2). 제곱근(x) 은 정확한
# 반올림(sqrt.rn). 큰쪽(a, b) 은 max(한쪽이 NaN 이면 다른 쪽).
# 3단계 성능: 비동기복사(판, i, 원본, j) — 판[i] ← 원본[j] 를 비동기로(cp.async, 4 바이트, sm_80 부터). 비동기묶기() 는 지금까지의
# 복사를 한 묶음으로, 비동기기다리기(n) 은 끝나지 않은 묶음이 n 개 이하가 될 때까지 기다린다(n 은 상수). 값은 그대로 옮겨질 뿐이다 —
# 다음 조각을 레지스터 없이 미리 읽어 두려고 쓴다. 다른 스레드가 쓴 칸을 읽으려면 그 뒤에 동기화가 있어야 한다.
# 비동기복사16 은 네 칸(16 바이트)을 한 번에 — 두 주소가 16 바이트 정렬이어야 한다(부르는 쪽의 약속; 어기면 실행 오류로 멈춘다,
# 조용히 틀리지 않는다).
ASYNC = ("비동기복사", "비동기복사16", "비동기묶기", "비동기기다리기", "넓게미리올리기")
# 넓게미리올리기(판, i, 원본, j) — 비동기복사16 과 같고, L2 가 그 자리부터 256 바이트를 한꺼번에 불러오게 한다(.L2::256B, PTX 7.4).
# 미리읽기용(버림칸에 복사): 요청 하나로 256 바이트가 L2 에 올라온다.
# 미리읽기(원본, j): 원본[j] 가 든 줄을 L2 캐시로 미리 불러 둔다(prefetch.global.L2). 값을 읽지도 바꾸지도 않는다 — 다음 커널이 읽을
# 가중치를 지금 커널의 끝에서 불러 두어 메모리가 쉬지 않게 하려고 쓴다.
PREFETCH = ("미리읽기",)
# 워프 셔플: 아래에서받기(v, s) = 같은 워프에서 레인 (내 레인 + s) 의 v (shfl.sync.down — 범위 밖이면 내 값), 레인에서받기(v, k) =
# 레인 k 의 v (shfl.sync.idx). 32 비트(짧은실수·중간정수)와 64 비트 정수(두 번에 나눠). 값은 그대로 옮겨질 뿐이다 — 워프 안의
# 나무 모양 덧셈을 공유 메모리·동기화 없이 하려고 쓴다. 워프의 32 레인이 모두 함께 불러야 한다.
SHUFFLE = ("아래에서받기", "레인에서받기", "정수아래에서받기", "정수레인에서받기")   # 정수판은 64 비트 정수용 이름(같은 명령)
# 격자 전체의 만남(메가커널용): 원자더하기(칸, i, v) = 칸[i] 에 v 를 원자적으로 더하고 그 전 값(atom.add.gpu, 64 비트 정수),
# 획득읽기(칸, i) = 칸[i] 를 다른 블록이 쓴 것까지 보이게 읽는다(ld.acquire.gpu), 울타리() = 앞의 쓰기가 GPU 전체에 보인 뒤에
# 나아간다(fence.acq_rel.gpu). 블록들이 모두 함께 올라 있어야(협력 실행) 기다리기가 끝난다.
GRID = ("원자더하기", "획득읽기", "울타리")
# 시각() = GPU 의 전역 시계(나노초, %globaltimer) — 재기 도구가 커널 안의 단계 시간을 보려고 쓴다. 값의 계산과는 상관없다.
CLOCK = ("시각",)
# 워프동기화() = 같은 워프의 32 레인이 여기까지 오고, 그 앞의 공유 메모리 쓰기가 서로 보인다(bar.warp.sync) — 워프 안에서만 주고받는
# 공유 메모리 칸에 블록 전체의 동기화를 쓰지 않으려고.
WARP = ("워프동기화",)
# 6단계 — 정수 텐서 코어(정확한 정수 곱합). 정수텐서곱(j, a₀, a₁, a₂, a₃, b₀, b₁, c₀, c₁, c₂, c₃) = 워프의 32 레인이 함께 하는
# 정수 행렬곱 D = A · B + C (m16n8k32: A 16 × 32, B 32 × 8, C · D 16 × 8 의 32 비트 정수) 에서 이 레인이 맡은 D 의 j 번째 칸.
# 레인 ℓ 의 g = ℓ / 4, t = ℓ % 4: aᵢ 는 바이트 넷(부호 있는 8 비트, 낮은 바이트가 먼저) — a₀ = A[g][4t … 4t+3], a₁ = A[g+8][4t …],
# a₂ = A[g][16+4t …], a₃ = A[g+8][16+4t …]; b₀ = B[4t … 4t+3][g], b₁ = B[16+4t …][g]; c · 결과 j = 0 … 3 은 D[g][2t], D[g][2t+1],
# D[g+8][2t], D[g+8][2t+1]. 곱과 합은 정수로 **정확하다**(반올림이 없다 — PTX 명세가 결과를 다 정한다. 2³² 를 넘지 않음은 쓰는 쪽이
# 보인다). 실수 텐서 코어(f16 · bf16 · tf32)는 합의 반올림을 명세가 정하지 않아 쓰지 않는다(PTX 계약). 넷(j = 0 … 3)을 같은 인자로
# 잇달아 부르면 명령 하나(mma.sync)가 되고, 그렇지 않은 꼴은 거부한다. _나부호없음 판은 B 의 바이트가 부호 없는 8 비트.
# 바이트넷곱더하기(a, b, c) = c + Σᵢ a 의 바이트 i × b 의 바이트 i (i < 4, 부호 있는 8 비트, 정확 — dp4a). _나부호없음: b 가 부호 없음.
# 실수비트(x) = 짧은실수 x 의 비트를 중간정수로, 비트실수(i) = 그 거꾸로 — 값을 바꾸지 않고 보는 법만 바꾼다(mov.b32).
TENSOR = ("정수텐서곱", "정수텐서곱_나부호없음")
BYTEDOT = ("바이트넷곱더하기", "바이트넷곱더하기_나부호없음")
# 바이트고르기(a, b, 선택자) = a · b 의 여덟 바이트(a 의 0~3, b 의 4~7)에서 선택자의 니블 i 가 고른 바이트를 결과의 바이트 i 로(prmt.b32 — 값을 바꾸지 않고
# 옮기기만, 9단계).
BITS = ("실수비트", "비트실수", "바이트고르기")
# 가까운정수(x) = 짧은실수 x 를 가장 가까운 정수로(같으면 짝수 — IEEE 의 roundToIntegralTiesToEven) 바꾼 중간정수(cvt.rni.s32.f32).
# 범위 [−2³¹, 2³¹) 밖이면(NaN 포함) 2c 처럼 오류 칸에 1.
ROUND = ("가까운정수",)
INTRINSICS = ("실행번호", "실행개수", "동기화", "곱해더하기", "근사지수", "제곱근", "큰쪽") + tuple(BLOCK_REGS) + tuple(SHARED) + ASYNC + \
    PREFETCH + SHUFFLE + GRID + CLOCK + WARP + TENSOR + BYTEDOT + BITS + ROUND


class PTXError(Exception):
    pass


def ptx_name(name):
    """PTX 식별자: 라틴 이름은 그대로, 그 밖은 _G + UTF-8 16진수."""
    ok = name and (name[0].isascii() and (name[0].isalpha() or name[0] == "_")) and \
        all(c.isascii() and (c.isalnum() or c == "_") for c in name)
    return name if ok else "_G" + name.encode("utf-8").hex()


def reg_type(t):
    """IR 타입 → PTX 레지스터 타입. 8·16비트 정수도 32비트 레지스터에 둔다. 반실수는 16비트 레지스터(.b16 — 값은 옮기고 바꾸기만)."""
    if t.is_float():
        return {16: ".b16", 32: ".f32"}.get(t.bits, ".f64")
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
        return {16: ".b16", 32: ".f32"}.get(t.bits, ".f64")
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
        self.addr_off = self.fold_offsets() if FOLD_OFFSETS else {}
        self.vst_last, self.vst_skip = {}, set()
        self.vec_lead, self.vec_skip = self.vector_loads() if (VECTOR_LOADS and FOLD_OFFSETS) else ({}, set())
        self._mma, self._ver, self._mma_n = None, {}, 0  # 6단계: 정수텐서곱 넷의 묶음(인자의 서명), 레지스터 변수마다 대입 횟수, mma 결과 레지스터의 다음 번호

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

    def fold_offsets(self):
        """3단계 성능: a[x + c] 의 상수 c 를 메모리 명령의 즉시 오프셋으로 접는다 — 주소 = (a + x·크기) + c·크기.
        색인 주소가 load/store 의 자리로만 쓰일 때만 접는다(값으로 새면 그 주소가 c 를 빠뜨리므로). 값은 그대로다."""
        insts = self.f.insts
        defs, ndef = {}, {}
        for i in insts:
            d = getattr(i, "dst", None)
            if d is not None:
                defs[d] = i
                ndef[d] = ndef.get(d, 0) + 1
        self.ndef = ndef
        one = lambda t: ndef.get(t, 0) == 1              # IR 의 임시값은 슬롯이라 여러 번 대입될 수 있다 — 하나뿐일 때만 믿는다
        uses = {}
        for i in insts:
            for fld in USE_FIELDS + ("args",):
                v = getattr(i, fld, None)
                for t in (v if isinstance(v, (list, tuple)) else [v]):
                    if t is not None:
                        uses.setdefault(t, []).append((i, fld))
        out = {}
        for i in insts:
            if i.op != "index_addr" or width(i.idx.type) != 64:
                continue
            if not all(u.op in ("load", "store") and fld == "addr" for u, fld in uses.get(i.dst, [])):
                continue
            d = defs.get(i.idx)
            if d is None or not one(i.idx) or d.op != "bin" or d.bop not in ("add", "sub") or not (one(d.a) and one(d.b)):
                continue
            ca, cb = defs.get(d.a), defs.get(d.b)
            if cb is not None and cb.op == "const":
                x, c = d.a, int(cb.value) if d.bop == "add" else -int(cb.value)
            elif ca is not None and ca.op == "const" and d.bop == "add":
                x, c = d.b, int(ca.value)
            else:
                continue
            off = c * i.size
            if -(1 << 23) <= off < (1 << 23):
                out[i.dst] = (x, off)
        return out

    def trailing_zeros(self):
        """3단계 성능: 정수 값이 2^k 의 배수임을 증명한다(k = 끝의 0 비트 수). 근거는 상수와 연산의 규칙뿐 — 매개변수·메모리에서
        읽은 값·스레드 번호는 0 (모름). 변수는 모든 대입의 최솟값(흐름을 보지 않는다), 줄어들기만 하므로 끝난다."""
        insts = self.f.insts
        ivars = {v for v in self.regvar if v.type.is_int()}
        params = {sym for sym, _ in self.f.params}
        tzv = {v: (0 if v in params else 64) for v in ivars}
        tz = {}
        ctz = lambda c: 64 if c == 0 else ((c & -c).bit_length() - 1)
        T = lambda t: tz.get(t, 64)                      # 아직 구하지 않은 값은 위(64)에서 시작해 내려온다 — 가장 큰 고정점
        for _ in range(200):
            changed = False
            new = {}
            for i in insts:
                d = getattr(i, "dst", None)
                if d is None or not d.type.is_int():
                    continue
                op = i.op
                if op == "const":
                    r = ctz(int(i.value) & ((1 << 64) - 1))
                elif op == "load" and self.addr_of.get(i.addr) in tzv:
                    r = tzv[self.addr_of[i.addr]]
                elif op == "copy" and i.src.type.is_int():
                    r = T(i.src)
                elif op == "cast" and i.kind in ("sext", "zext", "trunc") and i.src.type.is_int():
                    r = min(T(i.src), width(d.type))
                elif op == "bin":
                    a, b = T(i.a), T(i.b)
                    if i.bop in ("add", "sub", "or", "xor"):
                        r = min(a, b)
                    elif i.bop == "mul":
                        r = min(64, a + b)
                    elif i.bop == "and":
                        r = max(a, b)
                    elif i.bop == "shl" and self.defs_c.get(i.b) is not None:
                        r = min(64, a + self.defs_c[i.b])
                    else:
                        r = 0
                else:
                    r = 0
                new[d] = min(new.get(d, 64), r)             # 여러 번 대입되는 임시값은 모든 대입의 최솟값
            for t, r in new.items():
                if tz.get(t) != r:
                    tz[t] = r
                    changed = True
            for i in insts:
                if i.op == "store" and self.addr_of.get(i.addr) in tzv:
                    v = self.addr_of[i.addr]
                    r = min(tzv[v], tz.get(i.src, 0) if i.src.type.is_int() else 0)
                    if r != tzv[v]:
                        tzv[v] = r
                        changed = True
            if not changed:
                break
        self.tzv = tzv
        return tz

    def vector_loads(self):
        """3단계 성능: 같은 기본 블록에서 a[x+c], a[x+c+1], a[x+c+2], a[x+c+3] 을 차례로 읽는 짧은실수 넷을 ld.shared.v4 하나로 낸다.
        조건 — a 는 공유 메모리 판의 시작(16 바이트 정렬), x 는 4 의 배수(증명), c 는 4 의 배수, 넷 사이에 메모리 쓰기·동기화·호출이
        없다. 값은 그대로다(같은 네 칸을 한 명령으로 읽을 뿐)."""
        insts = self.f.insts
        consts = {i.dst: int(i.value) for i in insts if i.op == "const" and self.ndef.get(i.dst) == 1}
        self.defs_c = consts
        tz = self.trailing_zeros()
        defs = {i.dst: i for i in insts if getattr(i, "dst", None) is not None}
        lead, skip = {}, set()
        # 함수 전체에서 한 번만 대입되는 포인터 변수가 공유 메모리 내장의 값이면, 어느 블록에서 읽어도 그 판의 시작이다
        calls = {i.dst: i.callee for i in insts if i.op == "call" and i.extern and i.callee in SHARED
                 and getattr(i, "dst", None) is not None}
        stores = {}
        for i in insts:
            if i.op == "store" and self.addr_of.get(i.addr) in self.regvar:
                stores.setdefault(self.addr_of[i.addr], []).append(i)
        fixed = {v: ("판", calls[st[0].src]) for v, st in stores.items() if len(st) == 1 and st[0].src in calls}
        # 6단계: 정수 텐서 코어를 쓰는 함수에서는 매개변수를 먼저 넣어, 매개변수를 다른 원소 타입으로 본 변수도 아래에서 판이 된다
        # (이전 모듈의 PTX 는 그대로다)
        if VECTOR_GLOBAL and any(i.op == "call" and i.extern and i.callee in TENSOR for i in insts):
            for v in self.global_params:
                if v not in stores:
                    fixed[v] = ("판", ("매개", v.name))
        # 6단계: 판을 다른 원소 타입으로 본 변수(`판 으로 중간정수 참조` — 복사 하나)도 같은 판의 시작이다
        defs1 = {i.dst: i for i in insts if getattr(i, "dst", None) is not None and self.ndef.get(i.dst) == 1}
        for v, st in stores.items():
            if v in fixed or len(st) != 1:
                continue
            c = defs1.get(st[0].src)
            u = defs1.get(c.src) if c is not None and c.op == "copy" else None
            if u is not None and u.op == "load" and self.addr_of.get(u.addr) in fixed:
                fixed[v] = fixed[self.addr_of[u.addr]]
        # 커널의 참조 매개변수는 16 바이트 정렬이다(호스트의 약속 — 글gpt2.py 가 띄울 때 확인한다). 다시 대입되지 않는 매개변수만.
        if VECTOR_GLOBAL:
            for v in self.global_params:
                if v not in stores:
                    fixed[v] = ("판", ("매개", v.name))
        version = {}                                      # 레지스터 변수 -> 이 블록에서의 판
        key = {}                                          # 임시값 -> 값의 열쇠 (같은 블록 안에서)
        run = []                                          # 지금 이어지는 후보 (load 명령, 열쇠, 바이트 오프셋)
        srun = []                                         # 쓰기 쪽 후보 (store 명령, 열쇠, 바이트 오프셋)
        self.vst_last, self.vst_skip = {}, set()

        def sflush():
            # 네 칸 묶어 쓰기: 같은 판·같은 x 에 오프셋 c, c+4, c+8, c+12 로 차례로 쓰는 넷 — 넷째 자리에서 st.v4 하나로 낸다
            # (그 사이에 메모리 읽기·쓰기가 없으니 늦춰 써도 같다)
            k = 0
            while k + 4 <= len(srun):
                (i0, k0, o0) = srun[k]
                ok = o0 % 16 == 0 and all(srun[k + e][1] == k0 and srun[k + e][2] == o0 + 4 * e for e in range(1, 4))
                if ok:
                    self.vst_last[srun[k + 3][0]] = (i0.addr, [srun[k + e][0].src for e in range(4)])
                    for e in range(3):
                        self.vst_skip.add(srun[k + e][0])
                    k += 4
                else:
                    k += 1
            srun.clear()

        # 6단계: 정수 텐서 코어를 쓰는 함수에서는 4 바이트 둘(8 바이트, x 는 짝수)도 묶는다 — 이전 모듈의 PTX 는 그대로다
        pair32 = any(i.op == "call" and i.extern and i.callee in TENSOR for i in insts)

        def flush():
            # 짧은실수: 넷(16 바이트, x 는 4 의 배수). 반실수(4단계 2): 넷(8 바이트, x 는 4 의 배수) 또는 둘(4 바이트, x 는 짝수)
            k = 0
            while k < len(run):
                (i0, k0, o0, sz, tzx) = run[k]
                for n in ((4, 2) if sz == 2 or pair32 else (4,)):
                    if k + n <= len(run) and tzx >= (2 if n == 4 else 1) and o0 % (n * sz) == 0 and \
                            all(run[k + e][1] == k0 and run[k + e][2] == o0 + sz * e and run[k + e][3] == sz for e in range(1, n)):
                        lead[i0] = [run[k + e][0].dst for e in range(n)]
                        for e in range(1, n):
                            skip.add(run[k + e][0])
                        k += n
                        break
                else:
                    k += 1
            run.clear()

        def store_key(i):
            if not (i.src.type.is_float() and i.src.type.bits == 32 and self.mem(i.addr) in (".shared", ".global")):
                return None
            ia = defs.get(i.addr)
            if ia is None or ia.op != "index_addr" or ia.size != 4 or self.ndef.get(i.addr) != 1:
                return None
            x, off = self.addr_off.get(i.addr, (ia.idx, 0))
            bk = key.get(ia.base)
            if bk is None or bk[0] != "판" or x not in key or tz.get(x, 0) < 2:
                return None
            return (bk, key[x]), off

        for i in insts:
            op = i.op
            memstore = op == "store" and self.addr_of.get(i.addr) not in self.regvar
            if memstore:
                flush()
                sk = store_key(i)
                if sk is None:
                    sflush()
                else:
                    srun.append((i, sk[0], sk[1]))
                continue
            if op in ("label", "jmp", "br", "ret", "call", "copy_mem", "swap"):
                flush()
                sflush()
                if op in ("label", "jmp", "br", "ret"):
                    version.clear()
                    key.clear()
                if op == "call" and getattr(i, "dst", None) is not None and i.extern and i.callee in SHARED:
                    key[i.dst] = ("판", i.callee)
                continue
            if op == "store":                              # 레지스터 변수에 대입 — 판이 바뀐다
                v = self.addr_of[i.addr]
                version[v] = version.get(v, 0) + 1
                if i.src in key and v.type.is_ptr():
                    key[("var", v, version[v])] = key[i.src]
                continue
            d = getattr(i, "dst", None)
            if d is None:
                continue
            if op == "load" and self.addr_of.get(i.addr) in self.regvar:
                v = self.addr_of[i.addr]
                vk = ("var", v, version.get(v, 0))
                key[d] = fixed[v] if v in fixed else key.get(vk, vk)
            elif op == "const" and self.ndef.get(d) == 1:
                key[d] = ("c", int(i.value))
            elif op == "bin" and i.a in key and i.b in key:
                key[d] = (i.bop, key[i.a], key[i.b])
            elif op == "copy" and i.src in key:
                key[d] = key[i.src]
            elif op == "load" and self.addr_of.get(i.addr) not in self.regvar and (sflush() or True) and \
                    self.mem(i.addr) in (".shared", ".global") and \
                    ((d.type.is_float() and d.type.bits in (16, 32)) or (d.type.is_int() and d.type.bits == 32)):
                sz = d.type.bits // 8
                ia = defs.get(i.addr)
                if ia is None or ia.op != "index_addr" or ia.size != sz or self.ndef.get(i.addr) != 1:
                    flush()
                    continue
                x, off = self.addr_off.get(i.addr, (ia.idx, 0))
                bk = key.get(ia.base)
                if bk is None or bk[0] != "판" or x not in key or tz.get(x, 0) < (2 if sz == 4 and not pair32 else 1):
                    flush()
                    continue
                run.append((i, (bk, key[x]), off, sz, tz.get(x, 0)))
            else:
                key.pop(d, None)
        flush()
        sflush()
        return lead, skip

    def split_const(self, t):
        """t 가 (x + 상수) 또는 (상수 + x) 로 한 번만 대입됐으면 (x, 상수), 아니면 (t, 0). x 도 한 번만 대입된 것이어야 한다."""
        d = None
        for i in self.f.insts:
            if getattr(i, "dst", None) is t:
                if d is not None:
                    return t, 0
                d = i
        if d is None or d.op != "bin" or d.bop != "add" or self.ndef.get(d.a) != 1 or self.ndef.get(d.b) != 1:
            return t, 0
        for x, c in ((d.a, d.b), (d.b, d.a)):
            cv = self.const_of(c)
            if cv is not None and -(1 << 20) <= cv < (1 << 20):
                return x, cv
        return t, 0

    def const_of(self, t):
        """임시값이 한 번만 대입된 정수 상수면 그 값."""
        for i in self.f.insts:
            if getattr(i, "dst", None) is t:
                if i.op == "const":
                    return int(i.value)
                if i.op == "cast" and i.kind in ("sext", "zext", "trunc"):
                    return self.const_of(i.src)
                return None
        return None

    def at(self, addr):
        """메모리 명령의 주소 자리: 접은 상수가 있으면 [reg+off]."""
        x = self.addr_off.get(addr)
        if x is None or x[1] == 0:
            return f"[{self.r(addr)}]"
        return f"[{self.r(addr)}+{x[1]}]"                 # 음수는 [reg+-n] (PTX 의 꼴)

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
        bounds = LAUNCH_BOUNDS.get(f.name)
        out = [f"// kernel: {ptx_name(f.name)}", f".visible .entry {ptx_name(f.name)}(", ",\n".join(params), ")"]
        if bounds:                             # 실행한도: 드라이버 컴파일러가 레지스터 수를 이 블록 수에 맞춘다
            out += [f".maxntid {bounds[0]}, 1, 1", f".minnctapersm {bounds[1]}"]
        out.append("{")
        if self.depot:
            out.append(f"    .local .align 8 .b8 __depot[{self.depot}];")
        out.append("    .reg .u64 %SPL, %SP;")
        out.append("    .reg .pred %p, %q;")
        out.append("    .reg .u32 %x<4>;")
        out.append("    .reg .u64 %X<3>;")
        out.append("    .reg .b32 %w<3>;")
        out.append("    .reg .f32 %fw<2>;")
        n_mma = sum(1 for i in f.insts if i.op == "call" and i.extern and i.callee in TENSOR)
        if n_mma:                                  # mma 마다 제 결과 레지스터 넷 — 같은 레지스터를 돌려 쓰면 mma 끼리 기다린다
            out.append(f"    .reg .b32 %m<{n_mma + 4}>;")
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
        if op in ("label", "jmp", "br", "ret"):        # 정수텐서곱 넷의 묶음은 기본 블록을 넘지 않는다
            self._mma = None
        if op == "store" and self.addr_of.get(i.addr) in self.regvar:
            v = self.addr_of[i.addr]
            self._ver[v] = self._ver.get(v, 0) + 1
        if op == "label":
            self.lines.append(f"{self.label(i.name)}:")
        elif op == "const":
            t = i.dst.type
            bits = width(t)
            e(f"mov.b{bits} {self.r(i.dst)}, {int(i.value) & ((1 << bits) - 1):#x};")
        elif op == "fconst":
            if i.dst.type.bits == 16:              # 앞단이 리터럴을 반실수로 두지 않는다(좁히기는 밝힌다)
                raise PTXError("반실수 상수는 받지 않는다 — '으로 반실수' 로 밝혀라")
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
            elif i in self.vec_lead:                   # 네 칸(반실수는 둘·넷) 묶어 읽기
                regs = ", ".join(self.r(t) for t in self.vec_lead[i])
                e(f"ld{self.mem(i.addr)}.v{len(self.vec_lead[i])}{mem_type(i.dst.type)} {{{regs}}}, {self.at(i.addr)};")
            elif i in self.vec_skip:                   # 앞의 묶음이 이미 읽었다
                pass
            else:
                e(f"ld{self.mem(i.addr)}{mem_type(i.dst.type)} {self.r(i.dst)}, {self.at(i.addr)};")
        elif op == "store":
            var = self.addr_of.get(i.addr)
            if var in self.regvar:
                e(f"mov{reg_type(var.type)} {self.regvar[var]}, {self.r(i.src)};")
            elif i in self.vst_skip:                   # 넷째 쓰기 자리에서 함께 쓴다
                pass
            elif i in self.vst_last:                   # 네 칸 묶어 쓰기
                a0, srcs = self.vst_last[i]
                e(f"st{self.mem(a0)}.v4{mem_type(i.type)} {self.at(a0)}, {{{', '.join(self.r(t) for t in srcs)}}};")
            else:
                e(f"st{self.mem(i.addr)}{mem_type(i.type)} {self.at(i.addr)}, {self.r(i.src)};")
        elif op == "gep":
            e(f"add.s64 {self.r(i.dst)}, {self.r(i.base)}, {i.offset};")
        elif op == "index_addr":
            idx = self.r(i.idx)
            if i.dst in self.addr_off:                 # 상수는 메모리 명령의 오프셋으로 — 여기서는 a + x·크기
                idx = self.r(self.addr_off[i.dst][0])
            elif width(i.idx.type) == 32:
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

    def byte_field(self, i):
        """5단계: 정수 → 짧은실수 변환 i 의 값이 ((w >> s) & m) − c 의 꼴인가 — m 은 255(바이트, s ∈ {0, 8, 16, 24}) 또는
        15(니블, s ∈ {0, 4, …, 28}), s · c 는 상수, w 는 32 비트 정수, 값의 범위는 2e 가 [−2²², 2²²) 로 증명. 사슬(빼기 · 그리고 ·
        밀기 · 넓히기)의 임시값은 모두 한 번만 대입되고 i 와 같은 기본 블록 안에서 i 앞에 있어야 한다(그래서 w 의 레지스터가 그때의
        값 그대로다). 맞으면 (w 의 레지스터, s, m, c), 아니면 None."""
        defs, ndef = getattr(self, "defs", None), getattr(self, "ndef", None)
        r = self.rng.get(i.src)
        if not defs or ndef is None or r is None or not (-(1 << 22) <= r[0] and r[1] < (1 << 22)):
            return None
        if not hasattr(self, "_blk"):                      # 명령마다 그 기본 블록의 첫 자리
            self._pos, self._blk, b = {}, [], 0
            for k, x in enumerate(self.f.insts):
                if x.op == "label":
                    b = k
                self._pos[id(x)] = k
                self._blk.append(b)
                if x.op in ("jmp", "br", "ret"):
                    b = k + 1
        one = lambda t: ndef.get(t, 0) == 1

        def const(t):
            d = defs.get(t)
            if d is None or not one(t):
                return None
            if d.op == "const":
                return int(d.value)
            if d.op == "cast" and d.kind in ("sext", "zext", "trunc") and d.src.type.is_int():
                return const(d.src)
            return None
        chain = []
        t = i.src
        d = defs.get(t)
        if d is not None and one(t) and d.op == "cast" and d.kind in ("sext", "zext") and d.src.type.is_int():
            chain.append(d)
            t, d = d.src, defs.get(d.src)
        if d is None or not one(t) or d.op != "bin" or d.bop != "sub" or const(d.b) is None:
            return None
        c = const(d.b)
        chain.append(d)
        t, d = d.a, defs.get(d.a)
        if d is None or not one(t) or d.op != "bin" or d.bop != "and":
            return None
        m, x = const(d.b), d.a
        if m is None:
            m, x = const(d.a), d.b
        if m not in (255, 15):
            return None
        chain.append(d)
        t, d, s = x, defs.get(x), 0
        if d is not None and one(t) and d.op == "bin" and d.bop in ("ashr", "lshr") and const(d.b) is not None:
            s = const(d.b)
            chain.append(d)
            t = d.a
        if not (t.type.is_int() and width(t.type) == 32 and one(t) and -(1 << 20) <= c <= (1 << 20)):
            return None
        if (m == 255 and (s % 8 or not 0 <= s <= 24)) or (m == 15 and (s % 4 or not 0 <= s <= 28)):
            return None
        k = self._pos.get(id(i))
        if k is None or any(self._pos.get(id(x), k) > k or self._blk[self._pos[id(x)]] != self._blk[k] for x in chain):
            return None
        return self.r(t), s, m, c

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
        elif k in ("sitofp", "uitofp", "fptosi", "fptoui") and ((dt.is_float() and dt.bits == 16) or (st.is_float() and st.bits == 16)):
            raise PTXError("정수와 반실수 사이의 변환은 아직 받지 않는다 — 짧은실수를 거쳐 밝혀라")
        elif k in ("sitofp", "uitofp") and dt.bits == 32 and (bf := self.byte_field(i)) is not None:
            # 5단계: 값이 ((w >> s) & 255) − c 또는 ((w >> s) & 15) − c (32 비트 w, 상수 s · c, 범위가 증명됨)면 바이트를 실수
            # 12582912 의 비트 아래 8 비트에 바로 끼운다(prmt 하나 — 그 실수는 12582912 + 바이트), 그다음 (12582912 + c) 를 뺀다 —
            # 결과는 바이트 − c 정확히(두 수가 두 배 안이라 뺄셈이 정확하다). 4 비트는 낱말의 니블들을 바이트마다 하나씩 모은 뒤(and ·
            # shr — 같은 낱말의 니블끼리 같은 식이라 ptxas 가 한 번만 계산한다) 같은 길. 위의 빠른 변환, 느린 변환과 비트까지 같다.
            w, s, m, c = bf
            src = w
            if m == 15:
                if s % 8:
                    e(f"shr.u32 %x2, {w}, 4;")
                    e("and.b32 %x2, %x2, 0x0F0F0F0F;")
                else:
                    e(f"and.b32 %x2, {w}, 0x0F0F0F0F;")
                src = "%x2"
            e("mov.b32 %x3, 0x4B400000;")
            e(f"prmt.b32 %x1, {src}, %x3, {0x7650 | (s // 8)};")
            e("mov.b32 %fw0, %x1;")
            e(f"sub.rn.f32 {d}, %fw0, {flit(12582912.0 + c, dt)};")
        elif k in ("sitofp", "uitofp") and dt.bits == 32 and self.rng.get(i.src) is not None and \
                -(1 << 22) <= self.rng[i.src][0] and self.rng[i.src][1] < (1 << 22):
            # 5단계: 범위가 증명된 작은 정수(|x| < 2²²)는 같은 값을 빠른 명령으로 — 실수 12582912 의 비트에 x 를 더하면 그 실수는
            # 12582912 + x (가수의 한 칸이 1), 빼면 x 가 정확히 남는다. 느린 변환(cvt.rn.f32.s64)과 비트까지 같다. 양자 가중치를 푸는
            # ((q >> s) & 15) − 8 같은 값의 범위를 2e 의 구간 해석이 증명한다.
            e(f"cvt.u32.u64 %x1, {s};" if width(st) == 64 else f"mov.b32 %x1, {s};")
            e("add.u32 %x1, %x1, 0x4B400000;")
            e("mov.b32 %fw0, %x1;")
            e(f"sub.rn.f32 {d}, %fw0, 0f4B400000;")
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
        elif k == "fpext" and st.bits == 16:     # 반실수 → 짧은실수·실수: 정확하다
            e(f"cvt{'.f32' if dt.bits == 32 else '.f64'}.f16 {d}, {s};")
        elif k == "fpext":
            e(f"cvt.f64.f32 {d}, {s};")
        elif k == "fptrunc" and dt.bits == 16:
            if st.bits != 32:
                raise PTXError("실수 → 반실수 는 아직 받지 않는다 — 짧은실수를 거쳐 밝혀라(반올림이 두 번이 된다)")
            e(f"cvt.rn.f16.f32 {d}, {s};")         # 가까운 쪽(같으면 짝수), 비정규수 그대로 (.ftz 없음 — PTX 계약 P2)
            if RANGE_CHECK:            # 4단계 2: 유한한 짧은실수가 반실수로 오며 무한이 되면 오류 칸에 4
                e(f"cvt.f32.f16 %fw1, {d};")
                e("testp.infinite.f32 %q, %fw1;")
                e(f"testp.finite.f32 %p, {s};")
                e("and.pred %q, %q, %p;")
                e("@%q red.global.or.b32 [__geul_err], 4;")
        elif k == "fptrunc":
            e(f"cvt.rn.f32.f64 {d}, {s};")
            if RANGE_CHECK:            # 2c: 유한한 실수가 짧은실수로 오며 무한이 되면 오류 칸에 2
                e(f"testp.infinite.f32 %q, {d};")
                e(f"testp.finite.f64 %p, {s};")
                e("and.pred %q, %q, %p;")
                e("@%q red.global.or.b32 [__geul_err], 2;")
        else:
            raise PTXError(f"PTX 탐침이 아직 받지 않는 변환 '{k}'")

    def one_const(self, t):
        """한 번만 대입된 정수 상수면 그 값(넓히기 · 좁히기를 거쳐도) — defs 로 바로 찾는다."""
        d = self.defs.get(t) if getattr(self, "defs", None) else None
        if d is None or self.ndef.get(t) != 1:
            return None
        if d.op == "const":
            return int(d.value)
        if d.op == "cast" and d.kind in ("sext", "zext", "trunc") and d.src.type.is_int():
            return self.one_const(d.src)
        return None

    def arg_sig(self, t):
        """6단계: 내장 인자의 '같음' 서명 — 레지스터 변수에서 읽은 임시값은 (변수, 그때까지의 대입 횟수), 상수는 값, 그 밖은 임시값 자체."""
        d = self.defs.get(t) if getattr(self, "defs", None) else None
        if d is not None and self.ndef.get(t) == 1:
            if d.op == "load" and self.addr_of.get(d.addr) in self.regvar:
                v = self.addr_of[d.addr]
                return ("v", id(v), self._ver.get(v, 0))
            if d.op == "const":
                return ("c", int(d.value))
        return ("t", id(t))

    def call(self, i):
        name = i.callee if isinstance(i.callee, str) else None
        if not (i.extern and name in INTRINSICS):
            raise PTXError(f"'{self.f.name}': 함수 호출은 아직 받지 않는다 (GPU 내장 {', '.join(INTRINSICS)} 만): {name}")
        e = self.emit
        if name == "동기화":          # 블록 안의 모든 스레드가 여기까지 오고, 그 앞의 공유 메모리 쓰기가 보인다
            e("bar.sync 0;")
            return
        if name == "워프동기화":
            e("bar.warp.sync -1;")
            return
        if name in ("비동기복사", "비동기복사16", "넓게미리올리기"):   # 판[i] ← 원본[j]. 공유 주소는 32 비트로, 전역 주소는 전역 공간의 것
            sp, si, gp, gi = i.args
            (xs, cs), (xg, cg) = self.split_const(si), self.split_const(gi)     # i = x + c 면 c 는 주소의 즉시 오프셋으로
            e(f"mad.lo.s64 %X1, {self.r(xs)}, 4, {self.r(sp)};")
            e("cvt.u32.u64 %x1, %X1;")
            e(f"mad.lo.s64 %X2, {self.r(xg)}, 4, {self.r(gp)};")
            if name == "비동기복사":
                e(f"cp.async.ca.shared.global [%x1+{4 * cs}], [%X2+{4 * cg}], 4;")
            elif name == "비동기복사16":
                e(f"cp.async.cg.shared.global [%x1+{4 * cs}], [%X2+{4 * cg}], 16;")
            else:
                e(f"cp.async.cg.shared.global.L2::256B [%x1+{4 * cs}], [%X2+{4 * cg}], 16;")
            return
        if name == "울타리":
            e("fence.acq_rel.gpu;")
            return
        if name == "미리읽기":
            gp, gi = i.args
            xg, cg = self.split_const(gi)
            e(f"mad.lo.s64 %X2, {self.r(xg)}, 4, {self.r(gp)};")
            e(f"prefetch.global.L2 [%X2+{4 * cg}];")
            return
        if name == "비동기묶기":
            e("cp.async.commit_group;")
            return
        if name == "비동기기다리기":
            d0 = self.const_of(i.args[0])
            if d0 is None or d0 < 0:
                raise PTXError("비동기기다리기 의 인자는 0 이상의 상수여야 한다")
            e(f"cp.async.wait_group {d0};")
            return
        if i.dst is None:
            raise PTXError(f"GPU 내장 '{name}' 의 값을 쓰지 않았다")
        d = self.r(i.dst)
        if name in TENSOR:
            # 넷(j = 0 … 3)을 같은 인자로 잇달아 — j = 0 에서 mma 하나를 내고 결과 넷을 %m0 … %m3 에 둔다. 인자의 같음은 "같은 레지스터
            # 변수를 그 사이에 대입하지 않고 읽은 것"(또는 같은 임시값 · 같은 상수)으로 본다. 아니면 거부(조용히 틀리지 않게).
            j = self.one_const(i.args[0])
            if j not in (0, 1, 2, 3) or len(i.args) != 11 or i.dst.type.bits != 32:
                raise PTXError(f"{name}(j, a₀ … a₃, b₀, b₁, c₀ … c₃) — j 는 상수 0 … 3, 값은 중간정수")
            sig = (name,) + tuple(self.arg_sig(a) for a in i.args[1:])
            if j == 0:
                a = ", ".join(self.r(x) for x in i.args[1:5])
                b = ", ".join(self.r(x) for x in i.args[5:7])
                c = ", ".join(self.r(x) for x in i.args[7:11])
                bt = ".u8" if name.endswith("나부호없음") else ".s8"
                k = self._mma_n
                self._mma_n += 4
                e(f"mma.sync.aligned.m16n8k32.row.col.s32.s8{bt}.s32 {{%m{k}, %m{k + 1}, %m{k + 2}, %m{k + 3}}}, {{{a}}}, {{{b}}}, {{{c}}};")
                self._mma = [sig, 0, k]
            elif self._mma is None or self._mma[0] != sig or self._mma[1] != j - 1:
                raise PTXError(f"{name} 의 j = {j} 는 같은 인자로 부른 j = {j - 1} 바로 뒤에 와야 한다(같은 기본 블록, 그 사이에 인자 변수를 바꾸지 않음)")
            else:
                self._mma[1] = j
            e(f"mov.b32 {d}, %m{self._mma[2] + j};")
            return
        if name in BYTEDOT:
            bt = ".u32" if name.endswith("나부호없음") else ".s32"
            x, y, z = (self.r(a) for a in i.args)
            e(f"dp4a.s32{bt} {d}, {x}, {y}, {z};")
            return
        if name == "실수비트":
            e(f"mov.b32 {d}, {self.r(i.args[0])};")
            return
        if name == "가까운정수":
            x = self.r(i.args[0])
            if i.args[0].type.bits != 32 or i.dst.type.bits != 32:
                raise PTXError("가까운정수 는 짧은실수 → 중간정수만 받는다")
            if RANGE_CHECK:
                e(f"setp.ge.f32 %q, {x}, 0fCF000000;")
                e(f"setp.lt.and.f32 %q, {x}, 0f4F000000, %q;")
                e("@!%q red.global.or.b32 [__geul_err], 1;")
            e(f"cvt.rni.s32.f32 {d}, {x};")
            return
        if name == "비트실수":
            e(f"mov.b32 {d}, {self.r(i.args[0])};")
            return
        if name == "바이트고르기":
            a, b, c = (self.r(x) for x in i.args)
            e(f"prmt.b32 {d}, {a}, {b}, {c};")
            return
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
        elif name == "시각":
            e(f"mov.u64 {d}, %globaltimer;")
        elif name == "원자더하기":
            gp, gi, v = i.args
            if width(i.dst.type) != 64:
                raise PTXError("원자더하기는 정수(64 비트)만 받는다")
            e(f"mad.lo.s64 %X2, {self.r(gi)}, 8, {self.r(gp)};")
            e(f"atom.add.gpu.global.u64 {d}, [%X2], {self.r(v)};")
        elif name == "획득읽기":
            gp, gi = i.args
            if width(i.dst.type) != 64:
                raise PTXError("획득읽기는 정수(64 비트)만 받는다")
            e(f"mad.lo.s64 %X2, {self.r(gi)}, 8, {self.r(gp)};")
            e(f"ld.acquire.gpu.global.u64 {d}, [%X2];")
        elif name in SHUFFLE:
            v, k = i.args
            mode = "down" if name.endswith("아래에서받기") else "idx"
            e(f"cvt.u32.u64 %x2, {self.r(k)};")
            t = i.dst.type
            if width(t) == 64:
                e(f"mov.b64 {{%w0, %w1}}, {self.r(v)};")
                e(f"shfl.sync.{mode}.b32 %w0, %w0, %x2, 31, -1;")
                e(f"shfl.sync.{mode}.b32 %w1, %w1, %x2, 31, -1;")
                e(f"mov.b64 {d}, {{%w0, %w1}};")
            else:
                e(f"shfl.sync.{mode}.b32 {d}, {self.r(v)}, %x2, 31, -1;")
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
    # 3단계 성능: 소스의 주석 `(* 실행한도 이름 스레드수 블록수 *)` — 그 커널을 블록당 그 스레드 수 이하로만 띄우고 SM 하나에
    # 블록을 그만큼 올리겠다는 약속(PTX .maxntid·.minnctapersm). 드라이버 컴파일러가 레지스터 수를 거기에 맞춘다. 값과는 상관없다.
    LAUNCH_BOUNDS.clear()
    pat = r"\(\*\s*실행한도\s+(\S+)\s+(\d+)\s+(\d+)\s*\*\)"
    for name, nt, nb in re.findall(pat, open(src, encoding="utf-8").read()):
        LAUNCH_BOUNDS[name] = (int(nt), int(nb))
    research.enable()                 # 연구 옵션의 언어 확장(반실수) — 1.x 의 geulc.py 는 켜지 않는다
    program = load_program(src, os.path.join(ROOT, "표준"), auto_std=False)
    unit = sema.analyze(program, fragment=True)
    ir = inline.run(lower.lower_program(unit))
    kernels = [f for f in ir.functions if f.ret is None]
    if not kernels:
        raise PTXError("커널이 없다 — 반환값이 없는 함수가 커널이 된다")
    # cp.async(비동기복사)는 sm_80 부터 — 쓰는 커널이 있을 때만 대상을 올린다
    uses_async = any(i.op == "call" and i.extern and i.callee in ASYNC + GRID + TENSOR + BYTEDOT for f in kernels for i in f.insts)
    # 반실수(4단계 2)를 쓰는 모듈만 머리의 설명이 길어진다 — 짧은실수만 쓰는 모듈의 PTX 는 예전과 바이트까지 같다
    uses_half = any(getattr(t, "type", None) is not None and t.type.is_float() and t.type.bits == 16 for f in kernels for t in f.temps)
    head = ["//", "// geul -> PTX probe (research/gpu/geulptx). ASCII only: Korean names are mangled as _G + UTF-8 hex.", "//",
            ".version 7.4" if uses_async else ".version 7.0", ".target sm_80" if uses_async else ".target sm_52",
            ".address_size 64", "",
            "// 2c: range-check error cell (bit 1: float->int out of range, bit 2: float64->float32 overflow" +
            (", bit 4: float32->half overflow)" if uses_half else ")"),
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
