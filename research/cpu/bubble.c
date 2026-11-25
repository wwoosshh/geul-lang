/* bubble sort of 30,000 integers -- pair: bubble.gl */
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>

int main(void) {
    int64_t n = 30000;
    int64_t *a = malloc(n * 8);
    int64_t x = 12345;
    for (int64_t i = 0; i < n; i += 1) {
        x = (x * 1103515245 + 12345) & 2147483647;
        a[i] = x % 100000;
    }
    for (int64_t i = 0; i < n - 1; i += 1) {
        for (int64_t j = 0; j < n - 1 - i; j += 1) {
            if (a[j] > a[j + 1]) {
                int64_t t = a[j];
                a[j] = a[j + 1];
                a[j + 1] = t;
            }
        }
    }
    printf("%lld %lld %lld\n", (long long)a[0], (long long)a[n / 2], (long long)a[n - 1]);
    return 0;
}
