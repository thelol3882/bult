package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	agentv1 "github.com/thelol3882/bult/agent/gen/bult/agent/v1"
	"github.com/thelol3882/bult/agent/internal/build"
	"github.com/thelol3882/bult/agent/internal/docker"
	"github.com/thelol3882/bult/agent/internal/heartbeat"
	"github.com/thelol3882/bult/agent/internal/metrics"
	"github.com/thelol3882/bult/agent/internal/ports"
	"github.com/thelol3882/bult/agent/internal/server"
	"google.golang.org/grpc"
	"google.golang.org/grpc/keepalive"
	"google.golang.org/grpc/reflection"
)

var version = "dev"

const (
	shutdownTimeout = 10 * time.Second

	// nodeTokenEnv holds the node's secret; it is read from the environment so it
	// never shows up in the process list.
	nodeTokenEnv = "BULTD_NODE_TOKEN"
)

type config struct {
	addr     string
	portMin  int
	portMax  int
	role     string
	registry string
	dataDir  string

	controlPlaneURL string
	nodeName        string
	advertiseAddr   string
	nodeToken       string

	cloneTimeout time.Duration
	buildTimeout time.Duration
}

func main() {
	setupLogging()

	var cfg config
	flag.StringVar(&cfg.addr, "addr", ":50051", "address to listen on")
	flag.IntVar(&cfg.portMin, "port-min", 20000, "lowest host port to allocate")
	flag.IntVar(&cfg.portMax, "port-max", 29999, "highest host port to allocate")
	flag.StringVar(&cfg.role, "role", "runner", "agent role: runner, builder, or both")
	flag.StringVar(&cfg.registry, "registry", "", "container registry host (required for builder role)")
	flag.StringVar(&cfg.dataDir, "data-dir", "/var/lib/bult", "directory for persistent data")
	flag.DurationVar(&cfg.cloneTimeout, "clone-timeout", build.DefaultCloneTimeout, "deadline for cloning a repository")
	flag.DurationVar(&cfg.buildTimeout, "build-timeout", build.DefaultBuildTimeout, "deadline for building and pushing an image")
	flag.StringVar(&cfg.controlPlaneURL, "control-plane-url", "", "control plane base URL for heartbeats (empty disables them)")
	flag.StringVar(&cfg.nodeName, "node-name", "", "node name in the control plane (default: hostname)")
	flag.StringVar(&cfg.advertiseAddr, "advertise-addr", "", "gRPC host:port the control plane should dial (required with --control-plane-url)")
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

	if cfg.cloneTimeout <= 0 || cfg.buildTimeout <= 0 {
		slog.Error("--clone-timeout and --build-timeout must be positive")
		os.Exit(2)
	}

	cfg.nodeToken = os.Getenv(nodeTokenEnv)
	if cfg.controlPlaneURL != "" && cfg.advertiseAddr == "" {
		slog.Error("--advertise-addr is required with --control-plane-url")
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

	grpcServer := grpc.NewServer(
		grpc.ChainUnaryInterceptor(server.LoggingUnaryInterceptor),
		grpc.ChainStreamInterceptor(server.LoggingStreamInterceptor),
		grpc.KeepaliveEnforcementPolicy(keepalive.EnforcementPolicy{
			MinTime:             20 * time.Second,
			PermitWithoutStream: true,
		}),
		grpc.KeepaliveParams(keepalive.ServerParameters{
			Time:    60 * time.Second,
			Timeout: 10 * time.Second,
		}),
	)

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

		mgr.SetTimeouts(cfg.cloneTimeout, cfg.buildTimeout)

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

	// ctx is cancelled by the signal, which also stops the heartbeat loop.
	heartbeatDone := startHeartbeat(ctx, cfg, hostname, dc)

	select {
	case err := <-serveErr:
		return fmt.Errorf("serve: %w", err)
	case <-ctx.Done():
		slog.Info("shutting down")
	}

	shutdownCtx, cancelShutdown := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancelShutdown()

	<-heartbeatDone

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

// startHeartbeat starts the heartbeat loop and returns a channel that is closed
// when the loop has stopped (at once if heartbeats are disabled).
func startHeartbeat(ctx context.Context, cfg config, hostname string, dc *docker.Client) <-chan struct{} {
	done := make(chan struct{})

	if cfg.controlPlaneURL == "" || cfg.nodeToken == "" {
		slog.Info("heartbeat disabled: set --control-plane-url and " + nodeTokenEnv + " to register this node")
		close(done)
		return done
	}

	name := cfg.nodeName
	if name == "" {
		name = hostname
	}
	hb := heartbeat.Config{
		URL:      cfg.controlPlaneURL,
		Token:    cfg.nodeToken,
		Name:     name,
		Address:  cfg.advertiseAddr,
		Role:     cfg.role,
		Version:  version,
		Capacity: heartbeat.DetectCapacity(),
	}
	if cfg.role == "runner" || cfg.role == "both" {
		hb.Sampler = metrics.NewCollector(dc, metrics.DefaultTimeout)
	}
	slog.Info("heartbeat enabled", "control_plane", cfg.controlPlaneURL, "node", name, "advertise", cfg.advertiseAddr)

	go func() {
		defer close(done)
		heartbeat.Run(ctx, hb, &http.Client{Timeout: heartbeat.DefaultTimeout})
	}()
	return done
}

// setupLogging makes slog the process logger. Under systemd the journal
// already stamps every line with the time, so the handler drops its own;
// run by hand (no journal) it keeps the time.
func setupLogging() {
	opts := &slog.HandlerOptions{}
	// systemd sets JOURNAL_STREAM when stdout/stderr go to the journal.
	if os.Getenv("JOURNAL_STREAM") != "" {
		opts.ReplaceAttr = func(groups []string, a slog.Attr) slog.Attr {
			if len(groups) == 0 && a.Key == slog.TimeKey {
				return slog.Attr{} // an empty Attr is dropped from the output
			}
			return a
		}
	}
	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stdout, opts)))
}
