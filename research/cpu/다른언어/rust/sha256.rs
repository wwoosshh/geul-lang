// SHA-256 -- line-by-line port of ../../sha256.c (the same algorithm as ../../sha256.gl, GeulPU host/해시.gl):
// 64-bit integers with a 32-bit mask, round constants in a growable integer list with a range-checked accessor,
// rotation as a function. Hashes 64 MB of deterministic bytes.
// Upper-case locals (A..H, S0, S1) keep the C names.
#![allow(non_snake_case)]

use std::sync::OnceLock;

// C: typedef struct { int64_t *data; int64_t len; int64_t cap; } intlist;
struct IntList {
    data: Vec<i64>, // a buffer of `cap` elements, like the malloc'd block; len/cap are kept by hand as in the C
    len: i64,
    cap: i64,
}

fn list_new() -> Box<IntList> {
    // C: l = malloc(sizeof(intlist)); l->cap = 8; l->len = 0; l->data = malloc(8 * 8);
    let l: Box<IntList> = Box::new(IntList { cap: 8, len: 0, data: vec![0; 8] });
    return l;
}

fn list_add(l: &mut IntList, v: i64) {
    if l.len >= l.cap {
        l.cap = l.cap * 2;
        l.data.resize(l.cap as usize, 0); // C: realloc(l->data, l->cap * 8)
    }
    l.data[l.len as usize] = v;
    l.len += 1;
}

fn list_check(l: &IntList, i: i64) {
    if i < 0 || i >= l.len {
        println!("error: index {} out of [0, {})", i, l.len);
        std::process::exit(1);
    }
}

fn list_value(l: &IntList, i: i64) -> i64 {
    list_check(l, i);
    return l.data[i as usize];
}

// C: static intlist *K = NULL;  -- a global set once by prepare(). Safe Rust: a OnceLock.
static K: OnceLock<Box<IntList>> = OnceLock::new();
const MASK: i64 = 4294967295;

// s is NUL-terminated like the C string literal (the literals below end in \0)
fn hex_words(s: &[u8], l: &mut IntList) {
    let mut v: i64 = 0;
    let mut digits: i64 = 0;
    let mut k: i64 = 0;
    while s[k as usize] != 0 {
        let c: i64 = (s[k as usize] as i64) & 255;
        let mut d: i64 = -1;
        if c >= 48 && c <= 57 { d = c - 48; }
        if c >= 97 && c <= 102 { d = c - 87; }
        if c >= 65 && c <= 70 { d = c - 55; }
        if d >= 0 { v = v * 16 + d; digits += 1; }
        else if digits > 0 { list_add(l, v); v = 0; digits = 0; }
        k += 1;
    }
    if digits > 0 { list_add(l, v); }
}

fn prepare() {
    if K.get().is_some() { return; }
    // C stores the new list in K first and fills it after; a OnceLock is filled first and then published.
    let mut l: Box<IntList> = list_new();
    hex_words(b"428a2f98 71374491 b5c0fbcf e9b5dba5 3956c25b 59f111f1 923f82a4 ab1c5ed5 d807aa98 12835b01 243185be 550c7dc3 72be5d74 80deb1fe 9bdc06a7 c19bf174\0", &mut l);
    hex_words(b"e49b69c1 efbe4786 0fc19dc6 240ca1cc 2de92c6f 4a7484aa 5cb0a9dc 76f988da 983e5152 a831c66d b00327c8 bf597fc7 c6e00bf3 d5a79147 06ca6351 14292967\0", &mut l);
    hex_words(b"27b70a85 2e1b2138 4d2c6dfc 53380d13 650a7354 766a0abb 81c2c92e 92722c85 a2bfe8a1 a81a664b c24b8b70 c76c51a3 d192e819 d6990624 f40e3585 106aa070\0", &mut l);
    hex_words(b"19a4c116 1e376c08 2748774c 34b0bcb5 391c0cb3 4ed8aa4a 5b9cca4f 682e6ff3 748f82ee 78a5636f 84c87814 8cc70208 90befffa a4506ceb bef9a3f7 c67178f2\0", &mut l);
    let _ = K.set(l);
}

fn rotr(x: i64, n: i64) -> i64 { return ((x >> n) | (x << (32 - n))) & MASK; }

