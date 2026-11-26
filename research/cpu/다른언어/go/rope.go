// RoPE table -- pair: ../../rope.c (line-by-line port; the same algorithm as rope.gl / GeulPU host/로프.gl):
// double-double arithmetic, a fixed-point big integer for pi (Machin), a fp64 polynomial fast path with a rigorous
// error bound and correct rounding to float32, and the geul standard library's math helpers (absolute value, floor,
// scaling by 2^n, natural log) written the same way.
// Build with GOAMD64=v1 (the default): no FMA instructions, so the compiler never fuses a multiply and an add
// (the C is built with -ffp-contract=off for the same reason).
package main

import (
	"fmt"
	"math"
	"os"
)

// ---- the geul standard library's math (표준/수학.gl) ----
func dbits(x float64) int64  { return int64(math.Float64bits(x)) }
func bitsd(b int64) float64  { return math.Float64frombits(uint64(b)) }
func dAbs(v float64) float64 { return bitsd(dbits(v) & 9223372036854775807) }
func isInf(x float64) bool   { return (dbits(x) & 9223372036854775807) == 9218868437227405312 }
func isNaN(x float64) bool   { return (dbits(x) & 9223372036854775807) > 9218868437227405312 }
func dNaN() float64          { return bitsd(9221120237041090560) }
func dInf() float64          { return bitsd(9218868437227405312) }

const LN2 float64 = 0.69314718055994530942

func scale2(x float64, n int64) float64 {
	for n > 1000 {
		x = x * 8.98846567431158e307
		n = n - 1023
	}
	for n < -1000 {
		x = x * 1.1125369292536007e-308
		n = n + 1022
	}
	return x * bitsd((n+1023)<<52)
}

func dFloor(v float64) float64 {
	if isInf(v) || isNaN(v) {
		return v
	}
	if v >= 4503599627370496.0 || v <= -4503599627370496.0 {
		return v
	}
	n := int64(v)
	r := float64(n)
	if r > v {
		return r - 1.0
	}
	return r
}

func dLog(v float64) float64 {
	if isNaN(v) {
		return v
	}
	if v < 0.0 {
		return dNaN()
	}
	if v == 0.0 {
		return 0.0 - dInf()
	}
	if isInf(v) {
		return v
	}
	bits := dbits(v)
	ex := ((bits >> 52) & 2047)
	m := v
	var e int64 = 0
	if ex == 0 {
		m = v * 18014398509481984.0
		bits = dbits(m)
		ex = ((bits >> 52) & 2047)
		e = -54
	}
	e = e + ex - 1023
	m = bitsd((bits & 4503599627370495) | 4607182418800017408)
	if m > 1.4142135623730951 {
		m = m * 0.5
		e = e + 1
	}
	s := (m - 1.0) / (m + 1.0)
	s2 := s * s
	term := s
	sum := 0.0
	for n := int64(1); n < 60; n += 2 {
		sum = sum + term/float64(n)
		term = term * s2
		if dAbs(term) < 1.0e-18 {
			break
		}
	}
	return 2.0*sum + float64(e)*LN2
}

// ---- double-double ----
type dd struct {
	hi, lo float64
}

func twoSum(r *dd, a float64, b float64) {
	s := a + b
	bb := s - a
	r.hi = s
	r.lo = (a - (s - bb)) + (b - bb)
}

func fastSum(r *dd, a float64, b float64) {
	s := a + b
	r.hi = s
	r.lo = b - (s - a)
}

func twoProd(r *dd, a float64, b float64) {
	p := a * b
	ta := 134217729.0 * a
	ah := ta - (ta - a)
	al := a - ah
	tb := 134217729.0 * b
	bh := tb - (tb - b)
	bl := b - bh
	r.hi = p
	r.lo = ((ah*bh - p) + ah*bl + al*bh) + al*bl
}

func ddAdd(r *dd, a *dd, b *dd) {
	var s, t, v dd
	twoSum(&s, a.hi, b.hi)
	twoSum(&t, a.lo, b.lo)
	c := s.lo + t.hi
	fastSum(&v, s.hi, c)
	w := t.lo + v.lo
	fastSum(r, v.hi, w)
}

