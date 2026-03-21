import sys
import time

sys.setrecursionlimit(100000)

def fib(n):
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)

start = time.perf_counter()
result = fib(40)
end = time.perf_counter()
ms = (end - start) * 1000
print(f"fib(40) = {result}")
print(f"RESULT:{ms:.3f}")
