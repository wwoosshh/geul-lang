import sys
import time

if len(sys.argv) < 2:
    print("Usage: python fileio.py <filepath>", file=sys.stderr)
    sys.exit(1)

# Read file outside timer
with open(sys.argv[1], "rb") as f:
    buf = f.read()

start = time.perf_counter()

words = 0
in_word = False
for b in buf:
    if b in (0x20, 0x09, 0x0A, 0x0D, 0x0B, 0x0C):  # isspace
        in_word = False
    else:
        if not in_word:
            words += 1
            in_word = True

end = time.perf_counter()
ms = (end - start) * 1000

print(f"words: {words}")
print(f"RESULT:{ms:.3f}")
