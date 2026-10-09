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


# ── 9단계 — 정수 KV 계약: 어텐션의 CPU 참조 (docs/17 §7 "9단계" 의 계약 그대로) ──────────────────────────────────────────
# q · k · v 는 자리 둘 활성값과 같은 바꾸기(자리로(…, 2) — 블록 32 칸, |n| ≤ 2¹⁴). 점수 · 가중합은 자리 짝 넷의 정확한 정수 합을
# 짧은실수로 반올림 하나(numpy 의 int64 → float32 가 RN). 지수는 적힌지수(아래 — 모든 연산이 IEEE 짧은실수라 GPU 와 비트가 같다).
# 상수는 짧은실수로 정확히 표현되는 십진수로 적는다(커널생성.py 의 적힌지수식과 같은 글자).
지수상수 = {"log2e": "1.44269502162933349609375", "C1": "0.693359375", "C2": "0.000212194441701285541058",
         "c5": "0.000198756912141107022762", "c4": "0.001398199936375021934509", "c3": "0.008333452045917510986328",
         "c2": "0.041665796190500259399414", "c1": "0.166666656732559204101562", "c0": "0.5",
         "밑": "-88.0", "끝": "-87.3000030517578125"}
_k = {n: f32(float(v)) for n, v in 지수상수.items()}


def 적힌지수(x):
    """적힌지수(x), x ≤ 0 (짧은실수 배열) — docs/17 9단계 2: n = 가까운정수(max(x, −88) · log₂e) (정확한 곱을 마법수로 반올림), r = x − n·C₁ + n·C₂ (곱해더하기 둘),
    y = ((((c₅·r + c₄)·r + c₃)·r + c₂)·r + c₁)·r + c₀ (곱해더하기 사슬), y = y·r² + r (곱해더하기), y = y + 1, 결과 = y · 2ⁿ (지수 비트에 n 을
    더한다 — 정확), x < −87.3 이면 0. 가까운정수는 같으면 짝수(cvt.rni)."""
    x = np.asarray(x, f32)
    xc = np.maximum(x, _k["밑"]).astype(f32)
    nf = (fma32(xc, _k["log2e"], f32(12582912.0)) - f32(12582912.0)).astype(f32)   # 정확한 곱의 가까운 정수(마법수 1.5·2²³)
    n = nf.astype(np.int32)
    r = fma32(nf, -_k["C1"], xc)
    r = fma32(nf, _k["C2"], r)
    z = (r * r).astype(f32)
    y = fma32(_k["c5"], r, _k["c4"])
    for c in ("c3", "c2", "c1", "c0"):
        y = fma32(y, r, _k[c])
    y = fma32(y, z, r)
    y = (y + f32(1)).astype(f32)
    bits = y.view(np.int32) + (n.astype(np.int32) << 23)
    return np.where(x < _k["끝"], f32(0), bits.view(f32)).astype(f32)


def e자리(ep):
    """e′ [R][32] (≥ 0, 짧은실수) → 블록(키 32 개)마다 E = ⌊log₂ max⌋ (0 이면 −98), n = 가까운정수(e′ · 2^(13 − E)) — 정확한 곱을 마법수
    2²³ + 128 을 더하는 곱해더하기로 반올림(커널과 같은 식; n + 128 이 나온다). 돌려줌: n [R][32] int64, E [R][1]."""
    m = ep.max(1, keepdims=True)
    E = np.where(m > 0, np.clip(np.frexp(m.astype(np.float64))[1] - 1, -98, 100), -98).astype(np.int64)
    s = np.ldexp(f32(1), (13 - E)).astype(f32)
    me = fma32(ep, np.broadcast_to(s, ep.shape), f32(8388736.0)).view(np.int32).astype(np.int64) - 1258291200
    n = me - 128
    assert n.min() >= 0 and n.max() <= 2 ** 14
    return n, E


def 거듭제곱(E):
    """2^(E − 13) 을 짧은실수로(정확 — 비트 (E + 114) << 23)."""
    return ((np.asarray(E, np.int64) + 114) << 23).astype(np.int32).view(f32)


