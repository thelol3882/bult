package heartbeat

import (
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/thelol3882/bult/agent/internal/metrics"
	"github.com/thelol3882/bult/agent/internal/watch"
)

type fakeWatcher struct {
	states []watch.Status
	synced bool
}

func (f fakeWatcher) Snapshot() []watch.Status { return f.states }
func (f fakeWatcher) Synced() bool             { return f.synced }

func usage(id string) metrics.Replica {
	return metrics.Replica{ReplicaID: id, CPUCores: 0.25, CPULimitPct: 50, MemBytes: 10, MemLimitBytes: 20}
}

func TestMergeRunningWithUsageAndExited(t *testing.T) {
	finished := time.Date(2026, 10, 21, 12, 30, 5, 0, time.FixedZone("x", 3*3600))
	states := []watch.Status{
		{ReplicaID: "z-r0", State: watch.StateExited, ExitCode: 1, Healthy: false, FinishedAt: finished},
		{ReplicaID: "a-r0", State: watch.StateRunning, Healthy: true},
		{ReplicaID: "m-r0", State: watch.StateOOM, ExitCode: 137, OOMKilled: true, FinishedAt: finished},
	}
	// usage of the exited replica must be dropped, usage of an unknown one too
	got := mergeReplicas(states, []metrics.Replica{usage("a-r0"), usage("z-r0"), usage("unknown")})

	raw, err := json.Marshal(got)
	if err != nil {
		t.Fatal(err)
	}
	want := `[` +
		`{"replica_id":"a-r0","state":"running","oom_killed":false,"healthy":true,` +
		`"cpu_cores":0.25,"cpu_limit_pct":50,"mem_bytes":10,"mem_limit_bytes":20},` +
		`{"replica_id":"m-r0","state":"oom","exit_code":137,"oom_killed":true,"healthy":false,"finished_at":"2026-10-21T09:30:05Z"},` +
		`{"replica_id":"z-r0","state":"exited","exit_code":1,"oom_killed":false,"healthy":false,"finished_at":"2026-10-21T09:30:05Z"}` +
		`]`
	if string(raw) != want {
		t.Errorf("got  %s\nwant %s", raw, want)
	}
}

func TestMergeRunningWithoutReadingHasNoUsageFields(t *testing.T) {
	got := mergeReplicas([]watch.Status{{ReplicaID: "a", State: watch.StateRunning, Healthy: true}}, nil)
	raw, _ := json.Marshal(got)
	for _, f := range []string{"cpu_cores", "cpu_limit_pct", "mem_bytes", "mem_limit_bytes", "exit_code", "finished_at"} {
		if strings.Contains(string(raw), f) {
			t.Errorf("%s present without a reading: %s", f, raw)
		}
	}
}

func TestMergeZeroUsageIsKept(t *testing.T) {
	// a real reading of 0 is not the same as no reading
	got := mergeReplicas(
		[]watch.Status{{ReplicaID: "a", State: watch.StateRunning, Healthy: true}},
		[]metrics.Replica{{ReplicaID: "a"}},
	)
	raw, _ := json.Marshal(got)
	if !strings.Contains(string(raw), `"cpu_cores":0`) || !strings.Contains(string(raw), `"mem_bytes":0`) {
		t.Errorf("zero reading dropped: %s", raw)
	}
}

func TestMergeWithoutStatesKeepsOldShape(t *testing.T) {
	raw, _ := json.Marshal(mergeReplicas(nil, []metrics.Replica{usage("d-r0")}))
	want := `[{"replica_id":"d-r0","cpu_cores":0.25,"cpu_limit_pct":50,"mem_bytes":10,"mem_limit_bytes":20}]`
	if string(raw) != want {
		t.Errorf("got %s want %s", raw, want)
	}
}

func bodyOf(t *testing.T, cfg Config) map[string]json.RawMessage {
	t.Helper()
	srv, bodies := rawBodies(t)
	cfg.URL = srv.URL
	stop := start(t, cfg)
	defer stop()
	select {
	case m := <-bodies:
		return m
	case <-time.After(2 * time.Second):
		t.Fatal("no heartbeat received")
		return nil
	}
}

func TestBuilderBodyUnchanged(t *testing.T) {
	m := bodyOf(t, testConfig(""))
	for _, k := range []string{"replicas", "reports_replicas"} {
		if _, ok := m[k]; ok {
			t.Errorf("%s present for a builder", k)
		}
	}
}

func TestReportsReplicasOnlyWithSyncedWatcher(t *testing.T) {
	cfg := testConfig("")
	cfg.Watcher = fakeWatcher{synced: true}
	m := bodyOf(t, cfg)
	if string(m["reports_replicas"]) != "true" {
		t.Errorf("reports_replicas = %s, want true (an empty node still reports the full list)", m["reports_replicas"])
	}
	if _, ok := m["replicas"]; ok {
		t.Error("empty replicas must be omitted")
	}

	cfg.Watcher = fakeWatcher{synced: false, states: []watch.Status{{ReplicaID: "a", State: watch.StateRunning}}}
	m = bodyOf(t, cfg)
	if _, ok := m["reports_replicas"]; ok {
		t.Error("an unsynced watcher must not claim a complete list")
	}
	if _, ok := m["replicas"]; ok {
		t.Error("an unsynced watcher must not send states")
	}
}

func TestBeatCarriesStatesAndUsage(t *testing.T) {
	cfg := testConfig("")
	cfg.Sampler = fakeSampler{out: []metrics.Replica{usage("a")}}
	cfg.Watcher = fakeWatcher{synced: true, states: []watch.Status{
		{ReplicaID: "a", State: watch.StateRunning, Healthy: true},
		{ReplicaID: "b", State: watch.StateExited, ExitCode: 2},
	}}
	m := bodyOf(t, cfg)

	var got []map[string]any
	if err := json.Unmarshal(m["replicas"], &got); err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 || got[0]["replica_id"] != "a" || got[1]["replica_id"] != "b" {
		t.Fatalf("replicas = %v", got)
	}
	if got[0]["cpu_cores"] != 0.25 || got[0]["state"] != "running" {
		t.Errorf("running entry = %v", got[0])
	}
	if _, ok := got[1]["cpu_cores"]; ok {
		t.Errorf("exited entry has usage: %v", got[1])
	}
	if got[1]["exit_code"] != float64(2) {
		t.Errorf("exited entry = %v", got[1])
	}
}
