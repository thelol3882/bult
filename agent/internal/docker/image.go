package docker

import (
	"context"
	"fmt"

	"github.com/containerd/errdefs"
	"github.com/moby/moby/client"
)

// ensureImage makes sure ref ("repository@digest") is present on the node,
// pulling it if missing. It returns only after the pull has finished and
// succeeded.
func (c *Client) ensureImage(ctx context.Context, ref string) error {
	_, err := c.api.ImageInspect(ctx, ref)
	if err == nil {
		return nil
	}

	if !errdefs.IsNotFound(err) {
		return fmt.Errorf("inspect image %s: %w", ref, err)
	}

	response, err := c.api.ImagePull(ctx, ref, client.ImagePullOptions{})
	if err != nil {
		return fmt.Errorf("pull image %s: %w", ref, err)
	}
	defer response.Close()

	if err := response.Wait(ctx); err != nil {
		return fmt.Errorf("wait for pull %s: %w", ref, err)
	}

	return nil
}
