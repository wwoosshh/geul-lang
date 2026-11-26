// RoPE table -- line-by-line port of ../../rope.c (the same algorithm as ../../rope.gl, GeulPU host/로프.gl):
// double-double arithmetic, a fixed-point big integer for pi (Machin), a fp64 polynomial fast path with a rigorous
// error bound and correct rounding to float32, and the geul standard library's math helpers (absolute value, floor,
// scaling by 2^n, natural log) written the same way.
// Rust never fuses a multiply and an add (no mul_add here), like the C built with -ffp-contract=off.
//
// Two shapes differ from the C because safe Rust cannot express them (see README.md):
//  - the C's file-scope mutable statics live in one `Globals` value, made in main and passed as `g` to the functions
//    that use them;
//  - a `dd *r` out-parameter (which the C lets alias an input: dd_add(&sum, &sum, &term)) is the return value:
//    sum = dd_add(&sum, &term). Every C helper reads all of its inputs before it writes r, so the values are the same.
// The upper-case local `M` keeps the C name.
#![allow(non_snake_case)]

// ---- the geul standard library's math (표준/수학.gl) ----
fn dbits(x: f64) -> i64 { return x.to_bits() as i64; }
fn bitsd(b: i64) -> f64 { return f64::from_bits(b as u64); }
fn d_abs(v: f64) -> f64 { return bitsd(dbits(v) & 9223372036854775807); }
fn is_inf(x: f64) -> bool { return (dbits(x) & 9223372036854775807) == 9218868437227405312; }
fn is_nan(x: f64) -> bool { return (dbits(x) & 9223372036854775807) > 9218868437227405312; }
fn d_nan() -> f64 { return bitsd(9221120237041090560); }
fn d_inf() -> f64 { return bitsd(9218868437227405312); }
const LN2: f64 = 0.69314718055994530942;

fn scale2(mut x: f64, mut n: i64) -> f64 {
    while n > 1000 { x = x * 8.98846567431158e307; n = n - 1023; }
    while n < -1000 { x = x * 1.1125369292536007e-308; n = n + 1022; }
    return x * bitsd((n + 1023) << 52);
}

fn d_floor(v: f64) -> f64 {
    if is_inf(v) || is_nan(v) { return v; }
    if v >= 4503599627370496.0 || v <= -4503599627370496.0 { return v; }
    let n: i64 = v as i64;
    let r: f64 = n as f64;
    if r > v { return r - 1.0; }
    return r;
}

#[allow(unused_assignments)] // `m = v` is overwritten before it is read, as in the C
fn d_log(v: f64) -> f64 {
    if is_nan(v) { return v; }
    if v < 0.0 { return d_nan(); }
    if v == 0.0 { return 0.0 - d_inf(); }
    if is_inf(v) { return v; }
    let mut bits: i64 = dbits(v);
    let mut ex: i64 = (bits >> 52) & 2047;
    let mut m: f64 = v;
    let mut e: i64 = 0;
    if ex == 0 {
        m = v * 18014398509481984.0;
        bits = dbits(m);
        ex = (bits >> 52) & 2047;
        e = -54;
    }
    e = e + ex - 1023;
    m = bitsd((bits & 4503599627370495) | 4607182418800017408);
    if m > 1.4142135623730951 { m = m * 0.5; e = e + 1; }
    let s: f64 = (m - 1.0) / (m + 1.0);
    let s2: f64 = s * s;
    let mut term: f64 = s;
    let mut sum: f64 = 0.0;
    let mut n: i64 = 1;
    while n < 60 {
        sum = sum + term / (n as f64);
        term = term * s2;
        if d_abs(term) < 1.0e-18 { break; }
        n += 2;
    }
    return 2.0 * sum + (e as f64) * LN2;
}

// ---- double-double ----
#[derive(Clone, Copy)]
struct Dd { hi: f64, lo: f64 }

fn two_sum(a: f64, b: f64) -> Dd {
    let s: f64 = a + b;
    let bb: f64 = s - a;
    return Dd { hi: s, lo: (a - (s - bb)) + (b - bb) };
}

fn fast_sum(a: f64, b: f64) -> Dd {
    let s: f64 = a + b;
    return Dd { hi: s, lo: b - (s - a) };
}

