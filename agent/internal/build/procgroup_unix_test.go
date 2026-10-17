//go:build unix

package build

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
)

// fakeGit puts a `git` on PATH that hangs on `clone` together with a child
// that inherits the output pipe, and answers everything else with success.
func fakeGit(t *testing.T) (pidFile string) {
	t.Helper()
	bin := t.TempDir()
	pidFile = filepath.Join(bin, "child.pid")
	script := "#!/bin/sh\n" +
		"if [ \"$1\" = clone ]; then\n" +
		"  sleep 300 &\n" +
		"  echo $! > " + pidFile + "\n" +
		"  wait\n" +
		"fi\n"
	if err := os.WriteFile(filepath.Join(bin, "git"), []byte(script), 0o755); err != nil {
		t.Fatalf("write fake git: %v", err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	// The first exec of a fresh script can be slow (macOS scans it); keep that
	// out of the deadline under test.
	if err := exec.Command("git", "check-ref-format", "--branch", "main").Run(); err != nil {
		t.Fatalf("warm up fake git: %v", err)
	}
	return pidFile
}

func processGone(pid int) bool {
	if err := syscall.Kill(pid, 0); errors.Is(err, syscall.ESRCH) {
		return true
	}
	// A killed orphan can stay a zombie until init reaps it (containers).
	stat, err := os.ReadFile("/proc/" + strconv.Itoa(pid) + "/stat")
	return err == nil && strings.Contains(string(stat), ") Z")
}

func TestCloneDeadlineKillsProcessGroup(t *testing.T) {
	pidFile := fakeGit(t)
	src := Source{RepoURL: "https://github.com/example/repo.git", Branch: "main"}

	ctx, cancel := context.WithTimeout(context.Background(), 300*time.Millisecond)
	defer cancel()

	start := time.Now()
	_, err := Clone(ctx, src, t.TempDir())
	elapsed := time.Since(start)

	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("err = %v, want deadline exceeded", err)
	}
	if elapsed > 5*time.Second {
		t.Fatalf("Clone returned after %v, the hung process was not stopped", elapsed)
	}
	if got := userError(classifyCloneError(err, true)); got != "clone timed out (network problem?)" {
		t.Errorf("user error = %q", got)
	}

	raw, err := os.ReadFile(pidFile)
	if err != nil {
		t.Fatalf("child pid file: %v", err)
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(raw)))
	if err != nil {
		t.Fatalf("parse child pid: %v", err)
	}
	deadline := time.Now().Add(2 * time.Second)
	for !processGone(pid) {
		if time.Now().After(deadline) {
			_ = syscall.Kill(pid, syscall.SIGKILL)
			t.Fatalf("child %d of git survived the deadline", pid)
		}
		time.Sleep(20 * time.Millisecond)
	}
}