// C: static void hash_block(int64_t *h, const char *block)
fn hash_block(h: &mut [i64], block: &[u8]) {
    let mut w: [i64; 64] = [0; 64]; // C: int64_t w[64]; (uninitialized there)
    let mut i: i64 = 0;
    while i < 16 {
        w[i as usize] = (((block[(4 * i) as usize] as i64) & 255) << 24) | (((block[(4 * i + 1) as usize] as i64) & 255) << 16)
             | (((block[(4 * i + 2) as usize] as i64) & 255) << 8) | ((block[(4 * i + 3) as usize] as i64) & 255);
        i += 1;
    }
    let mut i2: i64 = 16;
    while i2 < 64 {
        let a: i64 = w[(i2 - 15) as usize];
        let b: i64 = w[(i2 - 2) as usize];
        let s0: i64 = rotr(a, 7) ^ rotr(a, 18) ^ (a >> 3);
        let s1: i64 = rotr(b, 17) ^ rotr(b, 19) ^ (b >> 10);
        w[i2 as usize] = (w[(i2 - 16) as usize] + s0 + w[(i2 - 7) as usize] + s1) & MASK;
        i2 += 1;
    }
    let mut A: i64 = h[0]; let mut B: i64 = h[1]; let mut C: i64 = h[2]; let mut D: i64 = h[3];
    let mut E: i64 = h[4]; let mut F: i64 = h[5]; let mut G: i64 = h[6]; let mut H: i64 = h[7];
    let mut t: i64 = 0;
    while t < 64 {
        let S1: i64 = rotr(E, 6) ^ rotr(E, 11) ^ rotr(E, 25);
        let ch: i64 = (E & F) ^ ((E ^ MASK) & G);
        let t1: i64 = (H + S1 + ch + list_value(K.get().unwrap(), t) + w[t as usize]) & MASK;
        let S0: i64 = rotr(A, 2) ^ rotr(A, 13) ^ rotr(A, 22);
        let maj: i64 = (A & B) ^ (A & C) ^ (B & C);
        let t2: i64 = (S0 + maj) & MASK;
        H = G; G = F; F = E;
        E = (D + t1) & MASK;
        D = C; C = B; B = A;
        A = (t1 + t2) & MASK;
        t += 1;
    }
    h[0] = (h[0] + A) & MASK; h[1] = (h[1] + B) & MASK; h[2] = (h[2] + C) & MASK; h[3] = (h[3] + D) & MASK;
    h[4] = (h[4] + E) & MASK; h[5] = (h[5] + F) & MASK; h[6] = (h[6] + G) & MASK; h[7] = (h[7] + H) & MASK;
}

// C: typedef struct { int64_t h[8]; int64_t total; int64_t rest_n; char rest[64]; } hashstate;
struct HashState {
    h: [i64; 8],
    total: i64,
    rest_n: i64,
    rest: [u8; 64],
}

fn hash_start(s: &mut HashState) {
    prepare();
    s.h[0] = 1779033703; s.h[1] = 3144134277; s.h[2] = 1013904242; s.h[3] = 2773480762;
    s.h[4] = 1359893119; s.h[5] = 2600822924; s.h[6] = 528734635; s.h[7] = 1541459225;
    s.total = 0;
    s.rest_n = 0;
}

fn hash_add(s: &mut HashState, data: &[u8], len: i64) {
    let d: &[u8] = data;
    let mut k: i64 = 0;
    s.total = s.total + len;
    while s.rest_n > 0 && k < len {
        s.rest[s.rest_n as usize] = d[k as usize];
        s.rest_n += 1;
        k += 1;
        if s.rest_n == 64 { hash_block(&mut s.h, &s.rest); s.rest_n = 0; }
    }
    while k + 64 <= len {
        hash_block(&mut s.h, &d[k as usize..]); // C: hash_block(s->h, d + k)
        k += 64;
    }
    while k < len {
        s.rest[s.rest_n as usize] = d[k as usize];
        s.rest_n += 1;
        k += 1;
    }
}

// returns 64 hex digits and a terminating 0, like the C's malloc(65) string
fn hash_end(s: &mut HashState) -> Vec<u8> {
    let bits: i64 = s.total * 8;
    let mut tail: [u8; 128] = [0; 128]; // C: char tail[128];
    let mut n: i64 = 0;
    tail[n as usize] = (-128i64) as u8; n += 1; // C: tail[n] = -128 (the byte 0x80)
    while (s.rest_n + n) % 64 != 56 { tail[n as usize] = 0; n += 1; }
    let mut j: i64 = 0;
    while j < 8 { tail[n as usize] = ((bits >> (56 - 8 * j)) & 255) as u8; n += 1; j += 1; }
    let before: i64 = s.total;
    hash_add(s, &tail, n);
    s.total = before;
    let mut out: Vec<u8> = vec![0; 65]; // C: char *out = malloc(65)
    let digits: &[u8] = b"0123456789abcdef";
    let mut i: i64 = 0;
    while i < 8 {
        let mut b: i64 = 0;
        while b < 8 { out[(i * 8 + b) as usize] = digits[((s.h[i as usize] >> (28 - 4 * b)) & 15) as usize]; b += 1; }
        i += 1;
    }
    out[64] = 0;
    return out;
}

fn main() {
    let n: i64 = 67108864;
    let mut buf: Vec<u8> = vec![0; n as usize]; // C: char *buf = malloc(n)
    let mut i: i64 = 0;
    while i < n {
        buf[i as usize] = (((i * 2654435761) >> 13) & 255) as u8;
        i += 1;
    }
    let mut s: HashState = HashState { h: [0; 8], total: 0, rest_n: 0, rest: [0; 64] }; // C: hashstate s; (uninitialized)
    hash_start(&mut s);
    hash_add(&mut s, &buf, n);
    let out: Vec<u8> = hash_end(&mut s);
    // C: printf("%s\n", out) -- the bytes up to the terminating 0
    let mut m: usize = 0;
    while out[m] != 0 { m += 1; }
    println!("{}", std::str::from_utf8(&out[..m]).unwrap());
}
