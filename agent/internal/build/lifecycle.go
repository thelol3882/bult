package build

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"time"
)

// Cancellation causes. ctx.Err() is context.Canceled for both; context.Cause
// tells them apart — and the cause is inherited from a parent context.
var (
	errCancelledByUser = errors.New("cancelled by user")
	errAgentShutdown   = errors.New("agent restarted")
)

// Shutdown cancels every running job with errAgentShutdown and waits until
// they have persisted their final status, or until ctx is done.
func (m *Manager) Shutdown(ctx context.Context) error {
	m.cancelAll(errAgentShutdown)

	done := make(chan struct{})
	go func() {
		m.wg.Wait()
		close(done)
	}()

	select {
	case <-done:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

// Recover marks every job persisted as running — but not run by this process —
// as failed. Call once at startup, before serving. Returns how many it fixed.
func (m *Manager) Recover() (int, error) {
	statuses, err := m.store.List()
	if err != nil {
		return 0, fmt.Errorf("recover: list statuses: %w", err)
	}

	now := time.Now()
	fixed := 0

	for _, st := range statuses {
		if st.State != StateRunning {
			continue
		}

		st.State = StateFailed
		st.Error = errAgentShutdown.Error()
		st.FinishedAt = now

		if err := m.store.WriteStatus(st); err != nil {
			return fixed, fmt.Errorf("recover: persist failed status for deploy %q: %w", st.DeployID, err)
		}
		fixed++
	}

	slog.Info("recovered abandoned jobs", "count", fixed)
	return fixed, nil
}

// finalStateForCancel is used in the finish of run (jobs.go) to pick the final state.
// Kept here next to the causes it decides on.
func finalStateForCancel(ctx context.Context) (State, string) {
	cause := context.Cause(ctx)
	switch {
	case errors.Is(cause, errCancelledByUser):
		return StateCancelled, ""
	case errors.Is(cause, errAgentShutdown):
		return StateFailed, errAgentShutdown.Error()
	default:
		return StateFailed, "internal error, see build log"
	}
}
