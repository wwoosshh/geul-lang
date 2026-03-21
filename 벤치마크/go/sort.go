package main

import (
	"fmt"
	"math/rand"
	"time"
)

func partition(arr []int, lo, hi int) int {
	pivot := arr[hi]
	i := lo - 1
	for j := lo; j < hi; j++ {
		if arr[j] <= pivot {
			i++
			arr[i], arr[j] = arr[j], arr[i]
		}
	}
	arr[i+1], arr[hi] = arr[hi], arr[i+1]
	return i + 1
}

func quicksort(arr []int, lo, hi int) {
	if lo < hi {
		p := partition(arr, lo, hi)
		quicksort(arr, lo, p-1)
		quicksort(arr, p+1, hi)
	}
}

func main() {
	n := 1000000
	arr := make([]int, n)
	rng := rand.New(rand.NewSource(42))
	for i := 0; i < n; i++ {
		arr[i] = int(rng.Int31())
	}

	start := time.Now()
	quicksort(arr, 0, n-1)
	elapsed := time.Since(start).Seconds() * 1000

	fmt.Printf("sorted[0]=%d sorted[999999]=%d\n", arr[0], arr[999999])
	fmt.Printf("RESULT:%.3f\n", elapsed)
}
