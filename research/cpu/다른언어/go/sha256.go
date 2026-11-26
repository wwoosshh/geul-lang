// SHA-256 -- pair: ../../sha256.c (line-by-line port; the same algorithm as sha256.gl / GeulPU host/해시.gl):
// 64-bit integers with a 32-bit mask, round constants in a growable integer list with a range-checked accessor,
// rotation as a function. Hashes 64 MB of deterministic bytes.
package main

import (
	"fmt"
	"os"
)

// C: typedef struct { int64_t *data; int64_t len; int64_t cap; } intlist;
type intlist struct {
	data []int64
	len  int64
	cap  int64
}

func listNew() *intlist {
	l := new(intlist)
	l.cap = 8
	l.len = 0
	l.data = make([]int64, 8)
	return l
}

func listAdd(l *intlist, v int64) {
	if l.len >= l.cap {
		l.cap = l.cap * 2
		// C: l->data = realloc(l->data, l->cap * 8);
		data := make([]int64, l.cap)
		copy(data, l.data)
		l.data = data
	}
	l.data[l.len] = v
	l.len += 1
}

func listCheck(l *intlist, i int64) {
	if i < 0 || i >= l.len {
		fmt.Printf("error: index %d out of [0, %d)\n", i, l.len)
		os.Exit(1)
	}
}

func listValue(l *intlist, i int64) int64 {
	listCheck(l, i)
	return l.data[i]
}

var K *intlist = nil

const MASK int64 = 4294967295

// s ends with a NUL like the C string literal ("\x00" at the end of each argument below).
func hexWords(s string, l *intlist) {
	var v, digits int64 = 0, 0
	for k := int64(0); s[k] != 0; k += 1 {
		c := int64(s[k]) & 255
		var d int64 = -1
		if c >= 48 && c <= 57 {
			d = c - 48
		}
		if c >= 97 && c <= 102 {
			d = c - 87
		}
		if c >= 65 && c <= 70 {
			d = c - 55
		}
		if d >= 0 {
			v = v*16 + d
			digits += 1
		} else if digits > 0 {
			listAdd(l, v)
			v = 0
			digits = 0
		}
	}
	if digits > 0 {
		listAdd(l, v)
	}
}

func prepare() {
	if K != nil {
		return
	}
	K = listNew()
	hexWords("428a2f98 71374491 b5c0fbcf e9b5dba5 3956c25b 59f111f1 923f82a4 ab1c5ed5 d807aa98 12835b01 243185be 550c7dc3 72be5d74 80deb1fe 9bdc06a7 c19bf174\x00", K)
	hexWords("e49b69c1 efbe4786 0fc19dc6 240ca1cc 2de92c6f 4a7484aa 5cb0a9dc 76f988da 983e5152 a831c66d b00327c8 bf597fc7 c6e00bf3 d5a79147 06ca6351 14292967\x00", K)
	hexWords("27b70a85 2e1b2138 4d2c6dfc 53380d13 650a7354 766a0abb 81c2c92e 92722c85 a2bfe8a1 a81a664b c24b8b70 c76c51a3 d192e819 d6990624 f40e3585 106aa070\x00", K)
	hexWords("19a4c116 1e376c08 2748774c 34b0bcb5 391c0cb3 4ed8aa4a 5b9cca4f 682e6ff3 748f82ee 78a5636f 84c87814 8cc70208 90befffa a4506ceb bef9a3f7 c67178f2\x00", K)
}

func rotr(x int64, n int64) int64 { return ((x >> n) | (x << (32 - n))) & MASK }

