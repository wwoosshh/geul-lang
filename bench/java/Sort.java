import java.util.Random;

public class Sort {
    static void swap(int[] arr, int a, int b) {
        int t = arr[a];
        arr[a] = arr[b];
        arr[b] = t;
    }

    static int partition(int[] arr, int lo, int hi) {
        int pivot = arr[hi];
        int i = lo - 1;
        for (int j = lo; j < hi; j++) {
            if (arr[j] <= pivot) {
                i++;
                swap(arr, i, j);
            }
        }
        swap(arr, i + 1, hi);
        return i + 1;
    }

    static void quicksort(int[] arr, int lo, int hi) {
        if (lo < hi) {
            int p = partition(arr, lo, hi);
            quicksort(arr, lo, p - 1);
            quicksort(arr, p + 1, hi);
        }
    }

    public static void main(String[] args) {
        int n = 1000000;
        int[] arr = new int[n];
        Random rng = new Random(42);
        for (int i = 0; i < n; i++) {
            arr[i] = rng.nextInt();
        }

        long start = System.nanoTime();
        quicksort(arr, 0, n - 1);
        double ms = (System.nanoTime() - start) / 1e6;

        System.out.println("sorted[0]=" + arr[0] + " sorted[999999]=" + arr[999999]);
        System.out.printf("RESULT:%.3f%n", ms);
    }
}
