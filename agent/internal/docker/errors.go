package docker

import (
	"errors"
	"fmt"

	"github.com/moby/moby/client"
)

// Domain errors of the docker package. The server maps them to gRPC codes
// with errors.Is; they never leak Docker SDK details into the server.
var (
	// ErrNotFound: no bult replica with this id on the node.
	ErrNotFound = errors.New("replica not found")
	// ErrSpecMismatch: a replica with this id exists, but was created from a
	// different spec (app, image or container port). A control-plane bug.
	ErrSpecMismatch = errors.New("replica exists with a different spec")
	// ErrImageNotFound: the image digest is not in the registry. The request
	// is valid, the world is not (FAILED_PRECONDITION).
	ErrImageNotFound = errors.New("image not found in registry")
	// ErrNameRace: an identical concurrent Run reserved the container name,
	// but the replica is not inspectable yet. Retry (ABORTED).
	ErrNameRace = errors.New("concurrent run of the same replica in progress")
	// ErrDockerUnavailable: the Docker daemon cannot be reached (UNAVAILABLE).
	ErrDockerUnavailable = errors.New("docker daemon unavailable")
)

// dockerErr wraps an SDK error with the failed operation and, if the daemon
// is unreachable, with ErrDockerUnavailable as well, so callers can detect it
// with errors.Is while the original error stays in the chain.
func dockerErr(op string, err error) error {
	if err == nil {
		return nil
	}

	if client.IsErrConnectionFailed(err) {
		return fmt.Errorf("%s: %w: %w", op, ErrDockerUnavailable, err)
	}

	return fmt.Errorf("%s: %w", op, err)
}