func hashBlock(h []int64, block []byte) {
	var w [64]int64
	for i := int64(0); i < 16; i += 1 {
		w[i] = ((int64(block[4*i]) & 255) << 24) | ((int64(block[4*i+1]) & 255) << 16) |
			((int64(block[4*i+2]) & 255) << 8) | (int64(block[4*i+3]) & 255)
	}
	for i2 := int64(16); i2 < 64; i2 += 1 {
		a := w[i2-15]
		b := w[i2-2]
		s0 := rotr(a, 7) ^ rotr(a, 18) ^ (a >> 3)
		s1 := rotr(b, 17) ^ rotr(b, 19) ^ (b >> 10)
		w[i2] = (w[i2-16] + s0 + w[i2-7] + s1) & MASK
	}
	A, B, C, D, E, F, G, H := h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7]
	for t := int64(0); t < 64; t += 1 {
		S1 := rotr(E, 6) ^ rotr(E, 11) ^ rotr(E, 25)
		ch := (E & F) ^ ((E ^ MASK) & G)
		t1 := (H + S1 + ch + listValue(K, t) + w[t]) & MASK
		S0 := rotr(A, 2) ^ rotr(A, 13) ^ rotr(A, 22)
		maj := (A & B) ^ (A & C) ^ (B & C)
		t2 := (S0 + maj) & MASK
		H = G
		G = F
		F = E
		E = (D + t1) & MASK
		D = C
		C = B
		B = A
		A = (t1 + t2) & MASK
	}
	h[0] = (h[0] + A) & MASK
	h[1] = (h[1] + B) & MASK
	h[2] = (h[2] + C) & MASK
	h[3] = (h[3] + D) & MASK
	h[4] = (h[4] + E) & MASK
	h[5] = (h[5] + F) & MASK
	h[6] = (h[6] + G) & MASK
	h[7] = (h[7] + H) & MASK
}

// C: typedef struct { int64_t h[8]; int64_t total; int64_t rest_n; char rest[64]; } hashstate;
type hashstate struct {
	h     [8]int64
	total int64
	restN int64
	rest  [64]byte
}

func hashStart(s *hashstate) {
	prepare()
	s.h[0] = 1779033703
	s.h[1] = 3144134277
	s.h[2] = 1013904242
	s.h[3] = 2773480762
	s.h[4] = 1359893119
	s.h[5] = 2600822924
	s.h[6] = 528734635
	s.h[7] = 1541459225
	s.total = 0
	s.restN = 0
}

// C: hash_add(hashstate *s, const void *data, int64_t len); d + k (a pointer) is the slice d[k:].
func hashAdd(s *hashstate, data []byte, length int64) {
	d := data
	var k int64 = 0
	s.total = s.total + length
	for s.restN > 0 && k < length {
		s.rest[s.restN] = d[k]
		s.restN += 1
		k += 1
		if s.restN == 64 {
			hashBlock(s.h[:], s.rest[:])
			s.restN = 0
		}
	}
	for k+64 <= length {
		hashBlock(s.h[:], d[k:])
		k += 64
	}
	for k < length {
		s.rest[s.restN] = d[k]
		s.restN += 1
		k += 1
	}
}

func hashEnd(s *hashstate) []byte {
	bits := s.total * 8
	var tail [128]byte
	var n int64 = 0
	tail[n] = 0x80 // C: tail[n] = -128 (char)
	n += 1
	for (s.restN+n)%64 != 56 {
		tail[n] = 0
		n += 1
	}
	for j := int64(0); j < 8; j += 1 {
		tail[n] = byte((bits >> (56 - 8*j)) & 255)
		n += 1
	}
	before := s.total
	hashAdd(s, tail[:], n)
	s.total = before
	out := make([]byte, 65)
	digits := "0123456789abcdef"
	for i := int64(0); i < 8; i += 1 {
		for b := int64(0); b < 8; b += 1 {
			out[i*8+b] = digits[(s.h[i]>>(28-4*b))&15]
		}
	}
	out[64] = 0
	return out
}

func main() {
	var n int64 = 67108864
	buf := make([]byte, n)
	for i := int64(0); i < n; i += 1 {
		buf[i] = byte(((i * 2654435761) >> 13) & 255)
	}
	var s hashstate
	hashStart(&s)
	hashAdd(&s, buf, n)
	fmt.Printf("%s\n", hashEnd(&s)[:64]) // C's %s stops at the NUL in out[64]
}
