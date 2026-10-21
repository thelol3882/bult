// Package heartbeat tells the control plane that this node is alive: it
// registers the node on the first beat and refreshes it every interval.
package heartbeat

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"slices"
	"strings"
	"time"

	"github.com/thelol3882/bult/agent/internal/metrics"
	"github.com/thelol3882/bult/agent/internal/watch"
)

const (
	// DefaultInterval is how often a beat is sent.
	DefaultInterval = 5 * time.Second
	// DefaultTimeout bounds one request, so a hung control plane cannot stall the loop.
	DefaultTimeout = 3 * time.Second

	// A failing control plane is reported on the first failure and then once per
	// this many consecutive failures, so a long outage does not flood the journal.
	logEveryFailures = 12

	endpoint = "/internal/nodes/heartbeat"
)

// Capacity is what the node offers to the scheduler.
type Capacity struct {
	CPUs        int   `json:"cpus"`
	MemoryBytes int64 `json:"memory_bytes"`
}

// Sampler reads the usage of the replicas running on this node. Collect never
// fails: what could not be read is left out.
type Sampler interface {
	Collect(ctx context.Context) []metrics.Replica
}

// ReplicaWatcher reports the state of every replica on the node, exited ones
// included. Synced is false until the first full list was read; until then
// the snapshot must not be taken for the complete picture.
type ReplicaWatcher interface {
	Snapshot() []watch.Status
	Synced() bool
}

// Config describes the node and where to report it.
type Config struct {
	URL      string // control plane base URL, e.g. http://192.168.252.1:8000
	Token    string // node token; sent as a bearer token, never logged
	Name     string
	Address  string // gRPC address the control plane should dial
	Role     string
	Version  string
	Capacity Capacity
	Interval time.Duration  // zero means DefaultInterval
	Sampler  Sampler        // nil: no replica metrics (builder-only nodes)
	Watcher  ReplicaWatcher // nil: no replica states
}

type payload struct {
	Name     string   `json:"name"`
	Address  string   `json:"address"`
	Role     string   `json:"role"`
	Version  string   `json:"version"`
	Capacity Capacity `json:"capacity"`
	// Replicas is omitted when empty so that an older control plane, and a
	// builder, see the same body as before.
	Replicas []replicaEntry `json:"replicas,omitempty"`
	// ReportsReplicas tells the control plane that Replicas is the complete
	// list, so a replica missing from it is gone.
	ReportsReplicas bool `json:"reports_replicas,omitempty"`
}

// replicaEntry is one replica in the beat. State fields are set only when a
// watcher is configured; the usage fields only for a running replica that
// could be read this beat (absent means no reading, never zero).
type replicaEntry struct {
	ReplicaID  string `json:"replica_id"`
	State      string `json:"state,omitempty"`
	ExitCode   *int   `json:"exit_code,omitempty"`
	OOMKilled  *bool  `json:"oom_killed,omitempty"`
	Healthy    *bool  `json:"healthy,omitempty"`
	FinishedAt string `json:"finished_at,omitempty"` // RFC3339, UTC

	CPUCores      *float64 `json:"cpu_cores,omitempty"`
	CPULimitPct   *float64 `json:"cpu_limit_pct,omitempty"`
	MemBytes      *int64   `json:"mem_bytes,omitempty"`
	MemLimitBytes *int64   `json:"mem_limit_bytes,omitempty"`
}

func withUsage(e replicaEntry, m metrics.Replica) replicaEntry {
	e.CPUCores = &m.CPUCores
	e.CPULimitPct = &m.CPULimitPct
	e.MemBytes = &m.MemBytes
	e.MemLimitBytes = &m.MemLimitBytes
	return e
}

// mergeReplicas combines replica states and usage readings by replica id,
// ordered by id. Without states the usage readings go out as they are. With
// states, a reading is attached only to a running replica, and a reading for
// a replica the watcher does not know yet is left for the next beat.
func mergeReplicas(states []watch.Status, usage []metrics.Replica) []replicaEntry {
	if states == nil {
		out := make([]replicaEntry, 0, len(usage))
		for _, m := range usage {
			out = append(out, withUsage(replicaEntry{ReplicaID: m.ReplicaID}, m))
		}
		return out
	}

	byID := make(map[string]metrics.Replica, len(usage))
	for _, m := range usage {
		byID[m.ReplicaID] = m
	}
	out := make([]replicaEntry, 0, len(states))
	for _, s := range states {
		e := replicaEntry{
			ReplicaID: s.ReplicaID,
			State:     string(s.State),
			OOMKilled: &s.OOMKilled,
			Healthy:   &s.Healthy,
		}
		if s.State == watch.StateRunning {
			if m, ok := byID[s.ReplicaID]; ok {
				e = withUsage(e, m)
			}
		} else {
			e.ExitCode = &s.ExitCode
			if !s.FinishedAt.IsZero() {
				e.FinishedAt = s.FinishedAt.UTC().Format(time.RFC3339)
			}
		}
		out = append(out, e)
	}
	slices.SortFunc(out, func(a, b replicaEntry) int { return strings.Compare(a.ReplicaID, b.ReplicaID) })
	return out
}

// Run sends a beat immediately and then one per interval until ctx is
// cancelled. client carries its own timeout; a nil client gets a default one.
func Run(ctx context.Context, cfg Config, client *http.Client) {
	if client == nil {
		client = &http.Client{Timeout: DefaultTimeout}
	}
	interval := cfg.Interval
	if interval <= 0 {
		interval = DefaultInterval
	}

	url := strings.TrimRight(cfg.URL, "/") + endpoint

	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	failures := 0
	for {
		err := send(ctx, client, url, cfg)
		switch {
		case ctx.Err() != nil:
			return
		case err != nil:
			failures++
			if failures%logEveryFailures == 1 {
				slog.Warn("heartbeat failed", "err", err, "consecutive_failures", failures)
			}
		default:
			if failures > 0 {
				slog.Info("heartbeat restored", "after_failures", failures)
			}
			failures = 0
		}

		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

// send builds the current payload, with fresh replica metrics, and beats.
// Metrics are collected first and are bounded by the sampler's own timeout, so
// they can delay a beat but not stop it.
func send(ctx context.Context, client *http.Client, url string, cfg Config) error {
	p := payload{
		Name:     cfg.Name,
		Address:  cfg.Address,
		Role:     cfg.Role,
		Version:  cfg.Version,
		Capacity: cfg.Capacity,
	}
	var usage []metrics.Replica
	if cfg.Sampler != nil {
		usage = cfg.Sampler.Collect(ctx)
	}
	if cfg.Watcher != nil && cfg.Watcher.Synced() {
		// Snapshot after the (slow) usage collection: it is the fresher of the two.
		states := cfg.Watcher.Snapshot()
		if states == nil {
			states = []watch.Status{}
		}
		p.Replicas = mergeReplicas(states, usage)
		p.ReportsReplicas = true
	} else if len(usage) > 0 {
		p.Replicas = mergeReplicas(nil, usage)
	}
	body, err := json.Marshal(p)
	if err != nil {
		return fmt.Errorf("encode payload: %w", err)
	}
	return beat(ctx, client, url, cfg.Token, body)
}

// beat sends one heartbeat. The token only goes into the header, so it cannot
// leak through an error message.
func beat(ctx context.Context, client *http.Client, url, token string, body []byte) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)

	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("send: %w", err)
	}
	defer resp.Body.Close()
	// Drain a little so the connection can be reused; the body itself is not needed.
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("control plane answered %s", resp.Status)
	}
	return nil
}
