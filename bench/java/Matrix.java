public class Matrix {
    public static void main(String[] args) {
        int n = 500;
        double[] a = new double[n * n];
        double[] b = new double[n * n];
        double[] c = new double[n * n];

        for (int i = 0; i < n * n; i++) {
            a[i] = i % 100;
            b[i] = (i * 7) % 100;
        }

        long start = System.nanoTime();

        // ikj loop order for cache efficiency
        for (int i = 0; i < n; i++) {
            for (int k = 0; k < n; k++) {
                double a_ik = a[i * n + k];
                for (int j = 0; j < n; j++) {
                    c[i * n + j] += a_ik * b[k * n + j];
                }
            }
        }

        double ms = (System.nanoTime() - start) / 1e6;

        System.out.printf("C[0][0]=%.0f C[499][499]=%.0f%n", c[0], c[499 * n + 499]);
        System.out.printf("RESULT:%.3f%n", ms);
    }
}
