/* double-precision matrix multiply 500 x 500 (i-k-j order) -- pair: matmul.gl.
   Build with -ffp-contract=off: geul never fuses a multiply and an add unless the source says so. */
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>

int main(void) {
    int64_t n = 500;
    double *a = malloc(n * n * 8);
    double *b = malloc(n * n * 8);
    double *c = malloc(n * n * 8);
    for (int64_t i = 0; i < n * n; i += 1) {
        a[i] = (double)(i % 7) * 0.5;
        b[i] = (double)(i % 11) * 0.25;
        c[i] = 0.0;
    }
    for (int64_t i = 0; i < n; i += 1) {
        for (int64_t k = 0; k < n; k += 1) {
            double aik = a[i * n + k];
            for (int64_t j = 0; j < n; j += 1) {
                c[i * n + j] = c[i * n + j] + aik * b[k * n + j];
            }
        }
    }
    double sum = 0.0;
    for (int64_t q = 0; q < n * n; q += 1) sum = sum + c[q];
    printf("%f\n", sum);
    return 0;
}
