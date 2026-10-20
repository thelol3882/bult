package heartbeat

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/thelol3882/bult/agent/internal/metrics"
)

func testConfig(url string) Config {
	return Config{
		URL:      url,
		Token:    "secret-token",
		Name:     "node-1",
		Address:  "10.0.0.5:50051",
		Role:     "runner",
		Version:  "v1",
		Capacity: Capacity{CPUs: 2, MemoryBytes: 2 << 30},
		Interval: 10 * time.Millisecond,
	}
}

// start runs the loop and returns a stop function that cancels it and waits for it to return.
func start(t *testing.T, cfg Config) (stop func()) {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		defer close(done)
		Run(ctx, cfg, &http.Client{Timeout: time.Second})
	}()
	return func() {
		cancel()
		select {
		case <-done:
		case <-time.After(2 * time.Second):
			t.Fatal("Run did not return after the context was cancelled")
		}
	}
}

func waitFor(t *testing.T, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for !cond() {
		if time.Now().After(deadline) {
			t.Fatal("condition not met in time")
		}
		time.Sleep(5 * time.Millisecond)
	}
}

func TestBeatSendsPayloadAndToken(t *testing.T) {
	type got struct {
		method, path, auth, contentType string
		body                            payload
	}
	seen := make(chan got, 1)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var p payload
		if err := json.NewDecoder(r.Body).Decode(&p); err != nil {
			t.Errorf("decode body: %v", err)
		}
		select {
		case seen <- got{r.Method, r.URL.Path, r.Header.Get("Authorization"), r.Header.Get("Content-Type"), p}:
		default:
		}
		w.WriteHeader(http.StatusNoContent)
	}))
	defer srv.Close()

	stop := start(t, testConfig(srv.URL+"/")) // trailing slash must not double up
	defer stop()

	select {
	case g := <-seen:
		if g.method != http.MethodPost || g.path != "/internal/nodes/heartbeat" {
			t.Errorf("request = %s %s", g.method, g.path)
		}
		if g.auth != "Bearer secret-token" {
			t.Errorf("Authorization = %q", g.auth)
		}
		if g.contentType != "application/json" {
			t.Errorf("Content-Type = %q", g.contentType)
		}
		want := payload{
			Name: "node-1", Address: "10.0.0.5:50051", Role: "runner", Version: "v1",
			Capacity: Capacity{CPUs: 2, MemoryBytes: 2 << 30},
		}
		if !reflect.DeepEqual(g.body, want) {
			t.Errorf("body = %+v, want %+v", g.body, want)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("no heartbeat received")
	}
}

func TestKeepsBeating(t *testing.T) {
	var n atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n.Add(1)
	}))
	defer srv.Close()

	stop := start(t, testConfig(srv.URL))
	defer stop()

	waitFor(t, func() bool { return n.Load() >= 3 })
}

func TestStopsOnCancelAndSendsNothingMore(t *testing.T) {
	var n atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n.Add(1)
	}))
	defer srv.Close()

	stop := start(t, testConfig(srv.URL))
	waitFor(t, func() bool { return n.Load() >= 1 })
	stop()

	after := n.Load()
	time.Sleep(60 * time.Millisecond) // several intervals
	if n.Load() != after {
		t.Errorf("heartbeats continued after cancel: %d -> %d", after, n.Load())
	}
}

func TestCancelAbortsHungRequest(t *testing.T) {
	release := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		select {
		case <-release:
		case <-r.Context().Done():
		}
	}))
	defer srv.Close()
	defer close(release)

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		defer close(done)
		Run(ctx, testConfig(srv.URL), &http.Client{Timeout: 30 * time.Second})
	}()
	time.Sleep(30 * time.Millisecond) // the first request is now in flight
	cancel()

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("Run stayed blocked on an in-flight request after cancel")
	}
}

