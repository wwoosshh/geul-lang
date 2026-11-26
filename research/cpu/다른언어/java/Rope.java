/* RoPE table -- line-by-line Java port of research/cpu/rope.c (pair: rope.gl, GeulPU host/rope): double-double arithmetic,
   a fixed-point big integer for pi (Machin), a fp64 polynomial fast path with a rigorous error bound and correct rounding to
   float32, and the geul standard library's math helpers (absolute value, floor, scaling by 2^n, natural log) written the same way.
   Java never fuses a multiply and an add (the C is built with -ffp-contract=off for the same reason).
   C locals of struct type become `new DD()` in the same block; C struct assignment becomes a field-by-field copy. */
public class Rope {
    /* ---- the geul standard library's math ---- */
    static long dbits(double x) { return Double.doubleToRawLongBits(x); }
    static double bitsd(long b) { return Double.longBitsToDouble(b); }
    static double dAbs(double v) { return bitsd(dbits(v) & 9223372036854775807L); }
    static boolean isInf(double x) { return (dbits(x) & 9223372036854775807L) == 9218868437227405312L; }
    static boolean isNan(double x) { return (dbits(x) & 9223372036854775807L) > 9218868437227405312L; }
    static double dNan() { return bitsd(9221120237041090560L); }
    static double dInf() { return bitsd(9218868437227405312L); }
    static final double LN2 = 0.69314718055994530942;

    static double scale2(double x, long n) {
        while (n > 1000) { x = x * 8.98846567431158e307; n = n - 1023; }
        while (n < -1000) { x = x * 1.1125369292536007e-308; n = n + 1022; }
        return x * bitsd((n + 1023) << 52);
    }

    static double dFloor(double v) {
        if (isInf(v) || isNan(v)) return v;
        if (v >= 4503599627370496.0 || v <= -4503599627370496.0) return v;
        long n = (long)v;
        double r = (double)n;
        if (r > v) return r - 1.0;
        return r;
    }

    static double dLog(double v) {
        if (isNan(v)) return v;
        if (v < 0.0) return dNan();
        if (v == 0.0) return 0.0 - dInf();
        if (isInf(v)) return v;
        long bits = dbits(v);
        long ex = ((bits >> 52) & 2047);
        double m = v;
        long e = 0;
        if (ex == 0) {
            m = v * 18014398509481984.0;
            bits = dbits(m);
            ex = ((bits >> 52) & 2047);
            e = -54;
        }
        e = e + ex - 1023;
        m = bitsd((bits & 4503599627370495L) | 4607182418800017408L);
        if (m > 1.4142135623730951) { m = m * 0.5; e = e + 1; }
        double s = (m - 1.0) / (m + 1.0);
        double s2 = s * s;
        double term = s;
        double sum = 0.0;
        for (long n = 1; n < 60; n += 2) {
            sum = sum + term / (double)n;
            term = term * s2;
            if (dAbs(term) < 1.0e-18) break;
        }
        return 2.0 * sum + (double)e * LN2;
    }

    /* ---- double-double ---- */
    /* typedef struct { double hi, lo; } dd; */
    static final class DD {
        double hi, lo;
    }

    static void twoSum(DD r, double a, double b) {
        double s = a + b;
        double bb = s - a;
        r.hi = s;
        r.lo = (a - (s - bb)) + (b - bb);
    }

    static void fastSum(DD r, double a, double b) {
        double s = a + b;
        r.hi = s;
        r.lo = b - (s - a);
    }

    static void twoProd(DD r, double a, double b) {
        double p = a * b;
        double ta = 134217729.0 * a;
        double ah = ta - (ta - a);
        double al = a - ah;
        double tb = 134217729.0 * b;
        double bh = tb - (tb - b);
        double bl = b - bh;
        r.hi = p;
        r.lo = ((ah * bh - p) + ah * bl + al * bh) + al * bl;
    }

    static void ddAdd(DD r, DD a, DD b) {
        DD s = new DD(), t = new DD(), v = new DD();
        twoSum(s, a.hi, b.hi);
        twoSum(t, a.lo, b.lo);
        double c = s.lo + t.hi;
        fastSum(v, s.hi, c);
        double w = t.lo + v.lo;
        fastSum(r, v.hi, w);
    }