fn two_prod(a: f64, b: f64) -> Dd {
    let p: f64 = a * b;
    let ta: f64 = 134217729.0 * a;
    let ah: f64 = ta - (ta - a);
    let al: f64 = a - ah;
    let tb: f64 = 134217729.0 * b;
    let bh: f64 = tb - (tb - b);
    let bl: f64 = b - bh;
    return Dd { hi: p, lo: ((ah * bh - p) + ah * bl + al * bh) + al * bl };
}

fn dd_add(a: &Dd, b: &Dd) -> Dd {
    let s: Dd = two_sum(a.hi, b.hi);
    let t: Dd = two_sum(a.lo, b.lo);
    let c: f64 = s.lo + t.hi;
    let v: Dd = fast_sum(s.hi, c);
    let w: f64 = t.lo + v.lo;
    return fast_sum(v.hi, w);
}

fn dd_sub(a: &Dd, b: &Dd) -> Dd {
    let nb: Dd = Dd { hi: 0.0 - b.hi, lo: 0.0 - b.lo };
    return dd_add(a, &nb);
}

fn dd_mul(a: &Dd, b: &Dd) -> Dd {
    let p: Dd = two_prod(a.hi, b.hi);
    let e: f64 = p.lo + (a.hi * b.lo + a.lo * b.hi);
    return fast_sum(p.hi, e);
}

fn dd_mul_d(a: &Dd, d: f64) -> Dd {
    let p: Dd = two_prod(a.hi, d);
    let e: f64 = p.lo + a.lo * d;
    return fast_sum(p.hi, e);
}

fn dd_div(a: &Dd, b: &Dd) -> Dd {
    let q1: f64 = a.hi / b.hi;
    let mut t: Dd;
    let mut rr: Dd;
    t = dd_mul_d(b, q1);
    rr = dd_sub(a, &t);
    let q2: f64 = rr.hi / b.hi;
    t = dd_mul_d(b, q2);
    rr = dd_sub(&rr, &t);
    let q3: f64 = rr.hi / b.hi;
    let q: Dd = fast_sum(q1, q2);
    let q3d: Dd = Dd { hi: q3, lo: 0.0 };
    return dd_add(&q, &q3d);
}

fn dd_set(a: f64) -> Dd { return Dd { hi: a, lo: 0.0 }; }

fn dd_div_d(a: &Dd, d: f64) -> Dd {
    let b: Dd = Dd { hi: d, lo: 0.0 };
    return dd_div(a, &b);
}

// ---- fixed-point big integer: word 0 integer part, words 1..8 fraction (32 bits each) ----
const BIGW: i64 = 9;

fn big_zero(a: &mut [i64]) {
    let mut i: i64 = 0;
    while i < BIGW { a[i as usize] = 0; i += 1; }
}

fn big_is_zero(a: &[i64]) -> bool {
    let mut i: i64 = 0;
    while i < BIGW { if a[i as usize] != 0 { return false; } i += 1; }
    return true;
}

fn big_div_small(a: &mut [i64], d: i64) {
    let mut rem: i64 = 0;
    let mut i: i64 = 0;
    while i < BIGW {
        let cur: i64 = (rem << 32) + a[i as usize];
        a[i as usize] = cur / d;
        rem = cur % d;
        i += 1;
    }
}

fn big_add(a: &mut [i64], b: &[i64]) {
    let mut carry: i64 = 0;
    let mut i: i64 = BIGW - 1;
    while i >= 0 {
        let s: i64 = a[i as usize] + b[i as usize] + carry;
        a[i as usize] = s & 4294967295;
        carry = s >> 32;
        i -= 1;
    }
}

fn big_sub(a: &mut [i64], b: &[i64]) {
    let mut borrow: i64 = 0;
    let mut i: i64 = BIGW - 1;
    while i >= 0 {
        let mut s: i64 = a[i as usize] - b[i as usize] - borrow;
        borrow = 0;
        if s < 0 { s = s + 4294967296; borrow = 1; }
        a[i as usize] = s;
        i -= 1;
    }
}

fn big_mul_small(a: &mut [i64], m: i64) {
    let mut carry: i64 = 0;
    let mut i: i64 = BIGW - 1;
    while i >= 0 {
        let s: i64 = a[i as usize] * m + carry;
        a[i as usize] = s & 4294967295;
        carry = s >> 32;
        i -= 1;
    }
}

