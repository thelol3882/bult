package docker

import (
	"fmt"

	"github.com/moby/moby/client"
)

// Labels put on every bult-managed object. They are the agent's only memory
// of what it created: ListReplicas will read them back.
const (
	labelManaged       = "bult.managed"
	labelReplicaID     = "bult.replica_id"
	labelAppID         = "bult.app_id"
	labelImageRepo     = "bult.image.repository"
	labelImageDigest   = "bult.image.digest"
	labelContainerPort = "bult.container_port"
)

// Client runs bult replicas on the local Docker daemon.
type Client struct {
	api *client.Client
}

// New connects to the Docker daemon configured by the environment.
func New() (*Client, error) {
	cli, err := client.New(client.FromEnv)
	if err != nil {
		return nil, fmt.Errorf("docker client: %w", err)
	}

	return &Client{
		api: cli,
	}, nil
}

// Close releases the underlying connection.
func (c *Client) Close() error {
	return c.api.Close()
}