    static void ddSub(DD r, DD a, DD b) {
        DD nb = new DD();
        nb.hi = 0.0 - b.hi;
        nb.lo = 0.0 - b.lo;
        ddAdd(r, a, nb);
    }

    static void ddMul(DD r, DD a, DD b) {
        DD p = new DD();
        twoProd(p, a.hi, b.hi);
        double e = p.lo + (a.hi * b.lo + a.lo * b.hi);
        fastSum(r, p.hi, e);
    }

    static void ddMulD(DD r, DD a, double d) {
        DD p = new DD();
        twoProd(p, a.hi, d);
        double e = p.lo + a.lo * d;
        fastSum(r, p.hi, e);
    }

    static void ddDiv(DD r, DD a, DD b) {
        double q1 = a.hi / b.hi;
        DD t = new DD(), rr = new DD();
        ddMulD(t, b, q1);
        ddSub(rr, a, t);
        double q2 = rr.hi / b.hi;
        ddMulD(t, b, q2);
        ddSub(rr, rr, t);
        double q3 = rr.hi / b.hi;
        DD q = new DD(), q3d = new DD();
        fastSum(q, q1, q2);
        q3d.hi = q3;
        q3d.lo = 0.0;
        ddAdd(r, q, q3d);
    }

    static void ddSet(DD r, double a) { r.hi = a; r.lo = 0.0; }

    static void ddDivD(DD r, DD a, double d) {
        DD b = new DD();
        b.hi = d;
        b.lo = 0.0;
        ddDiv(r, a, b);
    }

    /* ---- fixed-point big integer: word 0 integer part, words 1..8 fraction (32 bits each) ---- */
    static final int BIGW = 9;

    static void bigZero(long[] a) { for (long i = 0; i < BIGW; i += 1) a[(int)i] = 0; }

    static boolean bigIsZero(long[] a) {
        for (long i = 0; i < BIGW; i += 1) if (a[(int)i] != 0) return false;
        return true;
    }

    static void bigDivSmall(long[] a, long d) {
        long rem = 0;
        for (long i = 0; i < BIGW; i += 1) {
            long cur = (rem << 32) + a[(int)i];
            a[(int)i] = cur / d;
            rem = cur % d;
        }
    }

    static void bigAdd(long[] a, long[] b) {
        long carry = 0;
        for (long i = BIGW - 1; i >= 0; i -= 1) {
            long s = a[(int)i] + b[(int)i] + carry;
            a[(int)i] = s & 4294967295L;
            carry = s >> 32;
        }
    }

    static void bigSub(long[] a, long[] b) {
        long borrow = 0;
        for (long i = BIGW - 1; i >= 0; i -= 1) {
            long s = a[(int)i] - b[(int)i] - borrow;
            borrow = 0;
            if (s < 0) { s = s + 4294967296L; borrow = 1; }
            a[(int)i] = s;
        }
    }

    static void bigMulSmall(long[] a, long m) {
        long carry = 0;
        for (long i = BIGW - 1; i >= 0; i -= 1) {
            long s = a[(int)i] * m + carry;
            a[(int)i] = s & 4294967295L;
            carry = s >> 32;
        }
    }

    static void bigAtanInv(long[] sum, long x) {
        long[] pw = new long[BIGW], term = new long[BIGW];
        bigZero(pw);
        pw[0] = 1;
        bigDivSmall(pw, x);
        bigZero(sum);
        bigAdd(sum, pw);
        long j = 1;
        for (;;) {
            bigDivSmall(pw, x * x);
            for (long i = 0; i < BIGW; i += 1) term[(int)i] = pw[(int)i];
            bigDivSmall(term, 2 * j + 1);
            if (bigIsZero(term)) break;
            if (j % 2 == 1) bigSub(sum, term); else bigAdd(sum, term);
            j += 1;
        }
    }

    static long bigBit(long[] a, long n) {
        if (n == 0) return a[0] & 1;
        return (a[(int)((n - 1) / 32 + 1)] >> (31 - (n - 1) % 32)) & 1;
    }

    static void bigBitClear(long[] a, long n) {
        if (n == 0) { a[0] = a[0] & (0 - 2); return; }
        long i = (n - 1) / 32 + 1;
        a[(int)i] = a[(int)i] & (4294967295L ^ ((long)1 << (31 - (n - 1) % 32)));
    }

