#!/usr/bin/env python3
"""감사 A2 — 0단계의 지도로 찾는다 (README 의 H1~H4 검사 목록 그대로).

  build/감사venv/Scripts/python research/gpu/감사/지도검사.py [H1 H2 H3 H4]

검사마다 통과·손실·참고를 적고 결과/지도검사.json 에 쓴다. 손실은 "말한 의미"(성질)를 오류·경고 없이 어긴 것이다.
"""
import json
import os
import sys

import torch
import torch.nn.functional as F

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
dev = torch.device("cuda")
N1 = 2 ** 31 + 2 ** 20
R2 = 2 ** 21 + 1                          # [R2, 1024] — 마지막 행이 원소 2^31 에서 시작한다
INT_VIEW = {torch.float32: torch.int32, torch.bfloat16: torch.int16, torch.float16: torch.int16}
rows = []


def record(group, name, ok, detail, kind="손실"):
    r = {"묶음": group, "검사": name, "결과": "통과" if ok else kind, "세부": detail}
    rows.append(r)
    print(f"[{group}] {name:<58} {r['결과']:<3} {detail}")


def free():
    torch.cuda.synchronize()
    torch.cuda.empty_cache()


def rel(a, b):
    a, b = a.double(), b.double()
    return float((a - b).norm() / b.norm().clamp_min(1e-300))