def 어텐션(q, k, v, 조각=64):
    """머리 하나의 어텐션(원인 가림, × 0.125) — 정수 KV 계약의 참조. q · k · v [n][64] 짧은실수 → 출력 [n][64] 짧은실수(O / L).
    프롬프트 판(mma)과 생성 판(dp4a) 모두와 비트까지 같아야 한다(9a)."""
    q, k, v = (np.asarray(x, f32) for x in (q, k, v))
    n = q.shape[0]
    (Dq, Eq), (Dk, Ek), (Dv, Ev) = 자리로(q, 2), 자리로(k, 2), 자리로(v, 2)
    nq, nk, nv = (D[1] * 256 + D[0] for D in (Dq, Dk, Dv))          # [n][64] int64
    Pq, Pk, Pv = 거듭제곱(Eq), 거듭제곱(Ek), 거듭제곱(Ev)              # [n][2]
    M = np.full(n, -np.inf, f32)
    L = np.zeros(n, f32)
    O = np.zeros((n, 64), f32)
    rows = np.arange(n)
    for 시작 in range(0, n, 조각):
        R = rows[시작:]                                              # 이 조각에 유효한 키가 있는 질의들
        keys = np.arange(시작, min(시작 + 조각, n))
        valid = keys[None, :] <= R[:, None]                          # [R][keys]
        # 1. 점수
        s = None
        for b in range(2):
            sl = slice(32 * b, 32 * b + 32)
            u = (nq[R][:, sl] @ nk[keys][:, sl].T).astype(f32)        # 정확한 정수 합 → 반올림 하나
            부분 = (u * Pq[R, b][:, None]).astype(f32)                 # 정확
            s = (부분 * Pk[keys, b][None, :]).astype(f32) if b == 0 else fma32(부분, np.broadcast_to(Pk[keys, b][None, :], 부분.shape), s)
        s = (s * f32(0.125)).astype(f32)
        s = np.where(valid, s, f32(-3.0e38)).astype(f32)
        # 2. 최댓값 · 지수
        m = s.max(1)
        e = np.where(valid, 적힌지수((s - m[:, None]).astype(f32)), f32(0)).astype(f32)
        # 3. 합 — 2⁻²³ 눈금의 정수 합, 반올림 하나
        l = (np.rint((e * f32(8388608.0)).astype(f32)).astype(np.int64).sum(1).astype(f32) * f32(2.0 ** -23)).astype(f32)
        # 4. 가중합 — 값의 블록 b 마다 e′ = e · 2^(E_v − 13), 키 32 개 블록 j 마다 자리 둘
        o = np.zeros((len(R), 64), f32)
        for b in range(2):
            ep = (e * Pv[keys, b][None, :]).astype(f32)                 # 정확
            uj = []
            for j in range(0, len(keys), 32):
                epj = np.zeros((len(R), 32), f32)
                epj[:, :min(32, len(keys) - j)] = ep[:, j:j + 32]
                ne, Ee = e자리(epj)                                     # [R][32] ∈ [0, 2¹⁴], [R][1]
                nvj = np.zeros((32, 32), np.int64)
                nvj[:min(32, len(keys) - j)] = nv[keys[j:j + 32]][:, 32 * b:32 * b + 32]
                uj.append(((ne @ nvj).astype(f32), 거듭제곱(Ee[:, 0])))
            if len(uj) == 1:
                uj.append((np.zeros_like(uj[0][0]), 거듭제곱(np.full(len(R), -98))))
            (u0, P0), (u1, P1) = uj
            o[:, 32 * b:32 * b + 32] = fma32(u1, P1[:, None], (u0 * P0[:, None]).astype(f32))
        # 5. 접기
        첫 = 시작 == 0
        if 첫:
            M[R], L[R], O[R] = m, l, o
        else:
            M2 = np.maximum(M[R], m)
            가 = 적힌지수((M[R] - M2).astype(f32))
            나 = 적힌지수((m - M2).astype(f32))
            L[R] = fma32(l, 나, (L[R] * 가).astype(f32))
            O[R] = fma32(o, 나[:, None], (O[R] * 가[:, None]).astype(f32))
            M[R] = M2
    return (O / L[:, None]).astype(f32)


def 낱말차례(바이트):
    """[…][32] 바이트(블록 하나) → [0 4 1 5 2 6 3 7] 낱말 차례의 [...][32] 바이트 (정수로 · 타일 판의 A 조각 배치)."""
    b = np.asarray(바이트).reshape(*np.asarray(바이트).shape[:-1], 8, 4)
    return b[..., [0, 4, 1, 5, 2, 6, 3, 7], :].reshape(np.asarray(바이트).shape)


def 키캐시(k, 최대길이):
    """머리 하나의 키 캐시 바이트 — [자리 2][최대길이][64 바이트](위치 n 뒤는 0) 와 지수 [최대길이][2] (E + 114, uint8). k [n][64]."""
    D, E = 자리로(np.asarray(k, f32), 2)
    n = D.shape[1]
    out = np.zeros((2, 최대길이, 64), np.int8)
    out[:, :n] = 낱말차례(D.reshape(2, n, 2, 32)).reshape(2, n, 64)
    ex = np.zeros((최대길이, 2), np.uint8)
    ex[:n] = E + 114
    return out, ex


def 값캐시(v, 최대길이):
    """머리 하나의 값 캐시 바이트 — [키 블록 최대길이/32][자리 2][d 64][낱말 8][4 바이트]: 낱말 2c + h 의 바이트 i 는 키 16h + 2c + i (i < 2),
    16h + 8 + 2c + (i − 2) (i ≥ 2) 의 d 번째 자리. 지수 [최대길이][2] (int8). v [n][64]."""
    D, E = 자리로(np.asarray(v, f32), 2)
    n = D.shape[1]
    키 = np.zeros(32, np.int64)
    for h in range(2):
        for c in range(4):
            키[(2 * c + h) * 4:(2 * c + h) * 4 + 4] = [16 * h + 2 * c, 16 * h + 2 * c + 1, 16 * h + 8 + 2 * c, 16 * h + 8 + 2 * c + 1]
    Dp = np.zeros((2, 최대길이, 64), np.int64)
    Dp[:, :n] = D
    blk = Dp.reshape(2, 최대길이 // 32, 32, 64)[:, :, 키, :]                  # [자리][블록][자리 32 (낱말 차례)][d]
    out = np.ascontiguousarray(blk.transpose(1, 0, 3, 2)).astype(np.int8)    # [블록][자리][d][32 바이트]
    ex = np.zeros((최대길이, 2), np.uint8)
    ex[:n] = E + 114
    return out, ex
