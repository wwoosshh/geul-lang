/* bubble sort of 30,000 integers -- line-by-line Java port of research/cpu/bubble.c (pair: bubble.gl) */
public class Bubble {
    public static void main(String[] args) {
        long n = 30000;
        long[] a = new long[(int)n];
        long x = 12345;
        for (long i = 0; i < n; i += 1) {
            x = (x * 1103515245 + 12345) & 2147483647;
            a[(int)i] = x % 100000;
        }
        for (long i = 0; i < n - 1; i += 1) {
            for (long j = 0; j < n - 1 - i; j += 1) {
                if (a[(int)j] > a[(int)(j + 1)]) {
                    long t = a[(int)j];
                    a[(int)j] = a[(int)(j + 1)];
                    a[(int)(j + 1)] = t;
                }
            }
        }
        System.out.print(a[0] + " " + a[(int)(n / 2)] + " " + a[(int)(n - 1)] + "\n");
    }
}