func ddSub(r *dd, a *dd, b *dd) {
	var nb dd
	nb.hi = 0.0 - b.hi
	nb.lo = 0.0 - b.lo
	ddAdd(r, a, &nb)
}

func ddMul(r *dd, a *dd, b *dd) {
	var p dd
	twoProd(&p, a.hi, b.hi)
	e := p.lo + (a.hi*b.lo + a.lo*b.hi)
	fastSum(r, p.hi, e)
}

func ddMulD(r *dd, a *dd, d float64) {
	var p dd
	twoProd(&p, a.hi, d)
	e := p.lo + a.lo*d
	fastSum(r, p.hi, e)
}

func ddDiv(r *dd, a *dd, b *dd) {
	q1 := a.hi / b.hi
	var t, rr dd
	ddMulD(&t, b, q1)
	ddSub(&rr, a, &t)
	q2 := rr.hi / b.hi
	ddMulD(&t, b, q2)
	ddSub(&rr, &rr, &t)
	q3 := rr.hi / b.hi
	var q, q3d dd
	fastSum(&q, q1, q2)
	q3d.hi = q3
	q3d.lo = 0.0
	ddAdd(r, &q, &q3d)
}

func ddSet(r *dd, a float64) { r.hi = a; r.lo = 0.0 }

func ddDivD(r *dd, a *dd, d float64) {
	var b dd
	b.hi = d
	b.lo = 0.0
	ddDiv(r, a, &b)
}

// ---- fixed-point big integer: word 0 integer part, words 1..8 fraction (32 bits each) ----
// C passes int64_t * to the BIGW-word arrays; here they are slices of [BIGW]int64 arrays.
const BIGW = 9

func bigZero(a []int64) {
	for i := int64(0); i < BIGW; i += 1 {
		a[i] = 0
	}
}

func bigIsZero(a []int64) bool {
	for i := int64(0); i < BIGW; i += 1 {
		if a[i] != 0 {
			return false
		}
	}
	return true
}

func bigDivSmall(a []int64, d int64) {
	var rem int64 = 0
	for i := int64(0); i < BIGW; i += 1 {
		cur := (rem << 32) + a[i]
		a[i] = cur / d
		rem = cur % d
	}
}

func bigAdd(a []int64, b []int64) {
	var carry int64 = 0
	for i := int64(BIGW - 1); i >= 0; i -= 1 {
		s := a[i] + b[i] + carry
		a[i] = s & 4294967295
		carry = s >> 32
	}
}

func bigSub(a []int64, b []int64) {
	var borrow int64 = 0
	for i := int64(BIGW - 1); i >= 0; i -= 1 {
		s := a[i] - b[i] - borrow
		borrow = 0
		if s < 0 {
			s = s + 4294967296
			borrow = 1
		}
		a[i] = s
	}
}

func bigMulSmall(a []int64, m int64) {
	var carry int64 = 0
	for i := int64(BIGW - 1); i >= 0; i -= 1 {
		s := a[i]*m + carry
		a[i] = s & 4294967295
		carry = s >> 32
	}
}

func bigAtanInv(sum []int64, x int64) {
	var pw, term [BIGW]int64
	bigZero(pw[:])
	pw[0] = 1
	bigDivSmall(pw[:], x)
	bigZero(sum)
	bigAdd(sum, pw[:])
	var j int64 = 1
	for {
		bigDivSmall(pw[:], x*x)
		for i := int64(0); i < BIGW; i += 1 {
			term[i] = pw[i]
		}
		bigDivSmall(term[:], 2*j+1)
		if bigIsZero(term[:]) {
			break
		}
		if j%2 == 1 {
			bigSub(sum, term[:])
		} else {
			bigAdd(sum, term[:])
		}
		j += 1
	}
}

func bigBit(a []int64, n int64) int64 {
	if n == 0 {
		return a[0] & 1
	}
	return (a[(n-1)/32+1] >> (31 - (n-1)%32)) & 1
}

func bigBitClear(a []int64, n int64) {
	if n == 0 {
		a[0] = a[0] & (0 - 2)
		return
	}
	i := (n-1)/32 + 1
	a[i] = a[i] & (4294967295 ^ (int64(1) << (31 - (n-1)%32)))
}

