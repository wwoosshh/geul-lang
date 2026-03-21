package main

import (
	"fmt"
	"time"
)

func fib(n int) int {
	if n <= 1 {
		return n
	}
	return fib(n-1) + fib(n-2)
}

func main() {
	start := time.Now()
	result := fib(40)
	elapsed := time.Since(start).Seconds() * 1000
	fmt.Printf("fib(40) = %d\n", result)
	fmt.Printf("RESULT:%.3f\n", elapsed)
}
