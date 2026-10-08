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
	"github.com/thelol3882/bult/agent/internal/build"
	"github.com/thelol3882/bult/agent/internal/docker"
	"github.com/thelol3882/bult/agent/internal/ports"
	"github.com/thelol3882/bult/agent/internal/server"
	"google.golang.org/grpc"
	"google.golang.org/grpc/reflection"
)

var version = "dev"

const shutdownTimeout = 10 * time.Second

type config struct {
	addr     string
	portMin  int
	portMax  int
	role     string
	registry string
	dataDir  string
}

func main() {
	var cfg config
	flag.StringVar(&cfg.addr, "addr", ":50051", "address to listen on")
	flag.IntVar(&cfg.portMin, "port-min", 20000, "lowest host port to allocate")
	flag.IntVar(&cfg.portMax, "port-max", 29999, "highest host port to allocate")
	flag.StringVar(&cfg.role, "role", "runner", "agent role: runner, builder, or both")
	flag.StringVar(&cfg.registry, "registry", "", "container registry host (required for builder role)")
	flag.StringVar(&cfg.dataDir, "data-dir", "/var/lib/bult", "directory for persistent data")
	showVersion := flag.Bool("version", false, "print version and exit 0")

	flag.Parse()

	if *showVersion {
		fmt.Println(version)
		return
	}

	switch cfg.role {
	case "runner", "builder", "both":
	default:
		slog.Error("invalid --role, must be runner, builder, or both", "role", cfg.role)
		os.Exit(2)
	}

	if (cfg.role == "builder" || cfg.role == "both") && cfg.registry == "" {
		slog.Error("--registry is required when role is builder or both")
		os.Exit(2)
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

	grpcServer := grpc.NewServer()

	isRunner := cfg.role == "runner" || cfg.role == "both"
	isBuilder := cfg.role == "builder" || cfg.role == "both"

	if isRunner {
		if err := dc.LoadPorts(ctx); err != nil {
			return fmt.Errorf("load replica ports: %w", err)
		}
		impl := server.NewRuntime(dc)
		agentv1.RegisterRuntimeServiceServer(grpcServer, impl)
	}

	var mgr *build.Manager
	if isBuilder {
		store, err := build.NewStore(cfg.dataDir)
		if err != nil {
			return fmt.Errorf("init build store: %w", err)
		}
		mgr = build.NewManager(context.Background(), store, dc, cfg.registry)

		if _, err := mgr.Recover(); err != nil {
			return fmt.Errorf("recover abandoned jobs: %w", err)
		}

		builderServer := server.NewBuilder(mgr)
		agentv1.RegisterBuildServiceServer(grpcServer, builderServer)
	}

	reflection.Register(grpcServer)

	hostname, err := os.Hostname()
	if err != nil {
		hostname = "unknown"
	}
	slog.Info("listening", "addr", cfg.addr, "role", cfg.role, "version", version, "hostname", hostname)

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

	shutdownCtx, cancelShutdown := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancelShutdown()

	if mgr != nil {
		if err := mgr.Shutdown(shutdownCtx); err != nil {
			slog.Warn("manager shutdown finished with error", "err", err)
		}
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
