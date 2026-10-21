package watch

import (
	"context"
	"errors"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/thelol3882/bult/agent/internal/docker"
)

const testWait = 3 * time.Second

type fakeSource struct {
	mu   sync.Mutex
	reps map[string]docker.Replica

	events        chan string
	subscribes    atomic.Int32
	failSubscribe atomic.Int32 // the next N subscriptions end at once with an error
	listCalls     atomic.Int32
}

func newFakeSource(reps ...docker.Replica) *fakeSource {
	f := &fakeSource{reps: map[string]docker.Replica{}, events: make(chan string)}
	for _, r := range reps {
		f.reps[r.ReplicaID] = r
	}
	return f
}

func (f *fakeSource) set(r docker.Replica) {
	f.mu.Lock()
	f.reps[r.ReplicaID] = r
	f.mu.Unlock()
}

func (f *fakeSource) remove(id string) {
	f.mu.Lock()
	delete(f.reps, id)
	f.mu.Unlock()
}

func (f *fakeSource) List(context.Context) ([]docker.Replica, error) {
	f.listCalls.Add(1)
	f.mu.Lock()
	defer f.mu.Unlock()
	out := make([]docker.Replica, 0, len(f.reps))
	for _, r := range f.reps {
		out = append(out, r)
	}
	return out, nil
}

func (f *fakeSource) Inspect(_ context.Context, id string) (docker.Replica, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	r, ok := f.reps[id]
	if !ok {
		return docker.Replica{}, docker.ErrNotFound
	}
	return r, nil
}

func (f *fakeSource) ReplicaEvents(ctx context.Context) (<-chan string, <-chan error) {
	f.subscribes.Add(1)
	ids := make(chan string)
	errs := make(chan error, 1)
	if f.failSubscribe.Add(-1) >= 0 {
		errs <- errors.New("daemon gone")
		close(ids)
		return ids, errs
	}
	go func() {
		defer close(ids)
		for {
			select {
			case <-ctx.Done():
				errs <- ctx.Err()
				return
			case id := <-f.events:
				select {
				case ids <- id:
				case <-ctx.Done():
					errs <- ctx.Err()
					return
				}
			}
		}
	}()
	return ids, errs
}

// emit delivers an event, failing the test if nobody receives it.
func (f *fakeSource) emit(t *testing.T, id string) {
	t.Helper()
	select {
	case f.events <- id:
	case <-time.After(testWait):
		t.Fatal("event not consumed")
	}
}

func running(id string) docker.Replica {
	return docker.Replica{
		ReplicaID: id, State: docker.StateRunning, Status: "running", HostPort: 20000,
		StartedAt: time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC),
	}
}

func died(id string, code int) docker.Replica {
	r := running(id)
	r.State, r.Status, r.ExitCode = docker.StateExited, "exited", code
	r.FinishedAt = time.Date(2026, 1, 1, 0, 5, 0, 0, time.UTC)
	return r
}

// startWatcher runs w and returns a stop that cancels it and checks that Run returns.
func startWatcher(t *testing.T, w *Watcher) (stop func()) {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		defer close(done)
		w.Run(ctx)
	}()
	var once sync.Once
	stop = func() {
		once.Do(func() {
			cancel()
			select {
			case <-done:
			case <-time.After(testWait):
				t.Error("Run did not return after cancel")
			}
		})
	}
	t.Cleanup(stop)
	return stop
}

func waitFor(t *testing.T, what string, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(testWait)
	for !cond() {
		if time.Now().After(deadline) {
			t.Fatalf("timed out waiting for %s", what)
		}
		time.Sleep(2 * time.Millisecond)
	}
}

func statusOfID(w *Watcher, id string) (Status, bool) {
	for _, s := range w.Snapshot() {
		if s.ReplicaID == id {
			return s, true
		}
	}
	return Status{}, false
}

// quiet keeps the periodic loops out of the way unless a test wants them.
func quiet() Config {
	return Config{
		Resync: time.Hour, ProbeInterval: time.Hour, Reconnect: time.Millisecond,
		Probe: func(context.Context, int, string) bool { return true },
	}
}

func TestSyncReadsEverythingSorted(t *testing.T) {
	src := newFakeSource(running("b"), died("a", 1))
	w := New(src, quiet())
	if w.Synced() {
		t.Fatal("synced before the first list")
	}
	if err := w.Sync(context.Background()); err != nil {
		t.Fatal(err)
	}
	got := w.Snapshot()
	if len(got) != 2 || got[0].ReplicaID != "a" || got[1].ReplicaID != "b" {
		t.Fatalf("snapshot = %+v", got)
	}
	if !w.Synced() {
		t.Error("not synced after Sync")
	}
	if got[0].State != StateExited || got[0].ExitCode != 1 || got[0].Healthy {
		t.Errorf("exited replica = %+v", got[0])
	}
	if got[1].State != StateRunning || !got[1].Healthy {
		t.Errorf("running replica = %+v", got[1])
	}
}

