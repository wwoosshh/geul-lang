import random
import time

def quicksort(arr, lo, hi):
    if lo < hi:
        p = partition(arr, lo, hi)
        quicksort(arr, lo, p - 1)
        quicksort(arr, p + 1, hi)

def partition(arr, lo, hi):
    pivot = arr[hi]
    i = lo - 1
    for j in range(lo, hi):
        if arr[j] <= pivot:
            i += 1
            arr[i], arr[j] = arr[j], arr[i]
    arr[i + 1], arr[hi] = arr[hi], arr[i + 1]
    return i + 1

n = 1000000
random.seed(42)
arr = [random.randint(0, 2**31 - 1) for _ in range(n)]

import sys
sys.setrecursionlimit(1000000)

start = time.perf_counter()
quicksort(arr, 0, n - 1)
end = time.perf_counter()
ms = (end - start) * 1000

print(f"sorted[0]={arr[0]} sorted[999999]={arr[999999]}")
print(f"RESULT:{ms:.3f}")