fn big_atan_inv(sum: &mut [i64], x: i64) {
    let mut pw: [i64; BIGW as usize] = [0; BIGW as usize]; // C: int64_t pw[BIGW], term[BIGW]; (uninitialized there)
    let mut term: [i64; BIGW as usize] = [0; BIGW as usize];
    big_zero(&mut pw);
    pw[0] = 1;
    big_div_small(&mut pw, x);
    big_zero(sum);
    big_add(sum, &pw);
    let mut j: i64 = 1;
    loop {
        big_div_small(&mut pw, x * x);
        let mut i: i64 = 0;
        while i < BIGW { term[i as usize] = pw[i as usize]; i += 1; }
        big_div_small(&mut term, 2 * j + 1);
        if big_is_zero(&term) { break; }
        if j % 2 == 1 { big_sub(sum, &term); } else { big_add(sum, &term); }
        j += 1;
    }
}

fn big_bit(a: &[i64], n: i64) -> i64 {
    if n == 0 { return a[0] & 1; }
    return (a[((n - 1) / 32 + 1) as usize] >> (31 - (n - 1) % 32)) & 1;
}

fn big_bit_clear(a: &mut [i64], n: i64) {
    if n == 0 { a[0] = a[0] & (0 - 2); return; }
    let i: i64 = (n - 1) / 32 + 1;
    a[i as usize] = a[i as usize] & (4294967295 ^ ((1 as i64) << (31 - (n - 1) % 32)));
}

fn big_take_top(a: &mut [i64], nbits: i64) -> f64 {
    let mut n0: i64 = 0;
    while n0 <= 256 && big_bit(a, n0) == 0 { n0 += 1; }
    if n0 > 256 { return 0.0; }
    let mut M: i64 = 0;
    let mut j: i64 = 0;
    while j < nbits {
        let n: i64 = n0 + j;
        let mut b: i64 = 0;
        if n <= 256 { b = big_bit(a, n); }
        M = (M << 1) | b;
        if n <= 256 && b == 1 { big_bit_clear(a, n); }
        j += 1;
    }
    return scale2(M as f64, 0 - n0 - (nbits - 1));
}

fn big_take_double(a: &mut [i64]) -> f64 { return big_take_top(a, 53); }

// ---- the C's file-scope statics, in the C's order ----
struct Globals {
    halfpi1: f64, halfpi2: f64, halfpi3: f64, halfpi4: f64,
    #[allow(dead_code)] // set by prepare_pi and never read, as in the C
    halfpi_dd: Dd,
    dd_ln2: Dd,
    fhalfpi1: f64, fhalfpi2: f64, fhalfpi3: f64,
    hard_cases: i64,
    rope_cos: Dd, rope_sin: Dd,
    sin_coef: [f64; 11],
    cos_coef: [f64; 11],
    fast_rel: f64, fast_abs: f64, fast_cos: f64, fast_sin: f64,
    fast_sure: bool,
    slow_cases: i64,
    rope_cos_tab: Vec<f32>, rope_sin_tab: Vec<f32>,
}

fn prepare_pi(g: &mut Globals) {
    let mut a: [i64; BIGW as usize] = [0; BIGW as usize]; // C: int64_t a[BIGW], b[BIGW], c[BIGW]; (uninitialized there)
    let mut b: [i64; BIGW as usize] = [0; BIGW as usize];
    let mut c: [i64; BIGW as usize] = [0; BIGW as usize];
    big_atan_inv(&mut a, 5);
    big_mul_small(&mut a, 16);
    big_atan_inv(&mut b, 239);
    big_mul_small(&mut b, 4);
    big_sub(&mut a, &b);
    big_div_small(&mut a, 2);
    let mut i: i64 = 0;
    while i < BIGW { c[i as usize] = a[i as usize]; i += 1; }
    g.fhalfpi1 = big_take_top(&mut c, 36);
    g.fhalfpi2 = big_take_top(&mut c, 36);
    g.fhalfpi3 = big_take_top(&mut c, 53);
    g.halfpi1 = big_take_double(&mut a);
    g.halfpi2 = big_take_double(&mut a);
    g.halfpi3 = big_take_double(&mut a);
    g.halfpi4 = big_take_double(&mut a);
    g.halfpi_dd = fast_sum(g.halfpi1, g.halfpi2);
    let one: Dd = dd_set(1.0);
    let t: Dd = dd_div_d(&one, 3.0);
    let t2: Dd = dd_mul(&t, &t);
    let mut pw: Dd = t;
    let mut sum: Dd = t;
    let mut j: i64 = 1;
    while j < 40 {
        pw = dd_mul(&pw, &t2);
        let term: Dd = dd_div_d(&pw, (2 * j + 1) as f64);
        sum = dd_add(&sum, &term);
        j += 1;
    }
    g.dd_ln2 = dd_mul_d(&sum, 2.0);
}