func TestStatusMapping(t *testing.T) {
	oom := died("x", 137)
	oom.OOMKilled = true
	created := docker.Replica{ReplicaID: "c", Status: "created"}
	dead := died("d", 1)
	dead.Status = "dead"

	tests := []struct {
		name string
		rep  docker.Replica
		want State
	}{
		{"running", running("r"), StateRunning},
		{"exited", died("e", 2), StateExited},
		{"oom killed", oom, StateOOM},
		{"dead", dead, StateExited},
		{"created and never started", created, StateExited},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			s := statusOf(tc.rep)
			if s.State != tc.want {
				t.Errorf("state = %s, want %s", s.State, tc.want)
			}
			if s.State == StateRunning && (s.ExitCode != 0 || !s.FinishedAt.IsZero()) {
				t.Errorf("running replica carries exit data: %+v", s)
			}
		})
	}
}

func TestEventUpdatesState(t *testing.T) {
	src := newFakeSource(running("a"))
	w := New(src, quiet())
	if err := w.Sync(context.Background()); err != nil {
		t.Fatal(err)
	}
	startWatcher(t, w)

	src.set(died("a", 137))
	src.emit(t, "a")
	waitFor(t, "exit seen", func() bool {
		s, _ := statusOfID(w, "a")
		return s.State == StateExited && s.ExitCode == 137
	})

	// a replica the first list never saw, announced by an event
	src.set(running("new"))
	src.emit(t, "new")
	waitFor(t, "new replica", func() bool { _, ok := statusOfID(w, "new"); return ok })
}

func TestResyncCatchesChangeWithoutEvent(t *testing.T) {
	src := newFakeSource(running("a"))
	cfg := quiet()
	cfg.Resync = 10 * time.Millisecond
	w := New(src, cfg)
	if err := w.Sync(context.Background()); err != nil {
		t.Fatal(err)
	}
	startWatcher(t, w)

	src.set(died("a", 1)) // no event
	waitFor(t, "resync to see the exit", func() bool {
		s, _ := statusOfID(w, "a")
		return s.State == StateExited
	})
}

func TestResyncDropsVanishedReplica(t *testing.T) {
	src := newFakeSource(running("a"), running("b"))
	cfg := quiet()
	cfg.Resync = 10 * time.Millisecond
	w := New(src, cfg)
	if err := w.Sync(context.Background()); err != nil {
		t.Fatal(err)
	}
	startWatcher(t, w)

	src.remove("a")
	waitFor(t, "a to be dropped", func() bool { _, ok := statusOfID(w, "a"); return !ok })
	if _, ok := statusOfID(w, "b"); !ok {
		t.Error("b must stay")
	}
}

func TestEventForVanishedReplicaDropsIt(t *testing.T) {
	src := newFakeSource(running("a"))
	w := New(src, quiet())
	if err := w.Sync(context.Background()); err != nil {
		t.Fatal(err)
	}
	startWatcher(t, w)

	src.remove("a")
	src.emit(t, "a") // destroy
	waitFor(t, "a to be dropped", func() bool { _, ok := statusOfID(w, "a"); return !ok })
}

// A list taken before a destroy event must not bring the replica back.
func TestStaleListDoesNotResurrectDroppedReplica(t *testing.T) {
	src := newFakeSource(running("a"))
	w := New(src, quiet())
	if err := w.Sync(context.Background()); err != nil {
		t.Fatal(err)
	}

	stale := &staleList{fakeSource: src, hook: func() {
		// the destroy event is handled while the list is in flight
		src.remove("a")
		w.refresh(context.Background(), "a")
	}}
	w.src = stale
	if err := w.Sync(context.Background()); err != nil {
		t.Fatal(err)
	}
	if _, ok := statusOfID(w, "a"); ok {
		t.Error("a stale list resurrected a destroyed replica")
	}
}

type staleList struct {
	*fakeSource
	hook func()
}

func (s *staleList) List(ctx context.Context) ([]docker.Replica, error) {
	out, err := s.fakeSource.List(ctx)
	s.hook()
	return out, err
}

