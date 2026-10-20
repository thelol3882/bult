// Package metrics turns Docker's raw per-container counters into the CPU and
// memory numbers the node reports to the control plane in its heartbeat.
package metrics

import (
	"context"
	"errors"
	"log/slog"
	"math"
	"slices"
	"strings"
	"sync"
	"time"

	"github.com/thelol3882/bult/agent/internal/docker"
)

const (
	// DefaultTimeout bounds one collection. It must stay below the heartbeat
	// interval: a slow Docker daemon delays the beat, never the node's liveness.
	DefaultTimeout = 3 * time.Second

	// Each stats reading takes about a second (the daemon samples twice), so
	// replicas are read in parallel, a few at a time.
	defaultConcurrency = 8
)

// Replica is the usage of one replica, as sent in the heartbeat.
type Replica struct {
	ReplicaID string `json:"replica_id"`
	// CPUCores is the CPU time used, in cores (1.0 = one core fully busy).
	CPUCores float64 `json:"cpu_cores"`
	// CPULimitPct is CPUCores as a percentage of the replica's CPU limit;
	// 100 means it sits at its ceiling and is throttled.
	CPULimitPct float64 `json:"cpu_limit_pct"`
	// MemBytes is memory in use without the reclaimable file cache.
	MemBytes      int64 `json:"mem_bytes"`
	MemLimitBytes int64 `json:"mem_limit_bytes"`
}

// Source is what the collector needs from Docker.
type Source interface {
	RunningReplicaIDs(ctx context.Context) ([]string, error)
	Sample(ctx context.Context, replicaID string) (docker.Sample, error)
}

// Collector reads the usage of every running replica on the node.
type Collector struct {
	src         Source
	timeout     time.Duration
	concurrency int
}

// NewCollector returns a collector that gives up after timeout (zero means DefaultTimeout).
func NewCollector(src Source, timeout time.Duration) *Collector {
	if timeout <= 0 {
		timeout = DefaultTimeout
	}
	return &Collector{src: src, timeout: timeout, concurrency: defaultConcurrency}
}

// Collect returns one entry per running replica that could be read in time,
// ordered by replica id. A replica that fails is skipped, and an error
// listing the replicas yields nothing; none of this is fatal for the caller.
func (c *Collector) Collect(ctx context.Context) []Replica {
	ctx, cancel := context.WithTimeout(ctx, c.timeout)
	defer cancel()

	ids, err := c.src.RunningReplicaIDs(ctx)
	if err != nil {
		if ctx.Err() == nil {
			slog.Warn("metrics: list replicas", "err", err)
		}
		return nil
	}

	var (
		wg  sync.WaitGroup
		sem = make(chan struct{}, c.concurrency)
		mu  sync.Mutex
		out = make([]Replica, 0, len(ids))
	)
	for _, id := range ids {
		sem <- struct{}{}
		wg.Go(func() {
			defer func() { <-sem }()
			sample, err := c.src.Sample(ctx, id)
			if err != nil {
				// A replica removed between the list and the reading is normal.
				if !errors.Is(err, docker.ErrNotFound) && ctx.Err() == nil {
					slog.Warn("metrics: sample replica", "replica", id, "err", err)
				}
				return
			}
			r, ok := FromSample(sample)
			if !ok {
				return
			}
			mu.Lock()
			out = append(out, r)
			mu.Unlock()
		})
	}
	wg.Wait()

	slices.SortFunc(out, func(a, b Replica) int { return strings.Compare(a.ReplicaID, b.ReplicaID) })
	return out
}

// FromSample computes a replica's usage. ok is false when the sample is not
// usable: the container is not running or the CPU deltas cannot be computed.
func FromSample(s docker.Sample) (Replica, bool) {
	if !s.Running {
		return Replica{}, false
	}
	cores, ok := cpuCores(s)
	if !ok {
		return Replica{}, false
	}

	limit := cpuLimitCores(s)
	var pct float64
	if limit > 0 {
		pct = cores / limit * 100
	}

	return Replica{
		ReplicaID:     s.ReplicaID,
		CPUCores:      round(cores, 3),
		CPULimitPct:   round(pct, 1),
		MemBytes:      int64(memoryUsage(s)),
		MemLimitBytes: int64(s.MemLimit),
	}, true
}

// cpuCores is (cpu_delta / system_delta) * online_cpus: the share of the
// host's CPU time the container used between the two readings, times the
// number of CPUs, i.e. cores busy. Two readings are needed because the
// counters are cumulative since the container started: one reading says how
// much CPU time was ever used, not how fast it is being used now.
func cpuCores(s docker.Sample) (float64, bool) {
	if s.PreSystemCPU == 0 || s.SystemCPU <= s.PreSystemCPU || s.CPUTotal < s.PreCPUTotal {
		return 0, false
	}
	online := onlineCPUs(s)
	if online == 0 {
		return 0, false
	}
	cpuDelta := float64(s.CPUTotal - s.PreCPUTotal)
	systemDelta := float64(s.SystemCPU - s.PreSystemCPU)
	return cpuDelta / systemDelta * float64(online), true
}

func onlineCPUs(s docker.Sample) int {
	if s.OnlineCPUs > 0 {
		return int(s.OnlineCPUs)
	}
	return s.PerCPUCount
}

// cpuLimitCores is the replica's CPU quota in cores; without a quota the
// ceiling is every CPU of the host.
func cpuLimitCores(s docker.Sample) float64 {
	if s.CPULimitNanos > 0 {
		return float64(s.CPULimitNanos) / 1e9
	}
	return float64(onlineCPUs(s))
}

// memoryUsage is usage minus the inactive file cache, which the kernel drops
// under pressure and so is not what the process "uses" (the same number
// `docker stats` shows). cgroup v2 names the counter inactive_file, v1
// total_inactive_file.
func memoryUsage(s docker.Sample) uint64 {
	cache, ok := s.MemStats["inactive_file"]
	if !ok {
		cache = s.MemStats["total_inactive_file"]
	}
	if cache >= s.MemUsage {
		return s.MemUsage
	}
	return s.MemUsage - cache
}

func round(v float64, places int) float64 {
	p := math.Pow10(places)
	return math.Round(v*p) / p
}
