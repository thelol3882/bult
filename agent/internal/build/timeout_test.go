package build

import (
	"context"
	"errors"
	"fmt"
	"os/exec"
	"strings"
	"testing"
	"time"
)

// gitExitError returns a real *exec.ExitError, as runGit would wrap.
func gitExitError(t *testing.T, stderr string) error {
	t.Helper()
	runErr := exec.Command("sh", "-c", "exit 128").Run()
	var exitErr *exec.ExitError
	if !errors.As(runErr, &exitErr) {
		t.Fatalf("expected ExitError, got %v", runErr)
	}
	return fmt.Errorf("git clone: %w: %s", exitErr, stderr)
}

func TestClassifyCloneError(t *testing.T) {
	notExit := errors.New("create temp dir: disk full")

	tests := []struct {
		name     string
		err      error
		deadline bool
		want     string
	}{
		{"deadline", gitExitError(t, "fatal: unable to access"), true, "clone timed out (network problem?)"},
		{"not found", gitExitError(t, "remote: Repository not found.\nfatal: repository 'https://github.com/x/y/' not found"), false, "repository not found or private"},
		{"auth", gitExitError(t, "fatal: could not read Username for 'https://github.com': terminal prompts disabled"), false, "repository not found or private"},
		{"network", gitExitError(t, "fatal: unable to access: Could not resolve host: github.com"), false, "network error while cloning"},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got := userError(classifyCloneError(tc.err, tc.deadline))
			if !strings.HasPrefix(got, tc.want) {
				t.Errorf("user error = %q, want prefix %q", got, tc.want)
			}
		})
	}

	// Not a git failure: left alone, so it stays an internal error.
	if got := classifyCloneError(notExit, false); got != notExit {
		t.Errorf("non-git error was rewrapped: %v", got)
	}
	if got := userError(notExit); got != "internal error, see build log" {
		t.Errorf("user error = %q", got)
	}
}

func TestCloneTimeoutFailsJob(t *testing.T) {
	m := newTestManager(t, &fakeBuilder{})
	m.SetTimeouts(50*time.Millisecond, time.Minute)
	m.clone = func(ctx context.Context, _ Source, _ string) (Checkout, error) {
		<-ctx.Done()
		return Checkout{}, fmt.Errorf("git clone: %w: %w", ctx.Err(), exec.ErrNotFound)
	}

	spec := Spec{DeployID: "d-clone-timeout", AppID: "app-1",
		Source: Source{RepoURL: "https://github.com/example/repo.git", Branch: "main"}}
	if _, err := m.Start(context.Background(), spec); err != nil {
		t.Fatalf("Start: %v", err)
	}

	st := waitState(t, m, spec.DeployID)
	if st.State != StateFailed || st.Error != "clone timed out (network problem?)" {
		t.Fatalf("state = %v, error = %q", st.State, st.Error)
	}
}

func TestBuildTimeoutFailsJob(t *testing.T) {
	// block is never closed: the fake build only ends through its context.
	m := newTestManager(t, &fakeBuilder{block: make(chan struct{})})
	m.SetTimeouts(time.Minute, 50*time.Millisecond)

	spec := Spec{DeployID: "d-build-timeout", AppID: "app-1",
		Source: Source{RepoURL: "https://github.com/example/repo.git", Branch: "main"}}
	if _, err := m.Start(context.Background(), spec); err != nil {
		t.Fatalf("Start: %v", err)
	}

	st := waitState(t, m, spec.DeployID)
	if st.State != StateFailed || !strings.HasPrefix(st.Error, "build timed out after 50ms") {
		t.Fatalf("state = %v, error = %q", st.State, st.Error)
	}
}

// A user cancel while the build runs must stay CANCELLED, not turn into a timeout.
func TestCancelDuringBuildIsNotTimeout(t *testing.T) {
	m := newTestManager(t, &fakeBuilder{block: make(chan struct{})})

	spec := Spec{DeployID: "d-cancel-build", AppID: "app-1",
		Source: Source{RepoURL: "https://github.com/example/repo.git", Branch: "main"}}
	if _, err := m.Start(context.Background(), spec); err != nil {
		t.Fatalf("Start: %v", err)
	}
	time.Sleep(50 * time.Millisecond)
	if _, err := m.Cancel(spec.DeployID); err != nil {
		t.Fatalf("Cancel: %v", err)
	}

	st := waitState(t, m, spec.DeployID)
	if st.State != StateCancelled {
		t.Fatalf("state = %v (error %q), want cancelled", st.State, st.Error)
	}
}
