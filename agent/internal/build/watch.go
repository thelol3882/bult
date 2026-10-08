package build

import (
	"context"
	"errors"
	"fmt"
	"time"
)

// ErrInvalidOffset is returned when offset is negative.
var ErrInvalidOffset = errors.New("invalid offset")

// watchPollInterval: how often a watcher re-checks a running build's log.
const watchPollInterval = 200 * time.Millisecond

// Watch streams the build log of deployID from offset through emit, follows it
// while the build runs, and returns the final status once the build is over
// and every log byte has been emitted. It returns when ctx (the watcher's,
// i.e. the gRPC stream's) is done.
func (m *Manager) Watch(ctx context.Context, deployID string, offset int64, emit func(LogChunk) error) (Status, error) {
	if err := ValidateDeployID(deployID); err != nil {
		return Status{}, err
	}
	if offset < 0 {
		return Status{}, fmt.Errorf("%w: offset must be >= 0 (got %d)", ErrInvalidOffset, offset)
	}

	pos := offset
	ticker := time.NewTicker(watchPollInterval)
	defer ticker.Stop()

	for {
		st, err := m.Get(deployID)
		if err != nil {
			return Status{}, err
		}

		pos, err = m.store.ReadLogFrom(deployID, pos, emit)
		if err != nil {
			return Status{}, err
		}

		if st.State != StateRunning {
			return st, nil
		}

		select {
		case <-ctx.Done():
			return Status{}, ctx.Err()
		case <-ticker.C:
		}
	}
}
