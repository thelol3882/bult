package server

import (
	"context"

	agentv1 "github.com/thelol3882/bult/agent/gen/bult/agent/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// StopReplica implements agentv1.RuntimeServiceServer.
func (r *Runtime) StopReplica(ctx context.Context, req *agentv1.StopReplicaRequest) (*agentv1.StopReplicaResponse, error) {
	if req.GetReplicaId() == "" {
		return nil, status.Error(codes.InvalidArgument, "replica_id is required")
	}

	replica, err := r.docker.Stop(ctx, req.GetReplicaId())
	if err != nil {
		return nil, toStatus("stop replica", err)
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
		return nil, toStatus("start replica", err)
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
		return nil, toStatus("remove replica", err)
	}

	return &agentv1.RemoveReplicaResponse{}, nil
}

// ListReplicas implements agentv1.RuntimeServiceServer.
func (r *Runtime) ListReplicas(ctx context.Context, req *agentv1.ListReplicasRequest) (*agentv1.ListReplicasResponse, error) {
	replicas, err := r.docker.List(ctx)
	if err != nil {
		return nil, toStatus("list replicas", err)
	}

	protoReplicas := make([]*agentv1.Replica, 0, len(replicas))
	for _, rep := range replicas {
		protoReplicas = append(protoReplicas, toProtoReplica(rep))
	}

	return &agentv1.ListReplicasResponse{
		Replicas: protoReplicas,
	}, nil
}
