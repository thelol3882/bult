package ports

import (
	"errors"
	"sync"
	"testing"
)

func TestNewRejectsBadRange(t *testing.T) {
	cases := []struct {
		name     string
		min, max int
	}{
		{name: "min > max", min: 10, max: 5},
		{name: "min = 0", min: 0, max: 100},
		{name: "max = 70000", min: 1000, max: 70000},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			alloc, err := New(tc.min, tc.max)
			if err == nil {
				t.Fatalf("New(%d, %d) expected error, got nil (allocator: %+v)", tc.min, tc.max, alloc)
			}
		})
	}
}

func TestReserveReturnsDistinctPorts(t *testing.T) {
	min, max := 8000, 8002
	alloc, err := New(min, max)
	if err != nil {
		t.Fatalf("failed to create allocator: %v", err)
	}

	seen := make(map[int]bool)
	for i := 0; i < 3; i++ {
		port, err := alloc.Reserve()
		if err != nil {
			t.Fatalf("Reserve() call %d failed unexpectedly: %v", i+1, err)
		}
		if port < min || port > max {
			t.Fatalf("Reserve() returned %d, out of range [%d, %d]", port, min, max)
		}
		if seen[port] {
			t.Fatalf("Reserve() returned duplicate port: %d", port)
		}
		seen[port] = true
	}
}

func TestReserveExhausted(t *testing.T) {
	alloc, err := New(9000, 9001)
	if err != nil {
		t.Fatalf("failed to create allocator: %v", err)
	}

	// First two must succeed
	for i := 0; i < 2; i++ {
		if _, err := alloc.Reserve(); err != nil {
			t.Fatalf("Reserve() call %d failed: %v", i+1, err)
		}
	}

	// Third call must fail with ErrExhausted
	port, err := alloc.Reserve()
	if !errors.Is(err, ErrExhausted) {
		t.Fatalf("expected ErrExhausted, got port %d and error: %v", port, err)
	}
}

func TestReleaseMakesPortReusable(t *testing.T) {
	alloc, err := New(5000, 5000)
	if err != nil {
		t.Fatalf("failed to create allocator: %v", err)
	}

	port1, err := alloc.Reserve()
	if err != nil {
		t.Fatalf("first Reserve() failed: %v", err)
	}

	alloc.Release(port1)

	port2, err := alloc.Reserve()
	if err != nil {
		t.Fatalf("second Reserve() after release failed: %v", err)
	}

	if port1 != port2 {
		t.Fatalf("got port %d, want re-reserved port %d", port2, port1)
	}
}

func TestClaimSkipsTakenPorts(t *testing.T) {
	alloc, err := New(20000, 20002)
	if err != nil {
		t.Fatalf("failed to create allocator: %v", err)
	}

	// Out-of-range claim: should be ignored without panic/failure
	alloc.Claim(99)

	// Claim existing ports
	alloc.Claim(20000)
	alloc.Claim(20001)

	got, err := alloc.Reserve()
	if err != nil {
		t.Fatalf("Reserve() failed: %v", err)
	}
	if got != 20002 {
		t.Fatalf("Reserve() = %d, want 20002", got)
	}
}

func TestReserveConcurrent(t *testing.T) {
	const count = 100
	const min = 30000
	const max = min + count - 1

	alloc, err := New(min, max)
	if err != nil {
		t.Fatalf("failed to create allocator: %v", err)
	}

	type result struct {
		port int
		err  error
	}

	results := make(chan result, count)
	var wg sync.WaitGroup

	for i := 0; i < count; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			p, err := alloc.Reserve()
			results <- result{port: p, err: err}
		}()
	}

	wg.Wait()
	close(results)

	seen := make(map[int]bool)
	for res := range results {
		if res.err != nil {
			t.Fatalf("concurrent Reserve() failed with error: %v", res.err)
		}
		if res.port < min || res.port > max {
			t.Fatalf("concurrent Reserve() port %d out of bounds [%d, %d]", res.port, min, max)
		}
		if seen[res.port] {
			t.Fatalf("race/duplicate detected: port %d returned multiple times", res.port)
		}
		seen[res.port] = true
	}

	if len(seen) != count {
		t.Fatalf("expected %d distinct ports, allocated %d", count, len(seen))
	}
}
