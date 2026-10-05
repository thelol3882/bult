package server

import (
	agentv1 "github.com/thelol3882/bult/agent/gen/bult/agent/v1"
	"github.com/thelol3882/bult/agent/internal/docker"
)

// Runtime implements the gRPC RuntimeServiceServer.
type Runtime struct {
	agentv1.UnimplementedRuntimeServiceServer
	docker *docker.Client
}

// NewRuntime creates and initializes a new Runtime service instance.
func NewRuntime(dc *docker.Client) *Runtime {
	return &Runtime{
		docker: dc,
	}
}
