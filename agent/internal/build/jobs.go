package build

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"regexp"
	"sync"
	"time"

	"github.com/thelol3882/bult/agent/internal/docker"
)

var (
	// ErrInvalidDeployID / ErrInvalidAppID: both end up in paths and image names.
	ErrInvalidDeployID = errors.New("invalid deploy id")
	ErrInvalidAppID    = errors.New("invalid app id")
	// ErrDeploySpecMismatch: known deploy_id, different app or source (ALREADY_EXISTS).
	ErrDeploySpecMismatch = errors.New("deploy exists with a different spec")
	errClone              = errors.New("clone failed")
	errBuild              = errors.New("build failed")
)

// Deploy IDs must be 1-64 chars: alphanumeric plus '-' and '.'.
// Slashes, path traversal, underscores, or lengths > 64 are rejected.
var validDeployIDRe = regexp.MustCompile(`^[a-zA-Z0-9-]{1,64}$`)

// App IDs follow DNS-1123 label style (common for containers/k8s/slugs):
// lowercase alphanumeric and hyphens, 1-63 chars, no uppercase, no underscores, no slashes.
var validAppIDRe = regexp.MustCompile(`^[a-z0-9]([-a-z0-9]*[a-z0-9])?$`)

// Spec is what StartDeploy asks for.
type Spec struct {
	DeployID   string
	AppID      string
	Source     Source
	Dockerfile string
}

// imageBuilder is what a job needs from Docker. Declared here, by the consumer
type imageBuilder interface {
	BuildImage(ctx context.Context, buildContext io.Reader, opts docker.BuildOptions, log io.Writer) error
	PushImage(ctx context.Context, tag string) (digest string, err error)
}

var _ imageBuilder = (*docker.Client)(nil)

// cloneFunc matches Clone; a field so tests can avoid the network.
type cloneFunc func(ctx context.Context, src Source, parentDir string) (Checkout, error)

// job is a running build. Fields guarded by Manager.mu.
type job struct {
	status Status
	cancel context.CancelCauseFunc
}

// Manager runs build jobs and is the registry deploy_id → job.
type Manager struct {
	baseCtx   context.Context // parent of every job context: NOT a request context
	cancelAll context.CancelCauseFunc
	wg        sync.WaitGroup
	store     *Store
	builder   imageBuilder
	clone     cloneFunc
	registry  string // e.g. 192.168.252.1:5050 — from the agent's config

	mu   sync.Mutex
	jobs map[string]*job
}

// NewManager wires a job manager. baseCtx is the agent's lifetime context:
// cancelling it (graceful shutdown) cancels running builds.
func NewManager(parent context.Context, store *Store, builder imageBuilder, registry string) *Manager {
	baseCtx, cancelAll := context.WithCancelCause(parent)
	return &Manager{
		baseCtx:   baseCtx,
		cancelAll: cancelAll,
		store:     store,
		builder:   builder,
		clone:     Clone,
		registry:  registry,
		jobs:      make(map[string]*job),
	}
}

