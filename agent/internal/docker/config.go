package docker

import (
	"fmt"
	"net/netip"
	"strconv"

	"github.com/moby/moby/api/types/container"
	"github.com/moby/moby/api/types/network"
)

// containerConfigs builds the Docker configuration of a replica that will be
// published on hostPort. Pure, so the labels and the restart policy can be tested.
func containerConfigs(spec ReplicaSpec, hostPort int) (*container.Config, *container.HostConfig, error) {
	portStr := strconv.Itoa(spec.ContainerPort)
	targetPort, err := network.ParsePort(portStr)
	if err != nil {
		return nil, nil, fmt.Errorf("parse port %s: %w", portStr, err)
	}

	envList := make([]string, 0, len(spec.Env))
	for _, env := range spec.Env {
		envList = append(envList, fmt.Sprintf("%s=%s", env.Name, env.Value))
	}

	labels := map[string]string{
		labelManaged:       "true",
		labelAppID:         spec.AppID,
		labelReplicaID:     spec.ReplicaID,
		labelImageDigest:   spec.Image.Digest,
		labelImageRepo:     spec.Image.Repository,
		labelContainerPort: portStr,
	}
	if spec.HealthPath != "" {
		labels[labelHealthPath] = spec.HealthPath
	}

	cfg := &container.Config{
		Image:        spec.Image.String(),
		Labels:       labels,
		ExposedPorts: network.PortSet{targetPort: struct{}{}},
		Env:          envList,
	}
	hostCfg := &container.HostConfig{
		// The control plane is the only restarter. With Docker restarting
		// containers too, a node reboot would revive replicas the control
		// plane has already replaced or removed.
		RestartPolicy: container.RestartPolicy{Name: container.RestartPolicyDisabled},
		Resources: container.Resources{
			NanoCPUs: spec.CPUMillicores * 1_000_000,
			Memory:   spec.MemoryBytes,
		},
		PortBindings: network.PortMap{
			targetPort: []network.PortBinding{
				{HostIP: netip.IPv4Unspecified(), HostPort: strconv.Itoa(hostPort)},
			},
		},
	}
	return cfg, hostCfg, nil
}
