package main

import (
	"fmt"
	"time"
)

func main() {
	N := 200
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

	fmt.Printf("C[0][0]=%.0f C[%d][%d]=%.0f\n", C[0], N-1, N-1, C[(N-1)*N+(N-1)])
	fmt.Printf("RESULT:%.3f\n", elapsed)
}
