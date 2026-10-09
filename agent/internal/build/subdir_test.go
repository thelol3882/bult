package build

import (
	"archive/tar"
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"github.com/thelol3882/bult/agent/internal/docker"
)

func TestValidateSubdir(t *testing.T) {
	tests := []struct {
		subdir  string
		wantErr bool
	}{
		// Valid cases
		{subdir: "", wantErr: false},
		{subdir: "app", wantErr: false},
		{subdir: "examples/fastapi-hello", wantErr: false},

		// Rejected cases
		{subdir: "/etc", wantErr: true},
		{subdir: "..", wantErr: true},
		{subdir: "../x", wantErr: true},
		{subdir: "a/../b", wantErr: true},
		{subdir: "./a", wantErr: true},
		{subdir: "a//b", wantErr: true},
		{subdir: "a/", wantErr: true},
	}

	for _, tc := range tests {
		tc := tc
		t.Run(tc.subdir, func(t *testing.T) {
			src := Source{
				RepoURL: "https://github.com/example/repo.git",
				Branch:  "main",
				Subdir:  tc.subdir,
			}

			err := src.Validate(context.Background())
			if tc.wantErr {
				if err == nil {
					t.Fatalf("expected error for subdir %q, got nil", tc.subdir)
				}
				if !errors.Is(err, ErrInvalidSubdir) {
					t.Fatalf("expected ErrInvalidSubdir for %q, got: %v", tc.subdir, err)
				}
			} else {
				if err != nil {
					t.Fatalf("unexpected error for subdir %q: %v", tc.subdir, err)
				}
			}
		})
	}
}

func TestResolveSubdir(t *testing.T) {
	checkout := t.TempDir()
	appDir := filepath.Join(checkout, "app")
	if err := os.MkdirAll(appDir, 0o755); err != nil {
		t.Fatalf("failed to create app dir: %v", err)
	}

	filePath := filepath.Join(checkout, "file.txt")
	if err := os.WriteFile(filePath, []byte("hello"), 0o644); err != nil {
		t.Fatalf("failed to create file.txt: %v", err)
	}

	resolvedCheckout, err := filepath.EvalSymlinks(checkout)
	if err != nil {
		t.Fatalf("failed to eval symlink on checkout: %v", err)
	}
	resolvedApp, err := filepath.EvalSymlinks(appDir)
	if err != nil {
		t.Fatalf("failed to eval symlink on appDir: %v", err)
	}

	got, err := resolveSubdir(checkout, "")
	if err != nil {
		t.Fatalf("resolveSubdir(\"\") failed: %v", err)
	}
	if got != resolvedCheckout {
		t.Errorf("expected %q, got %q", resolvedCheckout, got)
	}

	got, err = resolveSubdir(checkout, "app")
	if err != nil {
		t.Fatalf("resolveSubdir(\"app\") failed: %v", err)
	}
	if got != resolvedApp {
		t.Errorf("expected %q, got %q", resolvedApp, got)
	}

	_, err = resolveSubdir(checkout, "missing")
	if !errors.Is(err, errBadSubdir) {
		t.Errorf("expected errBadSubdir for missing directory, got: %v", err)
	}

	_, err = resolveSubdir(checkout, "file.txt")
	if !errors.Is(err, errBadSubdir) {
		t.Errorf("expected errBadSubdir for regular file, got: %v", err)
	}
}

func TestResolveSubdirRejectsSymlinkEscape(t *testing.T) {
	outside := t.TempDir()
	checkout := t.TempDir()

	symlinkPath := filepath.Join(checkout, "app")
	if err := os.Symlink(outside, symlinkPath); err != nil {
		t.Fatalf("failed to create symlink: %v", err)
	}

	_, err := resolveSubdir(checkout, "app")
	if !errors.Is(err, errBadSubdir) {
		t.Fatalf("expected errBadSubdir for symlink escaping checkout, got: %v", err)
	}
}

type tarRecordingBuilder struct {
	mu         sync.Mutex
	entryNames []string
}

func (b *tarRecordingBuilder) BuildImage(ctx context.Context, buildContext io.Reader, opts docker.BuildOptions, log io.Writer) error {
	tr := tar.NewReader(buildContext)
	var names []string
	for {
		header, err := tr.Next()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return err
		}
		names = append(names, filepath.ToSlash(header.Name))
	}

	b.mu.Lock()
	b.entryNames = names
	b.mu.Unlock()
	return nil
}

func (b *tarRecordingBuilder) PushImage(ctx context.Context, tag string) (string, error) {
	return "sha256:dummy", nil
}

func TestBuildUsesSubdirAsContextRoot(t *testing.T) {
	storeDir := t.TempDir()
	store, err := NewStore(storeDir)
	if err != nil {
		t.Fatalf("NewStore failed: %v", err)
	}

	builder := &tarRecordingBuilder{}
	mgr := NewManager(context.Background(), store, builder, "registry.local:5000")

	mgr.clone = func(ctx context.Context, src Source, parentDir string) (Checkout, error) {
		checkoutDir := t.TempDir()
		svcDir := filepath.Join(checkoutDir, "svc")
		if err := os.MkdirAll(svcDir, 0o755); err != nil {
			return Checkout{}, err
		}

		if err := os.WriteFile(filepath.Join(svcDir, "Dockerfile"), []byte("FROM alpine\n"), 0o644); err != nil {
			return Checkout{}, err
		}
		if err := os.WriteFile(filepath.Join(svcDir, ".dockerignore"), []byte(".env\n"), 0o644); err != nil {
			return Checkout{}, err
		}
		if err := os.WriteFile(filepath.Join(svcDir, ".env"), []byte("SECRET=123\n"), 0o644); err != nil {
			return Checkout{}, err
		}

		return Checkout{
			Dir:    checkoutDir,
			Commit: "c0ffee1",
		}, nil
	}

	spec := Spec{
		DeployID: "deploy-subdir-test",
		AppID:    "test-app",
		Source: Source{
			RepoURL: "https://github.com/example/repo.git",
			Branch:  "main",
			Subdir:  "svc",
		},
		Dockerfile: "",
	}

	_, err = mgr.Start(context.Background(), spec)
	if err != nil {
		t.Fatalf("Start failed: %v", err)
	}

	var finalSt Status
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		st, err := mgr.Get(spec.DeployID)
		if err == nil && st.State != StateRunning {
			finalSt = st
			break
		}
		time.Sleep(20 * time.Millisecond)
	}

	if finalSt.State != StateSucceeded {
		t.Fatalf("expected state %v, got %v (err: %s)", StateSucceeded, finalSt.State, finalSt.Error)
	}

	builder.mu.Lock()
	entries := builder.entryNames
	builder.mu.Unlock()

	hasRootDockerfile := false
	hasEnv := false
	hasSvcPrefix := false

	for _, name := range entries {
		if name == "Dockerfile" {
			hasRootDockerfile = true
		}
		if name == ".env" {
			hasEnv = true
		}
		if name == "svc/Dockerfile" || filepath.ToSlash(name) == "svc" {
			hasSvcPrefix = true
		}
	}

	if !hasRootDockerfile {
		t.Errorf("expected 'Dockerfile' at tar root, but did not find it; tar entries: %v", entries)
	}
	if hasSvcPrefix {
		t.Errorf("expected build context to have 'svc' as root, but found paths with 'svc/' prefix: %v", entries)
	}
	if hasEnv {
		t.Errorf("expected .env to be ignored according to .dockerignore, but found it in tar: %v", entries)
	}
}
