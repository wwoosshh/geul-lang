// z: [T][V] logits, p: [T][V] probabilities. One thread per token row.
__global__ void softmax(const float* z, float* p, int T, int V) {
    int t = blockIdx.x * blockDim.x + threadIdx.x;
    if (t >= T) return;
    const float* row = z + (size_t)t * V;
    float m = -INFINITY;
    for (int v = 0; v < V; v++) m = fmaxf(m, row[v]);
    float s = 0.0f;
    for (int v = 0; v < V; v++) s += expf(row[v] - m);
    for (int v = 0; v < V; v++) p[(size_t)t * V + v] = expf(row[v] - m) / s;
}