// Start validates spec and starts its build in the background.
// Idempotent on DeployID.
func (m *Manager) Start(ctx context.Context, spec Spec) (Status, error) {
	if err := validateIDs(spec); err != nil {
		return Status{}, err
	}
	if err := spec.Source.Validate(ctx); err != nil {
		return Status{}, err
	}

	m.mu.Lock()
	if j, exists := m.jobs[spec.DeployID]; exists {
		st := j.status
		m.mu.Unlock()

		if !sameSpec(st, spec) {
			return Status{}, fmt.Errorf("%w: deploy %s", ErrDeploySpecMismatch, spec.DeployID)
		}
		return st, nil
	}
	m.mu.Unlock()

	if st, err := m.store.ReadStatus(spec.DeployID); err == nil {
		if !sameSpec(st, spec) {
			return Status{}, fmt.Errorf("%w: deploy %s", ErrDeploySpecMismatch, spec.DeployID)
		}
		return st, nil
	} else if !errors.Is(err, ErrDeployNotFound) {
		return Status{}, fmt.Errorf("check existing deploy on disk: %w", err)
	}

	jobCtx, cancel := context.WithCancelCause(m.baseCtx)

	initialStatus := Status{
		DeployID:  spec.DeployID,
		AppID:     spec.AppID,
		Source:    spec.Source,
		State:     StateRunning,
		StartedAt: time.Now(),
	}

	m.mu.Lock()
	if j, exists := m.jobs[spec.DeployID]; exists {
		m.mu.Unlock()
		cancel(nil)
		if !sameSpec(j.status, spec) {
			return Status{}, fmt.Errorf("%w: deploy %s", ErrDeploySpecMismatch, spec.DeployID)
		}
		return j.status, nil
	}

	m.jobs[spec.DeployID] = &job{
		status: initialStatus,
		cancel: cancel,
	}
	m.mu.Unlock()

	if err := m.store.WriteStatus(initialStatus); err != nil {
		m.mu.Lock()
		delete(m.jobs, spec.DeployID)
		m.mu.Unlock()
		cancel(nil)
		return Status{}, fmt.Errorf("write initial status: %w", err)
	}

	m.wg.Add(1)
	go m.run(jobCtx, spec.DeployID)

	return initialStatus, nil
}

// Get returns the job's status: from memory if known, else from disk.
func (m *Manager) Get(deployID string) (Status, error) {
	if err := ValidateDeployID(deployID); err != nil {
		return Status{}, err
	}

	m.mu.Lock()
	if j, exists := m.jobs[deployID]; exists {
		st := j.status
		m.mu.Unlock()
		return st, nil
	}
	m.mu.Unlock()

	return m.store.ReadStatus(deployID)
}

// Cancel cancels a running job. A finished job is returned as is (OK).
func (m *Manager) Cancel(deployID string) (Status, error) {
	if err := ValidateDeployID(deployID); err != nil {
		return Status{}, err
	}

	m.mu.Lock()
	if j, exists := m.jobs[deployID]; exists {
		if j.status.State == StateRunning {
			j.cancel(errCancelledByUser)
		}
		st := j.status
		m.mu.Unlock()
		return st, nil
	}
	m.mu.Unlock()

	return m.store.ReadStatus(deployID)
}

