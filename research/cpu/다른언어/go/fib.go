// fib(40) -- pair: ../../fib.c (line-by-line port of fib.gl)
package main

import "fmt"

func fib(n int64) int64 {
	if n < 2 {
		return n
	}
	return fib(n-1) + fib(n-2)
}

func main() {
	fmt.Printf("%d\n", fib(40))
}
