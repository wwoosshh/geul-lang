// bubble sort of 30,000 integers -- pair: ../../bubble.c (line-by-line port of bubble.gl)
package main

import "fmt"

func main() {
	var n int64 = 30000
	a := make([]int64, n)
	var x int64 = 12345
	for i := int64(0); i < n; i += 1 {
		x = (x*1103515245 + 12345) & 2147483647
		a[i] = x % 100000
	}
	for i := int64(0); i < n-1; i += 1 {
		for j := int64(0); j < n-1-i; j += 1 {
			if a[j] > a[j+1] {
				t := a[j]
				a[j] = a[j+1]
				a[j+1] = t
			}
		}
	}
	fmt.Printf("%d %d %d\n", a[0], a[n/2], a[n-1])
}