func bigTakeTop(a []int64, nbits int64) float64 {
	var n0 int64 = 0
	for n0 <= 256 && bigBit(a, n0) == 0 {
		n0 += 1
	}
	if n0 > 256 {
		return 0.0
	}
	var M int64 = 0
	for j := int64(0); j < nbits; j += 1 {
		n := n0 + j
		var b int64 = 0
		if n <= 256 {
			b = bigBit(a, n)
		}
		M = (M << 1) | b
		if n <= 256 && b == 1 {
			bigBitClear(a, n)
		}
	}
	return scale2(float64(M), 0-n0-(nbits-1))
}

func bigTakeDouble(a []int64) float64 { return bigTakeTop(a, 53) }

var halfpi1, halfpi2, halfpi3, halfpi4 float64 = 0.0, 0.0, 0.0, 0.0
var halfpiDD dd
var ddLn2 dd
var fhalfpi1, fhalfpi2, fhalfpi3 float64 = 0.0, 0.0, 0.0

func preparePi() {
	var a, b, c [BIGW]int64
	bigAtanInv(a[:], 5)
	bigMulSmall(a[:], 16)
	bigAtanInv(b[:], 239)
	bigMulSmall(b[:], 4)
	bigSub(a[:], b[:])
	bigDivSmall(a[:], 2)
	for i := int64(0); i < BIGW; i += 1 {
		c[i] = a[i]
	}
	fhalfpi1 = bigTakeTop(c[:], 36)
	fhalfpi2 = bigTakeTop(c[:], 36)
	fhalfpi3 = bigTakeTop(c[:], 53)
	halfpi1 = bigTakeDouble(a[:])
	halfpi2 = bigTakeDouble(a[:])
	halfpi3 = bigTakeDouble(a[:])
	halfpi4 = bigTakeDouble(a[:])
	fastSum(&halfpiDD, halfpi1, halfpi2)
	var t, one, t2, pw, sum dd
	ddSet(&one, 1.0)
	ddDivD(&t, &one, 3.0)
	ddMul(&t2, &t, &t)
	pw = t
	sum = t
	for j := int64(1); j < 40; j += 1 {
		ddMul(&pw, &pw, &t2)
		var term dd
		ddDivD(&term, &pw, float64(2*j+1))
		ddAdd(&sum, &sum, &term)
	}
	ddMulD(&ddLn2, &sum, 2.0)
}

func ddExp(r *dd, a *dd) {
	if a.hi == 0.0 {
		ddSet(r, 1.0)
		return
	}
	m := dFloor(a.hi/ddLn2.hi + 0.5)
	var s, x dd
	ddMulD(&s, &ddLn2, m)
	ddSub(&x, a, &s)
	ddMulD(&x, &x, 1.0/512.0)
	sum, term := x, x
	for n := int64(2); n < 20; n += 1 {
		ddMul(&term, &term, &x)
		ddDivD(&term, &term, float64(n))
		ddAdd(&sum, &sum, &term)
	}
	for i := int64(0); i < 9; i += 1 {
		var sq dd
		ddMul(&sq, &sum, &sum)
		ddMulD(&sum, &sum, 2.0)
		ddAdd(&sum, &sum, &sq)
	}
	var one dd
	ddSet(&one, 1.0)
	ddAdd(&sum, &sum, &one)
	r.hi = scale2(sum.hi, int64(m))
	r.lo = scale2(sum.lo, int64(m))
}

func ddLog(r *dd, a *dd) {
	var y dd
	ddSet(&y, dLog(a.hi))
	for i := int64(0); i < 3; i += 1 {
		var ny, e, t, one dd
		ny.hi = 0.0 - y.hi
		ny.lo = 0.0 - y.lo
		ddExp(&e, &ny)
		ddMul(&t, a, &e)
		ddSet(&one, 1.0)
		ddSub(&t, &t, &one)
		ddAdd(&y, &y, &t)
	}
	r.hi = y.hi
	r.lo = y.lo
}

// ---- correct rounding ----
var hardCases int64 = 0

func roundToDouble(v *dd) float64 {
	hi := v.hi
	halfUlp := dAbs(hi) * 1.1102230246251565e-16
	bound := dAbs(hi) * 8.077935669463161e-28
	if dAbs(dAbs(v.lo)-halfUlp) <= bound || dAbs(v.lo) > halfUlp*2.0 {
		hardCases += 1
	}
	return hi
}

