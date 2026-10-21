// Package watch tracks the state of the replicas on this node: whether each
// is running, how it died, and whether the app inside still answers. Docker
// events are only a trigger to re-read a container; a periodic full list
// catches whatever an event missed.
package watch

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"slices"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/thelol3882/bult/agent/internal/docker"
)

const (
	DefaultResync        = 30 * time.Second
	DefaultProbeInterval = 10 * time.Second
	DefaultProbeTimeout  = 2 * time.Second

	reconnectMin = time.Second
	reconnectMax = 30 * time.Second

	probeConcurrency = 8
	inspectTimeout   = 5 * time.Second
)

// State is what the control plane is told about a replica.
type State string

const (
	StateRunning State = "running"
	StateExited  State = "exited"
	StateOOM     State = "oom"
)

// Status is one replica as seen by the watcher.
type Status struct {
	ReplicaID  string
	State      State
	ExitCode   int
	OOMKilled  bool
	Healthy    bool // always false unless running
	FinishedAt time.Time
}

// Source is what the watcher needs from Docker.
type Source interface {
	List(ctx context.Context) ([]docker.Replica, error)
	Inspect(ctx context.Context, replicaID string) (docker.Replica, error)
	// ReplicaEvents: see docker.Client.ReplicaEvents.
	ReplicaEvents(ctx context.Context) (<-chan string, <-chan error)
}

// Config tunes a Watcher; zero values mean the defaults.
type Config struct {
	Resync        time.Duration
	ProbeInterval time.Duration
	ProbeTimeout  time.Duration
	Probe         ProbeFunc
	// Reconnect is the first wait before re-subscribing to events; it doubles
	// up to 30 s on repeated failures.
	Reconnect time.Duration
}

type entry struct {
	status     Status
	hostPort   int
	healthPath string
	startedAt  time.Time
	health     health
	seq        uint64 // last event-driven update; see resync
}

// Watcher keeps the state of every bult replica on the node.
type Watcher struct {
	src Source
	cfg Config

	mu      sync.Mutex
	entries map[string]*entry
	gone    map[string]uint64 // replicas dropped by an event, with that event's seq
	seq     uint64            // bumped by every event-driven update, under mu
	synced  atomic.Bool

	kick chan struct{} // asks the resync loop for an extra resync
}

// New returns a watcher that has not read anything yet; call Sync, then Run.
func New(src Source, cfg Config) *Watcher {
	if cfg.Resync <= 0 {
		cfg.Resync = DefaultResync
	}
	if cfg.ProbeInterval <= 0 {
		cfg.ProbeInterval = DefaultProbeInterval
	}
	if cfg.ProbeTimeout <= 0 {
		cfg.ProbeTimeout = DefaultProbeTimeout
	}
	if cfg.Probe == nil {
		cfg.Probe = Probe
	}
	if cfg.Reconnect <= 0 {
		cfg.Reconnect = reconnectMin
	}
	return &Watcher{
		src:     src,
		cfg:     cfg,
		entries: make(map[string]*entry),
		gone:    make(map[string]uint64),
		kick:    make(chan struct{}, 1),
	}
}

// Synced reports whether a full list has been read at least once, i.e.
// whether Snapshot can be taken as the complete picture of the node.
func (w *Watcher) Synced() bool { return w.synced.Load() }

// Snapshot returns a copy of every known replica (exited ones too), ordered
// by replica id.
func (w *Watcher) Snapshot() []Status {
	w.mu.Lock()
	out := make([]Status, 0, len(w.entries))
	for _, e := range w.entries {
		out = append(out, e.status)
	}
	w.mu.Unlock()
	slices.SortFunc(out, func(a, b Status) int { return strings.Compare(a.ReplicaID, b.ReplicaID) })
	return out
}

// Sync lists every replica and merges the result. Call it once before Run so
// the first heartbeat already has a picture; Run repeats it periodically.
func (w *Watcher) Sync(ctx context.Context) error {
	// A list that started before a later event may carry an older view of that
	// container, so changes made by events after this point win over it.
	w.mu.Lock()
	begin := w.seq
	w.mu.Unlock()

	reps, err := w.src.List(ctx)
	if err != nil {
		return err
	}

	w.mu.Lock()
	defer w.mu.Unlock()

	seen := make(map[string]struct{}, len(reps))
	for _, rep := range reps {
		seen[rep.ReplicaID] = struct{}{}
		if w.gone[rep.ReplicaID] > begin {
			continue
		}
		if e, ok := w.entries[rep.ReplicaID]; ok && e.seq > begin {
			continue
		}
		w.apply(rep, 0)
	}
	for id, e := range w.entries {
		if _, ok := seen[id]; !ok && e.seq <= begin {
			delete(w.entries, id)
		}
	}
	for id, s := range w.gone {
		if s <= begin {
			delete(w.gone, id)
		}
	}
	w.synced.Store(true)
	return nil
}

// apply merges what Docker says about one replica. mu must be held. seq is
// the event sequence number, 0 for a resync.
func (w *Watcher) apply(rep docker.Replica, seq uint64) {
	prev := w.entries[rep.ReplicaID]
	e := &entry{
		hostPort:   rep.HostPort,
		healthPath: rep.HealthPath,
		startedAt:  rep.StartedAt,
		status:     statusOf(rep),
	}
	switch {
	case e.status.State != StateRunning:
		// not running: health stays the zero value, reported as unhealthy
	case prev != nil && prev.status.State == StateRunning && prev.startedAt.Equal(rep.StartedAt):
		e.health = prev.health
	default:
		// A (re)start begins healthy with a clean failure count.
		e.health = newHealth()
	}
	e.status.Healthy = e.status.State == StateRunning && e.health.healthy

	if seq != 0 {
		e.seq = seq
	} else if prev != nil {
		e.seq = prev.seq
	}
	w.entries[rep.ReplicaID] = e
}