fn dd_exp(g: &Globals, a: &Dd) -> Dd {
    if a.hi == 0.0 { return dd_set(1.0); }
    let m: f64 = d_floor(a.hi / g.dd_ln2.hi + 0.5);
    let s: Dd = dd_mul_d(&g.dd_ln2, m);
    let mut x: Dd = dd_sub(a, &s);
    x = dd_mul_d(&x, 1.0 / 512.0);
    let mut sum: Dd = x;
    let mut term: Dd = x;
    let mut n: i64 = 2;
    while n < 20 {
        term = dd_mul(&term, &x);
        term = dd_div_d(&term, n as f64);
        sum = dd_add(&sum, &term);
        n += 1;
    }
    let mut i: i64 = 0;
    while i < 9 {
        let sq: Dd = dd_mul(&sum, &sum);
        sum = dd_mul_d(&sum, 2.0);
        sum = dd_add(&sum, &sq);
        i += 1;
    }
    let one: Dd = dd_set(1.0);
    sum = dd_add(&sum, &one);
    return Dd { hi: scale2(sum.hi, m as i64), lo: scale2(sum.lo, m as i64) };
}

fn dd_log(g: &Globals, a: &Dd) -> Dd {
    let mut y: Dd = dd_set(d_log(a.hi));
    let mut i: i64 = 0;
    while i < 3 {
        let ny: Dd = Dd { hi: 0.0 - y.hi, lo: 0.0 - y.lo };
        let e: Dd = dd_exp(g, &ny);
        let mut t: Dd = dd_mul(a, &e);
        let one: Dd = dd_set(1.0);
        t = dd_sub(&t, &one);
        y = dd_add(&y, &t);
        i += 1;
    }
    return Dd { hi: y.hi, lo: y.lo };
}

// ---- correct rounding ----
fn round_to_double(g: &mut Globals, v: &Dd) -> f64 {
    let hi: f64 = v.hi;
    let half_ulp: f64 = d_abs(hi) * 1.1102230246251565e-16;
    let bound: f64 = d_abs(hi) * 8.077935669463161e-28;
    if d_abs(d_abs(v.lo) - half_ulp) <= bound || d_abs(v.lo) > half_ulp * 2.0 { g.hard_cases += 1; }
    return hi;
}

fn float_next(mut f: f32, dir: i64) -> f32 {
    let mut i: i32 = f.to_bits() as i32; // C: memcpy(&i, &f, 4)
    let mut b: i64 = i as i64;
    if (f as f64) > 0.0 { b = b + dir; } else { b = b - dir; }
    i = b as i32;
    f = f32::from_bits(i as u32); // C: memcpy(&f, &i, 4)
    return f;
}

#[allow(unused_assignments)] // `other = t` is overwritten before it is read, as in the C
fn round_to_float(g: &mut Globals, v: &Dd) -> f32 {
    let hi: f64 = v.hi;
    if hi == 0.0 { return 0.0f64 as f32; }
    let t: f32 = hi as f32;
    let t64: f64 = t as f64;
    if t64 == hi { return t; }
    let mut other: f32 = t;
    if t64 < hi { other = float_next(t, 1); } else { other = float_next(t, -1); }
    if hi < 0.0 {
        if t64 < hi { other = float_next(t, -1); } else { other = float_next(t, 1); }
    }
    let other64: f64 = other as f64;
    let mid: f64 = (t64 + other64) * 0.5;
    let d: f64 = (hi - mid) + v.lo;
    let bound: f64 = d_abs(hi) * 8.077935669463161e-28;
    if d_abs(d) <= bound { g.hard_cases += 1; }
    if d > 0.0 {
        if t64 > other64 { return t; }
        return other;
    }
    if t64 < other64 { return t; }
    return other;
}