# ---------- H1 정수 폭 ----------
def h1():
    g = "H1 정수 폭"
    x = torch.ones(N1, dtype=torch.int8, device=dev)
    s = int(x.sum())
    record(g, "1 ones(N1, int8).sum()", s == N1, f"{s} (기대 {N1})")
    del x; free()

    x = torch.zeros(N1, dtype=torch.int8, device=dev)
    x[-1] = 7
    idx = torch.tensor([N1 - 1], device=dev)
    got = (int(x[-1]), int(torch.index_select(x, 0, idx)[0]), int(torch.take(x, idx)[0]))
    record(g, "2 끝 원소: x[-1], index_select, take", got == (7, 7, 7), f"{got}")
    del x; free()

    for pos in (N1 - 1, 2 ** 31 + 5, 2 ** 31 - 5):
        x = torch.zeros(N1, dtype=torch.float16, device=dev)
        x[pos] = 1
        a = int(x.argmax())
        record(g, f"3 argmax fp16, 1 의 자리 {pos}", a == pos, f"{a}")
        del x; free()

    a = torch.zeros(N1, dtype=torch.int8, device=dev)
    c = a + torch.ones(1, dtype=torch.int8, device=dev)
    del a; free()
    s, last = int(c.sum()), int(c[-1])
    record(g, "4 브로드캐스트 덧셈 zeros(N1)+ones(1) int8", s == N1 and last == 1, f"합 {s}, 끝 {last}")
    del c; free()

    R, C = 32768, 65568                                       # R*C = N1
    x = torch.arange(127, dtype=torch.int8, device=dev).repeat((N1 + 126) // 127)[:N1].view(R, C)
    y = x.t().contiguous()
    samples = [(R - 1, C - 1), (R - 1, 0), (0, C - 1), (R // 2, C - 3), (R - 2, C // 2), (32767, 65535)]
    bad = [(r, c) for r, c in samples if int(y[c, r]) != (r * C + c) % 127 or int(x[r, c]) != (r * C + c) % 127]
    record(g, "5 전치 복사 [32768, 65568] int8", not bad, f"틀린 표본 {bad}")
    del y; free()

    cond = x > 60
    w = torch.where(cond, x, torch.zeros((), dtype=torch.int8, device=dev))
    bad = []
    for r, c in samples:
        v = (r * C + c) % 127
        if int(w[r, c]) != (v if v > 60 else 0):
            bad.append((r, c))
    record(g, "6 torch.where int8 N1", not bad, f"틀린 표본 {bad}")
    del x, cond, w; free()

    gen = torch.Generator(device=dev).manual_seed(48)
    x = torch.randn(R2, 1024, dtype=torch.float16, device=dev, generator=gen)
    y = F.softmax(x, -1)
    alone = F.softmax(x[-1:], -1)[0]
    d = rel(y[-1], alone)
    ssum = float(y[-1].double().sum())
    record(g, "7 행 softmax [2^21+1, 1024] fp16 — 마지막 행", d <= 1e-2 and abs(ssum - 1) < 1e-2 and torch.isfinite(y[-1]).all().item(),
           f"그 행만 계산한 것과의 상대차 {d:.3g}, 행 합 {ssum:.5f}")
    del y; free()

    yl = F.layer_norm(x, (1024,))
    alone = F.layer_norm(x[-1:], (1024,))[0]
    d = rel(yl[-1], alone)
    record(g, "10 layer_norm [2^21+1, 1024] fp16 — 마지막 행", d <= 1e-2 and torch.isfinite(yl[-1]).all().item(), f"상대차 {d:.3g}")
    del yl; free()

    e = F.embedding(torch.tensor([R2 - 1], device=dev), x)[0]
    same = torch.equal(e.view(torch.int16), x[-1].view(torch.int16))
    record(g, "8 embedding 가중치 [2^21+1, 1024] fp16 — 마지막 행", same, "비트까지 같음" if same else "다름")
    del x, e; free()

    A = torch.randint(0, 3, (65536, 16), device=dev, generator=gen).to(torch.float16)
    B = torch.randint(0, 3, (16, 32784), device=dev, generator=gen).to(torch.float16)
    Cm = A @ B                                                 # 65536 × 32784 = N1 원소
    exact = (A[-1].double() @ B.double())
    ok_last = torch.equal(Cm[-1].double(), exact)
    probe = [(65535, 32783), (65535, 0), (65534, 16391), (40000, 32780)]
    bad = [(r, c) for r, c in probe if float(Cm[r, c]) != float(A[r].double() @ B[:, c].double())]
    record(g, "9 출력 N1 원소 행렬곱 [65536,16]@[16,32784] fp16 (값이 정확한 입력)", ok_last and not bad,
           f"마지막 행 정확 {ok_last}, 틀린 표본 {bad}")
    del A, B, Cm; free()


# ---------- H2 배치 무관 ----------
def h2():
    g = "H2 배치 무관"
    gen = torch.Generator(device=dev).manual_seed(48)
    for dn, dt in (("fp32", torch.float32), ("fp16", torch.float16), ("bf16", torch.bfloat16)):
        base = torch.randn(1024, 1024, device=dev, generator=gen).to(dt)
        pos = (base.abs() + 0.1).to(dt)
        views = {"전치": lambda t: t.t(), "[:, ::2]": lambda t: t[:, ::2],
                 "보폭 0": lambda t: t[:, :1].expand(1024, 1024), "[1:, 3:]": lambda t: t[1:, 3:]}
        other = {torch.float32: torch.float16, torch.float16: torch.float32, torch.bfloat16: torch.float32}[dt]
        ops = {
            "add": lambda v: v + torch.ones_like(v.contiguous()) * 0.37,
            "mul": lambda v: v * torch.full_like(v.contiguous(), 1.13),
            "div": lambda v: v / torch.full_like(v.contiguous(), 3.7),
            "exp": torch.exp, "sin": torch.sin, "tanh": torch.tanh, "sigmoid": torch.sigmoid,
            "gelu": F.gelu, "silu": F.silu, "pow3": lambda v: torch.pow(v, 3), "abs": torch.abs,
            f"to({str(other).split('.')[-1]})": lambda v: v.to(other),
        }
        pos_ops = {"log": torch.log, "sqrt": torch.sqrt, "rsqrt": torch.rsqrt}
        bad = []
        n = 0
        for vn, vf in views.items():
            for on, of in list(ops.items()) + [(k, v) for k, v in pos_ops.items()]:
                src = pos if on in pos_ops else base
                v = vf(src)
                a, b = of(v).contiguous(), of(v.contiguous()).contiguous()
                n += 1
                if not torch.equal(a.view(INT_VIEW[a.dtype]), b.view(INT_VIEW[b.dtype])):
                    bad.append(f"{on}@{vn} (최대차 {float((a.double() - b.double()).abs().max()):.3g})")
        record(g, f"원소별·변환 {n}개 조합 {dn}", not bad, "모두 비트까지 같음" if not bad else "; ".join(bad))
        refs = []
        w = torch.randn(1024, 256, device=dev, generator=gen).to(dt)
        for vn, vf in views.items():
            v = vf(base)
            last = v.shape[-1]
            pairs = {"sum": lambda t: t.sum(-1), "softmax": lambda t: F.softmax(t, -1),
                     "layer_norm": lambda t: F.layer_norm(t, (last,)), "matmul": lambda t: t @ w[:last]}
            for pn, pf in pairs.items():
                a, b = pf(v).contiguous(), pf(v.contiguous()).contiguous()
                if not torch.equal(a.view(INT_VIEW[a.dtype]), b.view(INT_VIEW[b.dtype])):
                    refs.append(f"{pn}@{vn}")
        record(g, f"줄이기 (참고) {dn}", True, "비트가 다른 조합: " + (", ".join(refs) if refs else "없음"), kind="참고")
        del base, pos, w; free()


# ---------- H3 범위 ----------
def h3():
    g = "H3 범위"
    gen = torch.Generator(device=dev).manual_seed(48)
    for dn, dt in (("fp16", torch.float16), ("bf16", torch.bfloat16)):
        def check(name, f, *inputs, tol=1e-2):
            xs = [t.to(dt) for t in inputs]
            got = f(*xs)
            ref = f(*[t.double() for t in xs])
            finite_ref = torch.isfinite(ref).all().item()
            representable = finite_ref and float(ref.abs().max()) <= float(torch.finfo(dt).max)
            if not representable:
                record(g, f"{name} {dn}", True, "참값이 표현되지 않아 건너뜀", kind="참고")
                return
            ok = torch.isfinite(got).all().item() and rel(got, ref) <= tol
            record(g, f"{name} {dn}", ok, f"유한 {torch.isfinite(got).all().item()}, 상대차 {rel(got, ref):.3g}")

        big = torch.randn(8, 1024, device=dev, generator=gen) * 10 + 60000
        mid = torch.randn(8, 1024, device=dev, generator=gen) * 16 + 30000
        check("1 softmax (로짓 6e4 근처)", lambda t: F.softmax(t, -1), big)
        check("2 logsumexp (6e4 근처)", lambda t: torch.logsumexp(t, -1), big)
        check("3 layer_norm (3e4 ± 16)", lambda t: F.layer_norm(t, (1024,)), mid)
        check("4 rms_norm (3e4 근처)", lambda t: F.rms_norm(t, (1024,)), mid)
        check("5 vector_norm ([3e4]×4)", lambda t: torch.linalg.vector_norm(t), torch.full((4,), 30000.0, device=dev))
        check("6a var (3e4 ± 16)", lambda t: t.var(-1), mid)
        check("6b std (3e4 ± 16)", lambda t: t.std(-1), mid)
        q = torch.full((1, 1, 16, 64), 100.0, device=dev)
        v = torch.randn(1, 1, 16, 64, device=dev, generator=gen)
        check("7 scaled_dot_product_attention (점수 8e4)", lambda a, b, c: F.scaled_dot_product_attention(a, b, c), q, q, v)
        tgt = torch.randint(0, 1024, (8,), device=dev, generator=gen)
        check("8 cross_entropy (로짓 6e4 근처)", lambda t: F.cross_entropy(t, tgt), big)
        check("9 cosine_similarity (3e4 근처, 길이 1024)", lambda a, b: F.cosine_similarity(a, b, -1), mid, mid.flip(0))
        check("10 mean ([6e4]×1024)", lambda t: t.mean(), torch.full((1024,), 60000.0, device=dev))
        free()


# ---------- H4 정밀도 ----------
def h4():
    g = "H4 정밀도"
    gen = torch.Generator(device=dev).manual_seed(48)
    x = torch.randn(8, 64, 32, 32, device=dev, generator=gen)
    w = torch.randn(64, 64, 3, 3, device=dev, generator=gen)
    d = rel(F.conv2d(x, w, padding=1), F.conv2d(x.double(), w.double(), padding=1))
    record(g, "1 conv2d fp32 (기본 설정)", d <= 1e-5, f"fp64 참값과의 상대차 {d:.3g} (fp32 라면 1e-7 근처)")

    a = torch.randn(1024, 1024, device=dev, generator=gen)
    b = torch.randn(1024, 1024, device=dev, generator=gen)
    d = rel(a @ b, a.double() @ b.double())
    record(g, "2 행렬곱 fp32", d <= 1e-5, f"상대차 {d:.3g}")

    def overflow_case(name, A):
        Bm = torch.ones(A.shape[1], 64, dtype=torch.float16, device=dev)
        out = A @ Bm                                            # 참값은 0
        ok = torch.isfinite(out).all().item() and float(out.abs().max()) == 0.0
        record(g, name, ok, f"유한 {torch.isfinite(out).all().item()}, 최대 |값| {float(out.float().abs().nan_to_num(float('inf')).max())}")

    alt = torch.tensor([300.0, -300.0], device=dev).repeat(512).to(torch.float16).repeat(64, 1)
    overflow_case("3a 행렬곱 fp16, ±300 번갈아 (방법에 적은 입력)", alt)
    for K in (1024, 8192, 65536):
        blk = torch.cat([torch.full((K // 2,), 300.0), torch.full((K // 2,), -300.0)]).to(dev, torch.float16).repeat(64, 1)
        overflow_case(f"3b 행렬곱 fp16, 앞 절반 +300 뒤 절반 −300, K={K} (덧붙임)", blk)

    a = torch.randn(64, 65536, device=dev, generator=gen).to(torch.bfloat16)
    b = torch.randn(65536, 64, device=dev, generator=gen).to(torch.bfloat16)
    d = rel(a @ b, a.double() @ b.double())
    record(g, "4 행렬곱 bf16 (K=65536)", d <= 1e-2, f"상대차 {d:.3g}")

    q, k, v = (torch.randn(2, 8, 512, 64, device=dev, generator=gen) for _ in range(3))
    d = rel(F.scaled_dot_product_attention(q, k, v), F.scaled_dot_product_attention(q.double(), k.double(), v.double()))
    record(g, "5 scaled_dot_product_attention fp32", d <= 1e-5, f"상대차 {d:.3g}")
    free()


def main(argv):
    which = argv or ["H1", "H2", "H3", "H4"]
    for h in which:
        {"H1": h1, "H2": h2, "H3": h3, "H4": h4}[h]()
    os.makedirs(os.path.join(HERE, "결과"), exist_ok=True)
    path = os.path.join(HERE, "결과", "지도검사.json")
    old = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else []
    keep = [r for r in old if r["묶음"].split()[0] not in which]
    json.dump(keep + rows, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(sys.argv[1:])