    static double bigTakeTop(long[] a, long nbits) {
        long n0 = 0;
        while (n0 <= 256 && bigBit(a, n0) == 0) n0 += 1;
        if (n0 > 256) return 0.0;
        long M = 0;
        for (long j = 0; j < nbits; j += 1) {
            long n = n0 + j;
            long b = 0;
            if (n <= 256) b = bigBit(a, n);
            M = (M << 1) | b;
            if (n <= 256 && b == 1) bigBitClear(a, n);
        }
        return scale2((double)M, 0 - n0 - (nbits - 1));
    }

    static double bigTakeDouble(long[] a) { return bigTakeTop(a, 53); }

    static double halfpi1 = 0.0, halfpi2 = 0.0, halfpi3 = 0.0, halfpi4 = 0.0;
    static final DD halfpiDd = new DD();
    static final DD ddLn2 = new DD();
    static double fhalfpi1 = 0.0, fhalfpi2 = 0.0, fhalfpi3 = 0.0;

    static void preparePi() {
        long[] a = new long[BIGW], b = new long[BIGW], c = new long[BIGW];
        bigAtanInv(a, 5);
        bigMulSmall(a, 16);
        bigAtanInv(b, 239);
        bigMulSmall(b, 4);
        bigSub(a, b);
        bigDivSmall(a, 2);
        for (long i = 0; i < BIGW; i += 1) c[(int)i] = a[(int)i];
        fhalfpi1 = bigTakeTop(c, 36);
        fhalfpi2 = bigTakeTop(c, 36);
        fhalfpi3 = bigTakeTop(c, 53);
        halfpi1 = bigTakeDouble(a);
        halfpi2 = bigTakeDouble(a);
        halfpi3 = bigTakeDouble(a);
        halfpi4 = bigTakeDouble(a);
        fastSum(halfpiDd, halfpi1, halfpi2);
        DD t = new DD(), one = new DD(), t2 = new DD(), pw = new DD(), sum = new DD();
        ddSet(one, 1.0);
        ddDivD(t, one, 3.0);
        ddMul(t2, t, t);
        pw.hi = t.hi; pw.lo = t.lo;   /* pw = t */
        sum.hi = t.hi; sum.lo = t.lo; /* sum = t */
        for (long j = 1; j < 40; j += 1) {
            ddMul(pw, pw, t2);
            DD term = new DD();
            ddDivD(term, pw, (double)(2 * j + 1));
            ddAdd(sum, sum, term);
        }
        ddMulD(ddLn2, sum, 2.0);
    }

    static void ddExp(DD r, DD a) {
        if (a.hi == 0.0) { ddSet(r, 1.0); return; }
        double m = dFloor(a.hi / ddLn2.hi + 0.5);
        DD s = new DD(), x = new DD();
        ddMulD(s, ddLn2, m);
        ddSub(x, a, s);
        ddMulD(x, x, 1.0 / 512.0);
        DD sum = new DD(), term = new DD();
        sum.hi = x.hi; sum.lo = x.lo;   /* sum = x */
        term.hi = x.hi; term.lo = x.lo; /* term = x */
        for (long n = 2; n < 20; n += 1) {
            ddMul(term, term, x);
            ddDivD(term, term, (double)n);
            ddAdd(sum, sum, term);
        }
        for (long i = 0; i < 9; i += 1) {
            DD sq = new DD();
            ddMul(sq, sum, sum);
            ddMulD(sum, sum, 2.0);
            ddAdd(sum, sum, sq);
        }
        DD one = new DD();
        ddSet(one, 1.0);
        ddAdd(sum, sum, one);
        r.hi = scale2(sum.hi, (long)m);
        r.lo = scale2(sum.lo, (long)m);
    }

    static void ddLog(DD r, DD a) {
        DD y = new DD();
        ddSet(y, dLog(a.hi));
        for (long i = 0; i < 3; i += 1) {
            DD ny = new DD(), e = new DD(), t = new DD(), one = new DD();
            ny.hi = 0.0 - y.hi; ny.lo = 0.0 - y.lo;
            ddExp(e, ny);
            ddMul(t, a, e);
            ddSet(one, 1.0);
            ddSub(t, t, one);
            ddAdd(y, y, t);
        }
        r.hi = y.hi; r.lo = y.lo;
    }

    /* ---- correct rounding ---- */
    static long hardCases = 0;

