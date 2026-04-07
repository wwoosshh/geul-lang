import time

class Node:
    __slots__ = ('value', 'next')
    def __init__(self, value, next_node):
        self.value = value
        self.next = next_node

start = time.perf_counter()

# Part 1: 1M allocations in batches of 1000 (allocate 1000, delete, repeat)
for batch in range(1000):
    blocks = [bytearray(64) for _ in range(1000)]
    del blocks

# Part 2: Build 100,000-node linked list, traverse
head = None
for i in range(100000):
    head = Node(i, head)

total = 0
cur = head
while cur is not None:
    total += cur.value
    cur = cur.next

# Free linked list
head = None

end = time.perf_counter()
ms = (end - start) * 1000

print(f"allocs: 1000000, list sum: {total}")
print(f"RESULT:{ms:.3f}")
