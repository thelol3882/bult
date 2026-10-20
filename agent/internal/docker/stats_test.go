package docker

import (
	"testing"

	"github.com/moby/moby/api/types/container"
)

func TestApplyStats(t *testing.T) {
	var st container.StatsResponse
	st.CPUStats.CPUUsage.TotalUsage = 30
	st.CPUStats.CPUUsage.PercpuUsage = []uint64{10, 20}
	st.CPUStats.SystemUsage = 300
	st.CPUStats.OnlineCPUs = 2
	st.PreCPUStats.CPUUsage.TotalUsage = 10
	st.PreCPUStats.SystemUsage = 200
	st.MemoryStats.Usage = 500
	st.MemoryStats.Limit = 1000
	st.MemoryStats.Stats = map[string]uint64{"inactive_file": 7}

	got := applyStats(Sample{ReplicaID: "d-r0", Running: true}, st)

	if got.CPUTotal != 30 || got.PreCPUTotal != 10 || got.SystemCPU != 300 || got.PreSystemCPU != 200 {
		t.Errorf("cpu counters = %+v", got)
	}
	if got.OnlineCPUs != 2 || got.PerCPUCount != 2 {
		t.Errorf("cpu count = %d / %d", got.OnlineCPUs, got.PerCPUCount)
	}
	if got.MemUsage != 500 || got.MemLimit != 1000 || got.MemStats["inactive_file"] != 7 {
		t.Errorf("memory = %+v", got)
	}
	if got.ReplicaID != "d-r0" || !got.Running {
		t.Errorf("identity lost: %+v", got)
	}
}
