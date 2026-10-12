/* RoPE table -- the same algorithm as rope.gl (GeulPU host/로프.gl): double-double arithmetic, a fixed-point big integer for pi
   (Machin), a fp64 polynomial fast path with a rigorous error bound and correct rounding to float32, and the geul standard
   library's math helpers (absolute value, floor, scaling by 2^n, natural log) written the same way.
   Build with -ffp-contract=off: geul never fuses a multiply and an add unless the source says so. */
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

/* ---- the geul standard library's math (표준/수학.gl) ---- */
static int64_t dbits(double x) { int64_t i; memcpy(&i, &x, 8); return i; }
static double bitsd(int64_t b) { double f; memcpy(&f, &b, 8); return f; }
static double d_abs(double v) { return bitsd(dbits(v) & 9223372036854775807LL); }
static int is_inf(double x) { return (dbits(x) & 9223372036854775807LL) == 9218868437227405312LL; }
static int is_nan(double x) { return (dbits(x) & 9223372036854775807LL) > 9218868437227405312LL; }
static double d_nan(void) { return bitsd(9221120237041090560LL); }
static double d_inf(void) { return bitsd(9218868437227405312LL); }
static const double LN2 = 0.69314718055994530942;

static double scale2(double x, int64_t n) {
    while (n > 1000) { x = x * 8.98846567431158e307; n = n - 1023; }
    while (n < -1000) { x = x * 1.1125369292536007e-308; n = n + 1022; }
    return x * bitsd((n + 1023) << 52);
}

static double d_floor(double v) {
    if (is_inf(v) || is_nan(v)) return v;
    if (v >= 4503599627370496.0 || v <= -4503599627370496.0) return v;
    int64_t n = (int64_t)v;
    double r = (double)n;
    if (r > v) return r - 1.0;
    return r;
}

static double d_log(double v) {
    if (is_nan(v)) return v;
    if (v < 0.0) return d_nan();
    if (v == 0.0) return 0.0 - d_inf();
    if (is_inf(v)) return v;
    int64_t bits = dbits(v);
    int64_t ex = ((bits >> 52) & 2047);
    double m = v;
    int64_t e = 0;
    if (ex == 0) {
        m = v * 18014398509481984.0;
        bits = dbits(m);
        ex = ((bits >> 52) & 2047);
        e = -54;
    }
    e = e + ex - 1023;
    m = bitsd((bits & 4503599627370495LL) | 4607182418800017408LL);
    if (m > 1.4142135623730951) { m = m * 0.5; e = e + 1; }
    double s = (m - 1.0) / (m + 1.0);
    double s2 = s * s;
    double term = s;
    double sum = 0.0;
    for (int64_t n = 1; n < 60; n += 2) {
        sum = sum + term / (double)n;
        term = term * s2;
        if (d_abs(term) < 1.0e-18) break;
    }
    return 2.0 * sum + (double)e * LN2;
}

/* ---- double-double ---- */
typedef struct { double hi, lo; } dd;

static void two_sum(dd *r, double a, double b) {
    double s = a + b;
    double bb = s - a;
    r->hi = s;
    r->lo = (a - (s - bb)) + (b - bb);
}

static void fast_sum(dd *r, double a, double b) {
    double s = a + b;
    r->hi = s;
    r->lo = b - (s - a);
}

static void two_prod(dd *r, double a, double b) {
    double p = a * b;
    double ta = 134217729.0 * a;
    double ah = ta - (ta - a);
    double al = a - ah;
    double tb = 134217729.0 * b;
    double bh = tb - (tb - b);
    double bl = b - bh;
    r->hi = p;
    r->lo = ((ah * bh - p) + ah * bl + al * bh) + al * bl;
}

static void dd_add(dd *r, dd *a, dd *b) {
    dd s, t, v;
    two_sum(&s, a->hi, b->hi);
    two_sum(&t, a->lo, b->lo);
    double c = s.lo + t.hi;
    fast_sum(&v, s.hi, c);
    double w = t.lo + v.lo;
    fast_sum(r, v.hi, w);
}

static void dd_sub(dd *r, dd *a, dd *b) {
    dd nb;
    nb.hi = 0.0 - b->hi;
    nb.lo = 0.0 - b->lo;
    dd_add(r, a, &nb);
}

