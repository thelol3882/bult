package server

import (
	"context"
	"log/slog"
	"strings"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// A gRPC interceptor wraps every call, like middleware in Django: it runs
// before and after the handler and sees the method name and the result.
// Unary and streaming RPCs have different signatures, so there are two.

// LoggingUnaryInterceptor logs every unary RPC: method, status code, duration.
// It must return the handler's response and error UNCHANGED.
func LoggingUnaryInterceptor(ctx context.Context, req any, info *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (any, error) {
	start := time.Now()
	resp, err := handler(ctx, req)
	logRPC(info.FullMethod, err, time.Since(start))
	return resp, err
}

// LoggingStreamInterceptor does the same for streaming RPCs (Logs, WatchDeploy).
// The duration is how long the stream was open, not the build itself.
func LoggingStreamInterceptor(srv any, ss grpc.ServerStream, info *grpc.StreamServerInfo, handler grpc.StreamHandler) error {
	start := time.Now()
	err := handler(srv, ss)
	logRPC(info.FullMethod, err, time.Since(start))
	return err
}

// logRPC writes one log line per call. Never log request or response bodies:
// they carry users' env vars (secrets) and Dockerfile texts.
func logRPC(method string, err error, d time.Duration) {
	// Reflection is tooling (grpcurl asks for the schema before every call),
	// not platform traffic: logging it doubles the journal for nothing.
	if strings.HasPrefix(method, "/grpc.reflection.") {
		return
	}

	code := status.Code(err)
	if code == codes.OK {
		slog.Info("rpc",
			"method", method,
			"code", code.String(),
			"duration", d,
		)
		return
	}

	slog.Warn("rpc",
		"method", method,
		"code", code.String(),
		"duration", d,
		"err", err,
	)
}
