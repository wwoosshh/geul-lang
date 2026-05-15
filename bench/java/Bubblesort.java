public class Bubblesort {
    public static void main(String[] args) {
        int n = 30000;
        int[] arr = new int[n];

        long seed = 42;
        for (int i = 0; i < n; i++) {
            seed = (seed * 1103515245L + 12345) & 0xFFFFFFFFL;
            arr[i] = (int)((seed >> 16) & 0x7fff);
        }

        long start = System.nanoTime();
        for (int i = 0; i < n - 1; i++) {
            for (int j = 0; j < n - i - 1; j++) {
                if (arr[j] > arr[j + 1]) {
                    int t = arr[j];
                    arr[j] = arr[j + 1];
                    arr[j + 1] = t;
                }
            }
        }
        double ms = (System.nanoTime() - start) / 1e6;

        System.out.printf("sorted[0]=%d sorted[%d]=%d%n", arr[0], n - 1, arr[n - 1]);
        System.out.printf("RESULT:%.3f%n", ms);
    }
}
