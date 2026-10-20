package docker

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/containerd/errdefs"
	"github.com/moby/moby/api/types/container"
	"github.com/moby/moby/client"
)

// Sample is one reading of a replica's resource usage, as raw counters.
// The metrics package turns it into rates and percentages.
type Sample struct {
	ReplicaID string
	Running   bool

	// CPULimitNanos is the CPU quota in billionths of a core; 0 means no limit.
	CPULimitNanos int64

	// Cumulative CPU time of the container and of the whole host, now and at
	// the previous reading (taken about a second earlier by the daemon).
	CPUTotal     uint64
	PreCPUTotal  uint64
	SystemCPU    uint64
	PreSystemCPU uint64 // 0 when the daemon sent no previous reading
	OnlineCPUs   uint32
	PerCPUCount  int // fallback for OnlineCPUs

	MemUsage uint64
	MemLimit uint64
	MemStats map[string]uint64
}

// RunningReplicaIDs lists the ids of the bult replicas whose containers are running.
func (c *Client) RunningReplicaIDs(ctx context.Context) ([]string, error) {
	filters := make(client.Filters).Add("label", labelManaged+"=true")

	res, err := c.api.ContainerList(ctx, client.ContainerListOptions{Filters: filters})
	if err != nil {
		return nil, dockerErr("list containers", err)
	}

	ids := make([]string, 0, len(res.Items))
	for _, item := range res.Items {
		if id := item.Labels[labelReplicaID]; id != "" {
			ids = append(ids, id)
		}
	}
	return ids, nil
}

// Sample reads the replica's limits and takes one stats reading. The daemon
// waits about a second to fill the previous-sample fields, so callers should
// run several of these concurrently.
func (c *Client) Sample(ctx context.Context, replicaID string) (Sample, error) {
	name := containerName(replicaID)

	ins, err := c.api.ContainerInspect(ctx, name, client.ContainerInspectOptions{})
	if err != nil {
		if errdefs.IsNotFound(err) {
			return Sample{}, fmt.Errorf("sample %s: %w", replicaID, ErrNotFound)
		}
		return Sample{}, dockerErr(fmt.Sprintf("inspect container %s", name), err)
	}

	s := Sample{ReplicaID: replicaID}
	if st := ins.Container.State; st != nil {
		s.Running = st.Running
	}
	if hc := ins.Container.HostConfig; hc != nil {
		s.CPULimitNanos = hc.NanoCPUs
	}
	if !s.Running {
		return s, nil
	}

	res, err := c.api.ContainerStats(ctx, name, client.ContainerStatsOptions{IncludePreviousSample: true})
	if err != nil {
		if errdefs.IsNotFound(err) {
			return Sample{}, fmt.Errorf("sample %s: %w", replicaID, ErrNotFound)
		}
		return Sample{}, dockerErr(fmt.Sprintf("stats container %s", name), err)
	}
	defer res.Body.Close()

	var stats container.StatsResponse
	if err := json.NewDecoder(res.Body).Decode(&stats); err != nil {
		return Sample{}, fmt.Errorf("decode stats of %s: %w", name, err)
	}

	return applyStats(s, stats), nil
}

// applyStats copies the counters of a stats response into s.
func applyStats(s Sample, st container.StatsResponse) Sample {
	s.CPUTotal = st.CPUStats.CPUUsage.TotalUsage
	s.PreCPUTotal = st.PreCPUStats.CPUUsage.TotalUsage
	s.SystemCPU = st.CPUStats.SystemUsage
	s.PreSystemCPU = st.PreCPUStats.SystemUsage
	s.OnlineCPUs = st.CPUStats.OnlineCPUs
	s.PerCPUCount = len(st.CPUStats.CPUUsage.PercpuUsage)
	s.MemUsage = st.MemoryStats.Usage
	s.MemLimit = st.MemoryStats.Limit
	s.MemStats = st.MemoryStats.Stats
	return s
}