    static double roundToDouble(DD v) {
        double hi = v.hi;
        double halfUlp = dAbs(hi) * 1.1102230246251565e-16;
        double bound = dAbs(hi) * 8.077935669463161e-28;
        if (dAbs(dAbs(v.lo) - halfUlp) <= bound || dAbs(v.lo) > halfUlp * 2.0) hardCases += 1;
        return hi;
    }

    static float floatNext(float f, long dir) {
        int i;
        i = Float.floatToRawIntBits(f);
        long b = i;
        if (f > 0.0) b = b + dir; else b = b - dir;
        i = (int)b;
        f = Float.intBitsToFloat(i);
        return f;
    }

    static float roundToFloat(DD v) {
        double hi = v.hi;
        if (hi == 0.0) return (float)0.0;
        float t = (float)hi;
        double t64 = (double)t;
        if (t64 == hi) return t;
        float other = t;
        if (t64 < hi) other = floatNext(t, 1); else other = floatNext(t, -1);
        if (hi < 0.0) {
            if (t64 < hi) other = floatNext(t, -1); else other = floatNext(t, 1);
        }
        double other64 = (double)other;
        double mid = (t64 + other64) * 0.5;
        double d = (hi - mid) + v.lo;
        double bound = dAbs(hi) * 8.077935669463161e-28;
        if (dAbs(d) <= bound) hardCases += 1;
        if (d > 0.0) {
            if (t64 > other64) return t;
            return other;
        }
        if (t64 < other64) return t;
        return other;
    }

    /* ---- cos and sin in double-double ---- */
    static final DD ropeCos = new DD(), ropeSin = new DD();

    static void ddTrig(double x) {
        if (x == 0.0) { ddSet(ropeCos, 1.0); ddSet(ropeSin, 0.0); return; }
        double k = dFloor(x * 0.6366197723675814 + 0.5);
        long q = (long)k % 4;
        DD r = new DD(), p = new DD();
        ddSet(r, x);
        twoProd(p, k, halfpi1); ddSub(r, r, p);
        twoProd(p, k, halfpi2); ddSub(r, r, p);
        twoProd(p, k, halfpi3); ddSub(r, r, p);
        twoProd(p, k, halfpi4); ddSub(r, r, p);
        DD r2 = new DD();
        ddMul(r2, r, r);
        DD s = new DD(), c = new DD(), ts = new DD(), tc = new DD();
        s.hi = r.hi; s.lo = r.lo;   /* s = r */
        ts.hi = r.hi; ts.lo = r.lo; /* ts = r */
        ddSet(c, 1.0);
        ddSet(tc, 1.0);
        for (long j = 1; j < 18; j += 1) {
            ddMul(ts, ts, r2);
            ddDivD(ts, ts, (double)((2 * j) * (2 * j + 1)));
            ddMul(tc, tc, r2);
            ddDivD(tc, tc, (double)((2 * j - 1) * (2 * j)));
            if (j % 2 == 1) { ddSub(s, s, ts); ddSub(c, c, tc); }
            else { ddAdd(s, s, ts); ddAdd(c, c, tc); }
        }
        if (q == 0) { ropeSin.hi = s.hi; ropeSin.lo = s.lo; ropeCos.hi = c.hi; ropeCos.lo = c.lo; }
        else if (q == 1) { ropeSin.hi = c.hi; ropeSin.lo = c.lo; ropeCos.hi = 0.0 - s.hi; ropeCos.lo = 0.0 - s.lo; }
        else if (q == 2) { ropeSin.hi = 0.0 - s.hi; ropeSin.lo = 0.0 - s.lo; ropeCos.hi = 0.0 - c.hi; ropeCos.lo = 0.0 - c.lo; }
        else { ropeSin.hi = 0.0 - c.hi; ropeSin.lo = 0.0 - c.lo; ropeCos.hi = s.hi; ropeCos.lo = s.lo; }
    }

    /* ---- fast path ---- */
    static final double[] sinCoef = new double[11];
    static final double[] cosCoef = new double[11];
    static double fastRel = 0.0, fastAbs = 0.0, fastCos = 0.0, fastSin = 0.0;
    static boolean fastSure = true;
    static long slowCases = 0;

