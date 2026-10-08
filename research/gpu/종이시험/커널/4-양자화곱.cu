#include <stdint.h>
// Wq: [N][K/2] int4 packed (low nibble first, zero point 8), S: [N][K/32] scales, x: [K], y: [N].
__global__ void qgemv(const uint8_t* Wq, const float* S, const float* x, float* y, int N, int K) {
    int n = blockIdx.x * blockDim.x + threadIdx.x;
    if (n >= N) return;
    float acc = 0.0f;
    for (int k = 0; k < K; k++) {
        uint8_t b = Wq[(size_t)n * (K / 2) + k / 2];
        int q = (k & 1) ? (b >> 4) : (b & 15);
        float w = (float)(q - 8) * S[(size_t)n * (K / 32) + k / 32];
        acc += w * x[k];
    }
    y[n] = acc;
}