func TestSurvivesServerErrors(t *testing.T) {
	var n atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if n.Add(1) <= 3 {
			http.Error(w, "boom", http.StatusInternalServerError)
			return
		}
		w.WriteHeader(http.StatusNoContent)
	}))
	defer srv.Close()

	stop := start(t, testConfig(srv.URL))
	defer stop()

	// Beats continue past the failures (the 4th and later succeed).
	waitFor(t, func() bool { return n.Load() >= 6 })
}

func TestSurvivesUnreachableServer(t *testing.T) {
	srv := httptest.NewServer(http.NotFoundHandler())
	url := srv.URL
	srv.Close() // nothing listens any more

	stop := start(t, testConfig(url))
	time.Sleep(60 * time.Millisecond)
	stop() // must still stop cleanly
}

func TestBeatReportsNon2xxWithoutLeakingTheToken(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "nope", http.StatusUnauthorized)
	}))
	defer srv.Close()

	err := beat(context.Background(), srv.Client(), srv.URL, "very-secret-token", []byte("{}"))
	if err == nil {
		t.Fatal("expected an error for a 401 answer")
	}
	if strings.Contains(err.Error(), "very-secret-token") {
		t.Errorf("error leaks the token: %v", err)
	}
}

func TestMemTotal(t *testing.T) {
	path := filepath.Join(t.TempDir(), "meminfo")
	content := "MemFree:         100 kB\nMemTotal:       2035636 kB\nBuffers: 1 kB\n"
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	got, err := memTotal(path)
	if err != nil {
		t.Fatal(err)
	}
	if want := int64(2035636) * 1024; got != want {
		t.Errorf("memTotal = %d, want %d", got, want)
	}

	bad := filepath.Join(t.TempDir(), "bad")
	if err := os.WriteFile(bad, []byte("MemTotal: lots\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := memTotal(bad); err == nil {
		t.Error("expected an error for a malformed line")
	}
}

type fakeSampler struct{ out []metrics.Replica }

func (f fakeSampler) Collect(context.Context) []metrics.Replica { return f.out }

// rawBodies serves heartbeats and passes each raw body on.
func rawBodies(t *testing.T) (*httptest.Server, <-chan map[string]json.RawMessage) {
	t.Helper()
	ch := make(chan map[string]json.RawMessage, 1)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var m map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&m); err != nil {
			t.Errorf("decode body: %v", err)
		}
		select {
		case ch <- m:
		default:
		}
	}))
	t.Cleanup(srv.Close)
	return srv, ch
}

func TestBeatCarriesReplicaMetrics(t *testing.T) {
	srv, bodies := rawBodies(t)
	cfg := testConfig(srv.URL)
	want := []metrics.Replica{{ReplicaID: "d-r0", CPUCores: 0.25, CPULimitPct: 50, MemBytes: 10, MemLimitBytes: 20}}
	cfg.Sampler = fakeSampler{out: want}

	stop := start(t, cfg)
	defer stop()

	select {
	case m := <-bodies:
		var got []metrics.Replica
		if err := json.Unmarshal(m["replicas"], &got); err != nil {
			t.Fatalf("replicas: %v", err)
		}
		if !reflect.DeepEqual(got, want) {
			t.Errorf("replicas = %+v, want %+v", got, want)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("no heartbeat received")
	}
}

func TestBeatWithoutSamplerHasNoReplicasField(t *testing.T) {
	srv, bodies := rawBodies(t)
	stop := start(t, testConfig(srv.URL))
	defer stop()

	select {
	case m := <-bodies:
		if _, ok := m["replicas"]; ok {
			t.Error("replicas present without a sampler")
		}
	case <-time.After(2 * time.Second):
		t.Fatal("no heartbeat received")
	}
}

func TestSamplerNothingToReportOmitsField(t *testing.T) {
	srv, bodies := rawBodies(t)
	cfg := testConfig(srv.URL)
	cfg.Sampler = fakeSampler{}
	stop := start(t, cfg)
	defer stop()

	select {
	case m := <-bodies:
		if _, ok := m["replicas"]; ok {
			t.Error("empty replicas must be omitted")
		}
	case <-time.After(2 * time.Second):
		t.Fatal("no heartbeat received")
	}
}
