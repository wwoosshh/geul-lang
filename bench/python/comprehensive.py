import time, sys
sys.setrecursionlimit(200000)

def fib(n):
    if n <= 1: return n
    return fib(n-1) + fib(n-2)

def count_primes(limit):
    sieve = bytearray(b'\x01') * (limit+1)
    sieve[0] = sieve[1] = 0
    i = 2
    while i*i <= limit:
        if sieve[i]:
            j = i*i
            while j <= limit: sieve[j] = 0; j += i
        i += 1
    return sum(sieve[2:])

def sum_squares(limit):
    s = 0
    for i in range(1, limit+1): s += i*i
    return s

def iter_fib(n):
    a, b = 0, 1
    for _ in range(2, n+1): a, b = b, a+b
    return b

def mem_bench(count):
    for _ in range(count): b = bytearray(64); del b

def struct_bench(count):
    x, y, z, s = 1, 2, 3, 0
    for _ in range(count): s += x+y+z; x += 1
    return s

print("================================================================")
print("  Python -- Comprehensive Benchmark")
print("================================================================\n")

t=time.perf_counter(); r=fib(40); e=time.perf_counter()
print(f"[1] fib(40)          = {r}      | {(e-t)*1000:8.1f} ms")

t=time.perf_counter(); r=count_primes(1000000); e=time.perf_counter()
print(f"[2] primes(1M)       = {r}     | {(e-t)*1000:8.1f} ms")

t=time.perf_counter(); r=sum_squares(10000000); e=time.perf_counter()
print(f"[3] sum_sq(10M)      = {r} | {(e-t)*1000:8.1f} ms")

t=time.perf_counter(); r=iter_fib(80); e=time.perf_counter()
print(f"[4] iter_fib(80)     = {r} | {(e-t)*1000:8.3f} ms")

t=time.perf_counter(); mem_bench(1000000); e=time.perf_counter()
print(f"[5] malloc/free(1M)              | {(e-t)*1000:8.1f} ms")

t=time.perf_counter(); r=struct_bench(10000000); e=time.perf_counter()
print(f"[6] struct(10M)      = {r} | {(e-t)*1000:8.1f} ms")

print("\n================================================================")
