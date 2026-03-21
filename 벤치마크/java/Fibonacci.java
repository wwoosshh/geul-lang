public class Fibonacci {
    static int fib(int n) {
        if (n <= 1) return n;
        return fib(n - 1) + fib(n - 2);
    }

    public static void main(String[] args) {
        long start = System.nanoTime();
        int result = fib(40);
        double ms = (System.nanoTime() - start) / 1e6;
        System.out.println("fib(40) = " + result);
        System.out.printf("RESULT:%.3f%n", ms);
    }
}
