package docker

import (
	"testing"

	"github.com/moby/moby/api/types/container"
)

func testSpec() ReplicaSpec {
	return ReplicaSpec{
		ReplicaID: "d1-r0", AppID: "app", ContainerPort: 8000,
		Image:         ImageRef{Repository: "reg/app", Digest: "sha256:abc"},
		CPUMillicores: 500, MemoryBytes: 1 << 28,
		Env: []EnvVar{{Name: "A", Value: "1"}},
	}
}

func TestContainerConfigsRestartPolicyIsNo(t *testing.T) {
	_, host, err := containerConfigs(testSpec(), 20001)
	if err != nil {
		t.Fatal(err)
	}
	if host.RestartPolicy.Name != container.RestartPolicyDisabled {
		t.Errorf("restart policy = %q, want %q", host.RestartPolicy.Name, container.RestartPolicyDisabled)
	}
}

func TestContainerConfigsLabelsAndEnv(t *testing.T) {
	spec := testSpec()
	cfg, host, err := containerConfigs(spec, 20001)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Labels[labelManaged] != "true" || cfg.Labels[labelReplicaID] != "d1-r0" || cfg.Labels[labelContainerPort] != "8000" {
		t.Errorf("labels = %v", cfg.Labels)
	}
	if _, ok := cfg.Labels[labelHealthPath]; ok {
		t.Error("health path label set without a health path")
	}
	if len(cfg.Env) != 1 || cfg.Env[0] != "A=1" {
		t.Errorf("env = %v", cfg.Env)
	}
	if host.NanoCPUs != 500_000_000 || host.Memory != 1<<28 {
		t.Errorf("limits = %d / %d", host.NanoCPUs, host.Memory)
	}

	spec.HealthPath = "/healthz"
	cfg, _, err = containerConfigs(spec, 20001)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Labels[labelHealthPath] != "/healthz" {
		t.Errorf("health path label = %q", cfg.Labels[labelHealthPath])
	}
}
