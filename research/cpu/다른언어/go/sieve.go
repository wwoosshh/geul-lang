// sieve of Eratosthenes up to 50,000,000 -- pair: ../../sieve.c (line-by-line port of sieve.gl)
package main

import "fmt"

func main() {
	var n int64 = 50000000
	s := make([]byte, n+1)
	for i := int64(0); i <= n; i += 1 {
		s[i] = 1
	}
	s[0] = 0
	s[1] = 0
	for p := int64(2); p*p <= n; p += 1 {
		if s[p] != 0 {
			for j := p * p; j <= n; j += p {
				s[j] = 0
			}
		}
	}
	var count int64 = 0
	for k := int64(0); k <= n; k += 1 {
		if s[k] != 0 {
			count += 1
		}
	}
	fmt.Printf("%d\n", count)
}
