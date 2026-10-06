package server

import (
	"context"
	"errors"

	agentv1 "github.com/thelol3882/bult/agent/gen/bult/agent/v1"
	"github.com/thelol3882/bult/agent/internal/docker"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

func toGRPCError(op string, err error) error {
	if errors.Is(err, docker.ErrNotFound) {
		return status.Errorf(codes.NotFound, "%s: %v", op, err)
	}
	return status.Errorf(codes.Internal, "%s: %v", op, err)
}

// StopReplica implements agentv1.RuntimeServiceServer.
func (r *Runtime) StopReplica(ctx context.Context, req *agentv1.StopReplicaRequest) (*agentv1.StopReplicaResponse, error) {
	if req.GetReplicaId() == "" {
		return nil, status.Error(codes.InvalidArgument, "replica_id is required")
	}

	replica, err := r.docker.Stop(ctx, req.GetReplicaId())
	if err != nil {
		return nil, toGRPCError("stop replica", err)
	}

	return &agentv1.StopReplicaResponse{
		Replica: toProtoReplica(replica),
	}, nil
}

// StartReplica implements agentv1.RuntimeServiceServer.
func (r *Runtime) StartReplica(ctx context.Context, req *agentv1.StartReplicaRequest) (*agentv1.StartReplicaResponse, error) {
	if req.GetReplicaId() == "" {
		return nil, status.Error(codes.InvalidArgument, "replica_id is required")
	}

	replica, err := r.docker.Start(ctx, req.GetReplicaId())
	if err != nil {
		return nil, toGRPCError("start replica", err)
	}

	return &agentv1.StartReplicaResponse{
		Replica: toProtoReplica(replica),
	}, nil
}

// RemoveReplica implements agentv1.RuntimeServiceServer.
func (r *Runtime) RemoveReplica(ctx context.Context, req *agentv1.RemoveReplicaRequest) (*agentv1.RemoveReplicaResponse, error) {
	if req.GetReplicaId() == "" {
		return nil, status.Error(codes.InvalidArgument, "replica_id is required")
	}

	if err := r.docker.Remove(ctx, req.GetReplicaId()); err != nil {
		return nil, status.Errorf(codes.Internal, "remove replica: %v", err)
	}

	return &agentv1.RemoveReplicaResponse{}, nil
}

// ListReplicas implements agentv1.RuntimeServiceServer.
func (r *Runtime) ListReplicas(ctx context.Context, req *agentv1.ListReplicasRequest) (*agentv1.ListReplicasResponse, error) {
	replicas, err := r.docker.List(ctx)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "list replicas: %v", err)
	}

	protoReplicas := make([]*agentv1.Replica, 0, len(replicas))
	for _, rep := range replicas {
		protoReplicas = append(protoReplicas, toProtoReplica(rep))
	}

	return &agentv1.ListReplicasResponse{
		Replicas: protoReplicas,
	}, nil
}
