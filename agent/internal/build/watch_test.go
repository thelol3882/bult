package build

import (
	"bytes"
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

func TestReadLogFrom(t *testing.T) {
	storeDir := t.TempDir()
	store, err := NewStore(storeDir)
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}

	deployID := "d-read-log"
	f, err := store.OpenLog(deployID)
	if err != nil {
		t.Fatalf("OpenLog: %v", err)
	}
	content := "hello\nworld\n"
	if _, err := io.WriteString(f, content); err != nil {
		t.Fatalf("write to log: %v", err)
	}
	_ = f.Close()

	var chunks0 []LogChunk
	nextOff, err := store.ReadLogFrom(deployID, 0, func(c LogChunk) error {
		chunks0 = append(chunks0, LogChunk{
			Offset: c.Offset,
			Data:   bytes.Clone(c.Data),
		})
		return nil
	})
	if err != nil {
		t.Fatalf("ReadLogFrom(0): %v", err)
	}
	if nextOff != int64(len(content)) {
		t.Fatalf("nextOff = %d, want %d", nextOff, len(content))
	}
	var buf0 bytes.Buffer
	for _, c := range chunks0 {
		buf0.Write(c.Data)
	}
	if buf0.String() != content {
		t.Fatalf("collected data = %q, want %q", buf0.String(), content)
	}

	var chunks6 []LogChunk
	nextOff, err = store.ReadLogFrom(deployID, 6, func(c LogChunk) error {
		chunks6 = append(chunks6, LogChunk{
			Offset: c.Offset,
			Data:   bytes.Clone(c.Data),
		})
		return nil
	})
	if err != nil {
		t.Fatalf("ReadLogFrom(6): %v", err)
	}
	if nextOff != int64(len(content)) {
		t.Fatalf("nextOff = %d, want %d", nextOff, len(content))
	}
	if len(chunks6) == 0 {
		t.Fatal("expected at least one chunk for offset 6")
	}
	if chunks6[0].Offset != 6 {
		t.Errorf("chunk offset = %d, want 6", chunks6[0].Offset)
	}
	var buf6 bytes.Buffer
	for _, c := range chunks6 {
		buf6.Write(c.Data)
	}
	if buf6.String() != "world\n" {
		t.Fatalf("collected data = %q, want \"world\\n\"", buf6.String())
	}

	nextOff, err = store.ReadLogFrom(deployID, 100, func(c LogChunk) error {
		t.Fatalf("unexpected emit at offset 100: %+v", c)
		return nil
	})
	if err != nil {
		t.Fatalf("ReadLogFrom(100): %v", err)
	}
	if nextOff != 100 {
		t.Fatalf("nextOff = %d, want 100", nextOff)
	}

	nextOff, err = store.ReadLogFrom("unknown-deploy-id", 0, func(c LogChunk) error {
		t.Fatalf("unexpected emit for unknown deploy: %+v", c)
		return nil
	})
	if err != nil {
		t.Fatalf("ReadLogFrom unknown: %v", err)
	}
	if nextOff != 0 {
		t.Fatalf("nextOff = %d, want 0", nextOff)
	}
}

func TestWatchFinishedBuild(t *testing.T) {
	fb := &fakeBuilder{digest: "sha256:watch-finished"}
	m := newTestManager(t, fb)

	spec := Spec{
		DeployID: "d-watch-finished",
		AppID:    "app-1",
		Source: Source{
			RepoURL: "https://github.com/example/repo.git",
			Branch:  "main",
		},
	}

	if _, err := m.Start(context.Background(), spec); err != nil {
		t.Fatalf("Start: %v", err)
	}
	waitState(t, m, spec.DeployID)

	var joined bytes.Buffer
	emit := func(c LogChunk) error {
		joined.Write(c.Data)
		return nil
	}

	st, err := m.Watch(context.Background(), spec.DeployID, 0, emit)
	if err != nil {
		t.Fatalf("Watch: %v", err)
	}
	if st.State != StateSucceeded {
		t.Fatalf("status.State = %v, want %v", st.State, StateSucceeded)
	}

	rawLog, err := os.ReadFile(filepath.Join(m.store.jobDir(spec.DeployID), "build.log"))
	if err != nil {
		t.Fatalf("read build.log: %v", err)
	}
	if joined.String() != string(rawLog) {
		t.Fatalf("streamed log %q does not match file %q", joined.String(), string(rawLog))
	}
}

