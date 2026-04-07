package main

import (
	"fmt"
	"os"
	"time"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "Usage: fileio <filepath>")
		os.Exit(1)
	}

	// Read file outside timer
	buf, err := os.ReadFile(os.Args[1])
	if err != nil {
		fmt.Fprintf(os.Stderr, "Cannot open %s: %v\n", os.Args[1], err)
		os.Exit(1)
	}

	start := time.Now()

	words := 0
	inWord := false
	for _, b := range buf {
		if b == ' ' || b == '\t' || b == '\n' || b == '\r' || b == '\x0b' || b == '\x0c' {
			inWord = false
		} else {
			if !inWord {
				words++
				inWord = true
			}
		}
	}

	elapsed := time.Since(start).Seconds() * 1000

	fmt.Printf("words: %d\n", words)
	fmt.Printf("RESULT:%.3f\n", elapsed)
}
