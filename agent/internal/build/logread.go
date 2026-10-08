package build

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
)

// LogChunk is a piece of a build log and where it starts in the file.
// A watcher resumes from Offset + len(Data).
type LogChunk struct {
	Offset int64
	Data   []byte // valid only during the emit call — copy it to keep it
}

// maxLogChunk caps one chunk (and one gRPC message).
const maxLogChunk = 32 << 10

// ReadLogFrom reads build.log of deployID from offset to the current end of
// the file and calls emit for every chunk, in order. It returns the offset
// after the last byte read (where the next call should continue).
// A missing log file is not an error: the job may have failed before opening
// it — nothing to emit, return offset unchanged.
func (s *Store) ReadLogFrom(deployID string, offset int64, emit func(LogChunk) error) (int64, error) {
	logPath := filepath.Join(s.jobDir(deployID), "build.log")
	f, err := os.Open(logPath)
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return offset, nil
		}
		return offset, fmt.Errorf("open build log %q: %w", logPath, err)
	}
	defer f.Close()

	if _, err := f.Seek(offset, io.SeekStart); err != nil {
		return offset, fmt.Errorf("seek build log %q to %d: %w", logPath, offset, err)
	}

	buf := make([]byte, maxLogChunk)
	pos := offset

	for {
		n, readErr := f.Read(buf)
		if n > 0 {
			if err := emit(LogChunk{Offset: pos, Data: buf[:n]}); err != nil {
				return pos, err
			}
			pos += int64(n)
		}

		if readErr != nil {
			if errors.Is(readErr, io.EOF) {
				return pos, nil
			}
			return pos, fmt.Errorf("read build log %q: %w", logPath, readErr)
		}
	}
}

// List returns every persisted job status (used by Recover).
func (s *Store) List() ([]Status, error) {
	entries, err := os.ReadDir(s.dir)
	if err != nil {
		return nil, fmt.Errorf("read store dir %q: %w", s.dir, err)
	}

	var statuses []Status
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}

		st, err := s.ReadStatus(entry.Name())
		if err != nil {
			if errors.Is(err, ErrDeployNotFound) {
				continue
			}
			return nil, fmt.Errorf("read status for %q: %w", entry.Name(), err)
		}

		statuses = append(statuses, st)
	}

	return statuses, nil
}
