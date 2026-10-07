package build

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"strings"
)

// Checkout is a cloned source on disk.
type Checkout struct {
	Dir    string // temporary directory with the working tree
	Commit string // full SHA of HEAD — what exactly is being built
}

// Remove deletes the checkout directory. Call it with defer as soon as Clone
// succeeds; it is safe to call on an already removed directory.
func (c Checkout) Remove() error {
	if c.Dir == "" {
		return nil
	}
	return os.RemoveAll(c.Dir)
}

// Clone validates src and shallow-clones its branch into a new temporary
// directory under parentDir ("" = the system temp dir).
// On error nothing is left on disk.
func Clone(ctx context.Context, src Source, parentDir string) (Checkout, error) {
	if err := src.Validate(ctx); err != nil {
		return Checkout{}, fmt.Errorf("validate source: %w", err)
	}

	dir, err := os.MkdirTemp(parentDir, "bult-src-*")
	if err != nil {
		return Checkout{}, fmt.Errorf("create temp dir: %w", err)
	}

	var committed bool
	defer func() {
		if !committed {
			_ = os.RemoveAll(dir)
		}
	}()

	_, err = runGit(ctx, "", "clone",
		"--depth", "1",
		"--branch", src.Branch,
		"--single-branch",
		"--no-tags",
		"--no-recurse-submodules",
		"--",
		src.RepoURL,
		dir,
	)
	if err != nil {
		return Checkout{}, fmt.Errorf("clone repo: %w", err)
	}

	out, err := runGit(ctx, dir, "rev-parse", "HEAD")
	if err != nil {
		return Checkout{}, fmt.Errorf("rev-parse HEAD: %w", err)
	}

	sha := strings.TrimSpace(out)

	committed = true
	return Checkout{
		Dir:    dir,
		Commit: sha,
	}, nil
}

// runGit runs git with args in dir ("" = current directory) under ctx and
// returns its combined output. A non-zero exit becomes an error that includes
// git's output — that text is what the user will see in the build log.
func runGit(ctx context.Context, dir string, args ...string) (string, error) {
	cmd := exec.CommandContext(ctx, "git", args...)
	cmd.Dir = dir
	cmd.Env = append(os.Environ(), gitEnv()...)

	out, err := cmd.CombinedOutput()
	outStr := strings.TrimSpace(string(out))
	if err != nil {
		op := "git"
		if len(args) > 0 {
			op = fmt.Sprintf("git %s", args[0])
		}

		if ctxErr := ctx.Err(); ctxErr != nil {
			if outStr != "" {
				return "", fmt.Errorf("%s: %w: %w: %s", op, ctxErr, err, outStr)
			}
			return "", fmt.Errorf("%s: %w: %w", op, ctxErr, err)
		}

		if outStr != "" {
			return "", fmt.Errorf("%s: %w: %s", op, err, outStr)
		}
		return "", fmt.Errorf("%s: %w", op, err)
	}

	return outStr, nil
}

// gitEnv returns the environment entries that harden every git call.
func gitEnv() []string {
	return []string{
		"GIT_ALLOW_PROTOCOL=https",
		"GIT_TERMINAL_PROMPT=0",
	}
}
