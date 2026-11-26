/* sieve of Eratosthenes up to 50,000,000 -- line-by-line Java port of research/cpu/sieve.c (pair: sieve.gl) */
public class Sieve {
    public static void main(String[] args) {
        long n = 50000000;
        byte[] s = new byte[(int)(n + 1)];
        for (long i = 0; i <= n; i += 1) s[(int)i] = 1;
        s[0] = 0;
        s[1] = 0;
        for (long p = 2; p * p <= n; p += 1) {
            if (s[(int)p] != 0) {
                for (long j = p * p; j <= n; j += p) s[(int)j] = 0;
            }
        }
        long count = 0;
        for (long k = 0; k <= n; k += 1) {
            if (s[(int)k] != 0) count += 1;
        }
        System.out.print(count + "\n");
    }
}
