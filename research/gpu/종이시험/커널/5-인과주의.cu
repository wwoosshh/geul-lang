// Q, K, V, O: [T][D]. Causal single-head attention, one thread per query.
__global__ void causal_attention(const float* Q, const float* K, const float* V, float* O, int T, int D) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= T) return;
    const float* q = Q + (size_t)i * D;
    float scale = rsqrtf((float)D);
    float m = -INFINITY;
    for (int j = 0; j <= i; j++) {
        float dot = 0.0f;
        for (int d = 0; d < D; d++) dot += q[d] * K[(size_t)j * D + d];
        m = fmaxf(m, dot * scale);
    }
    float s = 0.0f;
    for (int j = 0; j <= i; j++) {
        float dot = 0.0f;
        for (int d = 0; d < D; d++) dot += q[d] * K[(size_t)j * D + d];
        s += expf(dot * scale - m);
    }
    for (int d = 0; d < D; d++) {
        float acc = 0.0f;
        for (int j = 0; j <= i; j++) {
            float dot = 0.0f;
            for (int e = 0; e < D; e++) dot += q[e] * K[(size_t)j * D + e];
            acc += expf(dot * scale - m) / s * V[(size_t)j * D + d];
        }
        O[(size_t)i * D + d] = acc;
    }
}
