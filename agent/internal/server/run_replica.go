package server

import (
	"context"
	"errors"
	"fmt"

	agentv1 "github.com/thelol3882/bult/agent/gen/bult/agent/v1"
	"github.com/thelol3882/bult/agent/internal/docker"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// RunReplica implements agentv1.RuntimeServiceServer.
func (r *Runtime) RunReplica(ctx context.Context, req *agentv1.RunReplicaRequest) (*agentv1.RunReplicaResponse, error) {
	if err := validateRunReplica(req); err != nil {
		return nil, status.Error(codes.InvalidArgument, err.Error())
	}

	spec := toSpec(req)
	replica, err := r.docker.Run(ctx, spec)
	if err != nil {
		code := codes.Internal
		if errors.Is(err, docker.ErrSpecMismatch) {
			code = codes.AlreadyExists
		}
		return nil, status.Errorf(code, "run replica: %v", err)
	}

	return &agentv1.RunReplicaResponse{
		Replica: toProtoReplica(replica),
	}, nil
}

// validateRunReplica checks what Docker cannot check for us.
// Returns an error naming the bad field, nil if the request is valid.
func validateRunReplica(req *agentv1.RunReplicaRequest) error {
	if req == nil {
		return errors.New("request is nil")
	}

	if req.GetReplicaId() == "" {
		return errors.New("replica_id is required")
	}
	if req.GetAppId() == "" {
		return errors.New("app_id is required")
	}
	if req.GetImage().GetRepository() == "" {
		return errors.New("image.repository is required")
	}
	if req.GetImage().GetDigest() == "" {
		return errors.New("image.digest is required")
	}

	port := req.GetContainerPort()
	if port < 1 || port > 65535 {
		return fmt.Errorf("container_port must be between 1 and 65535, got %d", port)
	}

	limits := req.GetLimits()
	if limits == nil {
		return errors.New("limits is required")
	}
	if limits.GetCpuMillicores() <= 0 {
		return errors.New("limits.cpu_millicores must be > 0")
	}
	if limits.GetMemoryBytes() <= 0 {
		return errors.New("limits.memory_bytes must be > 0")
	}

	for i, env := range req.GetEnv() {
		if env.GetName() == "" {
			return fmt.Errorf("env[%d].name cannot be empty", i)
		}
	}

	return nil
}

// toSpec converts a validated request into the docker package's spec.
func toSpec(req *agentv1.RunReplicaRequest) docker.ReplicaSpec {
	envVars := make([]docker.EnvVar, 0, len(req.GetEnv()))
	for _, e := range req.GetEnv() {
		envVars = append(envVars, docker.EnvVar{
			Name:  e.GetName(),
			Value: e.GetValue(),
		})
	}

	return docker.ReplicaSpec{
		ReplicaID: req.GetReplicaId(),
		AppID:     req.GetAppId(),
		Image: docker.ImageRef{
			Repository: req.GetImage().GetRepository(),
			Digest:     req.GetImage().GetDigest(),
		},
		ContainerPort: int(req.GetContainerPort()),
		CPUMillicores: req.GetLimits().GetCpuMillicores(),
		MemoryBytes:   req.GetLimits().GetMemoryBytes(),
		Env:           envVars,
	}
}

// toProtoReplica converts a domain replica into its protobuf message.
func toProtoReplica(rep docker.Replica) *agentv1.Replica {
	var state agentv1.ReplicaState
	switch rep.State {
	case docker.StateRunning:
		state = agentv1.ReplicaState_REPLICA_STATE_RUNNING
	case docker.StateExited:
		state = agentv1.ReplicaState_REPLICA_STATE_EXITED
	default:
		state = agentv1.ReplicaState_REPLICA_STATE_UNSPECIFIED
	}

	res := &agentv1.Replica{
		ReplicaId: rep.ReplicaID,
		AppId:     rep.AppID,
		State:     state,
		HostPort:  uint32(rep.HostPort),
		Image: &agentv1.ImageRef{
			Repository: rep.Image.Repository,
			Digest:     rep.Image.Digest,
		},
	}

	if !rep.StartedAt.IsZero() {
		res.StartedAt = timestamppb.New(rep.StartedAt)
	}

	if rep.State == docker.StateExited {
		exitCode := int32(rep.ExitCode)
		res.ExitCode = &exitCode
	}

	return res
}
