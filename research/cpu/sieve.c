/* sieve of Eratosthenes up to 50,000,000 -- pair: sieve.gl */
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>

int main(void) {
    int64_t n = 50000000;
    char *s = malloc(n + 1);
    for (int64_t i = 0; i <= n; i += 1) s[i] = 1;
    s[0] = 0;
    s[1] = 0;
    for (int64_t p = 2; p * p <= n; p += 1) {
        if (s[p] != 0) {
            for (int64_t j = p * p; j <= n; j += p) s[j] = 0;
        }
    }
    int64_t count = 0;
    for (int64_t k = 0; k <= n; k += 1) {
        if (s[k] != 0) count += 1;
    }
    printf("%lld\n", (long long)count);
    return 0;
}
