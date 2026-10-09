package server

import (
	"context"
	"errors"

	"github.com/thelol3882/bult/agent/internal/build"
	"github.com/thelol3882/bult/agent/internal/docker"
	"github.com/thelol3882/bult/agent/internal/ports"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// toStatus converts an error from the runtime into a gRPC status error.
// The single place where domain errors become codes (agent-api.md "Error codes").
// op is a short operation name ("run replica"); it is the ONLY context layer
// added here — the docker package already adds its own.
func toStatus(op string, err error) error {
	if err == nil {
		return nil
	}

	if errors.Is(err, context.DeadlineExceeded) || errors.Is(err, context.Canceled) {
		s := status.FromContextError(err)
		return status.Errorf(s.Code(), "%s: %s", op, s.Message())
	}

	var code codes.Code
	switch {
	case errors.Is(err, build.ErrInvalidRepoURL),
		errors.Is(err, build.ErrInvalidBranch),
		errors.Is(err, build.ErrInvalidDeployID),
		errors.Is(err, build.ErrInvalidAppID),
		errors.Is(err, build.ErrInvalidOffset),
		errors.Is(err, build.ErrInvalidSubdir):
		code = codes.InvalidArgument
	case errors.Is(err, build.ErrDeployNotFound),
		errors.Is(err, docker.ErrNotFound):
		code = codes.NotFound
	case errors.Is(err, build.ErrDeploySpecMismatch),
		errors.Is(err, docker.ErrSpecMismatch):
		code = codes.AlreadyExists
	case errors.Is(err, docker.ErrImageNotFound):
		code = codes.FailedPrecondition
	case errors.Is(err, docker.ErrNameRace):
		code = codes.Aborted
	case errors.Is(err, docker.ErrDockerUnavailable):
		code = codes.Unavailable
	case errors.Is(err, ports.ErrExhausted):
		code = codes.ResourceExhausted
	default:
		code = codes.Internal
	}

	return status.Errorf(code, "%s: %v", op, err)
}
