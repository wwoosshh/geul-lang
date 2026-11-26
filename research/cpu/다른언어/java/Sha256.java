/* SHA-256 -- line-by-line Java port of research/cpu/sha256.c (pair: sha256.gl, GeulPU host/hash): 64-bit integers with a 32-bit
   mask, round constants in a growable integer list with a range-checked accessor, rotation as a function.
   Hashes 64 MB of deterministic bytes. */
import java.nio.charset.StandardCharsets;
import java.util.Arrays;

public class Sha256 {
    /* typedef struct { int64_t *data; int64_t len; int64_t cap; } intlist; */
    static final class IntList {
        long[] data;
        long len;
        long cap;
    }

    static IntList listNew() {
        IntList l = new IntList();
        l.cap = 8;
        l.len = 0;
        l.data = new long[8];
        return l;
    }

    static void listAdd(IntList l, long v) {
        if (l.len >= l.cap) {
            l.cap = l.cap * 2;
            l.data = Arrays.copyOf(l.data, (int)l.cap); /* realloc(l->data, l->cap * 8) */
        }
        l.data[(int)l.len] = v;
        l.len += 1;
    }

    static void listCheck(IntList l, long i) {
        if (i < 0 || i >= l.len) {
            System.out.print("error: index " + i + " out of [0, " + l.len + ")\n");
            System.exit(1);
        }
    }

    static long listValue(IntList l, long i) {
        listCheck(l, i);
        return l.data[(int)i];
    }

    static IntList K = null;
    static final long MASK = 4294967295L;

    static void hexWords(byte[] s, IntList l) {
        long v = 0, digits = 0;
        for (long k = 0; s[(int)k] != 0; k += 1) {
            long c = s[(int)k] & 255;
            long d = -1;
            if (c >= 48 && c <= 57) d = c - 48;
            if (c >= 97 && c <= 102) d = c - 87;
            if (c >= 65 && c <= 70) d = c - 55;
            if (d >= 0) { v = v * 16 + d; digits += 1; }
            else if (digits > 0) { listAdd(l, v); v = 0; digits = 0; }
        }
        if (digits > 0) listAdd(l, v);
    }

    static void prepare() {
        if (K != null) return;
        K = listNew();
        hexWords(cstr("428a2f98 71374491 b5c0fbcf e9b5dba5 3956c25b 59f111f1 923f82a4 ab1c5ed5 d807aa98 12835b01 243185be 550c7dc3 72be5d74 80deb1fe 9bdc06a7 c19bf174"), K);
        hexWords(cstr("e49b69c1 efbe4786 0fc19dc6 240ca1cc 2de92c6f 4a7484aa 5cb0a9dc 76f988da 983e5152 a831c66d b00327c8 bf597fc7 c6e00bf3 d5a79147 06ca6351 14292967"), K);
        hexWords(cstr("27b70a85 2e1b2138 4d2c6dfc 53380d13 650a7354 766a0abb 81c2c92e 92722c85 a2bfe8a1 a81a664b c24b8b70 c76c51a3 d192e819 d6990624 f40e3585 106aa070"), K);
        hexWords(cstr("19a4c116 1e376c08 2748774c 34b0bcb5 391c0cb3 4ed8aa4a 5b9cca4f 682e6ff3 748f82ee 78a5636f 84c87814 8cc70208 90befffa a4506ceb bef9a3f7 c67178f2"), K);
    }

    static long rotr(long x, long n) { return ((x >> n) | (x << (32 - n))) & MASK; }

