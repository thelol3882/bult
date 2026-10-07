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
		return dockerErr(fmt.Sprintf("inspect image %s", ref), err)
	}

	response, err := c.api.ImagePull(ctx, ref, client.ImagePullOptions{})
	if err != nil {
		if errdefs.IsNotFound(err) {
			return fmt.Errorf("pull image %s: %w: %w", ref, err, ErrImageNotFound)
		}
		return dockerErr(fmt.Sprintf("pull image %s", ref), err)
	}
	defer response.Close()

	if err := response.Wait(ctx); err != nil {
		return dockerErr(fmt.Sprintf("wait for pull %s", ref), err)
	}

	return nil
}
