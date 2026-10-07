package build

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"

	"github.com/moby/go-archive"
	"github.com/moby/patternmatcher/ignorefile"
)

// alwaysExcluded is never sent to Docker, whatever .dockerignore says.
var alwaysExcluded = []string{".git"}

// Context streams dir as a tar archive for Docker's ImageBuild, honouring
// .dockerignore (Docker applies it client-side, so we must) and always
// excluding .git. Symlinks are archived as links, never followed.
// The caller MUST Close the result, also on error paths: it is fed by a
// goroutine through an io.Pipe inside go-archive.
func Context(dir string) (io.ReadCloser, error) {
	patterns, err := readIgnorePatterns(dir)
	if err != nil {
		return nil, fmt.Errorf("read ignore patterns: %w", err)
	}

	patterns = append(patterns, alwaysExcluded...)

	r, err := archive.TarWithOptions(dir, &archive.TarOptions{
		ExcludePatterns: patterns,
	})
	if err != nil {
		return nil, fmt.Errorf("tar build context: %w", err)
	}

	return r, nil
}

// readIgnorePatterns returns the patterns from dir/.dockerignore, or nil if
// the file does not exist.
func readIgnorePatterns(dir string) ([]string, error) {
	f, err := os.Open(filepath.Join(dir, ".dockerignore"))
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return nil, nil
		}
		return nil, fmt.Errorf("open .dockerignore: %w", err)
	}
	defer f.Close()

	patterns, err := ignorefile.ReadAll(f)
	if err != nil {
		return nil, fmt.Errorf("read .dockerignore patterns: %w", err)
	}

	return patterns, nil
}
