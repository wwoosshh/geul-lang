#include <cuda_bf16.h>
// A: [M][K] bf16, B: [K][N] bf16, C: [M][N] float. C = A x B, accumulated in float.
__global__ void matmul(const __nv_bfloat16* A, const __nv_bfloat16* B, float* C, int M, int N, int K) {
    int r = blockIdx.y * blockDim.y + threadIdx.y;
    int c = blockIdx.x * blockDim.x + threadIdx.x;
    if (r >= M || c >= N) return;
    float acc = 0.0f;
    for (int k = 0; k < K; k++)
        acc += __bfloat162float(A[(size_t)r * K + k]) * __bfloat162float(B[(size_t)k * N + c]);
    C[(size_t)r * N + c] = acc;
}