static void dd_mul(dd *r, dd *a, dd *b) {
    dd p;
    two_prod(&p, a->hi, b->hi);
    double e = p.lo + (a->hi * b->lo + a->lo * b->hi);
    fast_sum(r, p.hi, e);
}

static void dd_mul_d(dd *r, dd *a, double d) {
    dd p;
    two_prod(&p, a->hi, d);
    double e = p.lo + a->lo * d;
    fast_sum(r, p.hi, e);
}

static void dd_div(dd *r, dd *a, dd *b) {
    double q1 = a->hi / b->hi;
    dd t, rr;
    dd_mul_d(&t, b, q1);
    dd_sub(&rr, a, &t);
    double q2 = rr.hi / b->hi;
    dd_mul_d(&t, b, q2);
    dd_sub(&rr, &rr, &t);
    double q3 = rr.hi / b->hi;
    dd q, q3d;
    fast_sum(&q, q1, q2);
    q3d.hi = q3;
    q3d.lo = 0.0;
    dd_add(r, &q, &q3d);
}

static void dd_set(dd *r, double a) { r->hi = a; r->lo = 0.0; }

static void dd_div_d(dd *r, dd *a, double d) {
    dd b;
    b.hi = d;
    b.lo = 0.0;
    dd_div(r, a, &b);
}

/* ---- fixed-point big integer: word 0 integer part, words 1..8 fraction (32 bits each) ---- */
#define BIGW 9

static void big_zero(int64_t *a) { for (int64_t i = 0; i < BIGW; i += 1) a[i] = 0; }

static int big_is_zero(int64_t *a) {
    for (int64_t i = 0; i < BIGW; i += 1) if (a[i] != 0) return 0;
    return 1;
}

static void big_div_small(int64_t *a, int64_t d) {
    int64_t rem = 0;
    for (int64_t i = 0; i < BIGW; i += 1) {
        int64_t cur = (rem << 32) + a[i];
        a[i] = cur / d;
        rem = cur % d;
    }
}

static void big_add(int64_t *a, int64_t *b) {
    int64_t carry = 0;
    for (int64_t i = BIGW - 1; i >= 0; i -= 1) {
        int64_t s = a[i] + b[i] + carry;
        a[i] = s & 4294967295LL;
        carry = s >> 32;
    }
}

static void big_sub(int64_t *a, int64_t *b) {
    int64_t borrow = 0;
    for (int64_t i = BIGW - 1; i >= 0; i -= 1) {
        int64_t s = a[i] - b[i] - borrow;
        borrow = 0;
        if (s < 0) { s = s + 4294967296LL; borrow = 1; }
        a[i] = s;
    }
}

static void big_mul_small(int64_t *a, int64_t m) {
    int64_t carry = 0;
    for (int64_t i = BIGW - 1; i >= 0; i -= 1) {
        int64_t s = a[i] * m + carry;
        a[i] = s & 4294967295LL;
        carry = s >> 32;
    }
}

static void big_atan_inv(int64_t *sum, int64_t x) {
    int64_t pw[BIGW], term[BIGW];
    big_zero(pw);
    pw[0] = 1;
    big_div_small(pw, x);
    big_zero(sum);
    big_add(sum, pw);
    int64_t j = 1;
    for (;;) {
        big_div_small(pw, x * x);
        for (int64_t i = 0; i < BIGW; i += 1) term[i] = pw[i];
        big_div_small(term, 2 * j + 1);
        if (big_is_zero(term)) break;
        if (j % 2 == 1) big_sub(sum, term); else big_add(sum, term);
        j += 1;
    }
}

static int64_t big_bit(int64_t *a, int64_t n) {
    if (n == 0) return a[0] & 1;
    return (a[(n - 1) / 32 + 1] >> (31 - (n - 1) % 32)) & 1;
}

static void big_bit_clear(int64_t *a, int64_t n) {
    if (n == 0) { a[0] = a[0] & (0 - 2); return; }
    int64_t i = (n - 1) / 32 + 1;
    a[i] = a[i] & (4294967295LL ^ ((int64_t)1 << (31 - (n - 1) % 32)));
}

