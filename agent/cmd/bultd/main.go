package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"net"
	"os"
	"os/signal"
	"syscall"
	"time"

	agentv1 "github.com/thelol3882/bult/agent/gen/bult/agent/v1"
	"github.com/thelol3882/bult/agent/internal/docker"
	"github.com/thelol3882/bult/agent/internal/ports"
	"github.com/thelol3882/bult/agent/internal/server"
	"google.golang.org/grpc"
	"google.golang.org/grpc/reflection"
)

var version = "dev"

const shutdownTimeout = 10 * time.Second

type config struct {
	addr    string
	portMin int
	portMax int
}

func main() {
	var cfg config
	flag.StringVar(&cfg.addr, "addr", ":50051", "address to listen on")
	flag.IntVar(&cfg.portMin, "port-min", 20000, "lowest host port to allocate")
	flag.IntVar(&cfg.portMax, "port-max", 29999, "highest host port to allocate")
	showVersion := flag.Bool("version", false, "print version and exit 0")

	flag.Parse()

	if *showVersion {
		fmt.Println(version)
		return
	}

	if err := run(cfg); err != nil {
		slog.Error("bultd failed", "err", err)
		os.Exit(1)
	}
}

func run(cfg config) error {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	lis, err := net.Listen("tcp", cfg.addr)
	if err != nil {
		return err
	}
	defer lis.Close()

	alloc, err := ports.New(cfg.portMin, cfg.portMax)
	if err != nil {
		return fmt.Errorf("init port allocator: %w", err)
	}

	dc, err := docker.New(alloc)
	if err != nil {
		return err
	}
	defer dc.Close()

	if err := dc.LoadPorts(ctx); err != nil {
		return fmt.Errorf("load replica ports: %w", err)
	}

	grpcServer := grpc.NewServer()
	impl := server.NewRuntime(dc)
	agentv1.RegisterRuntimeServiceServer(grpcServer, impl)

	reflection.Register(grpcServer)

	hostname, err := os.Hostname()
	if err != nil {
		hostname = "unknown"
	}
	slog.Info("listening", "addr", cfg.addr, "version", version, "hostname", hostname)

	serveErr := make(chan error, 1)
	go func() {
		serveErr <- grpcServer.Serve(lis)
	}()

	select {
	case err := <-serveErr:
		return fmt.Errorf("serve: %w", err)
	case <-ctx.Done():
		slog.Info("shutting down")
	}

	stopped := make(chan struct{})
	go func() {
		grpcServer.GracefulStop()
		close(stopped)
	}()

	t := time.NewTimer(shutdownTimeout)
	defer t.Stop()

	select {
	case <-stopped:
	case <-t.C:
		slog.Warn("shutdown timed out, forcing stop")
		grpcServer.Stop()
	}

	slog.Info("stopped")
	return nil
}
