package docker

import (
	"context"
	"fmt"
	"io"
	"strconv"

	"github.com/containerd/errdefs"
	"github.com/moby/moby/api/pkg/stdcopy"
	"github.com/moby/moby/client"
)

// Logs writes the last tailLines lines of the replica's stdout and stderr to w,
// merged into one stream in the original order, without Docker's 8-byte frame
// headers. The docker package knows nothing about gRPC: w can be anything.
func (c *Client) Logs(ctx context.Context, replicaID string, tailLines int, w io.Writer) error {
	name := containerName(replicaID)

	logRes, err := c.api.ContainerLogs(ctx, name, client.ContainerLogsOptions{
		ShowStdout: true,
		ShowStderr: true,
		Tail:       strconv.Itoa(tailLines),
	})
	if err != nil {
		if errdefs.IsNotFound(err) {
			return fmt.Errorf("logs %s: %w", replicaID, ErrNotFound)
		}
		return dockerErr(fmt.Sprintf("logs container %s", name), err)
	}

	defer logRes.Close()

	if _, err := stdcopy.StdCopy(w, w, logRes); err != nil {
		return fmt.Errorf("copy logs: %w", err)
	}

	return nil
}
