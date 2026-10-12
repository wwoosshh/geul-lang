/* fib(40) -- pair: fib.gl */
#include <stdio.h>
#include <stdint.h>

static int64_t fib(int64_t n) {
    if (n < 2) return n;
    return fib(n - 1) + fib(n - 2);
}

int main(void) {
    printf("%lld\n", (long long)fib(40));
    return 0;
}