func TestWatchFollowsRunningBuild(t *testing.T) {
	blockChan := make(chan struct{})
	fb := &fakeBuilder{
		digest: "sha256:watch-running",
		block:  blockChan,
	}
	m := newTestManager(t, fb)

	spec := Spec{
		DeployID: "d-watch-running",
		AppID:    "app-1",
		Source: Source{
			RepoURL: "https://github.com/example/repo.git",
			Branch:  "main",
		},
	}

	if _, err := m.Start(context.Background(), spec); err != nil {
		t.Fatalf("Start: %v", err)
	}

	type watchResult struct {
		status Status
		err    error
	}
	resCh := make(chan watchResult, 1)

	var (
		mu     sync.Mutex
		joined bytes.Buffer
	)
	emit := func(c LogChunk) error {
		mu.Lock()
		defer mu.Unlock()
		joined.Write(c.Data)
		return nil
	}

	go func() {
		st, err := m.Watch(context.Background(), spec.DeployID, 0, emit)
		resCh <- watchResult{status: st, err: err}
	}()

	time.Sleep(300 * time.Millisecond)
	close(blockChan)

	select {
	case res := <-resCh:
		if res.err != nil {
			t.Fatalf("Watch returned error: %v", res.err)
		}
		if res.status.State != StateSucceeded {
			t.Fatalf("state = %v, want %v", res.status.State, StateSucceeded)
		}
		mu.Lock()
		output := joined.String()
		mu.Unlock()
		if bytes.Count([]byte(output), []byte("fake build\n")) != 1 {
			t.Fatalf("expected 'fake build\\n' exactly once, got: %q", output)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("timed out waiting for Watch to complete")
	}
}

func TestWatchStopsWhenClientLeaves(t *testing.T) {
	blockChan := make(chan struct{})
	defer close(blockChan)

	fb := &fakeBuilder{block: blockChan}
	m := newTestManager(t, fb)

	spec := Spec{
		DeployID: "d-watch-cancel",
		AppID:    "app-1",
		Source: Source{
			RepoURL: "https://github.com/example/repo.git",
			Branch:  "main",
		},
	}

	if _, err := m.Start(context.Background(), spec); err != nil {
		t.Fatalf("Start: %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	errCh := make(chan error, 1)

	go func() {
		_, err := m.Watch(ctx, spec.DeployID, 0, func(c LogChunk) error { return nil })
		errCh <- err
	}()

	time.Sleep(50 * time.Millisecond)
	cancel()

	select {
	case err := <-errCh:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("Watch returned error %v, want context.Canceled", err)
		}
	case <-time.After(1 * time.Second):
		t.Fatal("timed out waiting for Watch to exit upon context cancellation")
	}
}

func TestCancelVsShutdownCause(t *testing.T) {
	specA := Spec{
		DeployID: "d-cancel-cause",
		AppID:    "app-1",
		Source: Source{
			RepoURL: "https://github.com/example/repo.git",
			Branch:  "main",
		},
	}
	specB := Spec{
		DeployID: "d-shutdown-cause",
		AppID:    "app-1",
		Source: Source{
			RepoURL: "https://github.com/example/repo.git",
			Branch:  "main",
		},
	}

	blockA := make(chan struct{})
	fbA := &fakeBuilder{block: blockA}
	mA := newTestManager(t, fbA)

	if _, err := mA.Start(context.Background(), specA); err != nil {
		t.Fatalf("mA.Start: %v", err)
	}
	if _, err := mA.Cancel(specA.DeployID); err != nil {
		t.Fatalf("mA.Cancel: %v", err)
	}

	stA := waitState(t, mA, specA.DeployID)
	if stA.State != StateCancelled {
		t.Fatalf("stA.State = %v, want %v", stA.State, StateCancelled)
	}
	if stA.Error != "" {
		t.Fatalf("stA.Error = %q, want empty", stA.Error)
	}

	blockB := make(chan struct{})
	fbB := &fakeBuilder{block: blockB}
	mB := newTestManager(t, fbB)

	if _, err := mB.Start(context.Background(), specB); err != nil {
		t.Fatalf("mB.Start: %v", err)
	}

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer shutdownCancel()

	if err := mB.Shutdown(shutdownCtx); err != nil {
		t.Fatalf("mB.Shutdown: %v", err)
	}

	diskStB, err := mB.store.ReadStatus(specB.DeployID)
	if err != nil {
		t.Fatalf("ReadStatus B: %v", err)
	}
	if diskStB.State != StateFailed {
		t.Fatalf("disk state = %v, want %v", diskStB.State, StateFailed)
	}
	if diskStB.Error != errAgentShutdown.Error() {
		t.Fatalf("disk error = %q, want %q", diskStB.Error, errAgentShutdown.Error())
	}

	stB, err := mB.Get(specB.DeployID)
	if err != nil {
		t.Fatalf("mB.Get: %v", err)
	}
	if stB.State != StateFailed {
		t.Fatalf("stB.State = %v, want %v", stB.State, StateFailed)
	}
	if stB.Error != errAgentShutdown.Error() {
		t.Fatalf("stB.Error = %q, want %q", stB.Error, errAgentShutdown.Error())
	}
}

func TestRecover(t *testing.T) {
	storeDir := t.TempDir()
	store, err := NewStore(storeDir)
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}

	abandoned := Status{
		DeployID:  "d-abandoned",
		AppID:     "app-1",
		Source:    Source{RepoURL: "https://github.com/example/repo.git", Branch: "main"},
		State:     StateRunning,
		StartedAt: time.Now().Add(-5 * time.Minute),
	}
	if err := store.WriteStatus(abandoned); err != nil {
		t.Fatalf("WriteStatus: %v", err)
	}

	fb := &fakeBuilder{}
	m := NewManager(context.Background(), store, fb, "registry.test:5000")
	shutdownOnCleanup(t, m)
	m.clone = fakeClone

	recoveredCount, err := m.Recover()
	if err != nil {
		t.Fatalf("Recover: %v", err)
	}
	if recoveredCount != 1 {
		t.Fatalf("recoveredCount = %d, want 1", recoveredCount)
	}

	diskSt, err := store.ReadStatus(abandoned.DeployID)
	if err != nil {
		t.Fatalf("ReadStatus: %v", err)
	}
	if diskSt.State != StateFailed {
		t.Fatalf("recovered status State = %v, want %v", diskSt.State, StateFailed)
	}
	if diskSt.Error != errAgentShutdown.Error() {
		t.Fatalf("recovered status Error = %q, want %q", diskSt.Error, errAgentShutdown.Error())
	}
	if diskSt.FinishedAt.IsZero() {
		t.Fatal("expected non-zero FinishedAt timestamp on recovered status")
	}
}