func TestRestartResetsHealth(t *testing.T) {
	w := New(newFakeSource(), quiet())
	rep := running("a")

	w.mu.Lock()
	w.apply(rep, 0)
	for range unhealthyAfter {
		w.entries["a"].health.observe(false)
	}
	w.entries["a"].status.Healthy = w.entries["a"].health.healthy
	w.mu.Unlock()
	if s, _ := statusOfID(w, "a"); s.Healthy {
		t.Fatal("setup: replica should be unhealthy")
	}

	w.mu.Lock()
	w.apply(rep, 0) // the same container seen again: state is kept
	w.mu.Unlock()
	if s, _ := statusOfID(w, "a"); s.Healthy {
		t.Error("seeing the same run again must not reset health")
	}

	rep.StartedAt = rep.StartedAt.Add(time.Minute) // started again
	w.mu.Lock()
	w.apply(rep, 0)
	w.mu.Unlock()
	if s, _ := statusOfID(w, "a"); !s.Healthy {
		t.Error("a restart must begin healthy")
	}
}

func TestProbeMarksUnhealthyThenRecovers(t *testing.T) {
	src := newFakeSource(running("a"))
	var ok atomic.Bool
	cfg := quiet()
	cfg.ProbeInterval = 2 * time.Millisecond
	cfg.Probe = func(context.Context, int, string) bool { return ok.Load() }
	w := New(src, cfg)
	if err := w.Sync(context.Background()); err != nil {
		t.Fatal(err)
	}
	startWatcher(t, w)

	waitFor(t, "unhealthy", func() bool { s, _ := statusOfID(w, "a"); return !s.Healthy })
	ok.Store(true)
	waitFor(t, "healthy again", func() bool { s, _ := statusOfID(w, "a"); return s.Healthy })
}

func TestProbeUsesPortAndPath(t *testing.T) {
	rep := running("a")
	rep.HostPort, rep.HealthPath = 20123, "/healthz"
	src := newFakeSource(rep)

	type call struct {
		port int
		path string
	}
	calls := make(chan call, 1)
	cfg := quiet()
	cfg.ProbeInterval = 2 * time.Millisecond
	cfg.Probe = func(_ context.Context, port int, path string) bool {
		select {
		case calls <- call{port, path}:
		default:
		}
		return true
	}
	w := New(src, cfg)
	if err := w.Sync(context.Background()); err != nil {
		t.Fatal(err)
	}
	startWatcher(t, w)

	select {
	case c := <-calls:
		if c != (call{20123, "/healthz"}) {
			t.Errorf("probe call = %+v", c)
		}
	case <-time.After(testWait):
		t.Fatal("no probe")
	}
}

func TestExitedReplicaIsNotProbed(t *testing.T) {
	src := newFakeSource(died("a", 1))
	var n atomic.Int32
	cfg := quiet()
	cfg.ProbeInterval = 2 * time.Millisecond
	cfg.Probe = func(context.Context, int, string) bool { n.Add(1); return false }
	w := New(src, cfg)
	if err := w.Sync(context.Background()); err != nil {
		t.Fatal(err)
	}
	startWatcher(t, w)

	time.Sleep(30 * time.Millisecond)
	if n.Load() != 0 {
		t.Errorf("an exited replica was probed %d times", n.Load())
	}
}

func TestEventStreamReconnects(t *testing.T) {
	src := newFakeSource(running("a"))
	src.failSubscribe.Store(2)
	w := New(src, quiet())
	if err := w.Sync(context.Background()); err != nil {
		t.Fatal(err)
	}
	startWatcher(t, w)

	waitFor(t, "third subscription", func() bool { return src.subscribes.Load() >= 3 })
	// the stream that finally works delivers events
	src.set(died("a", 3))
	src.emit(t, "a")
	waitFor(t, "event after reconnect", func() bool {
		s, _ := statusOfID(w, "a")
		return s.ExitCode == 3
	})
	// reconnecting triggers a full list on top of the initial one
	waitFor(t, "resync after reconnect", func() bool { return src.listCalls.Load() >= 2 })
}

func TestRunReturnsAfterCancel(t *testing.T) {
	src := newFakeSource(running("a"))
	cfg := quiet()
	cfg.Resync, cfg.ProbeInterval = time.Millisecond, time.Millisecond
	w := New(src, cfg)
	stop := startWatcher(t, w)
	time.Sleep(20 * time.Millisecond)
	stop() // fails the test if Run hangs
}

func TestRunSyncsWhenNotSyncedYet(t *testing.T) {
	src := newFakeSource(running("a"))
	w := New(src, quiet())
	startWatcher(t, w)
	waitFor(t, "first sync", w.Synced)
	if _, ok := statusOfID(w, "a"); !ok {
		t.Error("replica missing after the first sync")
	}
}
