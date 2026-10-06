package ports

import (
	"errors"
	"fmt"
	"sync"
)

// ErrExhausted is returned by Reserve when every port in the range is taken.
// A sentinel error: callers check it with errors.Is.
var ErrExhausted = errors.New("ports: range exhausted")

// Allocator hands out host ports from [min, max]. Safe for concurrent use.
type Allocator struct {
	mu       sync.Mutex
	min, max int
	taken    map[int]struct{}
}

// New creates an allocator for ports min..max inclusive.
func New(min, max int) (*Allocator, error) {
	if min < 1 || max > 65535 || min > max {
		return nil, fmt.Errorf("invalid port range [%d, %d]: must satisfy 1 <= min <= max <= 65535", min, max)
	}

	return &Allocator{
		min:   min,
		max:   max,
		taken: map[int]struct{}{},
	}, nil
}

// Claim marks a specific port as taken. Used at startup to load the ports of
// existing replicas. Ports outside the range are ignored (not ours to manage).
func (a *Allocator) Claim(port int) {
	a.mu.Lock()
	defer a.mu.Unlock()

	if port < a.min || port > a.max {
		return
	}

	a.taken[port] = struct{}{}
}

// Reserve returns a free port and marks it taken, as one atomic step.
func (a *Allocator) Reserve() (int, error) {
	a.mu.Lock()
	defer a.mu.Unlock()

	for i := a.min; i <= a.max; i++ {
		if _, ok := a.taken[i]; !ok {
			a.taken[i] = struct{}{}
			return i, nil
		}
	}

	return 0, ErrExhausted
}

// Release returns a port to the pool. Releasing a free port is a no-op.
func (a *Allocator) Release(port int) {
	a.mu.Lock()
	defer a.mu.Unlock()

	delete(a.taken, port)
}
