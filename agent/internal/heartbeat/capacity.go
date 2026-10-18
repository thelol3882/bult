package heartbeat

import (
	"bufio"
	"fmt"
	"os"
	"runtime"
	"strconv"
	"strings"
)

// DetectCapacity reads the CPU count and total memory of this machine.
// Memory is 0 where /proc/meminfo is not available.
func DetectCapacity() Capacity {
	c := Capacity{CPUs: runtime.NumCPU()}
	mem, err := memTotal("/proc/meminfo")
	if err == nil {
		c.MemoryBytes = mem
	}
	return c
}

// memTotal parses the MemTotal line ("MemTotal:  2035636 kB") of a meminfo file.
func memTotal(path string) (int64, error) {
	f, err := os.Open(path)
	if err != nil {
		return 0, err
	}
	defer f.Close()

	sc := bufio.NewScanner(f)
	for sc.Scan() {
		rest, ok := strings.CutPrefix(sc.Text(), "MemTotal:")
		if !ok {
			continue
		}
		fields := strings.Fields(rest)
		if len(fields) != 2 || fields[1] != "kB" {
			return 0, fmt.Errorf("unexpected MemTotal line %q", sc.Text())
		}
		kb, err := strconv.ParseInt(fields[0], 10, 64)
		if err != nil {
			return 0, fmt.Errorf("parse MemTotal: %w", err)
		}
		return kb * 1024, nil
	}
	if err := sc.Err(); err != nil {
		return 0, err
	}
	return 0, fmt.Errorf("MemTotal not found in %s", path)
}
