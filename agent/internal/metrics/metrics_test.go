package metrics

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/thelol3882/bult/agent/internal/docker"
)

func near(a, b float64) bool { return math.Abs(a-b) < 1e-9 }

func TestCPUCores(t *testing.T) {
	base := docker.Sample{
		Running:      true,
		CPUTotal:     1_500_000_000,
		PreCPUTotal:  1_000_000_000,
		SystemCPU:    20_000_000_000,
		PreSystemCPU: 18_000_000_000,
		OnlineCPUs:   4,
	}
	tests := []struct {
		name   string
		mutate func(*docker.Sample)
		want   float64
		wantOK bool
	}{
		{"typical: 0.5s of 2s on 4 cpus", func(*docker.Sample) {}, 1.0, true},
		{"idle container", func(s *docker.Sample) { s.CPUTotal = s.PreCPUTotal }, 0, true},
		{"first sample, no previous reading", func(s *docker.Sample) { s.PreSystemCPU, s.PreCPUTotal = 0, 0 }, 0, false},
		{"zero system delta", func(s *docker.Sample) { s.SystemCPU = s.PreSystemCPU }, 0, false},
		{"counter went backwards", func(s *docker.Sample) { s.CPUTotal = s.PreCPUTotal - 1 }, 0, false},
		{"online cpus missing, per-cpu list used", func(s *docker.Sample) { s.OnlineCPUs, s.PerCPUCount = 0, 2 }, 0.5, true},
		{"no cpu count at all", func(s *docker.Sample) { s.OnlineCPUs, s.PerCPUCount = 0, 0 }, 0, false},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			s := base
			tc.mutate(&s)
			got, ok := cpuCores(s)
			if ok != tc.wantOK || (ok && !near(got, tc.want)) {
				t.Errorf("cpuCores = %v, %v; want %v, %v", got, ok, tc.want, tc.wantOK)
			}
		})
	}
}

func TestFromSampleCPULimit(t *testing.T) {
	s := docker.Sample{
		ReplicaID: "d-r0", Running: true,
		CPUTotal: 1_500_000_000, PreCPUTotal: 1_000_000_000,
		SystemCPU: 20_000_000_000, PreSystemCPU: 18_000_000_000,
		OnlineCPUs: 4, CPULimitNanos: 500_000_000, // half a core
		MemUsage: 100, MemLimit: 1000,
	}
	r, ok := FromSample(s)
	if !ok {
		t.Fatal("not ok")
	}
	if r.CPUCores != 1.0 || r.CPULimitPct != 200 {
		t.Errorf("cores=%v pct=%v, want 1.0 and 200 (a half-core limit used at 1 core)", r.CPUCores, r.CPULimitPct)
	}

	s.CPULimitNanos = 0 // no limit: percent of all 4 cpus
	r, _ = FromSample(s)
	if r.CPULimitPct != 25 {
		t.Errorf("unlimited pct = %v, want 25", r.CPULimitPct)
	}
}

func TestFromSampleSkipsStopped(t *testing.T) {
	if _, ok := FromSample(docker.Sample{Running: false}); ok {
		t.Error("a stopped container must not produce a reading")
	}
}

func TestMemoryUsage(t *testing.T) {
	tests := []struct {
		name  string
		usage uint64
		stats map[string]uint64
		want  uint64
	}{
		{"cgroup v2", 1000, map[string]uint64{"inactive_file": 300, "anon": 500}, 700},
		{"cgroup v1", 1000, map[string]uint64{"total_inactive_file": 400}, 600},
		{"v2 key wins", 1000, map[string]uint64{"inactive_file": 100, "total_inactive_file": 900}, 900},
		{"no cache counters", 1000, nil, 1000},
		{"cache larger than usage", 1000, map[string]uint64{"inactive_file": 2000}, 1000},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got := memoryUsage(docker.Sample{MemUsage: tc.usage, MemStats: tc.stats})
			if got != tc.want {
				t.Errorf("memoryUsage = %d, want %d", got, tc.want)
			}
		})
	}
}

func TestReplicaJSON(t *testing.T) {
	b, err := json.Marshal(Replica{ReplicaID: "d-r0", CPUCores: 0.25, CPULimitPct: 50, MemBytes: 10, MemLimitBytes: 20})
	if err != nil {
		t.Fatal(err)
	}
	want := `{"replica_id":"d-r0","cpu_cores":0.25,"cpu_limit_pct":50,"mem_bytes":10,"mem_limit_bytes":20}`
	if string(b) != want {
		t.Errorf("json = %s, want %s", b, want)
	}
}

