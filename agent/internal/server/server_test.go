package server

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"strings"
	"testing"
	"time"

	agentv1 "github.com/thelol3882/bult/agent/gen/bult/agent/v1"
	"github.com/thelol3882/bult/agent/internal/docker"
	"github.com/thelol3882/bult/agent/internal/ports"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// fakeRuntime is a hand-written fake of replicaRuntime: fields say what to
// return, `calls` records what was called. No mocking library.
type fakeRuntime struct {
	replica docker.Replica   // returned by Run/Stop/Start
	list    []docker.Replica // returned by List
	logs    string           // written to w by Logs
	err     error            // returned by every method

	calls []string
}

var _ replicaRuntime = (*fakeRuntime)(nil)

func (f *fakeRuntime) Run(ctx context.Context, spec docker.ReplicaSpec) (docker.Replica, error) {
	f.calls = append(f.calls, "Run")
	return f.replica, f.err
}

func (f *fakeRuntime) Stop(ctx context.Context, replicaID string) (docker.Replica, error) {
	f.calls = append(f.calls, "Stop")
	return f.replica, f.err
}

func (f *fakeRuntime) Start(ctx context.Context, replicaID string) (docker.Replica, error) {
	f.calls = append(f.calls, "Start")
	return f.replica, f.err
}

func (f *fakeRuntime) Remove(ctx context.Context, replicaID string) error {
	f.calls = append(f.calls, "Remove")
	return f.err
}

func (f *fakeRuntime) List(ctx context.Context) ([]docker.Replica, error) {
	f.calls = append(f.calls, "List")
	return f.list, f.err
}

func (f *fakeRuntime) Logs(ctx context.Context, replicaID string, tailLines int, w io.Writer) error {
	f.calls = append(f.calls, "Logs")
	if f.err != nil {
		return f.err
	}
	_, err := io.WriteString(w, f.logs)
	return err
}

type fakeLogsStream struct {
	grpc.ServerStreamingServer[agentv1.LogsResponse]
	ctx  context.Context
	sent [][]byte
}

func (s *fakeLogsStream) Context() context.Context {
	if s.ctx == nil {
		return context.Background()
	}
	return s.ctx
}

func (s *fakeLogsStream) Send(m *agentv1.LogsResponse) error {
	data := m.GetData()
	cp := make([]byte, len(data))
	copy(cp, data)
	s.sent = append(s.sent, cp)
	return nil
}

func validRunRequest() *agentv1.RunReplicaRequest {
	return &agentv1.RunReplicaRequest{
		ReplicaId: "rep-123",
		AppId:     "app-abc",
		Image: &agentv1.ImageRef{
			Repository: "library/redis",
			Digest:     "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
		},
		ContainerPort: 80,
		Limits: &agentv1.Limits{
			CpuMillicores: 500,
			MemoryBytes:   256 * 1024 * 1024,
		},
	}
}

func TestRunReplicaValidation(t *testing.T) {
	cases := []struct {
		name   string
		mutate func(*agentv1.RunReplicaRequest)
	}{
		{
			name:   "empty replica_id",
			mutate: func(r *agentv1.RunReplicaRequest) { r.ReplicaId = "" },
		},
		{
			name:   "empty app_id",
			mutate: func(r *agentv1.RunReplicaRequest) { r.AppId = "" },
		},
		{
			name:   "empty digest",
			mutate: func(r *agentv1.RunReplicaRequest) { r.Image.Digest = "" },
		},
		{
			name:   "port 0",
			mutate: func(r *agentv1.RunReplicaRequest) { r.ContainerPort = 0 },
		},
		{
			name:   "port 70000",
			mutate: func(r *agentv1.RunReplicaRequest) { r.ContainerPort = 70000 },
		},
		{
			name:   "nil limits",
			mutate: func(r *agentv1.RunReplicaRequest) { r.Limits = nil },
		},
		{
			name:   "memory 0",
			mutate: func(r *agentv1.RunReplicaRequest) { r.Limits.MemoryBytes = 0 },
		},
		{
			name: "env with empty name",
			mutate: func(r *agentv1.RunReplicaRequest) {
				r.Env = []*agentv1.EnvVar{{Name: "", Value: "foo"}}
			},
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			fake := &fakeRuntime{}
			srv := NewRuntime(fake)

			req := validRunRequest()
			tc.mutate(req)

			_, err := srv.RunReplica(context.Background(), req)
			if status.Code(err) != codes.InvalidArgument {
				t.Fatalf("got status %v, want %v (err: %v)", status.Code(err), codes.InvalidArgument, err)
			}
			if len(fake.calls) != 0 {
				t.Fatalf("fake runtime was called %v, expected 0 calls on invalid input", fake.calls)
			}
		})
	}
}

func TestRunReplicaErrorCodes(t *testing.T) {
	cases := []struct {
		name    string
		fakeErr error
		want    codes.Code
	}{
		{
			name:    "ErrSpecMismatch",
			fakeErr: fmt.Errorf("wrap: %w", docker.ErrSpecMismatch),
			want:    codes.AlreadyExists,
		},
		{
			name:    "ErrImageNotFound",
			fakeErr: fmt.Errorf("wrap: %w", docker.ErrImageNotFound),
			want:    codes.FailedPrecondition,
		},
		{
			name:    "ErrNameRace",
			fakeErr: fmt.Errorf("wrap: %w", docker.ErrNameRace),
			want:    codes.Aborted,
		},
		{
			name:    "ErrDockerUnavailable",
			fakeErr: fmt.Errorf("wrap: %w", docker.ErrDockerUnavailable),
			want:    codes.Unavailable,
		},
		{
			name:    "ErrExhausted",
			fakeErr: fmt.Errorf("wrap: %w", ports.ErrExhausted),
			want:    codes.ResourceExhausted,
		},
		{
			name:    "DeadlineExceeded",
			fakeErr: fmt.Errorf("wrap: %w", context.DeadlineExceeded),
			want:    codes.DeadlineExceeded,
		},
		{
			name:    "generic error",
			fakeErr: errors.New("boom"),
			want:    codes.Internal,
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			fake := &fakeRuntime{err: tc.fakeErr}
			srv := NewRuntime(fake)

			_, err := srv.RunReplica(context.Background(), validRunRequest())
			if got := status.Code(err); got != tc.want {
				t.Fatalf("status.Code(err) = %v, want %v (err: %v)", got, tc.want, err)
			}
		})
	}
}

