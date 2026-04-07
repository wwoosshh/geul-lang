import time

N = 500

A = [0.0] * (N * N)
B = [0.0] * (N * N)
C = [0.0] * (N * N)

for i in range(N * N):
    A[i] = float(i % 100)
    B[i] = float((i * 7) % 100)

start = time.perf_counter()

# ikj loop order for cache efficiency (matches C baseline)
for i in range(N):
    for k in range(N):
        a_ik = A[i * N + k]
        for j in range(N):
            C[i * N + j] += a_ik * B[k * N + j]

end = time.perf_counter()
ms = (end - start) * 1000

print(f"C[0][0]={C[0]:.0f} C[499][499]={C[499 * N + 499]:.0f}")
print(f"RESULT:{ms:.3f}")