    /* C: hash_block(int64_t *h, const char *block) -- the block pointer becomes (array, offset) */
    static void hashBlock(long[] h, byte[] block, long off) {
        long[] w = new long[64];
        for (long i = 0; i < 16; i += 1) {
            w[(int)i] = (((long)block[(int)(off + 4 * i)] & 255) << 24) | (((long)block[(int)(off + 4 * i + 1)] & 255) << 16)
                 | (((long)block[(int)(off + 4 * i + 2)] & 255) << 8) | ((long)block[(int)(off + 4 * i + 3)] & 255);
        }
        for (long i2 = 16; i2 < 64; i2 += 1) {
            long a = w[(int)(i2 - 15)];
            long b = w[(int)(i2 - 2)];
            long s0 = rotr(a, 7) ^ rotr(a, 18) ^ (a >> 3);
            long s1 = rotr(b, 17) ^ rotr(b, 19) ^ (b >> 10);
            w[(int)i2] = (w[(int)(i2 - 16)] + s0 + w[(int)(i2 - 7)] + s1) & MASK;
        }
        long A = h[0], B = h[1], C = h[2], D = h[3], E = h[4], F = h[5], G = h[6], H = h[7];
        for (long t = 0; t < 64; t += 1) {
            long S1 = rotr(E, 6) ^ rotr(E, 11) ^ rotr(E, 25);
            long ch = (E & F) ^ ((E ^ MASK) & G);
            long t1 = (H + S1 + ch + listValue(K, t) + w[(int)t]) & MASK;
            long S0 = rotr(A, 2) ^ rotr(A, 13) ^ rotr(A, 22);
            long maj = (A & B) ^ (A & C) ^ (B & C);
            long t2 = (S0 + maj) & MASK;
            H = G; G = F; F = E;
            E = (D + t1) & MASK;
            D = C; C = B; B = A;
            A = (t1 + t2) & MASK;
        }
        h[0] = (h[0] + A) & MASK; h[1] = (h[1] + B) & MASK; h[2] = (h[2] + C) & MASK; h[3] = (h[3] + D) & MASK;
        h[4] = (h[4] + E) & MASK; h[5] = (h[5] + F) & MASK; h[6] = (h[6] + G) & MASK; h[7] = (h[7] + H) & MASK;
    }

    /* typedef struct { int64_t h[8]; int64_t total; int64_t rest_n; char rest[64]; } hashstate; */
    static final class HashState {
        final long[] h = new long[8];
        long total;
        long restN;
        final byte[] rest = new byte[64];
    }

    static void hashStart(HashState s) {
        prepare();
        s.h[0] = 1779033703; s.h[1] = 3144134277L; s.h[2] = 1013904242; s.h[3] = 2773480762L;
        s.h[4] = 1359893119; s.h[5] = 2600822924L; s.h[6] = 528734635; s.h[7] = 1541459225;
        s.total = 0;
        s.restN = 0;
    }

    static void hashAdd(HashState s, byte[] data, long len) {
        byte[] d = data;
        long k = 0;
        s.total = s.total + len;
        while (s.restN > 0 && k < len) {
            s.rest[(int)s.restN] = d[(int)k];
            s.restN += 1;
            k += 1;
            if (s.restN == 64) { hashBlock(s.h, s.rest, 0); s.restN = 0; }
        }
        while (k + 64 <= len) {
            hashBlock(s.h, d, k);
            k += 64;
        }
        while (k < len) {
            s.rest[(int)s.restN] = d[(int)k];
            s.restN += 1;
            k += 1;
        }
    }

    static byte[] hashEnd(HashState s) {
        long bits = s.total * 8;
        byte[] tail = new byte[128];
        long n = 0;
        tail[(int)n] = -128; n += 1;
        while ((s.restN + n) % 64 != 56) { tail[(int)n] = 0; n += 1; }
        for (long j = 0; j < 8; j += 1) { tail[(int)n] = (byte)((bits >> (56 - 8 * j)) & 255); n += 1; }
        long before = s.total;
        hashAdd(s, tail, n);
        s.total = before;
        byte[] out = new byte[65];
        byte[] digits = cstr("0123456789abcdef");
        for (long i = 0; i < 8; i += 1)
            for (long b = 0; b < 8; b += 1) out[(int)(i * 8 + b)] = digits[(int)((s.h[(int)i] >> (28 - 4 * b)) & 15)];
        out[64] = 0;
        return out;
    }

    /* a C string literal: its bytes and a terminating 0 */
    static byte[] cstr(String s) {
        byte[] b = s.getBytes(StandardCharsets.US_ASCII);
        return Arrays.copyOf(b, b.length + 1);
    }

    /* printf("%s"): the bytes of a 0-terminated buffer up to the 0 */
    static String jstr(byte[] s) {
        int k = 0;
        while (s[k] != 0) k += 1;
        return new String(s, 0, k, StandardCharsets.US_ASCII);
    }

    public static void main(String[] args) {
        long n = 67108864;
        byte[] buf = new byte[(int)n];
        for (long i = 0; i < n; i += 1) buf[(int)i] = (byte)(((i * 2654435761L) >> 13) & 255);
        HashState s = new HashState();
        hashStart(s);
        hashAdd(s, buf, n);
        System.out.print(jstr(hashEnd(s)) + "\n");
    }
}