func floatNext(f float32, dir int64) float32 {
	var i int32
	i = int32(math.Float32bits(f)) // C: memcpy(&i, &f, 4)
	b := int64(i)
	if f > 0.0 {
		b = b + dir
	} else {
		b = b - dir
	}
	i = int32(b)
	f = math.Float32frombits(uint32(i)) // C: memcpy(&f, &i, 4)
	return f
}

func roundToFloat(v *dd) float32 {
	hi := v.hi
	if hi == 0.0 {
		return float32(0.0)
	}
	t := float32(hi)
	t64 := float64(t)
	if t64 == hi {
		return t
	}
	other := t
	if t64 < hi {
		other = floatNext(t, 1)
	} else {
		other = floatNext(t, -1)
	}
	if hi < 0.0 {
		if t64 < hi {
			other = floatNext(t, -1)
		} else {
			other = floatNext(t, 1)
		}
	}
	other64 := float64(other)
	mid := (t64 + other64) * 0.5
	d := (hi - mid) + v.lo
	bound := dAbs(hi) * 8.077935669463161e-28
	if dAbs(d) <= bound {
		hardCases += 1
	}
	if d > 0.0 {
		if t64 > other64 {
			return t
		}
		return other
	}
	if t64 < other64 {
		return t
	}
	return other
}

// ---- cos and sin in double-double ----
var ropeCos, ropeSin dd

func ddTrig(x float64) {
	if x == 0.0 {
		ddSet(&ropeCos, 1.0)
		ddSet(&ropeSin, 0.0)
		return
	}
	k := dFloor(x*0.6366197723675814 + 0.5)
	q := int64(k) % 4
	var r, p dd
	ddSet(&r, x)
	twoProd(&p, k, halfpi1)
	ddSub(&r, &r, &p)
	twoProd(&p, k, halfpi2)
	ddSub(&r, &r, &p)
	twoProd(&p, k, halfpi3)
	ddSub(&r, &r, &p)
	twoProd(&p, k, halfpi4)
	ddSub(&r, &r, &p)
	var r2 dd
	ddMul(&r2, &r, &r)
	s := r
	var c dd
	ts := r
	var tc dd
	ddSet(&c, 1.0)
	ddSet(&tc, 1.0)
	for j := int64(1); j < 18; j += 1 {
		ddMul(&ts, &ts, &r2)
		ddDivD(&ts, &ts, float64((2*j)*(2*j+1)))
		ddMul(&tc, &tc, &r2)
		ddDivD(&tc, &tc, float64((2*j-1)*(2*j)))
		if j%2 == 1 {
			ddSub(&s, &s, &ts)
			ddSub(&c, &c, &tc)
		} else {
			ddAdd(&s, &s, &ts)
			ddAdd(&c, &c, &tc)
		}
	}
	if q == 0 {
		ropeSin = s
		ropeCos = c
	} else if q == 1 {
		ropeSin = c
		ropeCos.hi = 0.0 - s.hi
		ropeCos.lo = 0.0 - s.lo
	} else if q == 2 {
		ropeSin.hi = 0.0 - s.hi
		ropeSin.lo = 0.0 - s.lo
		ropeCos.hi = 0.0 - c.hi
		ropeCos.lo = 0.0 - c.lo
	} else {
		ropeSin.hi = 0.0 - c.hi
		ropeSin.lo = 0.0 - c.lo
		ropeCos = s
	}
}

// ---- fast path ----
var sinCoef [11]float64
var cosCoef [11]float64
var fastRel, fastAbs, fastCos, fastSin float64 = 0.0, 0.0, 0.0, 0.0
var fastSure bool = true // C: static int fast_sure = 1;
var slowCases int64 = 0

func prepareFast() {
	f := 1.0
	for n := int64(1); n < 22; n += 1 {
		f = f * float64(n)
		j := n / 2
		sign := 1.0
		if j%2 == 1 {
			sign = -1.0
		}
		if n%2 == 1 && n >= 3 {
			sinCoef[j] = sign / f
		}
		if n%2 == 0 {
			cosCoef[j] = sign / f
		}
	}
	fastRel = scale2(1.0, -45)
	fastAbs = scale2(1.0, -97)
}

