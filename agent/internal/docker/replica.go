package docker

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strconv"
	"time"

	"github.com/containerd/errdefs"
	"github.com/moby/moby/api/types/container"
	"github.com/moby/moby/api/types/network"
	"github.com/moby/moby/client"
)

// ImageRef points to an image by digest.
type ImageRef struct {
	Repository string // registry host included: 192.168.252.1:5050/demo/nginx
	Digest     string
}

// String returns the reference Docker understands: "repository@digest".
func (r ImageRef) String() string {
	return fmt.Sprintf("%s@%s", r.Repository, r.Digest)
}

// EnvVar is one environment variable of a replica.
type EnvVar struct {
	Name  string
	Value string
}

// ReplicaSpec is what to run. Already validated by the caller.
type ReplicaSpec struct {
	ReplicaID     string
	AppID         string
	Image         ImageRef
	ContainerPort int
	CPUMillicores int64
	MemoryBytes   int64
	Env           []EnvVar
	// HealthPath is an HTTP path to probe; empty means a TCP probe. Kept in a
	// label so it survives an agent restart.
	HealthPath string
}

// State is the lifecycle state of a replica.
type State int

const (
	StateUnknown State = iota
	StateRunning
	StateExited
)

// Replica is a replica as Docker currently sees it.
type Replica struct {
	ReplicaID     string
	AppID         string
	State         State
	HostPort      int
	ContainerPort int
	Image         ImageRef
	StartedAt     time.Time
	ExitCode      int // meaningful only when State == StateExited
	// Status is Docker's own state name ("running", "exited", "dead",
	// "created", ...), for callers that need more than State tells.
	Status     string
	OOMKilled  bool
	FinishedAt time.Time // zero while the container never ran or is running
	HealthPath string
}

// containerName returns the container name of a replica: "bult-<replicaID>".
// Docker keeps names unique, so a retried Run fails instead of duplicating.
func containerName(replicaID string) string {
	return fmt.Sprintf("bult-%s", replicaID)
}

// Run pulls the image if needed, creates and starts the replica's container,
// and returns it as Docker reports it.
func (c *Client) Run(ctx context.Context, spec ReplicaSpec) (Replica, error) {
	name := containerName(spec.ReplicaID)

	existing, err := c.inspectReplica(ctx, name)
	if err == nil {
		if sameIdentity(existing, spec) {
			return existing, nil
		}
		return Replica{}, fmt.Errorf("replica %s: %w", spec.ReplicaID, ErrSpecMismatch)
	}
	if !errors.Is(err, ErrNotFound) {
		return Replica{}, fmt.Errorf("inspect existing replica: %w", err)
	}

	port, err := c.ports.Reserve()
	if err != nil {
		return Replica{}, fmt.Errorf("reserve port: %w", err)
	}

	var committed bool
	defer func() {
		if !committed {
			c.ports.Release(port)
		}
	}()

	if err := c.ensureImage(ctx, spec.Image.String()); err != nil {
		return Replica{}, err
	}

	netName, err := c.ensureNetwork(ctx, spec.AppID)
	if err != nil {
		return Replica{}, err
	}

	cfg, hostCfg, err := containerConfigs(spec, port)
	if err != nil {
		return Replica{}, err
	}

	createRes, err := c.api.ContainerCreate(ctx, client.ContainerCreateOptions{
		Name:       containerName(spec.ReplicaID),
		Config:     cfg,
		HostConfig: hostCfg,
		NetworkingConfig: &network.NetworkingConfig{
			EndpointsConfig: map[string]*network.EndpointSettings{
				netName: {},
			},
		},
	})

	if err != nil {
		if errdefs.IsConflict(err) {
			existing, inspectErr := c.inspectReplica(ctx, name)
			if inspectErr != nil {
				if errors.Is(inspectErr, ErrNotFound) {
					return Replica{}, fmt.Errorf("replica %s: %w", spec.ReplicaID, ErrNameRace)
				}
				return Replica{}, fmt.Errorf("inspect after create conflict: %w", inspectErr)
			}
			if sameIdentity(existing, spec) {
				return existing, nil
			}
			return Replica{}, fmt.Errorf("replica %s: %w", spec.ReplicaID, ErrSpecMismatch)
		}
		return Replica{}, dockerErr("create container", err)
	}

	containerID := createRes.ID

	if _, err := c.api.ContainerStart(ctx, containerID, client.ContainerStartOptions{}); err != nil {
		cleanupCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)
		defer cancel()

		_, rmErr := c.api.ContainerRemove(cleanupCtx, containerID, client.ContainerRemoveOptions{Force: true})
		if rmErr != nil {
			slog.Warn("remove container after failed start", "id", containerID, "err", rmErr)
		}
		return Replica{}, dockerErr("start container", err)
	}

	committed = true

	replica, err := c.inspectReplica(ctx, containerID)
	if err != nil {
		return Replica{}, fmt.Errorf("inspect created replica: %w", err)
	}

	return replica, nil
}