// run executes one build. The only writer of the job's final status.
func (m *Manager) run(ctx context.Context, deployID string) {
	defer m.wg.Done()

	var (
		finalCommitSHA string
		finalImage     docker.ImageRef
		buildErr       error
	)

	// Fetch job metadata for execution.
	m.mu.Lock()
	j, ok := m.jobs[deployID]
	if !ok {
		m.mu.Unlock()
		return
	}
	src := j.status.Source
	appID := j.status.AppID
	dockerfileText := j.status.Dockerfile
	jobCancel := j.cancel
	m.mu.Unlock()

	defer func() {
		defer jobCancel(nil)

		now := time.Now()

		m.mu.Lock()
		st := m.jobs[deployID].status
		m.mu.Unlock()

		st.FinishedAt = now

		switch {
		case buildErr == nil:
			st.State = StateSucceeded
			st.CommitSHA = finalCommitSHA
			st.Image = finalImage
		case errors.Is(ctx.Err(), context.Canceled):
			st.State, st.Error = finalStateForCancel(ctx)
		default:
			st.State = StateFailed
			st.Error = userError(buildErr)
			slog.Error("build failed", "deploy_id", deployID, "err", buildErr)
		}

		if err := m.store.WriteStatus(st); err != nil {
			slog.Error("failed to persist final status", "deploy_id", deployID, "err", err)
		}

		m.mu.Lock()
		if j, ok := m.jobs[deployID]; ok {
			j.status = st
		}
		m.mu.Unlock()
	}()

	logFile, err := m.store.OpenLog(deployID)
	if err != nil {
		buildErr = fmt.Errorf("open build log: %w", err)
		return
	}
	defer logFile.Close()

	checkout, err := m.clone(ctx, src, "")
	if err != nil {
		buildErr = fmt.Errorf("%w: %w", errClone, err)
		return
	}
	defer checkout.Remove()

	finalCommitSHA = checkout.Commit
	fmt.Fprintf(logFile, "commit %s\n", finalCommitSHA)

	contextDir, err := resolveSubdir(checkout.Dir, src.Subdir)
	if err != nil {
		buildErr = err
		return
	}

	dockerfilePath, err := prepareDockerfile(contextDir, dockerfileText)
	if err != nil {
		buildErr = fmt.Errorf("prepare dockerfile: %w", err)
		return
	}
	fmt.Fprintf(logFile, "dockerfile: %s\n", dockerfilePath)

	rc, err := Context(contextDir)
	if err != nil {
		buildErr = fmt.Errorf("create build context: %w", err)
		return
	}
	defer rc.Close()

	repository := fmt.Sprintf("%s/%s", m.registry, appID)
	tag := fmt.Sprintf("%s:%s", repository, deployID)

	opts := docker.BuildOptions{
		Dockerfile: dockerfilePath,
		Tag:        tag,
		Labels: map[string]string{
			"org.opencontainers.image.revision": finalCommitSHA,
			"org.opencontainers.image.source":   src.RepoURL,
			"bult.deploy_id":                    deployID,
		},
	}
	if err := m.builder.BuildImage(ctx, rc, opts, logFile); err != nil {
		buildErr = fmt.Errorf("%w: %w", errBuild, err)
		return
	}

	digest, err := m.builder.PushImage(ctx, tag)
	if err != nil {
		buildErr = fmt.Errorf("push image: %w", err)
		return
	}

	finalImage = docker.ImageRef{
		Repository: repository,
		Digest:     digest,
	}
}

func sameSpec(st Status, spec Spec) bool {
	return st.AppID == spec.AppID && st.Source == spec.Source && st.Dockerfile == spec.Dockerfile
}

// validateIDs checks deploy_id and app_id: both become part of filesystem
// paths and Docker image names, so allow-list them.
func validateIDs(spec Spec) error {
	if err := ValidateDeployID(spec.DeployID); err != nil {
		return err
	}
	if err := ValidateAppID(spec.AppID); err != nil {
		return err
	}
	return nil
}

// userError turns an internal error into text safe and useful for the user.
func userError(err error) string {
	if err == nil {
		return ""
	}

	if errors.Is(err, errBadSubdir) {
		return err.Error()
	}

	if errors.Is(err, errNoDockerfile) {
		return "no Dockerfile in the repository and no preset selected; add a Dockerfile or choose a preset in the app settings"
	}

	if errors.Is(err, ErrInvalidRepoURL) || errors.Is(err, ErrInvalidBranch) {
		return err.Error()
	}

	if errors.Is(err, errClone) {
		return "repository not found or private (only public https repositories are supported)"
	}

	if errors.Is(err, errBuild) {
		return err.Error()
	}

	return "internal error, see build log"
}

// ValidateDeployID checks that deployID is safe to use in filesystem paths.
func ValidateDeployID(id string) error {
	if len(id) == 0 || len(id) > 64 || !validDeployIDRe.MatchString(id) {
		return fmt.Errorf("%w: %q (must match %s)", ErrInvalidDeployID, id, validDeployIDRe.String())
	}
	return nil
}

// ValidateAppID ensures appID is a valid identifier (no uppercase, no underscores, no slashes).
func ValidateAppID(id string) error {
	if len(id) == 0 || len(id) > 63 || !validAppIDRe.MatchString(id) {
		return fmt.Errorf("%w: %q (must be lowercase alphanumeric with hyphens)", ErrInvalidAppID, id)
	}
	return nil
}
