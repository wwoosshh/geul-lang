// x: [T][D], w: [D], y: [T][D]. One thread per token.
__global__ void rmsnorm(const float* x, const float* w, float* y, int T, int D, float eps) {
    int t = blockIdx.x * blockDim.x + threadIdx.x;
    if (t >= T) return;
    const float* xr = x + (size_t)t * D;
    float ss = 0.0f;
    for (int d = 0; d < D; d++) ss += xr[d] * xr[d];
    float inv = rsqrtf(ss / D + eps);
    for (int d = 0; d < D; d++) y[(size_t)t * D + d] = xr[d] * inv * w[d];
}
