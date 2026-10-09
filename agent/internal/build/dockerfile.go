package build

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
)

// providedDockerfilePath is where a Dockerfile sent by the control plane is
// written inside the checkout. Its own name, so the user's Dockerfile (if any)
// stays untouched in the build context.
const providedDockerfilePath = ".bult/Dockerfile"

// errNoDockerfile: the repository has no Dockerfile and none was provided.
// A build outcome (job FAILED with a user-facing message), not an RPC error.
var errNoDockerfile = errors.New("no Dockerfile in the repository and no preset selected")

// prepareDockerfile decides which Dockerfile the build uses and returns its
// path relative to dir (what ImageBuildOptions.Dockerfile expects).
//
//	provided != "" → write it to dir/.bult/Dockerfile, return that path
//	provided == "" → dir/Dockerfile must exist, return "Dockerfile"
//	neither        → errNoDockerfile
func prepareDockerfile(dir, provided string) (string, error) {
	if provided != "" {
		targetPath := filepath.Join(dir, filepath.FromSlash(providedDockerfilePath))
		if err := os.MkdirAll(filepath.Dir(targetPath), 0o755); err != nil {
			return "", fmt.Errorf("creating .bult directory: %w", err)
		}
		if err := os.WriteFile(targetPath, []byte(provided), 0o644); err != nil {
			return "", fmt.Errorf("writing provided Dockerfile: %w", err)
		}
		return providedDockerfilePath, nil
	}

	repoDockerfilePath := filepath.Join(dir, "Dockerfile")
	if _, err := os.Stat(repoDockerfilePath); err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return "", errNoDockerfile
		}
		return "", fmt.Errorf("stat Dockerfile: %w", err)
	}

	return "Dockerfile", nil
}
