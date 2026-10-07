package server

import (
	"fmt"

	agentv1 "github.com/thelol3882/bult/agent/gen/bult/agent/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

const (
	defaultTailLines = 100
	maxTailLines     = 10000
	logChunkSize     = 32 << 10
)

// Logs implements agentv1.RuntimeServiceServer. A server-streaming RPC: there
// is no ctx parameter — it lives in stream.Context().
func (r *Runtime) Logs(req *agentv1.LogsRequest, stream grpc.ServerStreamingServer[agentv1.LogsResponse]) error {
	if req.GetReplicaId() == "" {
		return status.Error(codes.InvalidArgument, "replica_id is required")
	}

	if req.GetFollow() {
		return status.Error(codes.Unimplemented, "follow is not supported yet")
	}

	tailLines := int(req.GetTailLines())
	if tailLines == 0 {
		tailLines = defaultTailLines
	} else if tailLines < 0 || tailLines > maxTailLines {
		return status.Errorf(codes.InvalidArgument, "tail_lines must be between 1 and %d, got %d", maxTailLines, tailLines)
	}

	w := &chunkWriter{stream: stream}

	if err := r.docker.Logs(stream.Context(), req.GetReplicaId(), tailLines, w); err != nil {
		return toStatus("logs", err)
	}

	return nil
}

// chunkWriter is an io.Writer that sends everything written to it as
// LogsResponse messages, at most logChunkSize bytes each.
type chunkWriter struct {
	stream grpc.ServerStreamingServer[agentv1.LogsResponse]
}

// Write implements io.Writer.
func (w *chunkWriter) Write(p []byte) (int, error) {
	totalSent := 0

	for len(p) > 0 {
		chunkSize := len(p)
		if chunkSize > logChunkSize {
			chunkSize = logChunkSize
		}

		err := w.stream.Send(&agentv1.LogsResponse{
			Data: p[:chunkSize],
		})
		if err != nil {
			return totalSent, fmt.Errorf("send log chunk: %w", err)
		}

		totalSent += chunkSize
		p = p[chunkSize:]
	}

	return totalSent, nil
}
