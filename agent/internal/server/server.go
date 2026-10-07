package server

import (
	"context"
	"io"

	agentv1 "github.com/thelol3882/bult/agent/gen/bult/agent/v1"
	"github.com/thelol3882/bult/agent/internal/docker"
)

// replicaRuntime is what the gRPC handlers need from the container runtime.
// Declared here, by the consumer: *docker.Client satisfies it without knowing
// about it, and tests pass a fake.
type replicaRuntime interface {
	Run(ctx context.Context, spec docker.ReplicaSpec) (docker.Replica, error)
	Stop(ctx context.Context, replicaID string) (docker.Replica, error)
	Start(ctx context.Context, replicaID string) (docker.Replica, error)
	Remove(ctx context.Context, replicaID string) error
	List(ctx context.Context) ([]docker.Replica, error)
	Logs(ctx context.Context, replicaID string, tailLines int, w io.Writer) error
}

// Compile-time check: the real client satisfies the interface. If a method
// signature drifts, the build breaks here, not in main.
var _ replicaRuntime = (*docker.Client)(nil)

// Runtime implements the gRPC RuntimeServiceServer.
type Runtime struct {
	agentv1.UnimplementedRuntimeServiceServer
	docker replicaRuntime
}

// NewRuntime creates and initializes a new Runtime service instance.
func NewRuntime(dc replicaRuntime) *Runtime {
	return &Runtime{
		docker: dc,
	}
}
