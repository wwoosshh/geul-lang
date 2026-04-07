package main

import (
	"fmt"
	"time"
)

func main() {
	N := 500
	A := make([]float64, N*N)
	B := make([]float64, N*N)
	C := make([]float64, N*N)

	for i := 0; i < N*N; i++ {
		A[i] = float64(i % 100)
		B[i] = float64((i * 7) % 100)
	}

	start := time.Now()

	// ikj loop order for cache efficiency (matches C baseline)
	for i := 0; i < N; i++ {
		for k := 0; k < N; k++ {
			aik := A[i*N+k]
			for j := 0; j < N; j++ {
				C[i*N+j] += aik * B[k*N+j]
			}
		}
	}

	elapsed := time.Since(start).Seconds() * 1000

	fmt.Printf("C[0][0]=%.0f C[499][499]=%.0f\n", C[0], C[499*N+499])
	fmt.Printf("RESULT:%.3f\n", elapsed)
}