static double big_take_top(int64_t *a, int64_t nbits) {
    int64_t n0 = 0;
    while (n0 <= 256 && big_bit(a, n0) == 0) n0 += 1;
    if (n0 > 256) return 0.0;
    int64_t M = 0;
    for (int64_t j = 0; j < nbits; j += 1) {
        int64_t n = n0 + j;
        int64_t b = 0;
        if (n <= 256) b = big_bit(a, n);
        M = (M << 1) | b;
        if (n <= 256 && b == 1) big_bit_clear(a, n);
    }
    return scale2((double)M, 0 - n0 - (nbits - 1));
}

static double big_take_double(int64_t *a) { return big_take_top(a, 53); }

static double halfpi1 = 0.0, halfpi2 = 0.0, halfpi3 = 0.0, halfpi4 = 0.0;
static dd halfpi_dd;
static dd dd_ln2;
static double fhalfpi1 = 0.0, fhalfpi2 = 0.0, fhalfpi3 = 0.0;

static void prepare_pi(void) {
    int64_t a[BIGW], b[BIGW], c[BIGW];
    big_atan_inv(a, 5);
    big_mul_small(a, 16);
    big_atan_inv(b, 239);
    big_mul_small(b, 4);
    big_sub(a, b);
    big_div_small(a, 2);
    for (int64_t i = 0; i < BIGW; i += 1) c[i] = a[i];
    fhalfpi1 = big_take_top(c, 36);
    fhalfpi2 = big_take_top(c, 36);
    fhalfpi3 = big_take_top(c, 53);
    halfpi1 = big_take_double(a);
    halfpi2 = big_take_double(a);
    halfpi3 = big_take_double(a);
    halfpi4 = big_take_double(a);
    fast_sum(&halfpi_dd, halfpi1, halfpi2);
    dd t, one, t2, pw, sum;
    dd_set(&one, 1.0);
    dd_div_d(&t, &one, 3.0);
    dd_mul(&t2, &t, &t);
    pw = t;
    sum = t;
    for (int64_t j = 1; j < 40; j += 1) {
        dd_mul(&pw, &pw, &t2);
        dd term;
        dd_div_d(&term, &pw, (double)(2 * j + 1));
        dd_add(&sum, &sum, &term);
    }
    dd_mul_d(&dd_ln2, &sum, 2.0);
}

static void dd_exp(dd *r, dd *a) {
    if (a->hi == 0.0) { dd_set(r, 1.0); return; }
    double m = d_floor(a->hi / dd_ln2.hi + 0.5);
    dd s, x;
    dd_mul_d(&s, &dd_ln2, m);
    dd_sub(&x, a, &s);
    dd_mul_d(&x, &x, 1.0 / 512.0);
    dd sum = x, term = x;
    for (int64_t n = 2; n < 20; n += 1) {
        dd_mul(&term, &term, &x);
        dd_div_d(&term, &term, (double)n);
        dd_add(&sum, &sum, &term);
    }
    for (int64_t i = 0; i < 9; i += 1) {
        dd sq;
        dd_mul(&sq, &sum, &sum);
        dd_mul_d(&sum, &sum, 2.0);
        dd_add(&sum, &sum, &sq);
    }
    dd one;
    dd_set(&one, 1.0);
    dd_add(&sum, &sum, &one);
    r->hi = scale2(sum.hi, (int64_t)m);
    r->lo = scale2(sum.lo, (int64_t)m);
}

static void dd_log(dd *r, dd *a) {
    dd y;
    dd_set(&y, d_log(a->hi));
    for (int64_t i = 0; i < 3; i += 1) {
        dd ny, e, t, one;
        ny.hi = 0.0 - y.hi; ny.lo = 0.0 - y.lo;
        dd_exp(&e, &ny);
        dd_mul(&t, a, &e);
        dd_set(&one, 1.0);
        dd_sub(&t, &t, &one);
        dd_add(&y, &y, &t);
    }
    r->hi = y.hi; r->lo = y.lo;
}

/* ---- correct rounding ---- */
static int64_t hard_cases = 0;

static double round_to_double(dd *v) {
    double hi = v->hi;
    double half_ulp = d_abs(hi) * 1.1102230246251565e-16;
    double bound = d_abs(hi) * 8.077935669463161e-28;
    if (d_abs(d_abs(v->lo) - half_ulp) <= bound || d_abs(v->lo) > half_ulp * 2.0) hard_cases += 1;
    return hi;
}

