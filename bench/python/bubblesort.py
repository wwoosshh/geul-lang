import random, time

random.seed(42)
n = 30000
arr = [random.randint(0, 32767) for _ in range(n)]

start = time.perf_counter()
for i in range(n - 1):
    for j in range(n - i - 1):
        if arr[j] > arr[j + 1]:
            arr[j], arr[j + 1] = arr[j + 1], arr[j]
ms = (time.perf_counter() - start) * 1000

print(f"sorted[0]={arr[0]} sorted[{n-1}]={arr[-1]}")
print(f"RESULT:{ms:.3f}")
