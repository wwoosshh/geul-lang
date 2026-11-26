// double-precision matrix multiply 500 x 500 (i-k-j order) -- pair: ../../matmul.c (line-by-line port of matmul.gl).
// Build with GOAMD64=v1 (the default): no FMA instructions, so the compiler never fuses a multiply and an add
// (the C is built with -ffp-contract=off for the same reason).
package main

import "fmt"

func main() {
	var n int64 = 500
	a := make([]float64, n*n)
	b := make([]float64, n*n)
	c := make([]float64, n*n)
	for i := int64(0); i < n*n; i += 1 {
		a[i] = float64(i%7) * 0.5
		b[i] = float64(i%11) * 0.25
		c[i] = 0.0
	}
	for i := int64(0); i < n; i += 1 {
		for k := int64(0); k < n; k += 1 {
			aik := a[i*n+k]
			for j := int64(0); j < n; j += 1 {
				c[i*n+j] = c[i*n+j] + aik*b[k*n+j]
			}
		}
	}
	sum := 0.0
	for q := int64(0); q < n*n; q += 1 {
		sum = sum + c[q]
	}
	fmt.Printf("%f\n", sum)
}
