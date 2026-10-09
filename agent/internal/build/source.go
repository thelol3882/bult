package build

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"net/url"
	"os"
	"path"
	"path/filepath"
	"strings"
)

// Validation errors. Sentinels, so the gRPC layer can map them to
// INVALID_ARGUMENT with errors.Is.
var (
	ErrInvalidRepoURL = errors.New("invalid repository url")
	ErrInvalidBranch  = errors.New("invalid branch name")
	ErrInvalidSubdir  = errors.New("invalid subdir")
	errBadSubdir      = errors.New("bad subdir")
)

// Source is what the user gives us: where the code lives. Both fields are
// untrusted input.
type Source struct {
	RepoURL string
	Branch  string
	Subdir  string
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

	if err := s.validateSubdir(); err != nil {
		return err
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

// validateSubdir checks the subdir STRING. The real path is checked after
// clone (resolveSubdir): a valid string can still point outside via a symlink.
func (s Source) validateSubdir() error {
	if s.Subdir == "" {
		return nil
	}

	if filepath.IsAbs(s.Subdir) || strings.HasPrefix(s.Subdir, "/") {
		return fmt.Errorf("%w: subdir must be relative, got %q", ErrInvalidSubdir, s.Subdir)
	}

	if path.Clean(s.Subdir) != s.Subdir {
		return fmt.Errorf("%w: subdir %q is not canonical (expected %q)", ErrInvalidSubdir, s.Subdir, path.Clean(s.Subdir))
	}

	segments := strings.Split(s.Subdir, "/")
	for _, segment := range segments {
		if segment == ".." {
			return fmt.Errorf("%w: subdir %q cannot contain '..'", ErrInvalidSubdir, s.Subdir)
		}
	}

	return nil
}

// resolveSubdir returns the absolute directory to build from: checkoutDir
// joined with subdir, after resolving symlinks, and only if it stays inside
// checkoutDir and is a directory.
func resolveSubdir(checkoutDir, subdir string) (string, error) {
	root, err := filepath.EvalSymlinks(checkoutDir)
	if err != nil {
		return "", fmt.Errorf("eval symlinks checkout dir: %w", err)
	}

	if subdir == "" {
		return root, nil
	}

	target := filepath.Join(root, filepath.FromSlash(subdir))
	dir, err := filepath.EvalSymlinks(target)
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return "", fmt.Errorf("%w: subdir %q not found in the repository", errBadSubdir, subdir)
		}
		return "", fmt.Errorf("eval symlinks subdir: %w", err)
	}

	rel, err := filepath.Rel(root, dir)
	if err != nil {
		return "", fmt.Errorf("check relative path: %w", err)
	}

	if rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("%w: subdir points outside the repository", errBadSubdir)
	}

	info, err := os.Stat(dir)
	if err != nil {
		return "", fmt.Errorf("stat subdir: %w", err)
	}
	if !info.IsDir() {
		return "", fmt.Errorf("%w: subdir %q is not a directory", errBadSubdir, subdir)
	}

	return dir, nil
}
