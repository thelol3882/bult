package server

import (
	agentv1 "github.com/thelol3882/bult/agent/gen/bult/agent/v1"
)

// Runtime implements the gRPC RuntimeServiceServer.
type Runtime struct {
	agentv1.UnimplementedRuntimeServiceServer
}

// NewRuntime creates and initializes a new Runtime service instance.
func NewRuntime() *Runtime {
	return &Runtime{}
}
