package build

import (
	"archive/tar"
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
	"time"
)

func TestValidateURL(t *testing.T) {
	cases := []struct {
		name    string
		url     string
		wantErr bool
	}{
		{name: "ok https", url: "https://github.com/octocat/Hello-World", wantErr: false},
		{name: "file scheme", url: "file:///etc", wantErr: true},
		{name: "http scheme", url: "http://github.com/o/r", wantErr: true},
		{name: "ssh scheme", url: "ssh://git@github.com/o/r", wantErr: true},
		{name: "git scp-like", url: "git@github.com:o/r", wantErr: true},
		{name: "option injection", url: "-oops", wantErr: true},
		{name: "embedded credentials", url: "https://user:token@github.com/o/r", wantErr: true},
		{name: "no host", url: "https:///no-host", wantErr: true},
		{name: "empty url", url: "", wantErr: true},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			src := Source{RepoURL: tc.url, Branch: "main"}
			err := src.Validate(context.Background())

			if !tc.wantErr {
				if err != nil {
					t.Fatalf("unexpected error for %q: %v", tc.url, err)
				}
				return
			}

			if err == nil {
				t.Fatalf("expected error for %q, got nil", tc.url)
			}
			if !errors.Is(err, ErrInvalidRepoURL) {
				t.Fatalf("expected ErrInvalidRepoURL for %q, got: %v", tc.url, err)
			}
		})
	}
}

func TestValidateBranch(t *testing.T) {
	cases := []struct {
		name    string
		branch  string
		wantErr bool
	}{
		{name: "main", branch: "main", wantErr: false},
		{name: "nested branch", branch: "feature/x", wantErr: false},
		{name: "empty branch", branch: "", wantErr: true},
		{name: "starts with dash", branch: "-oops", wantErr: true},
		{name: "double dot", branch: "a..b", wantErr: true},
		{name: "space", branch: "with space", wantErr: true},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			src := Source{RepoURL: "https://github.com/octocat/Hello-World", Branch: tc.branch}
			err := src.Validate(context.Background())

			if !tc.wantErr {
				if err != nil {
					t.Fatalf("unexpected error for branch %q: %v", tc.branch, err)
				}
				return
			}

			if err == nil {
				t.Fatalf("expected error for branch %q, got nil", tc.branch)
			}
			if !errors.Is(err, ErrInvalidBranch) {
				t.Fatalf("expected ErrInvalidBranch for %q, got: %v", tc.branch, err)
			}
		})
	}
}

func TestContextExcludesAndSymlinks(t *testing.T) {
	dir := t.TempDir()

	if err := os.WriteFile(filepath.Join(dir, "app.py"), []byte("print('hello')"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, ".env"), []byte("SECRET=123"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, ".dockerignore"), []byte(".env\n"), 0644); err != nil {
		t.Fatal(err)
	}

	gitDir := filepath.Join(dir, ".git")
	if err := os.MkdirAll(gitDir, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(gitDir, "HEAD"), []byte("ref: refs/heads/main"), 0644); err != nil {
		t.Fatal(err)
	}

	if err := os.Symlink("/etc/hosts", filepath.Join(dir, "hosts-link")); err != nil {
		t.Fatal(err)
	}

	rc, err := Context(dir)
	if err != nil {
		t.Fatalf("Context failed: %v", err)
	}
	defer rc.Close()

	headers := make(map[string]byte)
	tr := tar.NewReader(rc)
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatalf("tar reading error: %v", err)
		}
		headers[filepath.Clean(hdr.Name)] = hdr.Typeflag
	}

	t.Logf("collected tar entries: %#v", headers)

	if _, ok := headers["app.py"]; !ok {
		t.Errorf("expected app.py in tar archive, found keys: %v", headers)
	}

	if _, ok := headers[".env"]; ok {
		t.Errorf(".env should be excluded by .dockerignore, but found in archive")
	}
	for name := range headers {
		if strings.HasPrefix(name, ".git") {
			t.Errorf(".git entry %q should be excluded unconditionally, but found in archive", name)
		}
	}

	flag, ok := headers["hosts-link"]
	if !ok {
		t.Fatalf("expected hosts-link symlink in archive")
	}
	if flag != tar.TypeSymlink {
		t.Errorf("hosts-link type = %v, want tar.TypeSymlink (%v)", flag, tar.TypeSymlink)
	}
}

func TestCloneRejectsInvalidSourceWithoutGit(t *testing.T) {
	parent := t.TempDir()

	_, err := Clone(context.Background(), Source{RepoURL: "file:///etc", Branch: "main"}, parent)
	if !errors.Is(err, ErrInvalidRepoURL) {
		t.Fatalf("expected ErrInvalidRepoURL, got: %v", err)
	}

	entries, err := os.ReadDir(parent)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 0 {
		t.Fatalf("expected parent dir to remain empty, found %d entries", len(entries))
	}
}

func TestClone(t *testing.T) {
	if os.Getenv("BULT_NET_TESTS") == "" {
		t.Skip("skipping network test; set BULT_NET_TESTS=1 to run")
	}

	parent := t.TempDir()
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	src := Source{
		RepoURL: "https://github.com/octocat/Hello-World",
		Branch:  "master",
	}

	checkout, err := Clone(ctx, src, parent)
	if err != nil {
		t.Fatalf("Clone failed: %v", err)
	}

	hexPattern := regexp.MustCompile(`^[0-9a-f]{40}$`)
	if !hexPattern.MatchString(checkout.Commit) {
		t.Errorf("invalid commit SHA: %q", checkout.Commit)
	}

	entries, err := os.ReadDir(checkout.Dir)
	if err != nil {
		t.Fatal(err)
	}
	hasReadme := false
	for _, entry := range entries {
		if strings.HasPrefix(strings.ToUpper(entry.Name()), "README") {
			hasReadme = true
			break
		}
	}
	if !hasReadme {
		t.Errorf("README not found in cloned directory %s", checkout.Dir)
	}

	if err := checkout.Remove(); err != nil {
		t.Fatalf("checkout.Remove failed: %v", err)
	}

	remaining, err := os.ReadDir(parent)
	if err != nil {
		t.Fatal(err)
	}
	if len(remaining) != 0 {
		t.Errorf("parent directory has leftover files: %v", remaining)
	}
}

func TestCloneMissingRepoFailsFast(t *testing.T) {
	if os.Getenv("BULT_NET_TESTS") == "" {
		t.Skip("skipping network test; set BULT_NET_TESTS=1 to run")
	}

	parent := t.TempDir()
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	src := Source{
		RepoURL: "https://github.com/octocat/definitely-not-a-repo-bult",
		Branch:  "main",
	}

	start := time.Now()
	_, err := Clone(ctx, src, parent)
	elapsed := time.Since(start)

	if err == nil {
		t.Fatal("expected clone of missing repo to fail, got nil")
	}

	if elapsed > 15*time.Second {
		t.Errorf("clone took %s; expected fast terminal rejection under 15s", elapsed)
	}

	if !strings.Contains(err.Error(), "terminal prompts disabled") {
		t.Errorf("expected 'terminal prompts disabled' in error, got: %v", err)
	}

	remaining, err := os.ReadDir(parent)
	if err != nil {
		t.Fatal(err)
	}
	if len(remaining) != 0 {
		t.Errorf("parent dir should be empty after failure, found %d items", len(remaining))
	}
}
