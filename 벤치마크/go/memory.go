package main

import (
	"fmt"
	"time"
)

type Node struct {
	value int
	next  *Node
}

func main() {
	start := time.Now()

	// Part 1: 1M allocations in batches of 1000
	for batch := 0; batch < 1000; batch++ {
		blocks := make([][]byte, 1000)
		for i := 0; i < 1000; i++ {
			blocks[i] = make([]byte, 64)
		}
		_ = blocks
	}

	// Part 2: Build 100,000-node linked list, traverse
	var head *Node
	for i := 0; i < 100000; i++ {
		head = &Node{value: i, next: head}
	}

	sum := int64(0)
	cur := head
	for cur != nil {
		sum += int64(cur.value)
		cur = cur.next
	}

	head = nil

	elapsed := time.Since(start).Seconds() * 1000

	fmt.Printf("allocs: 1000000, list sum: %d\n", sum)
	fmt.Printf("RESULT:%.3f\n", elapsed)
}
