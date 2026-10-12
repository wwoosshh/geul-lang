/* SHA-256 -- the same algorithm as sha256.gl (GeulPU host/해시.gl): 64-bit integers with a 32-bit mask,
   round constants in a growable integer list with a range-checked accessor, rotation as a function.
   Hashes 64 MB of deterministic bytes. */
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

typedef struct { int64_t *data; int64_t len; int64_t cap; } intlist;

static intlist *list_new(void) {
    intlist *l = malloc(sizeof(intlist));
    l->cap = 8;
    l->len = 0;
    l->data = malloc(8 * 8);
    return l;
}

static void list_add(intlist *l, int64_t v) {
    if (l->len >= l->cap) {
        l->cap = l->cap * 2;
        l->data = realloc(l->data, l->cap * 8);
    }
    l->data[l->len] = v;
    l->len += 1;
}

static void list_check(intlist *l, int64_t i) {
    if (i < 0 || i >= l->len) {
        printf("error: index %lld out of [0, %lld)\n", (long long)i, (long long)l->len);
        exit(1);
    }
}

static int64_t list_value(intlist *l, int64_t i) {
    list_check(l, i);
    return l->data[i];
}

static intlist *K = NULL;
static const int64_t MASK = 4294967295LL;

static void hex_words(const char *s, intlist *l) {
    int64_t v = 0, digits = 0;
    for (int64_t k = 0; s[k] != 0; k += 1) {
        int64_t c = s[k] & 255;
        int64_t d = -1;
        if (c >= 48 && c <= 57) d = c - 48;
        if (c >= 97 && c <= 102) d = c - 87;
        if (c >= 65 && c <= 70) d = c - 55;
        if (d >= 0) { v = v * 16 + d; digits += 1; }
        else if (digits > 0) { list_add(l, v); v = 0; digits = 0; }
    }
    if (digits > 0) list_add(l, v);
}

static void prepare(void) {
    if (K != NULL) return;
    K = list_new();
    hex_words("428a2f98 71374491 b5c0fbcf e9b5dba5 3956c25b 59f111f1 923f82a4 ab1c5ed5 d807aa98 12835b01 243185be 550c7dc3 72be5d74 80deb1fe 9bdc06a7 c19bf174", K);
    hex_words("e49b69c1 efbe4786 0fc19dc6 240ca1cc 2de92c6f 4a7484aa 5cb0a9dc 76f988da 983e5152 a831c66d b00327c8 bf597fc7 c6e00bf3 d5a79147 06ca6351 14292967", K);
    hex_words("27b70a85 2e1b2138 4d2c6dfc 53380d13 650a7354 766a0abb 81c2c92e 92722c85 a2bfe8a1 a81a664b c24b8b70 c76c51a3 d192e819 d6990624 f40e3585 106aa070", K);
    hex_words("19a4c116 1e376c08 2748774c 34b0bcb5 391c0cb3 4ed8aa4a 5b9cca4f 682e6ff3 748f82ee 78a5636f 84c87814 8cc70208 90befffa a4506ceb bef9a3f7 c67178f2", K);
}

static int64_t rotr(int64_t x, int64_t n) { return ((x >> n) | (x << (32 - n))) & MASK; }

static void hash_block(int64_t *h, const char *block) {
    int64_t w[64];
    for (int64_t i = 0; i < 16; i += 1) {
        w[i] = (((int64_t)block[4 * i] & 255) << 24) | (((int64_t)block[4 * i + 1] & 255) << 16)
             | (((int64_t)block[4 * i + 2] & 255) << 8) | ((int64_t)block[4 * i + 3] & 255);
    }
    for (int64_t i2 = 16; i2 < 64; i2 += 1) {
        int64_t a = w[i2 - 15];
        int64_t b = w[i2 - 2];
        int64_t s0 = rotr(a, 7) ^ rotr(a, 18) ^ (a >> 3);
        int64_t s1 = rotr(b, 17) ^ rotr(b, 19) ^ (b >> 10);
        w[i2] = (w[i2 - 16] + s0 + w[i2 - 7] + s1) & MASK;
    }
    int64_t A = h[0], B = h[1], C = h[2], D = h[3], E = h[4], F = h[5], G = h[6], H = h[7];
    for (int64_t t = 0; t < 64; t += 1) {
        int64_t S1 = rotr(E, 6) ^ rotr(E, 11) ^ rotr(E, 25);
        int64_t ch = (E & F) ^ ((E ^ MASK) & G);
        int64_t t1 = (H + S1 + ch + list_value(K, t) + w[t]) & MASK;
        int64_t S0 = rotr(A, 2) ^ rotr(A, 13) ^ rotr(A, 22);
        int64_t maj = (A & B) ^ (A & C) ^ (B & C);
        int64_t t2 = (S0 + maj) & MASK;
        H = G; G = F; F = E;
        E = (D + t1) & MASK;
        D = C; C = B; B = A;
        A = (t1 + t2) & MASK;
    }
    h[0] = (h[0] + A) & MASK; h[1] = (h[1] + B) & MASK; h[2] = (h[2] + C) & MASK; h[3] = (h[3] + D) & MASK;
    h[4] = (h[4] + E) & MASK; h[5] = (h[5] + F) & MASK; h[6] = (h[6] + G) & MASK; h[7] = (h[7] + H) & MASK;
}

typedef struct { int64_t h[8]; int64_t total; int64_t rest_n; char rest[64]; } hashstate;

static void hash_start(hashstate *s) {
    prepare();
    s->h[0] = 1779033703; s->h[1] = 3144134277LL; s->h[2] = 1013904242; s->h[3] = 2773480762LL;
    s->h[4] = 1359893119; s->h[5] = 2600822924LL; s->h[6] = 528734635; s->h[7] = 1541459225;
    s->total = 0;
    s->rest_n = 0;
}

static void hash_add(hashstate *s, const void *data, int64_t len) {
    const char *d = data;
    int64_t k = 0;
    s->total = s->total + len;
    while (s->rest_n > 0 && k < len) {
        s->rest[s->rest_n] = d[k];
        s->rest_n += 1;
        k += 1;
        if (s->rest_n == 64) { hash_block(s->h, s->rest); s->rest_n = 0; }
    }
    while (k + 64 <= len) {
        hash_block(s->h, d + k);
        k += 64;
    }
    while (k < len) {
        s->rest[s->rest_n] = d[k];
        s->rest_n += 1;
        k += 1;
    }
}

static char *hash_end(hashstate *s) {
    int64_t bits = s->total * 8;
    char tail[128];
    int64_t n = 0;
    tail[n] = -128; n += 1;
    while ((s->rest_n + n) % 64 != 56) { tail[n] = 0; n += 1; }
    for (int64_t j = 0; j < 8; j += 1) { tail[n] = (char)((bits >> (56 - 8 * j)) & 255); n += 1; }
    int64_t before = s->total;
    hash_add(s, tail, n);
    s->total = before;
    char *out = malloc(65);
    const char *digits = "0123456789abcdef";
    for (int64_t i = 0; i < 8; i += 1)
        for (int64_t b = 0; b < 8; b += 1) out[i * 8 + b] = digits[(s->h[i] >> (28 - 4 * b)) & 15];
    out[64] = 0;
    return out;
}

int main(void) {
    int64_t n = 67108864;
    char *buf = malloc(n);
    for (int64_t i = 0; i < n; i += 1) buf[i] = (char)(((i * 2654435761LL) >> 13) & 255);
    hashstate s;
    hash_start(&s);
    hash_add(&s, buf, n);
    printf("%s\n", hash_end(&s));
    return 0;
}
