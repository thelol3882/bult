package docker

import "errors"

// Domain errors of the docker package. The server maps them to gRPC codes
// with errors.Is; they never leak Docker SDK details into the server.
var (
	// ErrNotFound: no bult replica with this id on the node.
	ErrNotFound = errors.New("replica not found")
	// ErrSpecMismatch: a replica with this id exists, but was created from a
	// different spec (app, image or container port). A control-plane bug.
	ErrSpecMismatch = errors.New("replica exists with a different spec")
)

