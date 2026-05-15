package main

import (
	"fmt"
	"time"
)

func main() {
	n := 30000
	arr := make([]int32, n)

	var seed uint32 = 42
	for i := 0; i < n; i++ {
		seed = seed*1103515245 + 12345
		arr[i] = int32((seed >> 16) & 0x7fff)
	}

	start := time.Now()
	for i := 0; i < n-1; i++ {
		for j := 0; j < n-i-1; j++ {
			if arr[j] > arr[j+1] {
				arr[j], arr[j+1] = arr[j+1], arr[j]
			}
		}
	}
	ms := time.Since(start).Seconds() * 1000

	fmt.Printf("sorted[0]=%d sorted[%d]=%d\n", arr[0], n-1, arr[n-1])
	fmt.Printf("RESULT:%.3f\n", ms)
}
