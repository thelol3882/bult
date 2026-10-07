package build

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/thelol3882/bult/agent/internal/docker"
)

// fakeBuilder replaces Docker in Manager tests.
type fakeBuilder struct {
	mu       sync.Mutex
	buildErr error
	digest   string
	block    chan struct{} // if non-nil, BuildImage waits on it or ctx.Done() — for Cancel tests
	builds   int           // how many builds started (guard with a mutex if you read it concurrently)
}

func (f *fakeBuilder) BuildImage(ctx context.Context, buildContext io.Reader, opts docker.BuildOptions, log io.Writer) error {
	f.mu.Lock()
	f.builds++
	f.mu.Unlock()

	if _, err := io.Copy(io.Discard, buildContext); err != nil {
		return err
	}

	_, _ = io.WriteString(log, "fake build\n")

	if f.block != nil {
		select {
		case <-f.block:
		case <-ctx.Done():
			return ctx.Err()
		}
	}

	return f.buildErr
}

func (f *fakeBuilder) PushImage(ctx context.Context, tag string) (string, error) {
	return f.digest, nil
}

func fakeClone(ctx context.Context, src Source, parentDir string) (Checkout, error) {
	dir, err := os.MkdirTemp(parentDir, "fake-src-*")
	if err != nil {
		return Checkout{}, fmt.Errorf("create fake clone dir: %w", err)
	}

	dockerfilePath := filepath.Join(dir, "Dockerfile")
	if err := os.WriteFile(dockerfilePath, []byte("FROM alpine\nCMD [\"echo\", \"hello\"]\n"), 0o644); err != nil {
		_ = os.RemoveAll(dir)
		return Checkout{}, fmt.Errorf("write fake Dockerfile: %w", err)
	}

	return Checkout{
		Dir:    dir,
		Commit: strings.Repeat("a", 40),
	}, nil
}

func newTestManager(t *testing.T, fb *fakeBuilder) *Manager {
	t.Helper()
	store, err := NewStore(t.TempDir())
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}

	m := NewManager(context.Background(), store, fb, "registry.test:5000")
	m.clone = fakeClone
	return m
}

func waitState(t *testing.T, m *Manager, id string) Status {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		st, err := m.Get(id)
		if err != nil {
			t.Fatalf("waitState: Get(%q) error: %v", id, err)
		}
		if st.State != StateRunning {
			return st
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("timed out waiting for deploy %q to finish", id)
	return Status{}
}

func TestBuildSucceeds(t *testing.T) {
	fb := &fakeBuilder{digest: "sha256:112233445566"}
	m := newTestManager(t, fb)

	spec := Spec{
		DeployID: "d-success",
		AppID:    "app-1",
		Source: Source{
			RepoURL: "https://github.com/example/repo.git",
			Branch:  "main",
		},
	}

	initSt, err := m.Start(context.Background(), spec)
	if err != nil {
		t.Fatalf("Start: %v", err)
	}
	if initSt.State != StateRunning {
		t.Fatalf("initial state = %v, want %v", initSt.State, StateRunning)
	}

	finalSt := waitState(t, m, spec.DeployID)
	if finalSt.State != StateSucceeded {
		t.Fatalf("final state = %v, want %v (error: %q)", finalSt.State, StateSucceeded, finalSt.Error)
	}

	wantImage := docker.ImageRef{
		Repository: "registry.test:5000/app-1",
		Digest:     fb.digest,
	}
	if finalSt.Image != wantImage {
		t.Errorf("image = %+v, want %+v", finalSt.Image, wantImage)
	}
	if finalSt.CommitSHA != strings.Repeat("a", 40) {
		t.Errorf("commit_sha = %q, want %q", finalSt.CommitSHA, strings.Repeat("a", 40))
	}

	diskSt, err := m.store.ReadStatus(spec.DeployID)
	if err != nil {
		t.Fatalf("ReadStatus: %v", err)
	}
	if diskSt.State != finalSt.State || diskSt.CommitSHA != finalSt.CommitSHA || diskSt.Image != finalSt.Image {
		t.Errorf("disk status %+v does not match memory status %+v", diskSt, finalSt)
	}

	logPath := filepath.Join(m.store.jobDir(spec.DeployID), "build.log")
	logBytes, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("read log: %v", err)
	}
	if !strings.Contains(string(logBytes), "fake build") {
		t.Errorf("build.log does not contain 'fake build': %q", string(logBytes))
	}
}

