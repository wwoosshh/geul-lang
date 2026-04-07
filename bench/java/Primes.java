public class Primes {
    public static void main(String[] args) {
        int limit = 1000000;

        long start = System.nanoTime();

        boolean[] sieve = new boolean[limit + 1];
        for (int i = 2; i <= limit; i++) sieve[i] = true;

        for (int i = 2; (long) i * i <= limit; i++) {
            if (sieve[i]) {
                for (int j = i * i; j <= limit; j += i) {
                    sieve[j] = false;
                }
            }
        }

        int count = 0;
        for (int i = 2; i <= limit; i++) {
            if (sieve[i]) count++;
        }

        double ms = (System.nanoTime() - start) / 1e6;

        System.out.println("primes up to 1000000: " + count);
        System.out.printf("RESULT:%.3f%n", ms);
    }
}