// Inspect reads one replica back from Docker; ErrNotFound if it is gone.
func (c *Client) Inspect(ctx context.Context, replicaID string) (Replica, error) {
	return c.inspectReplica(ctx, containerName(replicaID))
}

// inspectReplica reads a container back from Docker and maps it to Replica:
// IDs and image from labels, state/exit code/start time from State,
// host port from the port bindings. ListReplicas will reuse it.
func (c *Client) inspectReplica(ctx context.Context, containerID string) (Replica, error) {
	insRes, err := c.api.ContainerInspect(ctx, containerID, client.ContainerInspectOptions{})
	if err != nil {
		if errdefs.IsNotFound(err) {
			return Replica{}, fmt.Errorf("inspect replica %s: %w", containerID, ErrNotFound)
		}
		return Replica{}, dockerErr(fmt.Sprintf("inspect container %s", containerID), err)
	}

	labels := insRes.Container.Config.Labels
	replica := Replica{
		ReplicaID: labels[labelReplicaID],
		AppID:     labels[labelAppID],
		Image: ImageRef{
			Repository: labels[labelImageRepo],
			Digest:     labels[labelImageDigest],
		},
		HealthPath: labels[labelHealthPath],
	}

	containerState := insRes.Container.State
	if containerState != nil {
		switch containerState.Status {
		case container.StateRunning:
			replica.State = StateRunning
		case container.StateExited:
			replica.State = StateExited
		default:
			replica.State = StateUnknown
		}

		replica.ExitCode = containerState.ExitCode
		replica.Status = string(containerState.Status)
		replica.OOMKilled = containerState.OOMKilled

		if containerState.FinishedAt != "" {
			t, err := time.Parse(time.RFC3339, containerState.FinishedAt)
			if err != nil {
				return Replica{}, fmt.Errorf("parse finished_at %q: %w", containerState.FinishedAt, err)
			}
			replica.FinishedAt = t
		}

		if containerState.StartedAt != "" {
			t, err := time.Parse(time.RFC3339, containerState.StartedAt)
			if err != nil {
				return Replica{}, fmt.Errorf("parse started_at %q: %w", containerState.StartedAt, err)
			}
			replica.StartedAt = t
		}
	}

	rawPort, ok := labels[labelContainerPort]
	if !ok || rawPort == "" {
		return Replica{}, fmt.Errorf("missing %q label on container %s", labelContainerPort, containerID)
	}

	containerPort, err := strconv.Atoi(rawPort)
	if err != nil {
		return Replica{}, fmt.Errorf("bad label %q value %q: %w", labelContainerPort, rawPort, err)
	}
	replica.ContainerPort = containerPort

	key, err := network.ParsePort(rawPort)
	if err != nil {
		return Replica{}, fmt.Errorf("bad label %q value %q: %w", labelContainerPort, rawPort, err)
	}

	var bindings []network.PortBinding
	if insRes.Container.HostConfig != nil && insRes.Container.HostConfig.PortBindings != nil {
		bindings = insRes.Container.HostConfig.PortBindings[key]
	}

	if len(bindings) == 0 {
		return Replica{}, fmt.Errorf("replica %s missing host port binding for container port %s", replica.ReplicaID, rawPort)
	}

	hostPort, err := strconv.Atoi(bindings[0].HostPort)
	if err != nil {
		return Replica{}, fmt.Errorf("invalid host port string %q for replica %s: %w", bindings[0].HostPort, replica.ReplicaID, err)
	}
	replica.HostPort = hostPort

	return replica, nil
}
