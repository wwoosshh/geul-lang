import time

limit = 1000000

start = time.perf_counter()

sieve = bytearray(b'\x01' * (limit + 1))
sieve[0] = 0
sieve[1] = 0

i = 2
while i * i <= limit:
    if sieve[i]:
        j = i * i
        while j <= limit:
            sieve[j] = 0
            j += i
    i += 1

count = 0
for i in range(2, limit + 1):
    if sieve[i]:
        count += 1

end = time.perf_counter()
ms = (end - start) * 1000

print(f"primes up to 1000000: {count}")
print(f"RESULT:{ms:.3f}")