// ---- cos and sin in double-double ----
fn dd_trig(g: &mut Globals, x: f64) {
    if x == 0.0 { g.rope_cos = dd_set(1.0); g.rope_sin = dd_set(0.0); return; }
    let k: f64 = d_floor(x * 0.6366197723675814 + 0.5);
    let q: i64 = (k as i64) % 4;
    let mut r: Dd;
    let mut p: Dd;
    r = dd_set(x);
    p = two_prod(k, g.halfpi1); r = dd_sub(&r, &p);
    p = two_prod(k, g.halfpi2); r = dd_sub(&r, &p);
    p = two_prod(k, g.halfpi3); r = dd_sub(&r, &p);
    p = two_prod(k, g.halfpi4); r = dd_sub(&r, &p);
    let r2: Dd = dd_mul(&r, &r);
    let mut s: Dd = r;
    let mut c: Dd;
    let mut ts: Dd = r;
    let mut tc: Dd;
    c = dd_set(1.0);
    tc = dd_set(1.0);
    let mut j: i64 = 1;
    while j < 18 {
        ts = dd_mul(&ts, &r2);
        ts = dd_div_d(&ts, ((2 * j) * (2 * j + 1)) as f64);
        tc = dd_mul(&tc, &r2);
        tc = dd_div_d(&tc, ((2 * j - 1) * (2 * j)) as f64);
        if j % 2 == 1 { s = dd_sub(&s, &ts); c = dd_sub(&c, &tc); }
        else { s = dd_add(&s, &ts); c = dd_add(&c, &tc); }
        j += 1;
    }
    if q == 0 { g.rope_sin = s; g.rope_cos = c; }
    else if q == 1 { g.rope_sin = c; g.rope_cos.hi = 0.0 - s.hi; g.rope_cos.lo = 0.0 - s.lo; }
    else if q == 2 { g.rope_sin.hi = 0.0 - s.hi; g.rope_sin.lo = 0.0 - s.lo; g.rope_cos.hi = 0.0 - c.hi; g.rope_cos.lo = 0.0 - c.lo; }
    else { g.rope_sin.hi = 0.0 - c.hi; g.rope_sin.lo = 0.0 - c.lo; g.rope_cos = s; }
}

// ---- fast path ----
fn prepare_fast(g: &mut Globals) {
    let mut f: f64 = 1.0;
    let mut n: i64 = 1;
    while n < 22 {
        f = f * (n as f64);
        let j: i64 = n / 2;
        let mut sign: f64 = 1.0;
        if j % 2 == 1 { sign = -1.0; }
        if n % 2 == 1 && n >= 3 { g.sin_coef[j as usize] = sign / f; }
        if n % 2 == 0 { g.cos_coef[j as usize] = sign / f; }
        n += 1;
    }
    g.fast_rel = scale2(1.0, -45);
    g.fast_abs = scale2(1.0, -97);
}

fn fast_trig(g: &mut Globals, x: f64) {
    let k: f64 = d_floor(x * 0.6366197723675814 + 0.5);
    let q: i64 = (k as i64) % 4;
    let r1: f64 = x - k * g.fhalfpi1;
    let p2: f64 = 0.0 - k * g.fhalfpi2;
    let r2: f64 = r1 + p2;
    let bb: f64 = r2 - r1;
    let e2: f64 = (r1 - (r2 - bb)) + (p2 - bb);
    let p3: f64 = 0.0 - k * g.fhalfpi3;
    let rh: f64 = r2 + p3;
    let bb2: f64 = rh - r2;
    let rl: f64 = ((r2 - (rh - bb2)) + (p3 - bb2)) + e2;
    let z: f64 = rh * rh;
    let mut ps: f64 = g.sin_coef[10];
    let mut j: i64 = 9;
    while j >= 1 { ps = ps * z + g.sin_coef[j as usize]; j -= 1; }
    let mut pc: f64 = g.cos_coef[10];
    let mut j2: i64 = 9;
    while j2 >= 1 { pc = pc * z + g.cos_coef[j2 as usize]; j2 -= 1; }
    let s0: f64 = rh + rh * (z * ps);
    let c0: f64 = 1.0 + z * pc;
    let s: f64 = s0 + rl * c0;
    let c: f64 = c0 - rl * s0;
    if q == 0 { g.fast_cos = c; g.fast_sin = s; }
    else if q == 1 { g.fast_cos = 0.0 - s; g.fast_sin = c; }
    else if q == 2 { g.fast_cos = 0.0 - c; g.fast_sin = 0.0 - s; }
    else { g.fast_cos = s; g.fast_sin = 0.0 - c; }
}

fn fast_float(g: &mut Globals, a: f64, bound: f64) -> f32 {
    let t: f32 = a as f32;
    let t64: f64 = t as f64;
    let lo: f64 = (t64 + (float_next(t, -1) as f64)) * 0.5;
    let hi: f64 = (t64 + (float_next(t, 1) as f64)) * 0.5;
    g.fast_sure = (a - lo > bound) && (hi - a > bound);
    return t;
}