    static void prepareFast() {
        double f = 1.0;
        for (long n = 1; n < 22; n += 1) {
            f = f * (double)n;
            long j = n / 2;
            double sign = 1.0;
            if (j % 2 == 1) sign = -1.0;
            if (n % 2 == 1 && n >= 3) sinCoef[(int)j] = sign / f;
            if (n % 2 == 0) cosCoef[(int)j] = sign / f;
        }
        fastRel = scale2(1.0, -45);
        fastAbs = scale2(1.0, -97);
    }

    static void fastTrig(double x) {
        double k = dFloor(x * 0.6366197723675814 + 0.5);
        long q = (long)k % 4;
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
        double ps = sinCoef[10];
        for (long j = 9; j >= 1; j -= 1) ps = ps * z + sinCoef[(int)j];
        double pc = cosCoef[10];
        for (long j2 = 9; j2 >= 1; j2 -= 1) pc = pc * z + cosCoef[(int)j2];
        double s0 = rh + rh * (z * ps);
        double c0 = 1.0 + z * pc;
        double s = s0 + rl * c0;
        double c = c0 - rl * s0;
        if (q == 0) { fastCos = c; fastSin = s; }
        else if (q == 1) { fastCos = 0.0 - s; fastSin = c; }
        else if (q == 2) { fastCos = 0.0 - c; fastSin = 0.0 - s; }
        else { fastCos = s; fastSin = 0.0 - c; }
    }

    static float fastFloat(double a, double bound) {
        float t = (float)a;
        double t64 = (double)t;
        double lo = (t64 + (double)floatNext(t, -1)) * 0.5;
        double hi = (t64 + (double)floatNext(t, 1)) * 0.5;
        fastSure = (a - lo > bound) && (hi - a > bound);
        return t;
    }

    /* ---- table ---- */
    static float[] ropeCosTab, ropeSinTab;

    static double ropeFreq(double base, long i, long half) {
        if (i == 0) return 1.0;
        DD a = new DD(), l = new DD(), e = new DD();
        ddSet(a, base);
        ddLog(l, a);
        ddMulD(l, l, (double)(0 - i));
        ddMulD(l, l, 1.0 / (double)half);
        ddExp(e, l);
        return roundToDouble(e);
    }

    static void ropeTable(long maxlen, double base, long half) {
        preparePi();
        prepareFast();
        ropeCosTab = new float[(int)(maxlen * half)]; /* malloc(maxlen * half * 4) */
        ropeSinTab = new float[(int)(maxlen * half)];
        double[] freq = new double[64];
        for (long i = 0; i < half; i += 1) freq[(int)i] = ropeFreq(base, i, half);
        for (long pos = 0; pos < maxlen; pos += 1) {
            for (long i2 = 0; i2 < half; i2 += 1) {
                double ang = (double)pos * freq[(int)i2];
                long idx = pos * half + i2;
                boolean done = false;
                if (ang > 0.0 && ang < 131072.0) {
                    fastTrig(ang);
                    float fc = fastFloat(fastCos, dAbs(fastCos) * fastRel + fastAbs);
                    boolean cc = fastSure;
                    float fs = fastFloat(fastSin, dAbs(fastSin) * fastRel + fastAbs);
                    if (cc && fastSure) {
                        ropeCosTab[(int)idx] = fc;
                        ropeSinTab[(int)idx] = fs;
                        done = true;
                    }
                }
                if (!done) {
                    if (ang > 0.0) slowCases += 1;
                    ddTrig(ang);
                    ropeCosTab[(int)idx] = roundToFloat(ropeCos);
                    ropeSinTab[(int)idx] = roundToFloat(ropeSin);
                }
            }
        }
        if (hardCases > 0) {
            System.err.print("RoPE table: " + hardCases + " values too close to a rounding boundary\n");
            System.exit(1);
        }
    }

    public static void main(String[] args) {
        ropeTable(32768, 1000000.0, 64);
        long h = 0;
        long n = 32768 * 64;
        for (long k = 0; k < n; k += 1) {
            int i;
            i = Float.floatToRawIntBits(ropeCosTab[(int)k]);
            h = ((h * 31) + ((long)i & 4294967295L)) & 281474976710655L;
        }
        for (long k2 = 0; k2 < n; k2 += 1) {
            int i;
            i = Float.floatToRawIntBits(ropeSinTab[(int)k2]);
            h = ((h * 31) + ((long)i & 4294967295L)) & 281474976710655L;
        }
        System.out.print(h + " " + slowCases + " " + hardCases + "\n");
    }
}