// statusOf maps Docker's view to a reported state. Exited and dead containers
// are "oom" when the kernel killed them for memory. Anything else that is not
// running (created and never started, paused, restarting, removing) is
// reported as exited, because it serves no traffic.
func statusOf(rep docker.Replica) Status {
	s := Status{ReplicaID: rep.ReplicaID, ExitCode: rep.ExitCode, OOMKilled: rep.OOMKilled, FinishedAt: rep.FinishedAt}
	switch {
	case rep.Status == "running" || rep.State == docker.StateRunning:
		s.State = StateRunning
		s.ExitCode = 0
		s.FinishedAt = time.Time{}
	case rep.OOMKilled:
		s.State = StateOOM
	default:
		s.State = StateExited
	}
	return s
}

// refresh re-reads one replica after an event and merges it.
func (w *Watcher) refresh(ctx context.Context, replicaID string) {
	ictx, cancel := context.WithTimeout(ctx, inspectTimeout)
	defer cancel()
	rep, err := w.src.Inspect(ictx, replicaID)

	w.mu.Lock()
	defer w.mu.Unlock()
	switch {
	case errors.Is(err, docker.ErrNotFound):
		w.seq++
		delete(w.entries, replicaID)
		w.gone[replicaID] = w.seq
	case err != nil:
		if ctx.Err() == nil {
			slog.Warn("watch: inspect replica", "replica", replicaID, "err", err)
		}
	default:
		w.seq++
		delete(w.gone, replicaID)
		w.apply(rep, w.seq)
	}
}

// Run keeps the state current until ctx is cancelled and returns once all its
// goroutines have stopped.
func (w *Watcher) Run(ctx context.Context) {
	var wg sync.WaitGroup
	wg.Go(func() { w.watchEvents(ctx) })
	wg.Go(func() { w.resyncLoop(ctx) })
	wg.Go(func() { w.probeLoop(ctx) })
	wg.Wait()
}

func (w *Watcher) watchEvents(ctx context.Context) {
	delay := w.cfg.Reconnect
	outage := false
	for ctx.Err() == nil {
		err := w.consume(ctx, func() {
			if outage {
				slog.Info("watch: docker event stream restored")
				outage = false
			}
			delay = w.cfg.Reconnect
		})
		if ctx.Err() != nil {
			return
		}
		if !outage {
			slog.Warn("watch: docker event stream broke, reconnecting", "err", err)
			outage = true
		}

		t := time.NewTimer(delay)
		select {
		case <-ctx.Done():
			t.Stop()
			return
		case <-t.C:
		}
		delay = min(delay*2, reconnectMax)

		// Events were missed while disconnected.
		select {
		case w.kick <- struct{}{}:
		default:
		}
	}
}

// consume handles events until the stream ends; alive is called per event.
func (w *Watcher) consume(ctx context.Context, alive func()) error {
	sctx, cancel := context.WithCancel(ctx)
	defer cancel()
	ids, errs := w.src.ReplicaEvents(sctx)
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case id, ok := <-ids:
			if !ok {
				select {
				case err := <-errs:
					return err
				default:
					return io.EOF
				}
			}
			alive()
			w.refresh(ctx, id)
		}
	}
}

func (w *Watcher) resyncLoop(ctx context.Context) {
	t := time.NewTicker(w.cfg.Resync)
	defer t.Stop()

	failing := false
	run := func() {
		err := w.Sync(ctx)
		switch {
		case ctx.Err() != nil:
		case err != nil && !failing:
			slog.Warn("watch: resync failed", "err", err)
			failing = true
		case err == nil && failing:
			slog.Info("watch: resync restored")
			failing = false
		}
	}

	if !w.Synced() {
		run()
	}
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
		case <-w.kick:
		}
		run()
	}
}

type probeTarget struct {
	id        string
	hostPort  int
	path      string
	startedAt time.Time
}

func (w *Watcher) probeLoop(ctx context.Context) {
	t := time.NewTicker(w.cfg.ProbeInterval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
		}
		w.probeRound(ctx)
	}
}

// probeRound probes every running replica, a few at a time. Each probe has its
// own timeout, so the round is bounded by ceil(n/concurrency) timeouts.
func (w *Watcher) probeRound(ctx context.Context) {
	w.mu.Lock()
	var targets []probeTarget
	for id, e := range w.entries {
		if e.status.State == StateRunning {
			targets = append(targets, probeTarget{id, e.hostPort, e.healthPath, e.startedAt})
		}
	}
	w.mu.Unlock()

	var wg sync.WaitGroup
	sem := make(chan struct{}, probeConcurrency)
	for _, tg := range targets {
		select {
		case sem <- struct{}{}:
		case <-ctx.Done():
			wg.Wait()
			return
		}
		wg.Go(func() {
			defer func() { <-sem }()
			pctx, cancel := context.WithTimeout(ctx, w.cfg.ProbeTimeout)
			ok := w.cfg.Probe(pctx, tg.hostPort, tg.path)
			cancel()
			if ctx.Err() != nil {
				return
			}
			w.recordProbe(tg, ok)
		})
	}
	wg.Wait()
}

// recordProbe applies a result unless the replica restarted or stopped while
// the probe was in flight.
func (w *Watcher) recordProbe(tg probeTarget, ok bool) {
	w.mu.Lock()
	defer w.mu.Unlock()
	e := w.entries[tg.id]
	if e == nil || e.status.State != StateRunning || !e.startedAt.Equal(tg.startedAt) {
		return
	}
	e.health.observe(ok)
	e.status.Healthy = e.health.healthy
}
