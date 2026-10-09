package build

import (
	"archive/tar"
	"context"
	"errors"
	"io"
	"sync"
	"testing"

	"github.com/thelol3882/bult/agent/internal/docker"
)

// recordingBuilder captures what actually reached "Docker": the Dockerfile
// path from the build options and that file's content inside the tar context.
type recordingBuilder struct {
	mu         sync.Mutex
	path       string
	dockerfile string
	builds     int
}

func (b *recordingBuilder) BuildImage(ctx context.Context, buildContext io.Reader, opts docker.BuildOptions, log io.Writer) error {
	var content string
	tr := tar.NewReader(buildContext)
	for {
		hdr, err := tr.Next() // Next skips the unread rest of the previous entry: the tar is drained
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return err
		}
		if hdr.Name == opts.Dockerfile {
			data, err := io.ReadAll(tr)
			if err != nil {
				return err
			}
			content = string(data)
		}
	}

	b.mu.Lock()
	defer b.mu.Unlock()
	b.path, b.dockerfile = opts.Dockerfile, content
	b.builds++
	return nil
}

func (b *recordingBuilder) PushImage(ctx context.Context, tag string) (string, error) {
	return "sha256:feed", nil
}

// TestProvidedDockerfileReachesBuild follows the preset text end to end:
// request → Start → status → run → prepareDockerfile → tar context → builder.
// A unit test of prepareDockerfile alone cannot see a break in this chain.
func TestProvidedDockerfileReachesBuild(t *testing.T) {
	rb := &recordingBuilder{}
	store, err := NewStore(t.TempDir())
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	m := NewManager(context.Background(), store, rb, "registry.test:5000")
	m.clone = fakeClone // the repository has its OWN Dockerfile: the preset must still win
	shutdownOnCleanup(t, m)

	spec := Spec{
		DeployID:   "d-preset",
		AppID:      "app-1",
		Source:     Source{RepoURL: "https://github.com/example/repo.git", Branch: "main"},
		Dockerfile: "FROM preset\n",
	}

	// (a) the provided text reaches the build.
	if _, err := m.Start(context.Background(), spec); err != nil {
		t.Fatalf("Start: %v", err)
	}
	st := waitState(t, m, spec.DeployID)
	if st.State != StateSucceeded {
		t.Fatalf("state = %v (error %q), want %v", st.State, st.Error, StateSucceeded)
	}

	rb.mu.Lock()
	path, got, builds := rb.path, rb.dockerfile, rb.builds
	rb.mu.Unlock()
	if path != providedDockerfilePath {
		t.Errorf("Dockerfile path = %q, want %q", path, providedDockerfilePath)
	}
	if got != spec.Dockerfile {
		t.Errorf("Dockerfile in context = %q, want %q", got, spec.Dockerfile)
	}

	// (b) an identical repeat is the same job, not a mismatch.
	if _, err := m.Start(context.Background(), spec); err != nil {
		t.Fatalf("repeated identical Start: %v", err)
	}
	if builds != 1 {
		t.Errorf("builds = %d, want 1", builds)
	}
}