// fakeSource serves canned samples; a missing id fails with a plain error.
type fakeSource struct {
	listErr error
	ids     []string
	samples map[string]docker.Sample
	errs    map[string]error
	delay   time.Duration

	mu       sync.Mutex
	inFlight int
	maxSeen  int
	calls    atomic.Int32
}

func (f *fakeSource) RunningReplicaIDs(context.Context) ([]string, error) { return f.ids, f.listErr }

func (f *fakeSource) Sample(ctx context.Context, id string) (docker.Sample, error) {
	f.calls.Add(1)
	f.mu.Lock()
	f.inFlight++
	f.maxSeen = max(f.maxSeen, f.inFlight)
	f.mu.Unlock()
	defer func() {
		f.mu.Lock()
		f.inFlight--
		f.mu.Unlock()
	}()

	if f.delay > 0 {
		select {
		case <-time.After(f.delay):
		case <-ctx.Done():
			return docker.Sample{}, ctx.Err()
		}
	}
	if err := f.errs[id]; err != nil {
		return docker.Sample{}, err
	}
	return f.samples[id], nil
}

func goodSample(id string) docker.Sample {
	return docker.Sample{
		ReplicaID: id, Running: true,
		CPUTotal: 200, PreCPUTotal: 100, SystemCPU: 1000, PreSystemCPU: 900, OnlineCPUs: 1,
		MemUsage: 50, MemLimit: 100,
	}
}

func TestCollectSkipsFailingReplicas(t *testing.T) {
	src := &fakeSource{
		ids: []string{"b-r0", "a-r1", "gone-r0", "bad-r0", "stopped-r0", "first-r0"},
		samples: map[string]docker.Sample{
			"a-r1":       goodSample("a-r1"),
			"b-r0":       goodSample("b-r0"),
			"stopped-r0": {ReplicaID: "stopped-r0"},
			"first-r0":   {ReplicaID: "first-r0", Running: true, CPUTotal: 5, SystemCPU: 5, OnlineCPUs: 1},
		},
		errs: map[string]error{
			"gone-r0": docker.ErrNotFound,
			"bad-r0":  errors.New("boom"),
		},
	}
	got := NewCollector(src, time.Second).Collect(context.Background())
	if len(got) != 2 || got[0].ReplicaID != "a-r1" || got[1].ReplicaID != "b-r0" {
		t.Fatalf("got %+v, want a-r1 and b-r0 in id order", got)
	}
	if got[0].CPUCores != 1 || got[0].CPULimitPct != 100 {
		t.Errorf("a-r1 = %+v", got[0])
	}
}

func TestCollectListError(t *testing.T) {
	src := &fakeSource{listErr: docker.ErrDockerUnavailable}
	if got := NewCollector(src, time.Second).Collect(context.Background()); len(got) != 0 {
		t.Errorf("got %+v, want nothing", got)
	}
}

func TestCollectBoundedByTimeout(t *testing.T) {
	src := &fakeSource{
		ids:     []string{"a-r0", "b-r0"},
		samples: map[string]docker.Sample{"a-r0": goodSample("a-r0"), "b-r0": goodSample("b-r0")},
		delay:   time.Minute,
	}
	start := time.Now()
	got := NewCollector(src, 50*time.Millisecond).Collect(context.Background())
	if elapsed := time.Since(start); elapsed > 2*time.Second {
		t.Errorf("Collect took %v, the timeout did not bound it", elapsed)
	}
	if len(got) != 0 {
		t.Errorf("got %+v, want nothing from a stalled daemon", got)
	}
}

func TestCollectLimitsConcurrency(t *testing.T) {
	src := &fakeSource{samples: map[string]docker.Sample{}, delay: 20 * time.Millisecond}
	for i := range 20 {
		id := string(rune('a'+i)) + "-r0"
		src.ids = append(src.ids, id)
		src.samples[id] = goodSample(id)
	}
	c := NewCollector(src, 5*time.Second)
	c.concurrency = 3

	got := c.Collect(context.Background())
	if len(got) != 20 {
		t.Fatalf("got %d replicas, want 20", len(got))
	}
	if src.maxSeen > 3 {
		t.Errorf("%d samples in flight at once, limit is 3", src.maxSeen)
	}
	if src.maxSeen < 2 {
		t.Errorf("only %d in flight: replicas are not read concurrently", src.maxSeen)
	}
}
