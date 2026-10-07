package build

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"time"

	"github.com/thelol3882/bult/agent/internal/docker"
)

var (
	ErrDeployNotFound = errors.New("deploy not found")
)

// State of a build job. Strings, so status.json stays human-readable.
type State string

const (
	StateRunning   State = "running"
	StateSucceeded State = "succeeded"
	StateFailed    State = "failed"
	StateCancelled State = "cancelled"
)

// Status is the job as persisted in <data-dir>/deploys/<deploy_id>/status.json.
type Status struct {
	DeployID   string          `json:"deploy_id"`
	AppID      string          `json:"app_id"`
	Source     Source          `json:"source"`
	State      State           `json:"state"`
	CommitSHA  string          `json:"commit_sha,omitempty"`
	Image      docker.ImageRef `json:"image,omitzero"`
	Error      string          `json:"error,omitempty"` // user-facing
	StartedAt  time.Time       `json:"started_at"`
	FinishedAt time.Time       `json:"finished_at,omitzero"`
}

// Store keeps job statuses and logs under <dataDir>/deploys.
type Store struct {
	dir string
}

// NewStore creates <dataDir>/deploys if needed.
func NewStore(dataDir string) (*Store, error) {
	dir := filepath.Join(dataDir, "deploys")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, fmt.Errorf("create deploys dir: %w", err)
	}
	return &Store{dir: dir}, nil
}

// jobDir returns <store>/<deployID>. deployID must already be validated
func (s *Store) jobDir(deployID string) string {
	return filepath.Join(s.dir, deployID)
}

// WriteStatus persists st atomically: readers see either the old or the new
// file, never a half-written one.
func (s *Store) WriteStatus(st Status) error {
	dir := s.jobDir(st.DeployID)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return fmt.Errorf("create job dir %q: %w", dir, err)
	}

	data, err := json.MarshalIndent(st, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal status for deploy %q: %w", st.DeployID, err)
	}

	data = append(data, '\n')

	targetPath := filepath.Join(dir, "status.json")
	if err := writeFileAtomic(targetPath, data); err != nil {
		return fmt.Errorf("write atomic status %q: %w", targetPath, err)
	}

	return nil
}

// ReadStatus loads status.json of a job. Missing → ErrDeployNotFound.
func (s *Store) ReadStatus(deployID string) (Status, error) {
	path := filepath.Join(s.jobDir(deployID), "status.json")

	data, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return Status{}, fmt.Errorf("%w: %s", ErrDeployNotFound, deployID)
		}
		return Status{}, fmt.Errorf("read status %q: %w", path, err)
	}

	var st Status
	if err := json.Unmarshal(data, &st); err != nil {
		return Status{}, fmt.Errorf("decode status %q: %w", path, err)
	}

	return st, nil
}

// OpenLog opens build.log of a job for appending (created if missing).
// The caller closes it.
func (s *Store) OpenLog(deployID string) (*os.File, error) {
	dir := s.jobDir(deployID)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, fmt.Errorf("create job dir %q: %w", dir, err)
	}

	logPath := filepath.Join(dir, "build.log")
	f, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return nil, fmt.Errorf("open log file %q: %w", logPath, err)
	}

	return f, nil
}

// writeFileAtomic replaces path with data via temp file + fsync + rename.
func writeFileAtomic(path string, data []byte) (err error) {
	dir := filepath.Dir(path)

	f, err := os.CreateTemp(dir, ".tmp-*")
	if err != nil {
		return fmt.Errorf("create temp file: %w", err)
	}

	tmpName := f.Name()

	defer func() {
		if err != nil {
			_ = f.Close()
			_ = os.Remove(tmpName)
		}
	}()

	if _, err = f.Write(data); err != nil {
		return fmt.Errorf("write data: %w", err)
	}

	if err = f.Sync(); err != nil {
		return fmt.Errorf("sync temp file: %w", err)
	}

	if err = f.Close(); err != nil {
		return fmt.Errorf("close temp file: %w", err)
	}

	if err = os.Rename(tmpName, path); err != nil {
		return fmt.Errorf("rename to target %q: %w", path, err)
	}

	return nil
}