func fastTrig(x float64) {
	k := dFloor(x*0.6366197723675814 + 0.5)
	q := int64(k) % 4
	r1 := x - k*fhalfpi1
	p2 := 0.0 - k*fhalfpi2
	r2 := r1 + p2
	bb := r2 - r1
	e2 := (r1 - (r2 - bb)) + (p2 - bb)
	p3 := 0.0 - k*fhalfpi3
	rh := r2 + p3
	bb2 := rh - r2
	rl := ((r2 - (rh - bb2)) + (p3 - bb2)) + e2
	z := rh * rh
	ps := sinCoef[10]
	for j := int64(9); j >= 1; j -= 1 {
		ps = ps*z + sinCoef[j]
	}
	pc := cosCoef[10]
	for j2 := int64(9); j2 >= 1; j2 -= 1 {
		pc = pc*z + cosCoef[j2]
	}
	s0 := rh + rh*(z*ps)
	c0 := 1.0 + z*pc
	s := s0 + rl*c0
	c := c0 - rl*s0
	if q == 0 {
		fastCos = c
		fastSin = s
	} else if q == 1 {
		fastCos = 0.0 - s
		fastSin = c
	} else if q == 2 {
		fastCos = 0.0 - c
		fastSin = 0.0 - s
	} else {
		fastCos = s
		fastSin = 0.0 - c
	}
}

func fastFloat(a float64, bound float64) float32 {
	t := float32(a)
	t64 := float64(t)
	lo := (t64 + float64(floatNext(t, -1))) * 0.5
	hi := (t64 + float64(floatNext(t, 1))) * 0.5
	fastSure = (a-lo > bound) && (hi-a > bound)
	return t
}

// ---- table ----
var ropeCosTab, ropeSinTab []float32

func ropeFreq(base float64, i int64, half int64) float64 {
	if i == 0 {
		return 1.0
	}
	var a, l, e dd
	ddSet(&a, base)
	ddLog(&l, &a)
	ddMulD(&l, &l, float64(0-i))
	ddMulD(&l, &l, 1.0/float64(half))
	ddExp(&e, &l)
	return roundToDouble(&e)
}

func ropeTable(maxlen int64, base float64, half int64) {
	preparePi()
	prepareFast()
	ropeCosTab = make([]float32, maxlen*half)
	ropeSinTab = make([]float32, maxlen*half)
	var freq [64]float64
	for i := int64(0); i < half; i += 1 {
		freq[i] = ropeFreq(base, i, half)
	}
	for pos := int64(0); pos < maxlen; pos += 1 {
		for i2 := int64(0); i2 < half; i2 += 1 {
			ang := float64(pos) * freq[i2]
			idx := pos*half + i2
			done := false
			if ang > 0.0 && ang < 131072.0 {
				fastTrig(ang)
				fc := fastFloat(fastCos, dAbs(fastCos)*fastRel+fastAbs)
				cc := fastSure
				fs := fastFloat(fastSin, dAbs(fastSin)*fastRel+fastAbs)
				if cc && fastSure {
					ropeCosTab[idx] = fc
					ropeSinTab[idx] = fs
					done = true
				}
			}
			if !done {
				if ang > 0.0 {
					slowCases += 1
				}
				ddTrig(ang)
				ropeCosTab[idx] = roundToFloat(&ropeCos)
				ropeSinTab[idx] = roundToFloat(&ropeSin)
			}
		}
	}
	if hardCases > 0 {
		fmt.Fprintf(os.Stderr, "RoPE table: %d values too close to a rounding boundary\n", hardCases)
		os.Exit(1)
	}
}

func main() {
	ropeTable(32768, 1000000.0, 64)
	var h int64 = 0
	var n int64 = 32768 * 64
	for k := int64(0); k < n; k += 1 {
		var i int32
		i = int32(math.Float32bits(ropeCosTab[k])) // C: memcpy(&i, &rope_cos_tab[k], 4)
		h = ((h * 31) + (int64(i) & 4294967295)) & 281474976710655
	}
	for k2 := int64(0); k2 < n; k2 += 1 {
		var i int32
		i = int32(math.Float32bits(ropeSinTab[k2]))
		h = ((h * 31) + (int64(i) & 4294967295)) & 281474976710655
	}
	fmt.Printf("%d %d %d\n", h, slowCases, hardCases)
}
