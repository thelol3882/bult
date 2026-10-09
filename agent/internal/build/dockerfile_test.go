package build

import (
	"archive/tar"
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestPrepareDockerfileProvided(t *testing.T) {
	dir := t.TempDir()

	userDockerfile := filepath.Join(dir, "Dockerfile")
	if err := os.WriteFile(userDockerfile, []byte("FROM user"), 0o644); err != nil {
		t.Fatalf("failed to write repo Dockerfile: %v", err)
	}

	gotPath, err := prepareDockerfile(dir, "FROM preset")
	if err != nil {
		t.Fatalf("prepareDockerfile failed: %v", err)
	}

	if gotPath != providedDockerfilePath {
		t.Errorf("expected path %q, got %q", providedDockerfilePath, gotPath)
	}

	presetContent, err := os.ReadFile(filepath.Join(dir, filepath.FromSlash(providedDockerfilePath)))
	if err != nil {
		t.Fatalf("failed to read written preset Dockerfile: %v", err)
	}
	if string(presetContent) != "FROM preset" {
		t.Errorf("expected preset content %q, got %q", "FROM preset", string(presetContent))
	}

	originalContent, err := os.ReadFile(userDockerfile)
	if err != nil {
		t.Fatalf("failed to read original user Dockerfile: %v", err)
	}
	if string(originalContent) != "FROM user" {
		t.Errorf("expected user Dockerfile to remain untouched, got %q", string(originalContent))
	}
}

func TestPrepareDockerfileFromRepo(t *testing.T) {
	dir := t.TempDir()

	repoDockerfile := filepath.Join(dir, "Dockerfile")
	if err := os.WriteFile(repoDockerfile, []byte("FROM repo"), 0o644); err != nil {
		t.Fatalf("failed to write repo Dockerfile: %v", err)
	}

	gotPath, err := prepareDockerfile(dir, "")
	if err != nil {
		t.Fatalf("prepareDockerfile failed: %v", err)
	}

	if gotPath != "Dockerfile" {
		t.Errorf("expected path %q, got %q", "Dockerfile", gotPath)
	}

	if _, err := os.Stat(filepath.Join(dir, ".bult")); !errors.Is(err, os.ErrNotExist) {
		t.Errorf("expected .bult directory not to exist, got err: %v", err)
	}
}

func TestPrepareDockerfileMissing(t *testing.T) {
	dir := t.TempDir()

	_, err := prepareDockerfile(dir, "")
	if !errors.Is(err, errNoDockerfile) {
		t.Fatalf("expected errNoDockerfile, got %v", err)
	}
}

func TestContextKeepsProvidedDockerfile(t *testing.T) {
	dir := t.TempDir()

	if err := os.WriteFile(filepath.Join(dir, ".dockerignore"), []byte("*\n"), 0o644); err != nil {
		t.Fatalf("failed to write .dockerignore: %v", err)
	}

	if err := os.WriteFile(filepath.Join(dir, "extra.txt"), []byte("ignored"), 0o644); err != nil {
		t.Fatalf("failed to write extra file: %v", err)
	}

	if _, err := prepareDockerfile(dir, "FROM x"); err != nil {
		t.Fatalf("prepareDockerfile failed: %v", err)
	}

	rc, err := Context(dir)
	if err != nil {
		t.Fatalf("Context failed: %v", err)
	}
	defer rc.Close()

	tr := tar.NewReader(rc)
	foundProvidedDockerfile := false
	foundExtra := false

	for {
		header, err := tr.Next()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			t.Fatalf("tar read error: %v", err)
		}

		cleanPath := filepath.ToSlash(header.Name)
		if cleanPath == providedDockerfilePath {
			foundProvidedDockerfile = true
		}
		if cleanPath == "extra.txt" {
			foundExtra = true
		}
	}

	if !foundProvidedDockerfile {
		t.Errorf("expected %s in build context tar, but it was omitted", providedDockerfilePath)
	}
	if foundExtra {
		t.Errorf("expected extra.txt to be omitted due to '*', but it was present")
	}
}

func TestBuildWithoutDockerfileFails(t *testing.T) {
	tmpDir := t.TempDir()
	store, err := NewStore(tmpDir)
	if err != nil {
		t.Fatalf("NewStore failed: %v", err)
	}

	mgr := NewManager(context.Background(), store, &fakeBuilder{}, "registry.local:5000")
	shutdownOnCleanup(t, mgr)
	mgr.clone = func(ctx context.Context, src Source, parentDir string) (Checkout, error) {
		checkoutDir := t.TempDir()
		return Checkout{
			Dir:    checkoutDir,
			Commit: "abc1234",
		}, nil
	}

	spec := Spec{
		DeployID:   "deploy-nodockerfile",
		AppID:      "test-app",
		Source:     Source{RepoURL: "https://github.com/example/repo.git", Branch: "main"},
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

	if finalSt.State != StateFailed {
		t.Fatalf("expected state %v, got %v", StateFailed, finalSt.State)
	}

	if !strings.Contains(finalSt.Error, "preset") {
		t.Errorf("expected error message to contain preset hint, got: %q", finalSt.Error)
	}
}

func TestStartDifferentDockerfileMismatch(t *testing.T) {
	tmpDir := t.TempDir()
	store, err := NewStore(tmpDir)
	if err != nil {
		t.Fatalf("NewStore failed: %v", err)
	}

	mgr := NewManager(context.Background(), store, &fakeBuilder{}, "registry.local:5000")
	shutdownOnCleanup(t, mgr)
	mgr.clone = func(ctx context.Context, src Source, parentDir string) (Checkout, error) {
		checkoutDir := t.TempDir()
		return Checkout{
			Dir:    checkoutDir,
			Commit: "abc1234",
		}, nil
	}

	specA := Spec{
		DeployID:   "deploy-mismatch",
		AppID:      "test-app",
		Source:     Source{RepoURL: "https://github.com/example/repo.git", Branch: "main"},
		Dockerfile: "FROM alpine",
	}

	if _, err := mgr.Start(context.Background(), specA); err != nil {
		t.Fatalf("first Start failed: %v", err)
	}

	specB := specA
	specB.Dockerfile = "FROM ubuntu"

	_, err = mgr.Start(context.Background(), specB)
	if !errors.Is(err, ErrDeploySpecMismatch) {
		t.Fatalf("expected ErrDeploySpecMismatch, got: %v", err)
	}
}
