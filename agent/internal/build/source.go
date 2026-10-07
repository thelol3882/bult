package build

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"strings"
)

// Validation errors. Sentinels, so the gRPC layer can map them to
// INVALID_ARGUMENT with errors.Is.
var (
	ErrInvalidRepoURL = errors.New("invalid repository url")
	ErrInvalidBranch  = errors.New("invalid branch name")
)

// Source is what the user gives us: where the code lives. Both fields are
// untrusted input.
type Source struct {
	RepoURL string
	Branch  string
}

// Validate checks the source against an allow-list before anything reaches git.
// ctx is needed because the branch check may run `git check-ref-format`.
func (s Source) Validate(ctx context.Context) error {
	if err := s.validateURL(); err != nil {
		return fmt.Errorf("%w: %w", ErrInvalidRepoURL, err)
	}

	if err := s.validateBranch(ctx); err != nil {
		return fmt.Errorf("%w: %w", ErrInvalidBranch, err)
	}

	return nil
}

// validateURL accepts only https URLs with a host and without credentials.
func (s Source) validateURL() error {
	u, err := url.Parse(s.RepoURL)
	if err != nil {
		return fmt.Errorf("parse repo_url: %w", err)
	}

	if u.Scheme != "https" {
		return fmt.Errorf("repo_url scheme must be https, got %q", u.Scheme)
	}

	if u.Host == "" {
		return errors.New("repo_url host must not be empty")
	}

	if u.User != nil {
		return errors.New("repo_url must not contain user credentials")
	}

	return nil
}

// validateBranch accepts a non-empty git branch name that cannot be read as
// a command-line option.
func (s Source) validateBranch(ctx context.Context) error {
	if s.Branch == "" {
		return errors.New("branch cannot be empty")
	}

	if strings.HasPrefix(s.Branch, "-") {
		return fmt.Errorf("branch %q cannot start with '-'", s.Branch)
	}

	if _, err := runGit(ctx, "", "check-ref-format", "--branch", s.Branch); err != nil {
		return fmt.Errorf("invalid branch %q: %w", s.Branch, err)
	}

	return nil
}