func TestBuildFails(t *testing.T) {
	fb := &fakeBuilder{
		// What Docker really reports for a failing RUN: no builder paths in it.
		buildErr: errors.New("build: The command '/bin/sh -c pip install -r requirements.txt' returned a non-zero code: 1"),
	}
	m := newTestManager(t, fb)

	spec := Spec{
		DeployID: "d-fail",
		AppID:    "app-1",
		Source: Source{
			RepoURL: "https://github.com/example/repo.git",
			Branch:  "main",
		},
	}

	_, err := m.Start(context.Background(), spec)
	if err != nil {
		t.Fatalf("Start: %v", err)
	}

	finalSt := waitState(t, m, spec.DeployID)
	if finalSt.State != StateFailed {
		t.Fatalf("final state = %v, want %v", finalSt.State, StateFailed)
	}
	if finalSt.Error == "" {
		t.Fatal("expected non-empty user error on build failure")
	}
	// A build error is the user's own Dockerfile: they must see Docker's message.
	if !strings.Contains(finalSt.Error, "returned a non-zero code: 1") {
		t.Errorf("user error hides the build failure: %q", finalSt.Error)
	}
	if strings.Contains(finalSt.Error, "/tmp/") || strings.Contains(finalSt.Error, "fake-src") {
		t.Errorf("user error leaked internal temp paths: %q", finalSt.Error)
	}
}

func TestStartIsIdempotent(t *testing.T) {
	fb := &fakeBuilder{digest: "sha256:112233"}
	m := newTestManager(t, fb)

	spec := Spec{
		DeployID: "d-idempotent",
		AppID:    "app-1",
		Source: Source{
			RepoURL: "https://github.com/example/repo.git",
			Branch:  "main",
		},
	}

	st1, err := m.Start(context.Background(), spec)
	if err != nil {
		t.Fatalf("first Start: %v", err)
	}

	st2, err := m.Start(context.Background(), spec)
	if err != nil {
		t.Fatalf("second Start: %v", err)
	}
	// Same job, not same snapshot: the fake build may already have finished
	// between the two calls, so State can differ. StartedAt is set once per job.
	if st1.DeployID != st2.DeployID || !st1.StartedAt.Equal(st2.StartedAt) {
		t.Fatalf("second Start returned another job: %+v vs %+v", st1, st2)
	}

	waitState(t, m, spec.DeployID)

	fb.mu.Lock()
	count := fb.builds
	fb.mu.Unlock()
	if count != 1 {
		t.Fatalf("expected 1 build executed, got %d", count)
	}

	diffSpec := spec
	diffSpec.AppID = "app-other"
	_, err = m.Start(context.Background(), diffSpec)
	if !errors.Is(err, ErrDeploySpecMismatch) {
		t.Fatalf("expected ErrDeploySpecMismatch, got: %v", err)
	}
}

func TestCancel(t *testing.T) {
	blockChan := make(chan struct{})
	fb := &fakeBuilder{block: blockChan}
	m := newTestManager(t, fb)

	spec := Spec{
		DeployID: "d-cancel",
		AppID:    "app-1",
		Source: Source{
			RepoURL: "https://github.com/example/repo.git",
			Branch:  "main",
		},
	}

	if _, err := m.Start(context.Background(), spec); err != nil {
		t.Fatalf("Start: %v", err)
	}

	if _, err := m.Cancel(spec.DeployID); err != nil {
		t.Fatalf("Cancel: %v", err)
	}

	finalSt := waitState(t, m, spec.DeployID)
	if finalSt.State != StateCancelled {
		t.Fatalf("state = %v, want %v", finalSt.State, StateCancelled)
	}
}

func TestGetAfterRestart(t *testing.T) {
	storeDir := t.TempDir()
	storeA, err := NewStore(storeDir)
	if err != nil {
		t.Fatalf("NewStore A: %v", err)
	}

	fbA := &fakeBuilder{digest: "sha256:restart-test"}
	mA := NewManager(context.Background(), storeA, fbA, "registry.test:5000")
	mA.clone = fakeClone

	spec := Spec{
		DeployID: "d-restart",
		AppID:    "app-1",
		Source: Source{
			RepoURL: "https://github.com/example/repo.git",
			Branch:  "main",
		},
	}

	if _, err := mA.Start(context.Background(), spec); err != nil {
		t.Fatalf("Start mA: %v", err)
	}
	origSt := waitState(t, mA, spec.DeployID)

	storeB, err := NewStore(storeDir)
	if err != nil {
		t.Fatalf("NewStore B: %v", err)
	}
	fbB := &fakeBuilder{}
	mB := NewManager(context.Background(), storeB, fbB, "registry.test:5000")
	mB.clone = fakeClone

	recoveredSt, err := mB.Get(spec.DeployID)
	if err != nil {
		t.Fatalf("Get mB: %v", err)
	}

	if recoveredSt.DeployID != origSt.DeployID {
		t.Errorf("DeployID = %q, want %q", recoveredSt.DeployID, origSt.DeployID)
	}
	if recoveredSt.State != origSt.State {
		t.Errorf("State = %v, want %v", recoveredSt.State, origSt.State)
	}
	if recoveredSt.Image != origSt.Image {
		t.Errorf("Image = %+v, want %+v", recoveredSt.Image, origSt.Image)
	}
	if recoveredSt.CommitSHA != origSt.CommitSHA {
		t.Errorf("CommitSHA = %q, want %q", recoveredSt.CommitSHA, origSt.CommitSHA)
	}
}
