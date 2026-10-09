package server

import (
	"context"

	agentv1 "github.com/thelol3882/bult/agent/gen/bult/agent/v1"
	"github.com/thelol3882/bult/agent/internal/build"
	"google.golang.org/grpc"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// Builder implements the gRPC BuildServiceServer.
type Builder struct {
	agentv1.UnimplementedBuildServiceServer
	jobs deployManager
}

// deployManager is what the handlers need.
type deployManager interface {
	Start(ctx context.Context, spec build.Spec) (build.Status, error)
	Get(deployID string) (build.Status, error)
	Cancel(deployID string) (build.Status, error)
	Watch(ctx context.Context, deployID string, offset int64, emit func(build.LogChunk) error) (build.Status, error)
}

var _ deployManager = (*build.Manager)(nil)

// NewBuilder initializes a new Builder server.
func NewBuilder(m deployManager) *Builder {
	return &Builder{jobs: m}
}

func (b *Builder) StartDeploy(ctx context.Context, req *agentv1.StartDeployRequest) (*agentv1.StartDeployResponse, error) {
	spec := build.Spec{
		DeployID: req.GetDeployId(),
		AppID:    req.GetAppId(),
		Source: build.Source{
			RepoURL: req.GetSource().GetRepoUrl(),
			Branch:  req.GetSource().GetBranch(),
			Subdir:  req.GetSource().GetSubdir(),
		},
		Dockerfile: req.GetDockerfile(),
	}

	st, err := b.jobs.Start(ctx, spec)
	if err != nil {
		return nil, toStatus("start deploy", err)
	}

	return &agentv1.StartDeployResponse{
		Deploy: toProtoDeploy(st),
	}, nil
}

func (b *Builder) GetDeploy(ctx context.Context, req *agentv1.GetDeployRequest) (*agentv1.GetDeployResponse, error) {
	st, err := b.jobs.Get(req.GetDeployId())
	if err != nil {
		return nil, toStatus("get deploy", err)
	}

	return &agentv1.GetDeployResponse{
		Deploy: toProtoDeploy(st),
	}, nil
}

func (b *Builder) CancelDeploy(ctx context.Context, req *agentv1.CancelDeployRequest) (*agentv1.CancelDeployResponse, error) {
	st, err := b.jobs.Cancel(req.GetDeployId())
	if err != nil {
		return nil, toStatus("cancel deploy", err)
	}

	return &agentv1.CancelDeployResponse{
		Deploy: toProtoDeploy(st),
	}, nil
}

func (b *Builder) WatchDeploy(req *agentv1.WatchDeployRequest, stream grpc.ServerStreamingServer[agentv1.WatchDeployResponse]) error {
	emit := func(c build.LogChunk) error {
		return stream.Send(&agentv1.WatchDeployResponse{
			Event: &agentv1.WatchDeployResponse_Log{
				Log: &agentv1.LogChunk{
					Offset: c.Offset,
					Data:   c.Data,
				},
			},
		})
	}

	st, err := b.jobs.Watch(stream.Context(), req.GetDeployId(), req.GetOffset(), emit)
	if err != nil {
		return toStatus("watch deploy", err)
	}

	return stream.Send(&agentv1.WatchDeployResponse{
		Event: &agentv1.WatchDeployResponse_Deploy{
			Deploy: toProtoDeploy(st),
		},
	})
}

// toProtoDeploy converts an internal build.Status to the protobuf Deploy message.
func toProtoDeploy(st build.Status) *agentv1.Deploy {
	d := &agentv1.Deploy{
		DeployId:  st.DeployID,
		AppId:     st.AppID,
		CommitSha: st.CommitSHA,
		Error:     st.Error,
		StartedAt: timestamppb.New(st.StartedAt),
	}

	switch st.State {
	case build.StateRunning:
		d.State = agentv1.DeployState_DEPLOY_STATE_RUNNING
	case build.StateSucceeded:
		d.State = agentv1.DeployState_DEPLOY_STATE_SUCCEEDED
		d.Image = &agentv1.ImageRef{
			Repository: st.Image.Repository,
			Digest:     st.Image.Digest,
		}
	case build.StateFailed:
		d.State = agentv1.DeployState_DEPLOY_STATE_FAILED
	case build.StateCancelled:
		d.State = agentv1.DeployState_DEPLOY_STATE_CANCELLED
	default:
		d.State = agentv1.DeployState_DEPLOY_STATE_UNSPECIFIED
	}

	if !st.FinishedAt.IsZero() {
		d.FinishedAt = timestamppb.New(st.FinishedAt)
	}

	return d
}
