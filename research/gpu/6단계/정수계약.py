#!/usr/bin/env python3
"""6단계 — 정수 블록 계약의 CPU 참조 구현(numpy). 정수는 정확히(int64), 짧은실수 연산은 IEEE 754 그대로(numpy float32 의 RN),
곱해더하기는 반올림 한 번을 정확히 흉내 낸다. GPU 의 커널(3단계/커널생성.py 의 정수로 · 정수타일선형 · 생성메가의 정수 판)과
비트까지 같아야 한다(6a). 계약은 3단계/커널생성.py 의 설명 그대로:

  E = ⌊log₂ max|x|⌋ (최댓값 0 이면 −98, [−98, 100] 로), n = 가까운정수(x · 2^(29 − E)), 균형 256진 네 자리 D₀ … D₃,
  S_j = Σ D_j · q (정확), v_j = S_j · 2^(8j + E − 29) (정확), u = ((v₃ + v₂) + v₁) + v₀, y ← 곱해더하기(u, d, y) (블록 차례),
  출력 = y + 치우침.
8단계 — 자리 둘(자리수=2): n = 가까운정수(x · 2^(13 − E)), |n| ≤ 2¹⁴, D₀ ∈ [−128, 127], D₁ ∈ [−64, 64], v_j = S_j · 2^(8j + E − 13),
u = v₁ + v₀. 일반으로 자리수 m 의 고정소수점 비트는 P = 8m − 3.
"""
import numpy as np

f32 = np.float32


def fma32(a, b, c):
    """짧은실수 a · b + c 를 반올림 한 번으로(가까운 쪽, 같으면 짝수) — fp64 로 곱하고(정확) 더한 뒤, 그 합이 짧은실수 두 수의
    한가운데에 떨어졌을 때만 오차의 부호(TwoSum)로 바로잡는다. a · b 는 fp64 안에서 정확해야 한다(가수 합 53 비트 이하)."""
    a, b, c = (np.asarray(v, dtype=f32).astype(np.float64) for v in (a, b, c))
    p = a * b
    r = p + c
    bb = r - p
    err = (p - (r - bb)) + (c - bb)                       # p + c = r + err (정확)
    f = r.astype(f32)
    fd = f.astype(np.float64)
    lo = np.where(fd <= r, f, np.nextafter(f, f32(-np.inf)))
    hi = np.where(fd <= r, np.nextafter(f, f32(np.inf)), f)
    mid = (lo.astype(np.float64) + hi.astype(np.float64)) / 2
    tie = (r == mid) & (err != 0)
    return np.where(tie, np.where(err > 0, hi, lo), f).astype(f32)


def 자리로(x, 자리수=4):
    """x [행][깊이] (짧은실수) → (자리 [자리수][행][깊이] int64, E [행][블록]). 고정소수점 비트 P = 8·자리수 − 3 (넷 29, 둘 13)."""
    x = np.asarray(x, f32)
    M, K = x.shape
    P = 8 * 자리수 - 3
    xb = x.reshape(M, K // 32, 32)
    m = np.abs(xb).max(2)
    e = np.frexp(m.astype(np.float64))[1] - 1                 # m = 가수 · 2^e, 가수 ∈ [0.5, 1) → ⌊log₂ m⌋ = e − 1
    E = np.where(m > 0, np.clip(e, -98, 100), -98).astype(np.int64)
    s = np.ldexp(f32(1), (P - E)).astype(f32)
    n = np.rint(xb * s[:, :, None]).astype(np.int64)          # 짧은실수 곱(2 의 거듭제곱 — 정확) 뒤 가까운 정수(같으면 짝수)
    assert np.abs(n).max() <= 2 ** (P + 1)
    D = []
    for _ in range(자리수 - 1):
        d = ((n + 128) & 255) - 128
        D.append(d)
        n = (n - d) >> 8
    D.append(n)
    assert np.abs(n).max() <= 64
    return np.stack(D).reshape(자리수, M, K), E


def 행렬곱(x, q, d, 치우침, 자리수=4):
    """정수 블록 계약의 출력 [행][열]. q [깊이][열] 정수(Q8_0 의 q 또는 Q4_0 의 니블 − 8), d [블록][열] (반실수 값), 치우침 [열].
    자리수 4 (6단계) 또는 2 (8단계) — u 는 맨 위 자리부터 차례로 더한다: ((v₃ + v₂) + v₁) + v₀ · v₁ + v₀."""
    D, E = 자리로(x, 자리수)
    P = 8 * 자리수 - 3
    M, K = D.shape[1:]
    KB = K // 32
    N = q.shape[1]
    y = np.zeros((M, N), f32)
    q = np.asarray(q, np.int64)
    d = np.asarray(d, f32)
    for b in range(KB):
        qb = q[32 * b:32 * b + 32]
        v = [np.ldexp((D[j][:, 32 * b:32 * b + 32] @ qb).astype(f32), (8 * j + E[:, b] - P)[:, None]).astype(f32)
             for j in range(자리수)]
        u = v[자리수 - 1]
        for j in range(자리수 - 2, -1, -1):
            u = u + v[j]
        y = fma32(u, np.broadcast_to(d[b][None, :], u.shape), y)
    return (y + np.asarray(치우침, f32)[None, :]).astype(f32)
