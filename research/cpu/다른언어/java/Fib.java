/* fib(40) -- line-by-line Java port of research/cpu/fib.c (pair: fib.gl) */
public class Fib {
    static long fib(long n) {
        if (n < 2) return n;
        return fib(n - 1) + fib(n - 2);
    }

    public static void main(String[] args) {
        System.out.print(fib(40) + "\n");
    }
}