static float float_next(float f, int64_t dir) {
    int32_t i;
    memcpy(&i, &f, 4);
    int64_t b = i;
    if (f > 0.0) b = b + dir; else b = b - dir;
    i = (int32_t)b;
    memcpy(&f, &i, 4);
    return f;
}

static float round_to_float(dd *v) {
    double hi = v->hi;
    if (hi == 0.0) return (float)0.0;
    float t = (float)hi;
    double t64 = (double)t;
    if (t64 == hi) return t;
    float other = t;
    if (t64 < hi) other = float_next(t, 1); else other = float_next(t, -1);
    if (hi < 0.0) {
        if (t64 < hi) other = float_next(t, -1); else other = float_next(t, 1);
    }
    double other64 = (double)other;
    double mid = (t64 + other64) * 0.5;
    double d = (hi - mid) + v->lo;
    double bound = d_abs(hi) * 8.077935669463161e-28;
    if (d_abs(d) <= bound) hard_cases += 1;
    if (d > 0.0) {
        if (t64 > other64) return t;
        return other;
    }
    if (t64 < other64) return t;
    return other;
}

/* ---- cos and sin in double-double ---- */
static dd rope_cos, rope_sin;

static void dd_trig(double x) {
    if (x == 0.0) { dd_set(&rope_cos, 1.0); dd_set(&rope_sin, 0.0); return; }
    double k = d_floor(x * 0.6366197723675814 + 0.5);
    int64_t q = (int64_t)k % 4;
    dd r, p;
    dd_set(&r, x);
    two_prod(&p, k, halfpi1); dd_sub(&r, &r, &p);
    two_prod(&p, k, halfpi2); dd_sub(&r, &r, &p);
    two_prod(&p, k, halfpi3); dd_sub(&r, &r, &p);
    two_prod(&p, k, halfpi4); dd_sub(&r, &r, &p);
    dd r2;
    dd_mul(&r2, &r, &r);
    dd s = r, c, ts = r, tc;
    dd_set(&c, 1.0);
    dd_set(&tc, 1.0);
    for (int64_t j = 1; j < 18; j += 1) {
        dd_mul(&ts, &ts, &r2);
        dd_div_d(&ts, &ts, (double)((2 * j) * (2 * j + 1)));
        dd_mul(&tc, &tc, &r2);
        dd_div_d(&tc, &tc, (double)((2 * j - 1) * (2 * j)));
        if (j % 2 == 1) { dd_sub(&s, &s, &ts); dd_sub(&c, &c, &tc); }
        else { dd_add(&s, &s, &ts); dd_add(&c, &c, &tc); }
    }
    if (q == 0) { rope_sin = s; rope_cos = c; }
    else if (q == 1) { rope_sin = c; rope_cos.hi = 0.0 - s.hi; rope_cos.lo = 0.0 - s.lo; }
    else if (q == 2) { rope_sin.hi = 0.0 - s.hi; rope_sin.lo = 0.0 - s.lo; rope_cos.hi = 0.0 - c.hi; rope_cos.lo = 0.0 - c.lo; }
    else { rope_sin.hi = 0.0 - c.hi; rope_sin.lo = 0.0 - c.lo; rope_cos = s; }
}

/* ---- fast path ---- */
static double sin_coef[11];
static double cos_coef[11];
static double fast_rel = 0.0, fast_abs = 0.0, fast_cos = 0.0, fast_sin = 0.0;
static int fast_sure = 1;
static int64_t slow_cases = 0;

static void prepare_fast(void) {
    double f = 1.0;
    for (int64_t n = 1; n < 22; n += 1) {
        f = f * (double)n;
        int64_t j = n / 2;
        double sign = 1.0;
        if (j % 2 == 1) sign = -1.0;
        if (n % 2 == 1 && n >= 3) sin_coef[j] = sign / f;
        if (n % 2 == 0) cos_coef[j] = sign / f;
    }
    fast_rel = scale2(1.0, -45);
    fast_abs = scale2(1.0, -97);
}

