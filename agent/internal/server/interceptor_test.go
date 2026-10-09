package server

import (
	"context"
	"testing"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

func TestUnaryInterceptorPassesThrough(t *testing.T) {
	tests := []struct {
		name string
		resp any
		err  error
	}{
		{
			name: "success",
			resp: "ok",
			err:  nil,
		},
		{
			name: "not_found_error",
			resp: nil,
			err:  status.Error(codes.NotFound, "x"),
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			called := false
			handler := func(ctx context.Context, req any) (any, error) {
				called = true
				return tc.resp, tc.err
			}

			info := &grpc.UnaryServerInfo{
				FullMethod: "/svc/M",
			}

			resp, err := LoggingUnaryInterceptor(context.Background(), "req", info, handler)

			if !called {
				t.Fatalf("expected handler to be called, but was not")
			}
			if resp != tc.resp {
				t.Errorf("expected response %v, got %v", tc.resp, resp)
			}
			if status.Code(err) != status.Code(tc.err) {
				t.Errorf("expected status code %v, got %v", status.Code(tc.err), status.Code(err))
			}
		})
	}
}

func TestStreamInterceptorPassesThrough(t *testing.T) {
	expectedErr := status.Error(codes.Canceled, "client left")
	called := false
	handler := func(srv any, stream grpc.ServerStream) error {
		called = true
		return expectedErr
	}

	info := &grpc.StreamServerInfo{
		FullMethod: "/svc/S",
	}

	err := LoggingStreamInterceptor(nil, nil, info, handler)

	if !called {
		t.Fatalf("expected handler to be called, but was not")
	}
	if status.Code(err) != status.Code(expectedErr) {
		t.Errorf("expected status code %v, got %v", status.Code(expectedErr), status.Code(err))
	}
}
