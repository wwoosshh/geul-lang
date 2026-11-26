/* double-precision matrix multiply 500 x 500 (i-k-j order) -- line-by-line Java port of research/cpu/matmul.c (pair: matmul.gl).
   Java never fuses a multiply and an add (the C is built with -ffp-contract=off for the same reason). */
import java.util.Locale;

public class Matmul {
    public static void main(String[] args) {
        long n = 500;
        double[] a = new double[(int)(n * n)];
        double[] b = new double[(int)(n * n)];
        double[] c = new double[(int)(n * n)];
        for (long i = 0; i < n * n; i += 1) {
            a[(int)i] = (double)(i % 7) * 0.5;
            b[(int)i] = (double)(i % 11) * 0.25;
            c[(int)i] = 0.0;
        }
        for (long i = 0; i < n; i += 1) {
            for (long k = 0; k < n; k += 1) {
                double aik = a[(int)(i * n + k)];
                for (long j = 0; j < n; j += 1) {
                    c[(int)(i * n + j)] = c[(int)(i * n + j)] + aik * b[(int)(k * n + j)];
                }
            }
        }
        double sum = 0.0;
        for (long q = 0; q < n * n; q += 1) sum = sum + c[(int)q];
        System.out.print(String.format(Locale.ROOT, "%f", sum) + "\n");
    }
}
