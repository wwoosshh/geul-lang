package main

import (
	"fmt"
	"time"
)

func main() {
	limit := 1000000

	start := time.Now()

	sieve := make([]bool, limit+1)
	for i := 2; i <= limit; i++ {
		sieve[i] = true
	}

	for i := 2; i*i <= limit; i++ {
		if sieve[i] {
			for j := i * i; j <= limit; j += i {
				sieve[j] = false
			}
		}
	}

	count := 0
	for i := 2; i <= limit; i++ {
		if sieve[i] {
			count++
		}
	}

	elapsed := time.Since(start).Seconds() * 1000

	fmt.Printf("primes up to 1000000: %d\n", count)
	fmt.Printf("RESULT:%.3f\n", elapsed)
}