// ---- table ----
fn rope_freq(g: &mut Globals, base: f64, i: i64, half: i64) -> f64 {
    if i == 0 { return 1.0; }
    let a: Dd;
    let mut l: Dd;
    let e: Dd;
    a = dd_set(base);
    l = dd_log(g, &a);
    l = dd_mul_d(&l, (0 - i) as f64);
    l = dd_mul_d(&l, 1.0 / (half as f64));
    e = dd_exp(g, &l);
    return round_to_double(g, &e);
}

fn rope_table(g: &mut Globals, maxlen: i64, base: f64, half: i64) {
    prepare_pi(g);
    prepare_fast(g);
    g.rope_cos_tab = vec![0.0; (maxlen * half) as usize]; // C: malloc(maxlen * half * 4)
    g.rope_sin_tab = vec![0.0; (maxlen * half) as usize];
    let mut freq: [f64; 64] = [0.0; 64]; // C: double freq[64]; (uninitialized there)
    let mut i: i64 = 0;
    while i < half { freq[i as usize] = rope_freq(g, base, i, half); i += 1; }
    let mut pos: i64 = 0;
    while pos < maxlen {
        let mut i2: i64 = 0;
        while i2 < half {
            let ang: f64 = (pos as f64) * freq[i2 as usize];
            let idx: i64 = pos * half + i2;
            let mut done: bool = false;
            if ang > 0.0 && ang < 131072.0 {
                fast_trig(g, ang);
                let fc: f32 = fast_float(g, g.fast_cos, d_abs(g.fast_cos) * g.fast_rel + g.fast_abs);
                let cc: bool = g.fast_sure;
                let fs: f32 = fast_float(g, g.fast_sin, d_abs(g.fast_sin) * g.fast_rel + g.fast_abs);
                if cc && g.fast_sure {
                    g.rope_cos_tab[idx as usize] = fc;
                    g.rope_sin_tab[idx as usize] = fs;
                    done = true;
                }
            }
            if !done {
                if ang > 0.0 { g.slow_cases += 1; }
                dd_trig(g, ang);
                // C: round_to_float(&rope_cos) -- copied first: &g.rope_cos cannot be lent while g is lent mutably
                let rc: Dd = g.rope_cos;
                g.rope_cos_tab[idx as usize] = round_to_float(g, &rc);
                let rs: Dd = g.rope_sin;
                g.rope_sin_tab[idx as usize] = round_to_float(g, &rs);
            }
            i2 += 1;
        }
        pos += 1;
    }
    if g.hard_cases > 0 {
        eprintln!("RoPE table: {} values too close to a rounding boundary", g.hard_cases);
        std::process::exit(1);
    }
}

fn main() {
    // the C statics' initial values
    let mut g: Globals = Globals {
        halfpi1: 0.0, halfpi2: 0.0, halfpi3: 0.0, halfpi4: 0.0,
        halfpi_dd: Dd { hi: 0.0, lo: 0.0 },
        dd_ln2: Dd { hi: 0.0, lo: 0.0 },
        fhalfpi1: 0.0, fhalfpi2: 0.0, fhalfpi3: 0.0,
        hard_cases: 0,
        rope_cos: Dd { hi: 0.0, lo: 0.0 }, rope_sin: Dd { hi: 0.0, lo: 0.0 },
        sin_coef: [0.0; 11],
        cos_coef: [0.0; 11],
        fast_rel: 0.0, fast_abs: 0.0, fast_cos: 0.0, fast_sin: 0.0,
        fast_sure: true,
        slow_cases: 0,
        rope_cos_tab: Vec::new(), rope_sin_tab: Vec::new(), // C: NULL until rope_table
    };
    rope_table(&mut g, 32768, 1000000.0, 64);
    let mut h: i64 = 0;
    let n: i64 = 32768 * 64;
    let mut k: i64 = 0;
    while k < n {
        let i: i32 = g.rope_cos_tab[k as usize].to_bits() as i32; // C: memcpy(&i, &rope_cos_tab[k], 4)
        h = ((h * 31) + ((i as i64) & 4294967295)) & 281474976710655;
        k += 1;
    }
    let mut k2: i64 = 0;
    while k2 < n {
        let i: i32 = g.rope_sin_tab[k2 as usize].to_bits() as i32;
        h = ((h * 31) + ((i as i64) & 4294967295)) & 281474976710655;
        k2 += 1;
    }
    println!("{} {} {}", h, g.slow_cases, g.hard_cases);
}
