package docker

import (
	"context"
	"fmt"

	"github.com/containerd/errdefs"
	"github.com/moby/moby/client"
)

// networkName returns the name of the per-app network: "bult-app-<appID>".
func networkName(appID string) string {
	return fmt.Sprintf("bult-app-%s", appID)
}

// ensureNetwork makes sure the network of appID exists and returns its name.
func (c *Client) ensureNetwork(ctx context.Context, appID string) (string, error) {
	name := networkName(appID)

	_, err := c.api.NetworkInspect(ctx, name, client.NetworkInspectOptions{})

	if err == nil {
		return name, nil
	}

	if !errdefs.IsNotFound(err) {
		return "", dockerErr(fmt.Sprintf("inspect network %s", name), err)
	}

	_, err = c.api.NetworkCreate(ctx, name, client.NetworkCreateOptions{
		Labels: map[string]string{
			labelManaged: "true",
			labelAppID:   appID,
		},
	})

	if err != nil {
		if errdefs.IsAlreadyExists(err) {
			return name, nil
		}
		return "", dockerErr(fmt.Sprintf("create network %s", name), err)
	}

	return name, nil
}
