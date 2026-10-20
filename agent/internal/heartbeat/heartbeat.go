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
	"strings"
	"time"

	"github.com/thelol3882/bult/agent/internal/metrics"
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

// Config describes the node and where to report it.
type Config struct {
	URL      string // control plane base URL, e.g. http://192.168.252.1:8000
	Token    string // node token; sent as a bearer token, never logged
	Name     string
	Address  string // gRPC address the control plane should dial
	Role     string
	Version  string
	Capacity Capacity
	Interval time.Duration // zero means DefaultInterval
	Sampler  Sampler       // nil: no replica metrics (builder-only nodes)
}

type payload struct {
	Name     string   `json:"name"`
	Address  string   `json:"address"`
	Role     string   `json:"role"`
	Version  string   `json:"version"`
	Capacity Capacity `json:"capacity"`
	// Replicas is omitted when empty so that an older control plane, and a
	// builder, see the same body as before.
	Replicas []metrics.Replica `json:"replicas,omitempty"`
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
	if cfg.Sampler != nil {
		p.Replicas = cfg.Sampler.Collect(ctx)
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