func TestStopReplicaNotFound(t *testing.T) {
	fake := &fakeRuntime{
		err: fmt.Errorf("stop container rep-1: %w", docker.ErrNotFound),
	}
	srv := NewRuntime(fake)

	_, err := srv.StopReplica(context.Background(), &agentv1.StopReplicaRequest{ReplicaId: "rep-1"})
	if got := status.Code(err); got != codes.NotFound {
		t.Fatalf("status.Code(err) = %v, want %v (err: %v)", got, codes.NotFound, err)
	}
}

func TestRunReplicaConvertsReplica(t *testing.T) {
	startedAt := time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC)

	fake := &fakeRuntime{
		replica: docker.Replica{
			ReplicaID:     "rep-123",
			AppID:         "app-abc",
			State:         docker.StateRunning,
			HostPort:      20000,
			ContainerPort: 80,
			Image: docker.ImageRef{
				Repository: "repo",
				Digest:     "sha256:123",
			},
			StartedAt: startedAt,
		},
	}
	srv := NewRuntime(fake)

	res, err := srv.RunReplica(context.Background(), validRunRequest())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	protoRep := res.GetReplica()
	if protoRep.GetReplicaId() != "rep-123" {
		t.Errorf("ReplicaId = %s, want rep-123", protoRep.GetReplicaId())
	}
	if protoRep.GetState() != agentv1.ReplicaState_REPLICA_STATE_RUNNING {
		t.Errorf("State = %v, want RUNNING", protoRep.GetState())
	}
	if protoRep.GetHostPort() != 20000 {
		t.Errorf("HostPort = %d, want 20000", protoRep.GetHostPort())
	}
	if protoRep.GetStartedAt().AsTime() != startedAt {
		t.Errorf("StartedAt = %v, want %v", protoRep.GetStartedAt().AsTime(), startedAt)
	}
	if protoRep.ExitCode != nil {
		t.Errorf("ExitCode = %v, want nil for running replica", protoRep.ExitCode)
	}

	fake.replica = docker.Replica{
		ReplicaID: "rep-123",
		State:     docker.StateExited,
		ExitCode:  137,
	}

	res, err = srv.RunReplica(context.Background(), validRunRequest())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	protoRep = res.GetReplica()
	if protoRep.GetState() != agentv1.ReplicaState_REPLICA_STATE_EXITED {
		t.Errorf("State = %v, want EXITED", protoRep.GetState())
	}
	if protoRep.GetExitCode() != 137 {
		t.Errorf("ExitCode = %d, want 137", protoRep.GetExitCode())
	}
}

func TestLogsValidation(t *testing.T) {
	cases := []struct {
		name string
		req  *agentv1.LogsRequest
		want codes.Code
	}{
		{
			name: "empty replica_id",
			req:  &agentv1.LogsRequest{ReplicaId: ""},
			want: codes.InvalidArgument,
		},
		{
			name: "follow true",
			req:  &agentv1.LogsRequest{ReplicaId: "rep-1", Follow: true},
			want: codes.Unimplemented,
		},
		{
			name: "tail -1",
			req:  &agentv1.LogsRequest{ReplicaId: "rep-1", TailLines: -1},
			want: codes.InvalidArgument,
		},
		{
			name: "tail 10001",
			req:  &agentv1.LogsRequest{ReplicaId: "rep-1", TailLines: 10001},
			want: codes.InvalidArgument,
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			fake := &fakeRuntime{}
			srv := NewRuntime(fake)
			stream := &fakeLogsStream{}

			err := srv.Logs(tc.req, stream)
			if got := status.Code(err); got != tc.want {
				t.Fatalf("status.Code(err) = %v, want %v (err: %v)", got, tc.want, err)
			}
			if len(fake.calls) != 0 {
				t.Fatalf("fake runtime was called %v, expected 0 calls on invalid input", fake.calls)
			}
		})
	}
}

func TestLogsChunks(t *testing.T) {
	const totalBytes = 70 * 1024
	payload := strings.Repeat("x", totalBytes)

	fake := &fakeRuntime{logs: payload}
	srv := NewRuntime(fake)
	stream := &fakeLogsStream{
		ctx: context.Background(),
	}

	req := &agentv1.LogsRequest{
		ReplicaId: "rep-1",
		TailLines: 100,
	}

	if err := srv.Logs(req, stream); err != nil {
		t.Fatalf("Logs failed unexpectedly: %v", err)
	}

	if len(stream.sent) != 3 {
		t.Fatalf("got %d chunks, want 3", len(stream.sent))
	}

	if len(stream.sent[0]) != logChunkSize || len(stream.sent[1]) != logChunkSize || len(stream.sent[2]) != 6*1024 {
		t.Fatalf("unexpected chunk sizes: [%d, %d, %d]", len(stream.sent[0]), len(stream.sent[1]), len(stream.sent[2]))
	}

	joined := string(bytes.Join(stream.sent, nil))
	if joined != payload {
		t.Fatalf("joined payload does not match original logs")
	}
}