static void fast_trig(double x) {
    double k = d_floor(x * 0.6366197723675814 + 0.5);
    int64_t q = (int64_t)k % 4;
    double r1 = x - k * fhalfpi1;
    double p2 = 0.0 - k * fhalfpi2;
    double r2 = r1 + p2;
    double bb = r2 - r1;
    double e2 = (r1 - (r2 - bb)) + (p2 - bb);
    double p3 = 0.0 - k * fhalfpi3;
    double rh = r2 + p3;
    double bb2 = rh - r2;
    double rl = ((r2 - (rh - bb2)) + (p3 - bb2)) + e2;
    double z = rh * rh;
    double ps = sin_coef[10];
    for (int64_t j = 9; j >= 1; j -= 1) ps = ps * z + sin_coef[j];
    double pc = cos_coef[10];
    for (int64_t j2 = 9; j2 >= 1; j2 -= 1) pc = pc * z + cos_coef[j2];
    double s0 = rh + rh * (z * ps);
    double c0 = 1.0 + z * pc;
    double s = s0 + rl * c0;
    double c = c0 - rl * s0;
    if (q == 0) { fast_cos = c; fast_sin = s; }
    else if (q == 1) { fast_cos = 0.0 - s; fast_sin = c; }
    else if (q == 2) { fast_cos = 0.0 - c; fast_sin = 0.0 - s; }
    else { fast_cos = s; fast_sin = 0.0 - c; }
}

static float fast_float(double a, double bound) {
    float t = (float)a;
    double t64 = (double)t;
    double lo = (t64 + (double)float_next(t, -1)) * 0.5;
    double hi = (t64 + (double)float_next(t, 1)) * 0.5;
    fast_sure = (a - lo > bound) && (hi - a > bound);
    return t;
}

/* ---- table ---- */
static float *rope_cos_tab, *rope_sin_tab;

static double rope_freq(double base, int64_t i, int64_t half) {
    if (i == 0) return 1.0;
    dd a, l, e;
    dd_set(&a, base);
    dd_log(&l, &a);
    dd_mul_d(&l, &l, (double)(0 - i));
    dd_mul_d(&l, &l, 1.0 / (double)half);
    dd_exp(&e, &l);
    return round_to_double(&e);
}

static void rope_table(int64_t maxlen, double base, int64_t half) {
    prepare_pi();
    prepare_fast();
    rope_cos_tab = malloc(maxlen * half * 4);
    rope_sin_tab = malloc(maxlen * half * 4);
    double freq[64];
    for (int64_t i = 0; i < half; i += 1) freq[i] = rope_freq(base, i, half);
    for (int64_t pos = 0; pos < maxlen; pos += 1) {
        for (int64_t i2 = 0; i2 < half; i2 += 1) {
            double ang = (double)pos * freq[i2];
            int64_t idx = pos * half + i2;
            int done = 0;
            if (ang > 0.0 && ang < 131072.0) {
                fast_trig(ang);
                float fc = fast_float(fast_cos, d_abs(fast_cos) * fast_rel + fast_abs);
                int cc = fast_sure;
                float fs = fast_float(fast_sin, d_abs(fast_sin) * fast_rel + fast_abs);
                if (cc && fast_sure) {
                    rope_cos_tab[idx] = fc;
                    rope_sin_tab[idx] = fs;
                    done = 1;
                }
            }
            if (!done) {
                if (ang > 0.0) slow_cases += 1;
                dd_trig(ang);
                rope_cos_tab[idx] = round_to_float(&rope_cos);
                rope_sin_tab[idx] = round_to_float(&rope_sin);
            }
        }
    }
    if (hard_cases > 0) {
        fprintf(stderr, "RoPE table: %lld values too close to a rounding boundary\n", (long long)hard_cases);
        exit(1);
    }
}

int main(void) {
    rope_table(32768, 1000000.0, 64);
    int64_t h = 0;
    int64_t n = 32768 * 64;
    for (int64_t k = 0; k < n; k += 1) {
        int32_t i;
        memcpy(&i, &rope_cos_tab[k], 4);
        h = ((h * 31) + ((int64_t)i & 4294967295LL)) & 281474976710655LL;
    }
    for (int64_t k2 = 0; k2 < n; k2 += 1) {
        int32_t i;
        memcpy(&i, &rope_sin_tab[k2], 4);
        h = ((h * 31) + ((int64_t)i & 4294967295LL)) & 281474976710655LL;
    }
    printf("%lld %lld %lld\n", (long long)h, (long long)slow_cases, (long long)hard_cases);
    return 0;
}
