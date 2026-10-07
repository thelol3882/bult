package build

import (
	"errors"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/thelol3882/bult/agent/internal/docker"
)

func TestStatusRoundTrip(t *testing.T) {
	s, err := NewStore(t.TempDir())
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}

	started := time.Now().Truncate(time.Millisecond)
	finished := started.Add(2 * time.Minute)

	want := Status{
		DeployID: "d-1",
		AppID:    "app-1",
		Source: Source{
			RepoURL: "https://github.com/example/repo.git",
			Branch:  "main",
		},
		State:     StateSucceeded,
		CommitSHA: "abc1234def5678",
		Image: docker.ImageRef{
			Repository: "registry.local:5050/my-app",
			Digest:     "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
		},
		Error:      "",
		StartedAt:  started,
		FinishedAt: finished,
	}

	if err := s.WriteStatus(want); err != nil {
		t.Fatalf("WriteStatus: %v", err)
	}

	got, err := s.ReadStatus(want.DeployID)
	if err != nil {
		t.Fatalf("ReadStatus: %v", err)
	}

	if got.DeployID != want.DeployID {
		t.Errorf("DeployID = %q, want %q", got.DeployID, want.DeployID)
	}
	if got.AppID != want.AppID {
		t.Errorf("AppID = %q, want %q", got.AppID, want.AppID)
	}
	if got.Source != want.Source {
		t.Errorf("Source = %+v, want %+v", got.Source, want.Source)
	}
	if got.State != want.State {
		t.Errorf("State = %v, want %v", got.State, want.State)
	}
	if got.CommitSHA != want.CommitSHA {
		t.Errorf("CommitSHA = %q, want %q", got.CommitSHA, want.CommitSHA)
	}
	if got.Image != want.Image {
		t.Errorf("Image = %+v, want %+v", got.Image, want.Image)
	}
	if got.Error != want.Error {
		t.Errorf("Error = %q, want %q", got.Error, want.Error)
	}
	if !got.StartedAt.Equal(want.StartedAt) {
		t.Errorf("StartedAt = %v, want %v", got.StartedAt, want.StartedAt)
	}
	if !got.FinishedAt.Equal(want.FinishedAt) {
		t.Errorf("FinishedAt = %v, want %v", got.FinishedAt, want.FinishedAt)
	}
}

func TestReadStatusNotFound(t *testing.T) {
	s, err := NewStore(t.TempDir())
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}

	_, err = s.ReadStatus("nope")
	if !errors.Is(err, ErrDeployNotFound) {
		t.Fatalf("expected ErrDeployNotFound, got: %v", err)
	}
}

func TestWriteStatusLeavesNoTempFiles(t *testing.T) {
	s, err := NewStore(t.TempDir())
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}

	st := Status{
		DeployID:  "d-1",
		AppID:     "app-1",
		State:     StateRunning,
		StartedAt: time.Now(),
	}

	if err := s.WriteStatus(st); err != nil {
		t.Fatalf("first WriteStatus: %v", err)
	}

	st.State = StateSucceeded
	st.FinishedAt = time.Now()
	if err := s.WriteStatus(st); err != nil {
		t.Fatalf("second WriteStatus: %v", err)
	}

	entries, err := os.ReadDir(s.jobDir(st.DeployID))
	if err != nil {
		t.Fatalf("ReadDir: %v", err)
	}

	if len(entries) != 1 {
		t.Fatalf("expected 1 file in job dir, got %d", len(entries))
	}

	if entries[0].Name() != "status.json" {
		t.Errorf("expected file 'status.json', got %q", entries[0].Name())
	}
}

func TestValidateIDs(t *testing.T) {
	t.Run("Valid IDs", func(t *testing.T) {
		if err := ValidateDeployID("d-1"); err != nil {
			t.Errorf("expected valid deploy_id, got error: %v", err)
		}
		if err := ValidateAppID("app-1"); err != nil {
			t.Errorf("expected valid app_id, got error: %v", err)
		}
	})

	t.Run("Invalid Deploy IDs", func(t *testing.T) {
		invalidDeployIDs := []string{
			"",
			"..", // filepath.Join(store, "..") escapes the deploys dir
			".",  // the deploys dir itself
			"../../etc",
			"a/b",
			strings.Repeat("a", 65),
		}

		for _, id := range invalidDeployIDs {
			err := ValidateDeployID(id)
			if !errors.Is(err, ErrInvalidDeployID) {
				t.Errorf("ValidateDeployID(%q) = %v, want %v", id, err, ErrInvalidDeployID)
			}
		}
	})

	t.Run("Invalid App IDs", func(t *testing.T) {
		invalidAppIDs := []string{
			"",
			"App",
			"a_b",
			"a/b",
		}

		for _, id := range invalidAppIDs {
			err := ValidateAppID(id)
			if !errors.Is(err, ErrInvalidAppID) {
				t.Errorf("ValidateAppID(%q) = %v, want %v", id, err, ErrInvalidAppID)
			}
		}
	})
}
