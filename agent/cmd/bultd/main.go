package main

import (
	"fmt"
	"os"
	"runtime"
)

var version = "dev"

func main() {
	hostname, err := os.Hostname()
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: failed to get hostname: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("%s, %s/%s, %s\n", hostname, runtime.GOOS, runtime.GOARCH, version)
}
