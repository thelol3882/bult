package docker

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strconv"

	"github.com/containerd/errdefs"
	"github.com/moby/moby/client"
)

// LoadPorts claims in the allocator the host ports of every existing bult
// replica, running or stopped. main calls it once, before the gRPC server
// starts serving.
func (c *Client) LoadPorts(ctx context.Context) error {
	filters := make(client.Filters).Add("label", labelManaged+"=true")

	listRes, err := c.api.ContainerList(ctx, client.ContainerListOptions{
		All:     true,
		Filters: filters,
	})
	if err != nil {
		return dockerErr("list containers", err)
	}

	totalClaimed := 0

	for _, container := range listRes.Items {
		insRes, err := c.api.ContainerInspect(ctx, container.ID, client.ContainerInspectOptions{})
		if err != nil {
			return dockerErr("inspect container", err)
		}

		if insRes.Container.HostConfig == nil {
			continue
		}

		for _, bindings := range insRes.Container.HostConfig.PortBindings {
			for _, b := range bindings {
				if b.HostPort == "" {
					continue
				}

				port, err := strconv.Atoi(b.HostPort)
				if err != nil {
					return fmt.Errorf("invalid host port %q for container %s: %w", b.HostPort, container.ID, err)
				}

				c.ports.Claim(port)
				totalClaimed++
			}
		}
	}

	slog.Info("loaded existing replica ports", slog.Int("count", totalClaimed))
	return nil
}

// Stop stops the replica's container (SIGTERM, then SIGKILL after Docker's
// timeout) and returns its state. Stopping a stopped replica is OK.
func (c *Client) Stop(ctx context.Context, replicaID string) (Replica, error) {
	name := containerName(replicaID)

	_, err := c.api.ContainerStop(ctx, name, client.ContainerStopOptions{})
	if err != nil {
		if errdefs.IsNotFound(err) {
			return Replica{}, fmt.Errorf("stop %s: %w", replicaID, ErrNotFound)
		}
		return Replica{}, dockerErr(fmt.Sprintf("stop container %s", name), err)
	}

	replica, err := c.inspectReplica(ctx, name)
	if err != nil {
		return Replica{}, fmt.Errorf("inspect after stop %s: %w", name, err)
	}

	return replica, nil
}

// Start starts a stopped replica. Starting a running replica is OK.
func (c *Client) Start(ctx context.Context, replicaID string) (Replica, error) {
	name := containerName(replicaID)

	_, err := c.api.ContainerStart(ctx, name, client.ContainerStartOptions{})
	if err != nil {
		if errdefs.IsNotFound(err) {
			return Replica{}, fmt.Errorf("start %s: %w", replicaID, ErrNotFound)
		}
		return Replica{}, dockerErr(fmt.Sprintf("start container %s", name), err)
	}

	replica, err := c.inspectReplica(ctx, name)
	if err != nil {
		return Replica{}, fmt.Errorf("inspect after start %s: %w", name, err)
	}

	return replica, nil
}

// Remove deletes the replica's container and frees its host port.
// Removing a missing replica is OK.
func (c *Client) Remove(ctx context.Context, replicaID string) error {
	name := containerName(replicaID)

	replica, err := c.inspectReplica(ctx, name)
	if err != nil {
		if errors.Is(err, ErrNotFound) {
			return nil
		}
		return fmt.Errorf("inspect %s: %w", name, err)
	}

	_, err = c.api.ContainerRemove(ctx, name, client.ContainerRemoveOptions{
		Force: true,
	})
	if err != nil {
		if errdefs.IsNotFound(err) {
			return nil
		}
		return dockerErr(fmt.Sprintf("remove container %s", name), err)
	}

	c.ports.Release(replica.HostPort)
	return nil
}

// List returns every bult replica on the node, running or stopped.
func (c *Client) List(ctx context.Context) ([]Replica, error) {
	filters := make(client.Filters).Add("label", labelManaged+"=true")

	listRes, err := c.api.ContainerList(ctx, client.ContainerListOptions{
		All:     true,
		Filters: filters,
	})
	if err != nil {
		return nil, dockerErr("list containers", err)
	}

	replicas := make([]Replica, 0, len(listRes.Items))

	for _, item := range listRes.Items {
		rep, err := c.inspectReplica(ctx, item.ID)
		if err != nil {
			if errors.Is(err, ErrNotFound) {
				continue
			}
			return nil, fmt.Errorf("inspect replica %s: %w", item.ID, err)
		}

		replicas = append(replicas, rep)
	}

	return replicas, nil
}

// sameIdentity reports whether an existing replica was created from the same
// spec, as far as the identity labels can tell: app, image and container port.
func sameIdentity(existing Replica, spec ReplicaSpec) bool {
	return existing.AppID == spec.AppID &&
		existing.Image.Repository == spec.Image.Repository &&
		existing.Image.Digest == spec.Image.Digest &&
		existing.ContainerPort == spec.ContainerPort
}
