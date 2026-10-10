"""상수 나눗셈의 낮추기(글ptx.py 의 const_div 와 같은 명령 차례)를 64 비트 2 의 보수로 흉내 내어 div · rem(0 쪽으로 자름)과 대조.
나누는 수: 2 … 5000 전부 + 큰 것들, 나뉘는 수: 끝값 · 배수 ± 1 · 무작위."""
import random
import sys
sys.stdout.reconfigure(encoding="utf-8")
M64 = (1 << 64) - 1


def s64(x):
    x &= M64
    return x - (1 << 64) if x >> 63 else x


def magic_s64(d):
    """Hacker's Delight 그림 10-1 의 64 비트 판(d ≥ 2) — (M 부호없는 64 비트, s)."""
    two63 = 1 << 63
    ad = d
    t = two63
    anc = t - 1 - t % ad
    p = 63
    q1, r1 = two63 // anc, two63 - (two63 // anc) * anc
    q2, r2 = two63 // ad, two63 - (two63 // ad) * ad
    while True:
        p += 1
        q1, r1 = 2 * q1, 2 * r1
        if r1 >= anc:
            q1, r1 = q1 + 1, r1 - anc
        q2, r2 = 2 * q2, 2 * r2
        if r2 >= ad:
            q2, r2 = q2 + 1, r2 - ad
        assert q1 <= M64 and q2 <= M64 and r1 <= M64 and r2 <= M64
        delta = ad - r2
        if not (q1 < delta or (q1 == delta and r1 == 0)):
            break
    return (q2 + 1) & M64, p - 64


def lower(n, c, div, nonneg):
    """const_div 의 명령 차례(부호 있는 판)."""
    k = c.bit_length() - 1
    if c == 1 << k:
        if nonneg:
            return (n & M64) >> k if div else n & (c - 1)
        x1 = s64(n) >> 63                      # shr.s64 63
        x1 = (x1 & M64) >> (64 - k)            # shr.u64 64-k
        x1 = s64(n + x1)                       # add.s64
        if div:
            return x1 >> k                     # shr.s64
        x1 = s64(x1 & ((-c) & M64))            # and.b64 마스크
        return s64(n - x1)
    M, s = magic_s64(c)
    Ms = s64(M)
    x1 = (n * Ms) >> 64                        # mul.hi.s64
    if M >> 63:
        x1 = s64(x1 + n)                       # add.s64
    if s:
        x1 = x1 >> s                           # shr.s64
    if not nonneg:
        x1 = s64(x1 + ((n & M64) >> 63))       # shr.u64 63 + add
    if div:
        return x1
    return s64(n - s64(x1 * c))                # mul.lo + sub


def ref(n, c, div):
    q = abs(n) // c
    q = -q if n < 0 else q
    return q if div else n - q * c


rng = random.Random(12)
cs = list(range(2, 5001)) + [50257, 102400, 131072, 1 << 20, 3 * 768, 4800, 6400, (1 << 31) - 1, 1 << 31, (1 << 31) + 1,
                             (1 << 40) + 7, (1 << 61) + 1, (1 << 62) - 1, 1 << 62]
틀림 = 0
시험 = 0
for c in cs:
    ns = [0, 1, -1, 2, -2, (1 << 63) - 1, -(1 << 63), -(1 << 63) + 1, (1 << 62), -(1 << 62), (1 << 31), -(1 << 31), (1 << 32) - 1]
    for base in (c, 2 * c, 1000 * c, (((1 << 62) // c) * c), (((1 << 63) - 1) // c) * c):
        for dlt in (-1, 0, 1):
            ns += [base + dlt, -(base + dlt)]
    ns += [rng.randrange(-(1 << 63), 1 << 63) for _ in range(300)]
    ns += [rng.randrange(0, 1 << 32) for _ in range(100)]
    for n in ns:
        n = s64(n)
        for div in (True, False):
            for nonneg in ((True, False) if n >= 0 else (False,)):
                시험 += 1
                if lower(n, c, div, nonneg) != ref(n, c, div):
                    틀림 += 1
                    if 틀림 < 10:
                        print("틀림", n, c, div, nonneg, lower(n, c, div, nonneg), ref(n, c, div))
print(f"시험 {시험} 가지, 틀림 {틀림}")
for c in (10, 24, 768, 1600, 2304, 4800):
    M, s = magic_s64(c)
    print(c, hex(M), s)
